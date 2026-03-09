#!/bin/bash
# Build AZAN TV desktop app for macOS (.app bundle).
# Run from app dir: ./build_app_mac.sh  (or from repo root: ./app/build_app_mac.sh)
# Requires: pip install -r requirements-app.txt

set -e
cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script is for macOS only. Use build_app.sh for Linux."
  exit 1
fi

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

echo "Building AZAN TV Qt app for macOS..."
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "AZAN TV" \
  --collect-all PySide6 \
  desktop_app.py

APP="dist/AZAN TV.app"
RESOURCES="$APP/Contents/Resources/azan-tv"
MACOS="$APP/Contents/MacOS"

# Copy stream/, data/; create empty keys/ (secrets are not bundled)
mkdir -p "$RESOURCES/stream" "$RESOURCES/data" "$RESOURCES/keys"
if [[ -d "$REPO_ROOT/stream" ]]; then
  for f in live-stream.py gen_playlist.py config.json network-program-hard.json ffplayout-template.yml ffplayout-template.toml; do
    if [[ -f "$REPO_ROOT/stream/$f" ]]; then cp -f "$REPO_ROOT/stream/$f" "$RESOURCES/stream/$f"; fi
  done
fi
if [[ -f "$REPO_ROOT/data/video-desc.txt" ]]; then cp -f "$REPO_ROOT/data/video-desc.txt" "$RESOURCES/data/"; fi
if [[ -d bundles ]]; then
  cp -R bundles "$RESOURCES/"
fi
# Bundle Python runtime with stream deps so the .app runs without user installing libraries (like AppImage).
# Set BUNDLE_STREAM_DEPS=0 to skip and use system python3 + your installed packages.
if [[ "${BUNDLE_STREAM_DEPS:-1}" == "1" ]]; then
  echo "Bundling runtime Python (stream dependencies)..."
  RUNTIME_VENV=".build-runtime-python-mac"
  rm -rf "$RUNTIME_VENV"
  python3 -m venv "$RUNTIME_VENV"
  "$RUNTIME_VENV/bin/python3" -m pip install --upgrade pip setuptools wheel -q
  "$RUNTIME_VENV/bin/python3" -m pip install -r "$REPO_ROOT/stream/requirements-stream.txt" -q
  mkdir -p "$RESOURCES/runtime-python"
  (cd "$RUNTIME_VENV" && cp -R . "$RESOURCES/runtime-python/")
  echo "Bundled runtime-python (stream deps)"
fi
# Platform-specific folders at repo root: bin/mac and ffplayout/mac
mkdir -p "$RESOURCES/bin/mac"
if [[ -x "$REPO_ROOT/ffplayout/mac/ffplayout" ]]; then
  mkdir -p "$RESOURCES/ffplayout/mac"
  cp -f "$REPO_ROOT/ffplayout/mac/ffplayout" "$RESOURCES/ffplayout/mac/ffplayout"
  chmod +x "$RESOURCES/ffplayout/mac/ffplayout"
  echo "Bundled ffplayout (mac)"
elif [[ -x "$REPO_ROOT/ffplayout/target/debug/ffplayout" ]]; then
  mkdir -p "$RESOURCES/ffplayout/mac"
  cp -f "$REPO_ROOT/ffplayout/target/debug/ffplayout" "$RESOURCES/ffplayout/mac/ffplayout"
  chmod +x "$RESOURCES/ffplayout/mac/ffplayout"
  echo "Bundled ffplayout (from target/debug)"
fi
for name in yt-dlp mediamtx; do
  if [[ -x "$REPO_ROOT/bin/mac/$name" ]]; then cp -f "$REPO_ROOT/bin/mac/$name" "$RESOURCES/bin/mac/$name"; chmod +x "$RESOURCES/bin/mac/$name"; echo "Bundled $name (bin/mac)"; fi
  if [[ -x "$REPO_ROOT/bin/$name" ]] && [[ ! -x "$RESOURCES/bin/mac/$name" ]]; then cp -f "$REPO_ROOT/bin/$name" "$RESOURCES/bin/mac/$name"; chmod +x "$RESOURCES/bin/mac/$name"; echo "Bundled $name"; fi
