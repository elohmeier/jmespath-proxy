from jmespath_proxy.app import apply_jmespath_expression


def test_apply_jmespath_expression_with_merge_all_alerts_labels():
    """Test applying a JMESPath expression that merges labels for all alerts in an array."""
    # Create test data with multiple alerts in the array
    body_data = {
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
    }

    # Query parameters to include in the context
    query_params = {"source": "test-source"}

    # JMESPath expression that merges labels for all alerts
    # Accesses `body` and `query_params` from the root context provided to jmespath.search
    expression = """
    {
      alerts: body.alerts[*].{
        status: status,
        labels: merge(labels, `{"new_label_1": "value1"}`, {source: $.query_params.source})
      }
    }
    """

    # Apply the expression
    result, error = apply_jmespath_expression(expression, body_data, query_params)

    # Verify no errors occurred
    assert error is None

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

    # Verify the result matches the expected output
    assert result == expected_result


def test_apply_jmespath_expression_with_invalid_expression():
    """Test applying an invalid JMESPath expression returns an error."""
    body_data = {"user": {"name": "John", "age": 30}}
    query_params = {}

    # Invalid JMESPath expression
    expression = "invalid["

    # Apply the expression
    result, error = apply_jmespath_expression(expression, body_data, query_params)

    # Verify an error was returned
    assert error is not None
    assert "JMESPath parse error" in error

    # Original data should be returned on error
    assert result == body_data


def test_apply_jmespath_expression_with_empty_expression():
    """Test applying an empty JMESPath expression returns the original data."""
    body_data = {"user": {"name": "John", "age": 30}}
    query_params = {"id": "12345"}

    # Empty expression
    expression = ""

    # Apply the expression
    result, error = apply_jmespath_expression(expression, body_data, query_params)

    # Verify no error was returned
    assert error is None

    # Original data should be returned when expression is empty
    assert result == body_data
