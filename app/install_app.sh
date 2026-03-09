#!/bin/bash
# Install AZAN TV app to application menu (non-AppImage install).
# Run from app dir: ./build_app.sh && ./install_app.sh  (or ./app/install_app.sh from repo root)

set -e
cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

BIN=dist/azan-tv
if [[ ! -f "$BIN" ]]; then
  echo "Run ./build_app.sh first to create dist/azan-tv"
  exit 1
fi

INSTALL_DIR="${AZAN_TV_INSTALL_DIR:-$HOME/.local/opt/azan-tv}"
BIN_DIR="${AZAN_TV_BIN_DIR:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$INSTALL_DIR/share/azan-tv" "$BIN_DIR"

# Binary + runtime resources (stream/ and data/)
cp -f "$BIN" "$INSTALL_DIR/azan-tv.bin"
chmod +x "$INSTALL_DIR/azan-tv.bin"
mkdir -p "$INSTALL_DIR/share/azan-tv/stream" "$INSTALL_DIR/share/azan-tv/data" "$INSTALL_DIR/share/azan-tv/keys"
if [[ -d "$REPO_ROOT/stream" ]]; then
  for f in live-stream.py gen_playlist.py config.json network-program-hard.json ffplayout-template.yml ffplayout-template.toml; do
    if [[ -f "$REPO_ROOT/stream/$f" ]]; then cp -f "$REPO_ROOT/stream/$f" "$INSTALL_DIR/share/azan-tv/stream/$f"; fi
  done
fi
if [[ -f "$REPO_ROOT/data/video-desc.txt" ]]; then cp -f "$REPO_ROOT/data/video-desc.txt" "$INSTALL_DIR/share/azan-tv/data/"; fi
# Prefer platform-specific ffplayout at repo root
if [[ -x "$REPO_ROOT/ffplayout/linux/ffplayout" ]]; then
  mkdir -p "$INSTALL_DIR/share/azan-tv/ffplayout/linux"
  cp -f "$REPO_ROOT/ffplayout/linux/ffplayout" "$INSTALL_DIR/share/azan-tv/ffplayout/linux/ffplayout"
  chmod +x "$INSTALL_DIR/share/azan-tv/ffplayout/linux/ffplayout"
elif [[ -d "$REPO_ROOT/ffplayout" && ! -e "$INSTALL_DIR/share/azan-tv/ffplayout" ]]; then
  cp -R "$REPO_ROOT/ffplayout" "$INSTALL_DIR/share/azan-tv/ffplayout"
  [[ -x "$INSTALL_DIR/share/azan-tv/ffplayout/target/debug/ffplayout" ]] && chmod +x "$INSTALL_DIR/share/azan-tv/ffplayout/target/debug/ffplayout"
fi
if [[ -d "$REPO_ROOT/bin/linux" ]]; then
  mkdir -p "$INSTALL_DIR/share/azan-tv/bin/linux"
  for f in "$REPO_ROOT/bin/linux"/*; do [[ -f "$f" ]] && cp -f "$f" "$INSTALL_DIR/share/azan-tv/bin/linux/"; done
  [[ -x "$REPO_ROOT/bin/linux/yt-dlp" ]] && chmod +x "$INSTALL_DIR/share/azan-tv/bin/linux/yt-dlp"
  [[ -x "$REPO_ROOT/bin/linux/mediamtx" ]] && chmod +x "$INSTALL_DIR/share/azan-tv/bin/linux/mediamtx"
elif [[ -d "$REPO_ROOT/bin" ]]; then
  mkdir -p "$INSTALL_DIR/share/azan-tv/bin/linux"
  for name in yt-dlp mediamtx mediamtx.yml; do
    [[ -f "$REPO_ROOT/bin/$name" ]] && cp -f "$REPO_ROOT/bin/$name" "$INSTALL_DIR/share/azan-tv/bin/linux/$name"
    [[ -x "$REPO_ROOT/bin/$name" ]] && chmod +x "$INSTALL_DIR/share/azan-tv/bin/linux/$name"
  done
fi

# Launcher wrapper sets app root + dedicated workdir
cat > "$INSTALL_DIR/azan-tv" << EOF
#!/bin/sh
export AZAN_TV_ROOT="$INSTALL_DIR/share/azan-tv"
if [ -n "$XDG_DATA_HOME" ]; then
  export AZAN_TV_WORKDIR="$XDG_DATA_HOME/azan-tv"
else
  export AZAN_TV_WORKDIR="$HOME/.local/share/azan-tv"
fi
exec "$INSTALL_DIR/azan-tv.bin" "$@"
EOF
chmod +x "$INSTALL_DIR/azan-tv"

# Symlink so "azan-tv" is in PATH if ~/.local/bin is on PATH
ln -sf "$INSTALL_DIR/azan-tv" "$BIN_DIR/azan-tv" 2>/dev/null || true

# Desktop entry
DESKTOP="$APPS_DIR/azan-tv.desktop"
mkdir -p "$APPS_DIR"
cat > "$DESKTOP" << EOF
[Desktop Entry]
Type=Application
Name=AZAN TV
Comment=Pre- and post-prayer streaming control panel
Exec=$INSTALL_DIR/azan-tv
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;
StartupNotify=true
EOF

echo "Installed launcher: $INSTALL_DIR/azan-tv"
echo "Menu entry: $DESKTOP"
echo "Working folder (data/logs/media/config): ${XDG_DATA_HOME:-$HOME/.local/share}/azan-tv"
