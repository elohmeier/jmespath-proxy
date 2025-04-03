import os
import pathlib
from dataclasses import dataclass
from typing import Any

import httpx
import jmespath
from jmespath.exceptions import ParseError
from litestar import Litestar, get, post
from litestar.connection import Request
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.logging import LoggingConfig
from litestar.response import Template
from litestar.static_files.config import create_static_files_router
from litestar.template import TemplateConfig

JMESPATH_EXPRESSION = os.environ.get("JMESPATH_EXPRESSION", default="")


@get("/")
async def index() -> Template:
    return Template(
        template_name="index.html", context={"default_expression": JMESPATH_EXPRESSION}
    )


@post(path="/forward")
async def forward_json(data: dict[str, Any], request: Request) -> Any:
    request.logger.info(f"Forward endpoint received data: {data}")

    if not JMESPATH_EXPRESSION:
        return data

    result = jmespath.search(JMESPATH_EXPRESSION, data)


@dataclass
class JMESPathTestPayload:
    data: dict
    expression: str | None = None


@post(path="/test")
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
        mirror_json,
        test_jmes,
        create_static_files_router(path="/static", directories=["static"]),
    ],
    template_config=TemplateConfig(
        directory=pathlib.Path("templates"),
        engine=JinjaTemplateEngine,
    ),
)
