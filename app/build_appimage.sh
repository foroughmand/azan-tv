#!/bin/bash
# Build AZAN TV AppImage (Linux).
# Run from app dir: ./build_appimage.sh  (or from repo root: ./app/build_appimage.sh)
# Requires: ./build_app.sh and appimagetool

set -e
cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

# Always rebuild so AppImage contains the latest Qt app binary.
# Set SKIP_REBUILD=1 to reuse existing dist/azan-tv.
if [[ "${SKIP_REBUILD:-0}" != "1" ]]; then
  ./build_app.sh
elif [[ ! -f "dist/azan-tv" ]]; then
  echo "dist/azan-tv missing. Run ./build_app.sh first."
  exit 1
fi

APPDIR="AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/azan-tv" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -f "dist/azan-tv" "$APPDIR/usr/bin/azan-tv"
chmod +x "$APPDIR/usr/bin/azan-tv"

# Build bundled runtime Python for live-stream/gen_playlist dependencies.
# Set BUNDLE_STREAM_DEPS=0 to skip and use host python packages.
if [[ "${BUNDLE_STREAM_DEPS:-1}" == "1" ]]; then
  echo "Preparing bundled runtime Python for streaming dependencies..."
  RUNTIME_VENV=".build-runtime-python"
  rm -rf "$RUNTIME_VENV"
  python3 -m venv "$RUNTIME_VENV"
  "$RUNTIME_VENV/bin/python3" -m pip install --upgrade pip setuptools wheel
  "$RUNTIME_VENV/bin/python3" -m pip install -r "$REPO_ROOT/stream/requirements-stream.txt"
  mkdir -p "$APPDIR/usr/share/azan-tv/runtime-python"
  cp -a "$RUNTIME_VENV"/. "$APPDIR/usr/share/azan-tv/runtime-python/"
fi

# Stream, data, and empty keys dirs for backend
mkdir -p "$APPDIR/usr/share/azan-tv/stream" "$APPDIR/usr/share/azan-tv/data" "$APPDIR/usr/share/azan-tv/keys"
if [[ -d "$REPO_ROOT/stream" ]]; then
  for f in live-stream.py gen_playlist.py config.json network-program-hard.json ffplayout-template.yml ffplayout-template.toml; do
    if [[ -f "$REPO_ROOT/stream/$f" ]]; then cp -f "$REPO_ROOT/stream/$f" "$APPDIR/usr/share/azan-tv/stream/$f"; fi
  done
fi
if [[ -f "$REPO_ROOT/data/video-desc.txt" ]]; then cp -f "$REPO_ROOT/data/video-desc.txt" "$APPDIR/usr/share/azan-tv/data/"; fi
# Platform-specific at repo root: ffplayout/linux and bin/linux
if [[ -x "$REPO_ROOT/ffplayout/linux/ffplayout" ]]; then
  mkdir -p "$APPDIR/usr/share/azan-tv/ffplayout/linux"
  cp -f "$REPO_ROOT/ffplayout/linux/ffplayout" "$APPDIR/usr/share/azan-tv/ffplayout/linux/ffplayout"
  chmod +x "$APPDIR/usr/share/azan-tv/ffplayout/linux/ffplayout"
elif [[ -x "$REPO_ROOT/ffplayout/target/debug/ffplayout" ]]; then
  mkdir -p "$APPDIR/usr/share/azan-tv/ffplayout/linux"
  cp -f "$REPO_ROOT/ffplayout/target/debug/ffplayout" "$APPDIR/usr/share/azan-tv/ffplayout/linux/ffplayout"
  chmod +x "$APPDIR/usr/share/azan-tv/ffplayout/linux/ffplayout"
else
  echo "ERROR: ffplayout binary not found. Put it in $REPO_ROOT/ffplayout/linux/ffplayout or build to $REPO_ROOT/ffplayout/target/debug/ffplayout"
  exit 1
fi
mkdir -p "$APPDIR/usr/share/azan-tv/bin/linux"
if [[ -x "$REPO_ROOT/bin/linux/yt-dlp" ]]; then cp -f "$REPO_ROOT/bin/linux/yt-dlp" "$APPDIR/usr/share/azan-tv/bin/linux/yt-dlp"; chmod +x "$APPDIR/usr/share/azan-tv/bin/linux/yt-dlp"; fi
if [[ -x "$REPO_ROOT/bin/linux/mediamtx" ]]; then cp -f "$REPO_ROOT/bin/linux/mediamtx" "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx"; chmod +x "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx"; fi
if [[ -f "$REPO_ROOT/bin/linux/mediamtx.yml" ]]; then cp -f "$REPO_ROOT/bin/linux/mediamtx.yml" "$APPDIR/usr/share/azan-tv/bin/linux/"; fi
if [[ -x "$REPO_ROOT/bin/yt-dlp" ]] && [[ ! -x "$APPDIR/usr/share/azan-tv/bin/linux/yt-dlp" ]]; then cp -f "$REPO_ROOT/bin/yt-dlp" "$APPDIR/usr/share/azan-tv/bin/linux/yt-dlp"; chmod +x "$APPDIR/usr/share/azan-tv/bin/linux/yt-dlp"; fi
if [[ -x "$REPO_ROOT/bin/mediamtx" ]] && [[ ! -x "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx" ]]; then cp -f "$REPO_ROOT/bin/mediamtx" "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx"; chmod +x "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx"; fi
if [[ -f "$REPO_ROOT/bin/mediamtx.yml" ]] && [[ ! -f "$APPDIR/usr/share/azan-tv/bin/linux/mediamtx.yml" ]]; then cp -f "$REPO_ROOT/bin/mediamtx.yml" "$APPDIR/usr/share/azan-tv/bin/linux/"; fi

# Explicitly remove sensitive files from AppImage payload (do not ship keys/)
rm -f \
  "$APPDIR/usr/share/azan-tv/stream/client_secret.json" \
  "$APPDIR/usr/share/azan-tv/stream/user-oauth2.json" \
  "$APPDIR/usr/share/azan-tv/data/client_secret.json" \
  "$APPDIR/usr/share/azan-tv/data/user-oauth2.json" \
  "$APPDIR/usr/share/azan-tv/keys/client_secret.json" \
  "$APPDIR/usr/share/azan-tv/keys/user-oauth2.json" \
  "$APPDIR/usr/share/azan-tv/keys/server.crt" \
  "$APPDIR/usr/share/azan-tv/keys/server.key" \
  "$APPDIR/usr/share/azan-tv/server.crt" \
  "$APPDIR/usr/share/azan-tv/server.key"

cp -f "appimage/AppRun" "$APPDIR/AppRun"
cp -f "appimage/azan-tv.desktop" "$APPDIR/azan-tv.desktop"
cp -f "appimage/azan-tv.svg" "$APPDIR/azan-tv.svg"
cp -f "appimage/azan-tv.desktop" "$APPDIR/usr/share/applications/azan-tv.desktop"
cp -f "appimage/azan-tv.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/azan-tv.svg"
chmod +x "$APPDIR/AppRun"

APPIMAGETOOL="${APPIMAGETOOL:-./appimagetool.AppImage}"
if [[ ! -x "$APPIMAGETOOL" ]]; then
  echo "Downloading appimagetool..."
  wget -q -O appimagetool.AppImage "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x appimagetool.AppImage
  APPIMAGETOOL=./appimagetool.AppImage
fi

ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "azan-tv-x86_64.AppImage"
echo "Done: azan-tv-x86_64.AppImage"
