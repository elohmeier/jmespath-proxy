from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import HTTPError
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
        "expression": "user.name",
    }
    response = await test_client.post("/test", json=test_data)
    # Expect 200 OK now
    assert response.status_code == HTTP_200_OK
    # Now the endpoint should correctly return "John"
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
        patch("jmespath_proxy.app.JMESPATH_EXPRESSION", "user.name"),
    ):
        test_data = {"user": {"name": "John", "age": 30}}

        # Mock the httpx client post method stored in app state
        # Ensure the client and state are available before mocking
        # The test_client fixture ensures the lifespan has run
        mock_post = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200

        # Ensure the mock .json() method is also an async function if needed by app code
        async def mock_json():
            return {"result": "success"}

        mock_response.json = mock_json
        mock_response.raise_for_status = lambda: None  # Mock this to do nothing on 200
        mock_post.return_value = mock_response

        # Patch the post method on the actual client instance in the app state
        # The path needs to point to where the AsyncClient instance actually is
        # which the test_client makes available via its app attribute.
        with patch.object(test_client.app.state.httpx_client, "post", mock_post):
            response = await test_client.post("/", json=test_data)

            # Expect 200 OK now
            assert response.status_code == HTTP_200_OK
            assert response.json() == {"result": "success"}

            # Verify the transformed data was sent
            mock_post.assert_awaited_once_with("http://mock.example.com", json="John")


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

            mock_post.assert_awaited_once_with(
                "http://mock.example.com", json=test_data
            )
