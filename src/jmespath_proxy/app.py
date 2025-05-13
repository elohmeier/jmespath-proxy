import logging
import os
import pathlib
import ssl
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import jmespath
import structlog
import truststore
from httpx import USE_CLIENT_DEFAULT, AsyncClient, BasicAuth, HTTPError
from jmespath.exceptions import ParseError
from litestar import Litestar, Response, get, post, status_codes
from litestar.connection import Request
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig, StructLoggingConfig
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.plugins.prometheus import PrometheusConfig, PrometheusController
from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
from litestar.response import Template
from litestar.static_files.config import create_static_files_router
from litestar.template import TemplateConfig
from prometheus_client import Counter, Histogram

logging_config = StructlogConfig(
    structlog_logging_config=StructLoggingConfig(
        log_exceptions="always",
        traceback_line_limit=4,
        standard_lib_logging_config=LoggingConfig(
            root={
                "level": logging.getLevelName(20),
                "handlers": ["queue_listener"],
            },
            loggers={
                "uvicorn.access": {
                    "propagate": False,
                    "level": 30,
                    "handlers": ["queue_listener"],
                },
                "uvicorn.error": {
                    "propagate": False,
                    "level": 20,
                    "handlers": ["queue_listener"],
                },
            },
        ),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    ),
    middleware_logging_config=LoggingMiddlewareConfig(
        request_log_fields=["method", "path", "path_params", "query"],
        response_log_fields=["status_code"],
    ),
)

logger = structlog.get_logger()

APP_DIR = pathlib.Path(__file__).parent.resolve()
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


JMESPATH_EXPRESSION = os.environ.get("JMESPATH_EXPRESSION", default="")
FORWARD_URL = os.environ.get("FORWARD_URL", default="")
METRICS_ANNOTATION_EXPRESSION = os.environ.get(
    "METRICS_ANNOTATION_EXPRESSION", default=""
)


# Default timeout in seconds for httpx requests
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", default="30.0"))

# SSL verification settings
# Set VERIFY_SSL=false to disable SSL verification (insecure)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() != "false"

# Basic auth credentials for the forward URL (optional)
FORWARD_BASIC_AUTH_USERNAME = os.environ.get("FORWARD_BASIC_AUTH_USERNAME", default="")
FORWARD_BASIC_AUTH_PASSWORD = os.environ.get("FORWARD_BASIC_AUTH_PASSWORD", default="")


# --- Define custom Prometheus metrics ---
def extract_labelnames(expression: str) -> list[str]:
    """Extract label names from a JMESPath expression.

    This function extracts the label names from a multi_select_dict JMESPath expression.
    For example, from the expression '{foo: a, bar: b}', it extracts ['foo', 'bar'].

    Args:
        expression: The JMESPath expression to analyze

    Returns:
        List of label names extracted from the expression
    """
    if not expression:
        return []

    try:
        # Compile the expression to get its parsed structure
        parsed = jmespath.compile(expression).parsed

        # Only multi_select_dict expressions are valid for label extraction
        if parsed.get("type") != "multi_select_dict":
            logger.warning(
                "Metrics annotation expression is not a multi_select_dict",
                expression=expression,
            )
            return []

        # Extract the label names from the key_val_pair children
        label_names = []
        for child in parsed.get("children", []):
            if child.get("type") == "key_val_pair":
                label_names.append(child.get("value"))

        logger.info("Extracted label names", label_names=label_names)
        return label_names
    except Exception as e:
        logger.error(
            "Error extracting label names from expression",
            error=str(e),
            expression=expression,
        )
        return []


# Extract label names from the metrics annotation expression
metric_label_names = extract_labelnames(METRICS_ANNOTATION_EXPRESSION)

# Counter for total successful forwarding requests
# Will be dynamically labeled based on METRICS_ANNOTATION_EXPRESSION if provided
metrics_forwarded_total = Counter(
    "jmespath_proxy_forwarded_total",
    "Total number of messages successfully forwarded.",
    metric_label_names if metric_label_names else (),
)

# Counter for forwarding errors
# Added a label for the error type (e.g., 'http_error', 'config_error')
metrics_forward_errors_total = Counter(
    "jmespath_proxy_forward_errors_total",
    "Total number of errors encountered during forwarding.",
    ["error_type"],  # Labels for differentiating error types
)

# Histogram for the duration of the *forwarded* HTTP request
metrics_forward_duration_seconds = Histogram(
    "jmespath_proxy_forward_duration_seconds",
    "Duration of forwarded HTTP requests in seconds.",
    buckets=[
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        float("inf"),
    ],
)

# --- End custom Prometheus metrics definition ---


