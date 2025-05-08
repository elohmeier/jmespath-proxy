from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import USE_CLIENT_DEFAULT, HTTPError
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK
from litestar.testing import AsyncTestClient

from jmespath_proxy.app import app as application


@pytest_asyncio.fixture(scope="function")
async def test_client() -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Create an async test client for testing the application."""
    # Pass the imported app instance
    async with AsyncTestClient(app=application) as client:
        yield client


@pytest.mark.asyncio
async def test_index_endpoint(test_client):
    """Test the index endpoint returns the expected template."""
    response = await test_client.get("/")
    assert response.status_code == HTTP_200_OK
    assert "text/html" in response.headers["content-type"]
    assert "JMESPath Proxy" in response.text


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_expression(test_client):
    """Test the test_jmes endpoint with a custom expression."""
    test_data = {
        "data": {"user": {"name": "John", "age": 30}},
        "expression": "body.user.name",
    }
    response = await test_client.post("/test", json=test_data)
    assert response.status_code == HTTP_200_OK
    # The endpoint returns the result as plain text when it's a string
    assert response.text == "John"


@pytest.mark.asyncio
async def test_test_jmes_endpoint_without_expression(test_client):
    """Test the test_jmes endpoint without an expression returns the original data."""
    test_data = {"data": {"user": {"name": "John", "age": 30}}}
    # Patch the global JMESPATH_EXPRESSION to be empty for this test case
    with patch("jmespath_proxy.app.JMESPATH_EXPRESSION", ""):
        response = await test_client.post("/test", json=test_data)
        assert response.status_code == HTTP_200_OK
        assert response.json() == test_data["data"]


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_invalid_expression(test_client):
    """Test the test_jmes endpoint with an invalid expression returns an error."""
    test_data = {
        "data": {"user": {"name": "John", "age": 30}},
        "expression": "invalid[",
    }
    response = await test_client.post("/test", json=test_data)
    assert response.status_code == HTTP_200_OK
    assert "error" in response.json()
    assert "JMESPath parse error" in response.json()["error"]
    assert "original_data" in response.json()
    assert "query_params" in response.json()


@pytest.mark.asyncio
async def test_forward_json_without_forward_url(test_client):
    """Test the forward_json endpoint without a FORWARD_URL returns an error."""
    # Patch the actual global variable used by the app
    with patch("jmespath_proxy.app.FORWARD_URL", ""):
        test_data = {"user": {"name": "John", "age": 30}}
        response = await test_client.post("/", json=test_data)
        assert response.status_code == HTTP_200_OK
        assert "error" in response.json()
        assert "FORWARD_URL environment variable is not set" in response.json()["error"]


@pytest.mark.asyncio
async def test_forward_json_with_jmespath_expression(test_client):
    """Test the forward_json endpoint with a JMESPath expression."""
    # Patch the actual global variables used by the app
    with (
        patch("jmespath_proxy.app.FORWARD_URL", "http://mock.example.com"),
        patch("jmespath_proxy.app.JMESPATH_EXPRESSION", "body.user.name"),
    ):
        test_data = {"user": {"name": "John", "age": 30}}

        # Mock the httpx client post method stored in app state
        mock_post = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        # Provide a dictionary for headers
        mock_response.headers = {"content-type": "application/json"}

        # Ensure the mock .json() method is also an async function if needed by app code
        async def mock_json():
            return {"result": "success"}

        mock_response.json = mock_json
        mock_response.raise_for_status = lambda: None  # Mock this to do nothing on 200
        mock_post.return_value = mock_response

        # Patch the post method on the actual client instance in the app state
        with patch.object(test_client.app.state.httpx_client, "post", mock_post):
            response = await test_client.post("/", json=test_data)

            # Expect 200 OK now
            assert response.status_code == HTTP_200_OK
            # The app should return the JSON content from the mock response
            assert response.json() == {"result": "success"}

            # Verify the transformed data was sent and auth was passed
            mock_post.assert_awaited_once_with(
                "http://mock.example.com", json="John", auth=USE_CLIENT_DEFAULT
            )


@pytest.mark.asyncio
async def test_forward_json_http_error(test_client):
    """Test the forward_json endpoint handles HTTP errors properly."""
    # Patch the actual global variable used by the app
    with (
        patch("jmespath_proxy.app.FORWARD_URL", "http://mock.example.com"),
        patch("jmespath_proxy.app.JMESPATH_EXPRESSION", ""),
    ):  # No expression for this test
        test_data = {"user": {"name": "John", "age": 30}}

        # Mock the httpx client post method to raise an HTTPError
        mock_post = AsyncMock(side_effect=HTTPError("Connection error"))

        with patch.object(test_client.app.state.httpx_client, "post", mock_post):
            response = await test_client.post("/", json=test_data)

            # Expect 200 OK now, returning the error payload
            assert response.status_code == HTTP_200_OK
            assert "error" in response.json()
            # Check the correct error message is present
            assert (
                "Failed to forward request: Connection error"
                in response.json()["error"]
            )
            # The original data should be the *untransformed* data because JMESPATH_EXPRESSION is ""
            assert response.json()["original_data"] == test_data
            # Query params should be included in the error response
            assert "query_params" in response.json()

            mock_post.assert_awaited_once_with(
                "http://mock.example.com", json=test_data, auth=USE_CLIENT_DEFAULT
            )


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_query_params_and_expression(test_client):
    """Test the test_jmes endpoint with query params and an expression accessing them."""
    test_data = {
        "data": {"user": {"name": "John", "age": 30}},
        "expression": "query_params.user_id",  # Access query param
    }
    response = await test_client.post("/test?user_id=12345", json=test_data)
    assert response.status_code == HTTP_200_OK
    # Query param 'user_id' should be accessible via 'query_params.user_id'
    assert response.text == "12345"  # JMESPath string result becomes text


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_query_params_accessing_body_data(test_client):
    """Test the test_jmes endpoint with query params and an expression accessing body data."""
    test_data = {
        "data": {"user": {"name": "John", "age": 30}},
        "expression": "body.user.name",  # Access body data
    }
    response = await test_client.post("/test?user_id=12345", json=test_data)
    assert response.status_code == HTTP_200_OK
    # Body data should be accessible via 'body.user.name'
    assert response.text == "John"


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_query_params_and_composite_expression(
    test_client,
):
    """Test the test_jmes endpoint with query params and a composite expression."""
    test_data = {
        "data": {"user": {"name": "John", "age": 30}},
        "expression": "{user_name: body.user.name, request_id: query_params.req_id}",
    }
    response = await test_client.post("/test?req_id=abcde", json=test_data)
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"user_name": "John", "request_id": "abcde"}


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_query_params_but_no_expression(test_client):
    """Test the test_jmes endpoint with query params but no expression (should ignore params)."""
    test_data = {"data": {"user": {"name": "John", "age": 30}}}
    # Patch the global JMESPATH_EXPRESSION to be empty for this test case
    with patch("jmespath_proxy.app.JMESPATH_EXPRESSION", ""):
        response = await test_client.post("/test?user_id=12345", json=test_data)
        assert response.status_code == HTTP_200_OK
        # Expect original data back, query params ignored
        assert response.json() == test_data["data"]


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_alert_label_merge_expression(test_client):
    """Test the test_jmes endpoint with an expression that merges labels into the first alert."""
    # Create test data with an alerts array containing one alert with labels
    test_data = {
        "data": {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "Test", "instance": "localhost:9090"},
                }
            ]
        },
        "expression": '{ alerts: body.alerts[*].{ status: status, labels: merge(labels, `{"new_label_1": "value1"}`, {source: $.query_params.source}) }}',
    }

    # Send request with source query parameter
    response = await test_client.post("/test?source=test-source", json=test_data)
    assert response.status_code == HTTP_200_OK

    # Expected result: the list of alerts wrapped in an 'alerts' key
    expected_result = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "Test",
                    "instance": "localhost:9090",
                    "new_label_1": "value1",
                    "source": "test-source",
                },
            }
        ]
    }

    assert response.json() == expected_result


@pytest.mark.asyncio
async def test_test_jmes_endpoint_with_merge_all_alerts_labels(test_client):
    """Test the test_jmes endpoint with an expression that merges labels for all alerts in the array."""
    # Create test data with multiple alerts in the array
    test_data = {
        "data": {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "Test1", "instance": "localhost:9090"},
                },
                {
                    "status": "resolved",
                    "labels": {"alertname": "Test2", "instance": "localhost:9091"},
                },
            ]
        },
        # Using the same expression format as the other test for consistency
        "expression": '{ alerts: body.alerts[*].{ status: status, labels: merge(labels, `{"new_label_1": "value1"}`, {source: $.query_params.source}) }}',
    }

    # Send request with source query parameter
    response = await test_client.post("/test?source=test-source", json=test_data)
    assert response.status_code == HTTP_200_OK

    # Expected result: all alerts with merged labels
    expected_result = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "Test1",
                    "instance": "localhost:9090",
                    "new_label_1": "value1",
                    "source": "test-source",
                },
            },
            {
                "status": "resolved",
                "labels": {
                    "alertname": "Test2",
                    "instance": "localhost:9091",
                    "new_label_1": "value1",
                    "source": "test-source",
                },
            },
        ]
    }

    assert response.json() == expected_result


@pytest.mark.asyncio
async def test_forward_json_with_query_params_and_expression(test_client):
    """Test the forward_json endpoint with query params and an expression accessing them."""
    # Patch the actual global variables used by the app
    with (
        patch("jmespath_proxy.app.FORWARD_URL", "http://mock.example.com/forward"),
        patch(
            "jmespath_proxy.app.JMESPATH_EXPRESSION",
            "{user_id: body.user.id, source: query_params.source}",
        ),
    ):
        test_data = {"user": {"id": "user123", "name": "John"}}
        query_params = "?source=web"

        # Mock the httpx client post method
        mock_post = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        async def mock_json():
            return {"status": "received"}

        mock_response.json = mock_json
        mock_response.raise_for_status = lambda: None
        mock_post.return_value = mock_response

        with patch.object(test_client.app.state.httpx_client, "post", mock_post):
            response = await test_client.post(f"/{query_params}", json=test_data)

            assert response.status_code == HTTP_200_OK
            assert response.json() == {"status": "received"}

            # Verify the transformed data sent includes query params
            expected_payload = {"user_id": "user123", "source": "web"}
            mock_post.assert_awaited_once_with(
                "http://mock.example.com/forward",
                json=expected_payload,
                auth=USE_CLIENT_DEFAULT,
            )


@pytest.mark.asyncio
async def test_forward_json_with_query_params_but_no_expression(test_client):
    """Test the forward_json endpoint with query params but no expression (should ignore params)."""
    # Patch the actual global variable used by the app
    with (
        patch("jmespath_proxy.app.FORWARD_URL", "http://mock.example.com/forward"),
        patch("jmespath_proxy.app.JMESPATH_EXPRESSION", ""),  # No expression
    ):
        test_data = {"user": {"name": "John", "age": 30}}
        query_params = "?extra_param=ignore_me"

        # Mock the httpx client post method
        mock_post = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        async def mock_json():
            return {"status": "received original"}

        mock_response.json = mock_json
        mock_response.raise_for_status = lambda: None
        mock_post.return_value = mock_response

        with patch.object(test_client.app.state.httpx_client, "post", mock_post):
            response = await test_client.post(f"/{query_params}", json=test_data)

            assert response.status_code == HTTP_200_OK
            assert response.json() == {"status": "received original"}

            # Verify the original data was sent (query params not included in payload)
            mock_post.assert_awaited_once_with(
                "http://mock.example.com/forward",
                json=test_data,
                auth=USE_CLIENT_DEFAULT,
            )
