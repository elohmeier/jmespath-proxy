import os
import pathlib
import ssl
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import jmespath
import truststore
from httpx import USE_CLIENT_DEFAULT, AsyncClient, BasicAuth, HTTPError
from jmespath.exceptions import ParseError
from litestar import Litestar, Response, get, post, status_codes
from litestar.connection import Request
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig
from litestar.response import Template
from litestar.static_files.config import create_static_files_router
from litestar.template import TemplateConfig

APP_DIR = pathlib.Path(__file__).parent.resolve()
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


JMESPATH_EXPRESSION = os.environ.get("JMESPATH_EXPRESSION", default="")
FORWARD_URL = os.environ.get("FORWARD_URL", default="")

# Default timeout in seconds for httpx requests
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", default="30.0"))

# SSL verification settings
# Set VERIFY_SSL=false to disable SSL verification (insecure)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() != "false"

# Basic auth credentials for the forward URL (optional)
FORWARD_BASIC_AUTH_USERNAME = os.environ.get("FORWARD_BASIC_AUTH_USERNAME", default="")
FORWARD_BASIC_AUTH_PASSWORD = os.environ.get("FORWARD_BASIC_AUTH_PASSWORD", default="")


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
        if app.logger:
            app.logger.warning("SSL verification is disabled. This is insecure!")

    app.state.httpx_client = AsyncClient(timeout=HTTPX_TIMEOUT, verify=verify)
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
    request.logger.info(f"Forward endpoint received data: {data}")

    # Apply JMESPath transformation if configured
    if JMESPATH_EXPRESSION:
        result = jmespath.search(JMESPATH_EXPRESSION, data)
    else:
        result = data

    request.logger.info(f"Transformed payload: {result}")

    # Raise an error if no FORWARD_URL is specified
    if not FORWARD_URL:
        request.logger.error("No FORWARD_URL environment variable specified")
        return {
            "error": "Configuration error: FORWARD_URL environment variable is not set",
            "original_data": result,
        }

    # Forward to remote system
    try:
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
            request.logger.info(f"Using basic auth for request to {FORWARD_URL}")

        response = await client.post(FORWARD_URL, json=result, auth=auth)
        response.raise_for_status()
        request.logger.info(
            f"Successfully forwarded to {FORWARD_URL}, status: {response.status_code}"
        )

        # Get the content type from the response
        content_type = response.headers.get("content-type", "")

        # If the response is JSON, parse it and return the Python object
        if "application/json" in content_type:
            content = await response.json()
        else:
            # For non-JSON responses, use the raw content
            content = response.content

        # Return the response with the appropriate content and headers
        return Response(
            content=content,
            status_code=response.status_code,
            media_type=content_type,
            headers=dict(response.headers),
        )
    except HTTPError as e:
        request.logger.error(f"Error forwarding to {FORWARD_URL}: {str(e)}")
        return {
            "error": f"Failed to forward request: {str(e)}",
            "original_data": result,
        }


@dataclass
class JMESPathTestPayload:
    data: dict
    expression: str | None = None


@post(path="/test", status_code=status_codes.HTTP_200_OK)
async def test_jmes(data: JMESPathTestPayload, request: Request) -> Any:
    request.logger.info(f"Test endpoint received data: {data.data}")
    request.logger.info(
        f"Test endpoint using expression: {data.expression or JMESPATH_EXPRESSION}"
    )

    # Use the provided expression if available, otherwise fall back to the server default
    jmespath_expression = data.expression if data.expression else JMESPATH_EXPRESSION

    # If no expression is provided (neither custom nor server default), return the original data
    if not jmespath_expression:
        return data.data

    # Apply the JMESPath expression to the data with error handling
    try:
        return jmespath.search(jmespath_expression, data.data)
    except ParseError as e:
        error_msg = str(e)
        return {
            "error": f"JMESPath parse error: {error_msg}",
        }


# Configure logging using Litestar's LoggingConfig
logging_config = LoggingConfig(
    root={"level": "INFO", "handlers": ["queue_listener"]},
    formatters={
        "standard": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"}
    },
    log_exceptions="always",
)

app = Litestar(
    logging_config=logging_config,
    route_handlers=[
        index,
        forward_json,
        test_jmes,
        create_static_files_router(path="/static", directories=[STATIC_DIR]),
    ],
    template_config=TemplateConfig(directory=TEMPLATE_DIR, engine=JinjaTemplateEngine),
    lifespan=[httpx_lifespan],
)
