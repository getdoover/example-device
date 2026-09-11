"""Doover example-device playback processor."""


def handler(event, context):
    """Lambda entry point; framework imports stay out of the pure data tools."""
    from .application import invoke

    return invoke(event, context)
