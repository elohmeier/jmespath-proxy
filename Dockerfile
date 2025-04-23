# First stage: build the application with uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation and copy from cache
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=0

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Add only the necessary source code files and install the project
ADD pyproject.toml README.md src uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Second stage: create the final image without uv
FROM python:3.12-slim-bookworm

# Create a non-root user to run the application
RUN useradd -m app

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /usr/local/lib/python3.12 /usr/local/lib/python3.12

# Set the working directory
WORKDIR /app

# Switch to the non-root user
USER app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

ENV LITESTAR_APP=jmespath_proxy.app:app

ENTRYPOINT ["litestar", "run", "-H", "0.0.0.0", "-p", "8000"]