done
if [[ -f "$REPO_ROOT/bin/mac/mediamtx.yml" ]]; then cp -f "$REPO_ROOT/bin/mac/mediamtx.yml" "$RESOURCES/bin/mac/"; fi
if [[ -f "$REPO_ROOT/bin/mediamtx.yml" ]] && [[ ! -f "$RESOURCES/bin/mac/mediamtx.yml" ]]; then cp -f "$REPO_ROOT/bin/mediamtx.yml" "$RESOURCES/bin/mac/"; fi
# Optional: download Mac binaries into repo root bin/mac/
if [[ "${BUNDLE_MAC_BINARIES:-0}" == "1" ]]; then
  echo "Downloading Mac binaries into $REPO_ROOT/bin/mac/..."
  mkdir -p "$REPO_ROOT/bin/mac"
  arch=$(uname -m)
  if [[ "$arch" == "arm64" ]]; then MTX_ARCH="darwin_arm64"; else MTX_ARCH="darwin_amd64"; fi
  if [[ ! -x "$REPO_ROOT/bin/mac/yt-dlp" ]]; then
    curl -sL -o "$REPO_ROOT/bin/mac/yt-dlp" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    chmod +x "$REPO_ROOT/bin/mac/yt-dlp"
    echo "Downloaded yt-dlp (Mac)"
  fi
  MTX_VER="v1.12.0"
  if [[ ! -x "$REPO_ROOT/bin/mac/mediamtx" ]]; then
    (cd "$REPO_ROOT/bin/mac" && curl -sL "https://github.com/bluenviron/mediamtx/releases/download/${MTX_VER}/mediamtx_${MTX_VER#v}_${MTX_ARCH}.tar.gz" | tar xz)
    for name in mediamtx mediamtx.yml; do [[ -f "$REPO_ROOT/bin/mac/$name" ]] && :; done
    echo "Downloaded mediamtx (Mac $MTX_ARCH)"
  fi
  if [[ -x "$REPO_ROOT/bin/mac/yt-dlp" ]]; then cp -f "$REPO_ROOT/bin/mac/yt-dlp" "$RESOURCES/bin/mac/yt-dlp"; chmod +x "$RESOURCES/bin/mac/yt-dlp"; fi
  if [[ -x "$REPO_ROOT/bin/mac/mediamtx" ]]; then cp -f "$REPO_ROOT/bin/mac/mediamtx" "$RESOURCES/bin/mac/mediamtx"; chmod +x "$RESOURCES/bin/mac/mediamtx"; fi
  if [[ -f "$REPO_ROOT/bin/mac/mediamtx.yml" ]]; then cp -f "$REPO_ROOT/bin/mac/mediamtx.yml" "$RESOURCES/bin/mac/"; fi
fi
# Exclude secrets/certs from bundle (do not ship keys/)
rm -f "$RESOURCES/stream/client_secret.json" "$RESOURCES/stream/user-oauth2.json" \
  "$RESOURCES/data/client_secret.json" "$RESOURCES/data/user-oauth2.json" \
  "$RESOURCES/keys/client_secret.json" "$RESOURCES/keys/user-oauth2.json" \
  "$RESOURCES/keys/server.crt" "$RESOURCES/keys/server.key" \
  "$RESOURCES/server.crt" "$RESOURCES/server.key" 2>/dev/null || true

# Launcher script sets AZAN_TV_ROOT so the app finds live-stream.py and config
REAL_BIN="$MACOS/azan-tv-bin"
EXE=""
for f in "$MACOS"/*; do
  if [[ -f "$f" && -x "$f" ]]; then EXE="$f"; break; fi
done
if [[ -z "$EXE" ]]; then
  echo "ERROR: No executable found in $MACOS"
  exit 1
fi
mv "$EXE" "$REAL_BIN"
cat > "$MACOS/AZAN TV" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export AZAN_TV_ROOT="$DIR/../Resources/azan-tv"
exec "$DIR/azan-tv-bin" "$@"
LAUNCHER
chmod +x "$MACOS/AZAN TV"
chmod +x "$REAL_BIN"

echo ""
echo "Done: $APP"
echo "Open with: open \"$APP\""
echo "Data folder: ~/Library/Application Support/azan-tv"
