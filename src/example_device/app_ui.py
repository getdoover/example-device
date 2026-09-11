"""Processor status UI exported through the native Doover schema builder."""

from pydoover import ui
from pydoover.tags import Tag, Tags


class ExampleTags(Tags):
    phase = Tag("string", default="initializing")


class ExampleUI(ui.UI):
    tags: ExampleTags
    notice = ui.TextVariable(
        "Example data",
        value="Inputs are acknowledged but do not change the precreated telemetry.",
    )
    phase = ui.TextVariable("Playback", value=ExampleTags.phase)