def apply_jmespath_expression(
    expression: str,
    body_data: dict[str, Any],
    query_params: dict[str, Any],
) -> tuple[Any, str | None]:
    """Apply a JMESPath expression to the provided data.

    Args:
        expression: The JMESPath expression to apply
        body_data: The body data to transform
        query_params: Query parameters to include in context

    Returns:
        Tuple containing:
        - The result of the JMESPath expression (or original data on error)
        - An error message if an error occurred, None otherwise
    """
    # Skip processing if no expression is provided
    if not expression:
        logger.info("No JMESPath expression provided", returning="original_data")
        return body_data, None

    # Create a combined context for JMESPath evaluation
    context_data = {"body": body_data, "query_params": query_params}

    try:
        logger.info("Applying JMESPath expression", expression=expression)
        result = jmespath.search(expression, context_data)
        return result, None
    except ParseError as e:
        error_msg = f"JMESPath parse error: {str(e)}"
        logger.error("JMESPath parse error", error=str(e), expression=expression)
        return body_data, error_msg
    except Exception as e:
        error_msg = f"JMESPath execution error: {str(e)}"
        logger.error("JMESPath execution error", error=str(e), expression=expression)
        return body_data, error_msg


def extract_metric_labels(
    expression: str,
    body_data: dict[str, Any],
    query_params: dict[str, Any],
) -> dict[str, str]:
    """Extract metric labels using a JMESPath expression.

    Args:
        expression: The JMESPath expression to apply
        body_data: The body data to extract labels from
        query_params: Query parameters to include in context

    Returns:
        Dictionary of label names and values for metrics
    """
    # Skip processing if no expression is provided
    if not expression:
        return {}

    # Create a combined context for JMESPath evaluation
    context_data = {"body": body_data, "query_params": query_params}

    try:
        logger.info("Extracting metric labels", expression=expression)
        result = jmespath.search(expression, context_data)

        # Ensure result is a dictionary with string values
        if not isinstance(result, dict):
            logger.warning(
                "Metrics annotation expression did not return a dictionary",
                result=result,
                expression=expression,
            )
            return {}

        # Convert all values to strings for Prometheus labels
        labels = {k: str(v) for k, v in result.items() if v is not None}
        logger.info("Extracted metric labels", labels=labels)
        return labels
    except Exception as e:
        logger.error(
            "Error extracting metric labels", error=str(e), expression=expression
        )
        return {}


@asynccontextmanager
async def httpx_lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Lifespan context manager for httpx client.

    Creates a single httpx client when the application starts and stores it in app.state.
    The client is automatically closed when the application shuts down.

    Uses truststore for SSL verification by default, which uses the system's certificate store.
    SSL verification can be disabled by setting VERIFY_SSL=false.

    Args:
        app: The Litestar application instance

    Yields:
        None
    """
    # Configure SSL verification
    verify: bool | ssl.SSLContext
    if VERIFY_SSL:
        # Use truststore to access system certificate stores
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        verify = ssl_context
    else:
        # Disable SSL verification (insecure)
        verify = False
        logger.warning("SSL verification is disabled. This is insecure!")

    app.state.httpx_client = AsyncClient(timeout=HTTPX_TIMEOUT, verify=verify)

    # Validate JMESPath expressions
    for expr_name, expr_value in [
        ("JMESPATH_EXPRESSION", JMESPATH_EXPRESSION),
        ("METRICS_ANNOTATION_EXPRESSION", METRICS_ANNOTATION_EXPRESSION),
    ]:
        if expr_value:
            try:
                jmespath.compile(expr_value)
                logger.info(
                    f"Successfully compiled {expr_name}",
                    expression=expr_value,
                )
            except ParseError as e:
                logger.error(
                    f"Invalid {expr_name}",
                    error=str(e),
                    expression=expr_value,
                )
                # Note: The application will still start, but the expression
                # will fail when applied. We log the error but don't exit.
            except Exception as e:
                logger.error(
                    f"Unexpected error compiling {expr_name}",
                    error=str(e),
                    expression=expr_value,
                )
        else:
            logger.info(f"No {expr_name} environment variable set.")

    try:
        yield
    finally:
        await app.state.httpx_client.aclose()


@get("/")
async def index() -> Template:
    return Template(
        template_name="index.html", context={"default_expression": JMESPATH_EXPRESSION}
    )


@get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for Kubernetes probes."""
    return {"status": "healthy"}


