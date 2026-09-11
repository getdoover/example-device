#!/bin/sh
set -eu

cd "$(dirname "$0")"

# Match the Python version and arm64 architecture in doover_config.json.
mkdir -p build
uv export --frozen --no-dev --no-editable --no-emit-project --quiet \
    --output-file build/processor-requirements.txt
rm -rf build/processor-package
rm -f package.zip
uv pip install \
    --no-deps \
    --no-installer-metadata \
    --no-compile-bytecode \
    --python-platform aarch64-manylinux2014 \
    --python 3.13 \
    --target build/processor-package \
    --requirements build/processor-requirements.txt

# Include dependencies and processor source only, never the whole repository.
uv run --no-project --python 3.13 python - <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

dependencies = Path("build/processor-package")
with ZipFile("build/processor-package.zip", "w", ZIP_DEFLATED) as archive:
    for path in sorted(dependencies.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(dependencies))
    for path in sorted(Path("src/example_device").glob("*.py")):
        archive.write(path, path)
Path("build/processor-package.zip").replace("package.zip")
print("Built package.zip for Python 3.13 on Linux arm64")
PY
