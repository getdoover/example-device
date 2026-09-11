from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from example_device.concurrency import (
    ConcurrencyConfigurationError,
    verify_lambda_serialization,
)


@pytest.mark.parametrize(
    "setting",
    [{}, {"ReservedConcurrentExecutions": 0}, {"ReservedConcurrentExecutions": 2}],
)
def test_refuses_unserialized_lambda(setting):
    client = Mock()
    client.get_function_concurrency.return_value = setting
    with pytest.raises(ConcurrencyConfigurationError):
        verify_lambda_serialization(
            SimpleNamespace(
                invoked_function_arn="arn:aws:lambda:region:account:function:processor:version"
            ),
            client,
        )


def test_checks_the_real_unqualified_function():
    client = Mock()
    client.get_function_concurrency.return_value = {"ReservedConcurrentExecutions": 1}
    verify_lambda_serialization(
        SimpleNamespace(
            invoked_function_arn="arn:aws:lambda:region:account:function:processor:version"
        ),
        client,
    )
    client.get_function_concurrency.assert_called_once_with(
        FunctionName="arn:aws:lambda:region:account:function:processor"
    )


def test_no_context_cannot_bypass_serialization():
    with pytest.raises(ConcurrencyConfigurationError):
        verify_lambda_serialization(None, Mock())
