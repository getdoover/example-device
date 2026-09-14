"""Processor status UI exported through the native Doover schema builder."""

from pydoover import ui
from pydoover.tags import Tag, Tags


class ExampleTags(Tags):
    phase = Tag("string", default="initializing")
    import_complete = Tag("boolean", default=False)
    import_progress = Tag("number", default=0)


class ExampleUI(
    ui.UI,
    hidden="$tag.app().import_complete",
    position=0,
    default_open=True,
    colour=ui.Colour.orange,
):
    tags: ExampleTags
    progress = ui.NumericVariable(
        "History importing",
        name="import_progress",
        value=ExampleTags.import_progress,
        units="%",
        precision=0,
        form=ui.Widget.linear,
        ranges=[ui.Range("History importing", 0, 100, ui.Colour.orange)],
        colour=ui.Colour.orange,
        graphable=False,
        show_activity=False,
        position=0,
    )
    notice = ui.TextVariable(
        "Uploading example history",
        value="History is being uploaded. This panel will hide when the import is complete.",
    )
