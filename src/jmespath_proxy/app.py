import os
import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import jmespath
from httpx import AsyncClient, HTTPError, BasicAuth
from jmespath.exceptions import ParseError
from litestar import Litestar, get, post, status_codes
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

# Basic auth credentials for the forward URL (optional)
FORWARD_BASIC_AUTH_USERNAME = os.environ.get("FORWARD_BASIC_AUTH_USERNAME", default="")
FORWARD_BASIC_AUTH_PASSWORD = os.environ.get("FORWARD_BASIC_AUTH_PASSWORD", default="")


@asynccontextmanager
async def httpx_lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Lifespan context manager for httpx client.

    Creates a single httpx client when the application starts and stores it in app.state.
    The client is automatically closed when the application shuts down.

    Args:
        app: The Litestar application instance

    Yields:
        None
    """
    app.state.httpx_client = AsyncClient(timeout=HTTPX_TIMEOUT)
    try:
        yield
    finally:
        await app.state.httpx_client.aclose()


@get("/")
async def index() -> Template:
    return Template(
        template_name="index.html", context={"default_expression": JMESPATH_EXPRESSION}
    )


@post(path="/", status_code=status_codes.HTTP_200_OK)
async def root_forward(data: dict[str, Any], request: Request) -> Any:
    """Root POST endpoint that forwards to the same logic as /forward."""
    return await forward_json(data, request)


@post(path="/forward", status_code=status_codes.HTTP_200_OK)
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
        auth = None
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
        return response.json()
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
        root_forward,
        forward_json,
        test_jmes,
        create_static_files_router(path="/static", directories=[STATIC_DIR]),
    ],
    template_config=TemplateConfig(directory=TEMPLATE_DIR, engine=JinjaTemplateEngine),
    lifespan=[httpx_lifespan],
)
