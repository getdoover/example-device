"""Fail closed unless Lambda provides the configured single-writer guarantee."""

from __future__ import annotations


class ConcurrencyConfigurationError(RuntimeError):
    pass


def verify_lambda_serialization(context, client=None) -> None:
    """Check the real AWS setting on every invocation before any Doover writes.

    The execution role needs lambda:GetFunctionConcurrency for this function.
    All example installations must use this one function. Local tests exercise
    Runtime with an explicit serialized transport instead of bypassing this gate.
    """
    arn = getattr(context, "invoked_function_arn", None)
    if not isinstance(arn, str) or ":function:" not in arn:
        raise ConcurrencyConfigurationError(
            "A Lambda context is required for cloud execution"
        )
    function_arn = ":".join(arn.split(":")[:7])
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "lambda",
            config=Config(
                connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}
            ),
        )
    result = client.get_function_concurrency(FunctionName=function_arn)
    if result.get("ReservedConcurrentExecutions") != 1:
        raise ConcurrencyConfigurationError(
            "Set ReservedConcurrentExecutions=1 on this processor function before enabling it"
        )
