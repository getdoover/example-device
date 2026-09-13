import importlib.util
from pathlib import Path

import bpy

if not getattr(bpy.types, "blendermcp_server", None):
    path = (
        Path.home() / "Library/Application Support/Blender/5.2/scripts/addons/addon.py"
    )
    spec = importlib.util.spec_from_file_location("addon", path)
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    if not hasattr(bpy.types.Scene, "blendermcp_port"):
        addon.register()
    else:
        bpy.ops.blendermcp.start_server()
print("QVB_MCP_READY", bpy.data.filepath, flush=True)