@post(path="/", status_code=status_codes.HTTP_200_OK)
async def forward_json(data: dict[str, Any], request: Request) -> Any:
    logger.info("Forward endpoint received data", data=data)

    # Retrieve query parameters and convert to a dictionary
    query_params_dict = dict(request.query_params)
    logger.info("Query parameters", query_params=query_params_dict)

    # Apply JMESPath transformation if configured
    result, error = apply_jmespath_expression(
        JMESPATH_EXPRESSION, data, query_params_dict
    )

    # Extract metric labels if configured
    metric_labels = extract_metric_labels(
        METRICS_ANNOTATION_EXPRESSION, data, query_params_dict
    )

    # Return error response if transformation failed
    if error:
        return {
            "error": f"Error in global expression: {error}",
            "original_data": data,
            "query_params": query_params_dict,
        }

    logger.info("Final payload for forwarding", payload=result)

    # Raise an error if no FORWARD_URL is specified
    if not FORWARD_URL:
        logger.error(
            "Configuration error", message="FORWARD_URL environment variable is not set"
        )
        # Increment a config error metric
        metrics_forward_errors_total.labels(error_type="config_error").inc()
        return {
            "error": "Configuration error: FORWARD_URL environment variable is not set",
            "original_data": result,  # This 'result' might be transformed or not
            "query_params": query_params_dict,
        }

    # Forward to remote system
    client = request.app.state.httpx_client

    if TYPE_CHECKING:
        client = cast(AsyncClient, client)

    # Set up basic auth if credentials are provided
    auth = USE_CLIENT_DEFAULT
    if FORWARD_BASIC_AUTH_USERNAME and FORWARD_BASIC_AUTH_PASSWORD:
        auth = BasicAuth(
            username=FORWARD_BASIC_AUTH_USERNAME,
            password=FORWARD_BASIC_AUTH_PASSWORD,
        )
        logger.info("Using basic auth for request", url=FORWARD_URL)

    response = None

    # Use the histogram's time() context manager to automatically record duration
    with metrics_forward_duration_seconds.time():
        try:
            response = await client.post(FORWARD_URL, json=result, auth=auth)
            response.raise_for_status()
        except HTTPError as e:
            # Get error content if available
            error_content = None
            if response is not None:
                try:
                    error_content = response.text
                except Exception:
                    error_content = str(response.content)

            logger.error(
                "Forwarding failed",
                error=str(e),
                url=FORWARD_URL,
                upstream_content=error_content,
                status_code=response.status_code if response else None,
            )

            # Increment the forwarding error metric with error type
            metrics_forward_errors_total.labels(error_type="http_error").inc()

            # Include query params in the error response as well
            return {
                "error": f"Failed to forward request: {str(e)}",
                "original_data": result,  # This 'result' might be transformed or not
                "query_params": query_params_dict,
            }
        except Exception as e:  # Catch any other exceptions during the request
            logger.error("Unexpected forwarding error", error=str(e), url=FORWARD_URL)

            # Increment the forwarding error metric with error type
            metrics_forward_errors_total.labels(error_type="unexpected_error").inc()

            return {
                "error": f"Unexpected error during forwarding: {str(e)}",
                "original_data": result,
                "query_params": query_params_dict,
            }
        else:
            # Request was successful
            logger.info(
                "Request forwarded successfully",
                url=FORWARD_URL,
                status_code=response.status_code,
            )

            # Increment the successful forwarding metric with any extracted labels
            if metric_label_names:
                # When we have label names from the expression, use the extracted values
                label_values = [
                    metric_labels.get(name, "") for name in metric_label_names
                ]
                metrics_forwarded_total.labels(*label_values).inc()
            else:
                # Fallback without labels
                metrics_forwarded_total.inc()

        # Return the response with the appropriate content and headers
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response.headers,
        )


@dataclass
class JMESPathTestPayload:
    data: dict
    expression: str | None = None


@post(path="/test", status_code=status_codes.HTTP_200_OK)
async def test_jmes(data: JMESPathTestPayload, request: Request) -> Any:
    logger.info("Test endpoint received data", data=data.data)

    # Retrieve query parameters and convert to a dictionary
    query_params_dict = dict(request.query_params)
    logger.info("Query parameters", query_params=query_params_dict)

    # Use the provided expression if available, otherwise fall back to the server default
    jmespath_expression = data.expression if data.expression else JMESPATH_EXPRESSION

    logger.info(
        "Test endpoint using expression",
        expression=jmespath_expression or "[No Expression]",
    )

    # Apply the JMESPath expression
    result, error = apply_jmespath_expression(
        jmespath_expression, data.data, query_params_dict
    )

    # Return error response if transformation failed
    if error:
        return {
            "error": error,
            "original_data": data.data,
            "query_params": query_params_dict,
        }

    return result


# Configure Prometheus metrics
prometheus_config = PrometheusConfig(
    app_name="jmespath_proxy",
    # These buckets are used by the Litestar plugin's middleware for *request* duration.
    # Our custom histogram uses its own buckets defined above.
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# Configure structlog plugin
structlog_plugin = StructlogPlugin(logging_config)

app = Litestar(
    route_handlers=[
        index,
        health_check,
        forward_json,
        test_jmes,
        create_static_files_router(path="/static", directories=[STATIC_DIR]),
        PrometheusController,
    ],
    middleware=[prometheus_config.middleware],
    template_config=TemplateConfig(directory=TEMPLATE_DIR, engine=JinjaTemplateEngine),
    lifespan=[httpx_lifespan],
    plugins=[structlog_plugin],
)
