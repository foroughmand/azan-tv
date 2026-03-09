#!/bin/bash
# Build AZAN TV desktop app for Linux (single executable).
# Run from project root: ./build_app.sh
# Requires: pip install -r requirements-app.txt

set -e
cd "$(dirname "$0")"

python3 - <<'PY'
import importlib.util
missing = []
for mod in ("PySide6", "PyInstaller"):
    if importlib.util.find_spec(mod) is None:
        missing.append(mod)
if missing:
    raise SystemExit(
        "Missing Python packages: " + ", ".join(missing) +
        ". Install with: pip install -r requirements-app.txt"
    )
PY

echo "Building AZAN TV Qt app..."
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name azan-tv \
  --collect-all PySide6 \
  desktop_app.py

echo ""
echo "Done. Executable: dist/azan-tv"
echo "Run with: ./dist/azan-tv"
echo "Build AppImage with: ./build_appimage.sh"
