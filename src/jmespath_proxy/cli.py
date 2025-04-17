import os

import uvicorn


def main():
    """Runs the Litestar application using Uvicorn."""
    host = os.environ.get("HOST", "127.0.0.1")  # Default to localhost
    port = int(os.environ.get("PORT", "8000"))  # Default to 8000
    reload = os.environ.get("APP_RELOAD", "false").lower() == "true"  # For dev
    workers = int(os.environ.get("WEB_CONCURRENCY", 1))  # For prod
    log_level = os.environ.get("LOG_LEVEL", "info")

    # Use the string format 'module:app' for reload to work correctly
    app_string = "jmespath_proxy.app:app"

    uvicorn.run(
        app_string,
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # Uvicorn recommends 1 worker with reload
        log_level=log_level,
    )


if __name__ == "__main__":
    # Allows running the script directly for testing: python -m jmespath_proxy.cli
    main()
