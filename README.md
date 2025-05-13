# JMESPath Proxy

Welcome to the JMESPath Proxy Application! This project provides an API service built with the Litestar web framework, allowing users to perform JMESPath queries on incoming JSON data and optionally forward the transformed payload to a specified URL.

## Features

- **JMESPath Expressions**: Apply JMESPath expressions to transform JSON data.
- **Query Parameter Context**: Access URL query parameters within your JMESPath expressions.
- **Forwarding**: Forward transformed JSON payloads to a configurable remote URL.
- **Test Endpoint**: Test JMESPath expressions directly via a test endpoint.
- **Async Support**: Built with async support using `httpx` for HTTP requests.
- **Prometheus Metrics**: Built-in metrics endpoint for monitoring with Prometheus.
- **Configurable via Environment Variables**: Customize the behavior of the application using environment variables.

## Environment Variables

- `JMESPATH_EXPRESSION`: Default JMESPath expression to apply to incoming JSON data.
- `FORWARD_URL`: URL to which the transformed JSON payload will be forwarded.
- `METRICS_ANNOTATION_EXPRESSION`: JMESPath expression to extract labels for Prometheus metrics.
- `HTTPX_TIMEOUT`: Timeout setting for `httpx` requests (default is 30 seconds).
- `VERIFY_SSL`: Enable or disable SSL verification (default is `true`).
- `FORWARD_BASIC_AUTH_USERNAME`: Username for basic auth when forwarding requests (optional).
- `FORWARD_BASIC_AUTH_PASSWORD`: Password for basic auth when forwarding requests (optional).
- `HOST`: Host for the server to bind to (default is `127.0.0.1`).
- `PORT`: Port for the server to listen on (default is `8000`).
- `APP_RELOAD`: Enable or disable auto-reload (useful for development; defaults to `false`).
- `WEB_CONCURRENCY`: Number of worker processes (default is `1`).
- `LOG_LEVEL`: Logging level (default is `info`).

## API Endpoints

### `/`

- **Method**: GET
- **Description**: Serves a template with information about the JMESPath proxy application.

### `/health`

- **Method**: GET
- **Description**: Health check endpoint for readiness/liveness probes.

### `/metrics`

- **Method**: GET
- **Description**: Prometheus metrics endpoint that exposes application metrics in Prometheus format.
- **Metrics**: Includes request counts, response times, status codes, and other standard HTTP metrics. Also includes custom metrics for tracking forwarded requests and errors.

### `/test`

- **Method**: POST
- **Description**: Accepts a JSON payload with the data and an optional JMESPath expression. Returns the result of applying the expression to the data within a context that includes query parameters.
- **Query Parameters**: Any URL query parameters provided are made available in the JMESPath context.
- **Request Body**:
  ```json
  {
    "data": { "key": "value" },
    "expression": "optional_jmespath_expression"
  }
  ```
- **JMESPath Context**: When evaluating the `expression`, the JMESPath context is a dictionary with two keys:
  - `body`: Contains the JSON data from the `data` field of the request body.
  - `query_params`: Contains a dictionary of the parsed URL query parameters (e.g., `/test?id=123` makes `{"id": "123"}` available). Note that if a parameter appears multiple times (`?tag=a&tag=b`), only the first value is included in the `query_params` dictionary (`{"tag": "a"}`).
- **Examples**:
  - Request: `POST /test?user_id=987` with body `{"data": {"user": {"name": "Alice"}}}`
  - Expression: `{"userId": query_params.user_id, "userName": body.user.name}`
  - Result: `{"userId": "987", "userName": "Alice"}`
  - Expression: `query_params.user_id`
  - Result: `"987"` (returned as plain text)

### `/`

- **Method**: POST
- **Description**: Accepts a JSON payload, applies the JMESPath expression configured via `JMESPATH_EXPRESSION`, and forwards the transformed result to the `FORWARD_URL`. The response from the `FORWARD_URL` is returned.
- **Query Parameters**: Any URL query parameters provided are made available in the JMESPath context _if_ a `JMESPATH_EXPRESSION` is configured.
- **Request Body**: The JSON payload to be processed and potentially forwarded.
- **JMESPath Context**: When evaluating the `JMESPATH_EXPRESSION`, the JMESPath context is a dictionary with two keys:
  - `body`: Contains the entire JSON payload from the request body.
  - `query_params`: Contains a dictionary of the parsed URL query parameters (e.g., `/?status=new` makes `{"status": "new"}` available). As with `/test`, only the first value is used for multi-value parameters.
- **Examples**:
  - Request: `POST /?event_source=webhook` with body `{"order": {"id": 101, "items": [...]}}`
  - `JMESPATH_EXPRESSION`: `{"order_id": body.order.id, "source": query_params.event_source, "item_count": length(body.order.items)}`
  - Result forwarded to `FORWARD_URL`: `{"order_id": 101, "source": "webhook", "item_count": 3}` (assuming 3 items)

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
   export JMESPATH_EXPRESSION='{order_id: body.id, source: query_params.channel}'
   export FORWARD_URL="http://example.com/api/receive_order"
   ```
   Then send a request like:
   ```bash
   curl -X POST "http://localhost:8000/?channel=web" -H "Content-Type: application/json" -d '{"id": 123, "value": 45.67}'
   ```
   The proxy would forward `{"order_id": 123, "source": "web"}` to `http://example.com/api/receive_order`.

### Running Tests

- Use `pytest` to run the test suite:
  ```bash
  pytest tests/
  ```

## Prometheus Metrics

### Default Litestar Metrics

The application includes the standard Litestar Prometheus metrics, which track:

- `litestar_requests_total`: Counter for the total number of HTTP requests, labeled by method, path, and status code.
- `litestar_requests_duration_seconds`: Histogram for the duration of HTTP requests in seconds.
- `litestar_requests_in_progress`: Gauge for the number of HTTP requests currently being processed.
- `litestar_responses_total`: Counter for the total number of HTTP responses, labeled by status code.

These metrics are automatically exposed at the `/metrics` endpoint in Prometheus format.

### Custom Prometheus Metrics

The application also provides the following custom metrics:

- `jmespath_proxy_forwarded_total`: Counter for the total number of messages successfully forwarded. Can be labeled using the `METRICS_ANNOTATION_EXPRESSION`.
- `jmespath_proxy_forward_errors_total`: Counter for errors encountered during forwarding, labeled by error type.
- `jmespath_proxy_forward_duration_seconds`: Histogram for the duration of forwarded HTTP requests in seconds.

### Using Metrics Annotation Expression

The `METRICS_ANNOTATION_EXPRESSION` allows you to add custom labels to the `jmespath_proxy_forwarded_total` metric based on the request content:

```
export METRICS_ANNOTATION_EXPRESSION='{alert_name: body.alerts[0].labels.alertname || "unknown", status: body.status || "unknown"}'
```

This would add `alert_name` and `status` labels to the metric, making it possible to filter and group metrics by these dimensions in Prometheus.

## Contributing

If you'd like to contribute to the project, please fork the repository and use a feature branch for your work. Pull requests are welcome!

## License

This project is licensed under the MIT License.

## Acknowledgments

- [Litestar Framework](https://litestar.dev)
- [JMESPath](https://jmespath.org/)
- [HTTPX](https://www.python-httpx.org/)
