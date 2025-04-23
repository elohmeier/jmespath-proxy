# JMESPath Proxy

Welcome to the JMESPath Proxy Application! This project provides an API service built with the Litestar web framework, allowing users to perform JMESPath queries on incoming JSON data and optionally forward the transformed payload to a specified URL.

## Features

- **JMESPath Expressions**: Apply JMESPath expressions to transform JSON data.
- **Forwarding**: Forward transformed JSON payloads to a configurable remote URL.
- **Test Endpoint**: Test JMESPath expressions directly via a test endpoint.
- **Async Support**: Built with async support using `httpx` for HTTP requests.
- **Configurable via Environment Variables**: Customize the behavior of the application using environment variables.

## Environment Variables

- `JMESPATH_EXPRESSION`: Default JMESPath expression to apply to incoming JSON data.
- `FORWARD_URL`: URL to which the transformed JSON payload will be forwarded.
- `HTTPX_TIMEOUT`: Timeout setting for `httpx` requests (default is 30 seconds).
- `HOST`: Host for the server to bind to (default is `127.0.0.1`).
- `PORT`: Port for the server to listen on (default is `8000`).
- `APP_RELOAD`: Enable or disable auto-reload (useful for development; defaults to `false`).
- `WEB_CONCURRENCY`: Number of worker processes (default is `1`).
- `LOG_LEVEL`: Logging level (default is `info`).

## API Endpoints

### `/`

- **Method**: GET
- **Description**: Serves a template with information about the JMESPath proxy application.

### `/test`

- **Method**: POST
- **Description**: Accepts a JSON payload with the data and a JMESPath expression. Returns the result of the expression applied to the data.
- **Request Body**:
  ```json
  {
    "data": { "key": "value" },
    "expression": "optional_jmespath_expression"
  }
  ```

### `/forward`

- **Method**: POST
- **Description**: Forwards incoming JSON data to the configured `FORWARD_URL` after applying the JMESPath expression. Returns the response from the forward URL.
- **Request Body**: JSON payload to be forwarded.

## Development and Testing

### Running the App Locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Start the application:
   ```bash
   python -m jmespath_proxy.cli
   ```

3. Use environment variables to configure the app as needed:
   ```bash
   export JMESPATH_EXPRESSION="user.name"
   export FORWARD_URL="http://example.com/forward"
   ```

### Running Tests

- Use `pytest` to run the test suite:
  ```bash
  pytest tests/
  ```

## Contributing

If you'd like to contribute to the project, please fork the repository and use a feature branch for your work. Pull requests are welcome!

## License

This project is licensed under the MIT License.

## Acknowledgments

- [Litestar Framework](https://litestar.dev)
- [JMESPath](https://jmespath.org/)
- [HTTPX](https://www.python-httpx.org/)
