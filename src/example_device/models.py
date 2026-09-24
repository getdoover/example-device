"""Load approved Python bytes and validate the model's JSON boundary.

This is trusted code execution, not a sandbox. Dataset configuration can select
an approved release; it cannot approve new code. Review changes to this allowlist
with the same care as processor code.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from types import ModuleType
from typing import Any

MAX_MODEL_BYTES = 64 * 1024
MAX_VALUE_BYTES = 64 * 1024
TRUSTED_REPOSITORY = "getdoover/example-device"
# Values are approved source SHA-256 digests, independent of dataset metadata.
APPROVED_MODELS = {
    (
        "vsd",
        "vsd-v1",
    ): "061cb37ef023a66f996819f31e32b6f86041550440285ee70e08fad60ba30061"
}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    app_key: str
    sha256: str
    initial_state: dict[str, Any]
    initial_commands: dict[str, Any]


def json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError(f"{label} must be a JSON object")
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label} must contain finite JSON values") from error
    if len(encoded.encode()) > MAX_VALUE_BYTES:
        raise ValueError(f"{label} exceeds the model value size limit")
    return deepcopy(value)


def require_approved(repository: str, slug: str, spec: ModelSpec) -> None:
    if (
        repository != TRUSTED_REPOSITORY
        or APPROVED_MODELS.get((slug, spec.name)) != spec.sha256
    ):
        raise ValueError("Python model is not approved by this processor release")


@dataclass(frozen=True)
class LoadedModel:
    spec: ModelSpec
    module: ModuleType

    def validate(self, state, commands):
        state = json_object(state, "Model state")
        commands = json_object(commands, "Model commands")
        self.module.validate(state, commands)
        return state, commands

    def step(self, state, commands, seconds):
        state, commands = self.validate(state, commands)
        if (
            type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise ValueError("Model elapsed time must be finite and nonnegative")
        new_state, tags = self.module.step(state, commands, seconds)
        self.validate(new_state, commands)
        tags = json_object(tags, "Model telemetry")
        # Models return scalar leaves under their one declared app, never paths,
        # processor metadata, aggregate instructions, or other app namespaces.
        if any(
            not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,127}", key)
            or type(value) not in (bool, int, float, str)
            for key, value in tags.items()
        ):
            raise ValueError("Model telemetry must contain scalar tag values")
        return deepcopy(new_state), tags

    def command(self, state, commands, method, value):
        state, commands = self.validate(state, commands)
        updated = self.module.command(commands, method, deepcopy(value))
        self.validate(state, updated)
        return deepcopy(updated)


def load_model(repository: str, slug: str, spec: ModelSpec, raw: bytes) -> LoadedModel:
    require_approved(repository, slug, spec)
    if len(raw) > MAX_MODEL_BYTES or hashlib.sha256(raw).hexdigest() != spec.sha256:
        raise ValueError("Python model bytes do not match the approved SHA-256")
    # Do not cache modules: each device load gets a fresh namespace. Code has
    # full processor privileges; hash verification MUST precede compilation.
    module = ModuleType(f"example_model_{spec.sha256}")
    exec(compile(raw, f"{slug}/model.py", "exec"), module.__dict__)
    if module.API_VERSION != 1 or any(
        not callable(getattr(module, name, None))
        for name in ("validate", "step", "command")
    ):
        raise ValueError("Unsupported Python model API")
    model = LoadedModel(spec, module)
    model.step(spec.initial_state, spec.initial_commands, 0)
    return model
