#!/bin/bash
# Build AZAN TV desktop app for macOS (.app bundle) and optionally a DMG for install on another Mac.
# Run from app dir: ./build_app_mac.sh  (or from repo root: ./app/build_app_mac.sh)
# Requires: pip install -r requirements-app.txt
#
# Bundle layout (Contents/Resources/azan-tv) matches repo so relative paths work:
#   stream/, data/, keys/, bundles/, bin/mac/, ffplayout/mac/, runtime-python/
# Put your Mac binaries (ffmpeg, ffprobe, yt-dlp, mediamtx, etc.) in repo bin/mac/ or bin/
# to have them included. Set SKIP_DMG=1 to skip creating the .dmg file.

set -Eeuo pipefail
trap 'status=$?; echo "ERROR: build_app_mac.sh failed at line $LINENO: $BASH_COMMAND" >&2; exit $status' ERR
cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"
BUILD_FFMPEG_STATIC="${BUILD_FFMPEG_STATIC:-1}"
FORCE_FFMPEG_REBUILD="${FORCE_FFMPEG_REBUILD:-0}"
FFMPEG_SRC_DIR="${FFMPEG_SRC_DIR:-$REPO_ROOT/bin/build/ffmpeg-custom/src/ffmpeg-8.0.1}"
FFMPEG_STAGE_DIR="${FFMPEG_STAGE_DIR:-$FFMPEG_SRC_DIR/stage-static}"
BUNDLE_MAC_BINARIES=1
APP_NAME="${APP_NAME:-AzanTV}"
APP_BUNDLE_ID="${APP_BUNDLE_ID:-com.azan.tv}"
TARGET_ARCH="${TARGET_ARCH:-$(uname -m)}"
# RELEASE_VERSION="${RELEASE_VERSION:-$(git -C "$REPO_ROOT" describe --tags --dirty --always 2>/dev/null || date +%Y%m%d)}"
RELEASE_VERSION="0.1.0"
RELEASE_FILE_BASENAME="${RELEASE_FILE_BASENAME:-${APP_NAME}-macos-${TARGET_ARCH}-${RELEASE_VERSION}}"
ICON_PNG="${ICON_PNG:-$REPO_ROOT/app/bundles/azan-tv-icon.png}"
ICON_ICNS="${ICON_ICNS:-$REPO_ROOT/app/bundles/${APP_NAME}.icns}"
REQUIRE_FFPLAY="${REQUIRE_FFPLAY:-1}"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script is for macOS only. Use build_app.sh for Linux."
  exit 1
fi

for tool in sips iconutil; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required macOS tool: $tool"
    exit 1
  fi
done

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
collect_homebrew_deps() {
  local seen_file="$1"
  shift
  local queue=("$@")

  : > "$seen_file"

  while [[ ${#queue[@]} -gt 0 ]]; do
    local f="${queue[0]}"
    queue=("${queue[@]:1}")

    [[ -e "$f" ]] || continue
    grep -Fxq "$f" "$seen_file" && continue
    echo "$f" >> "$seen_file"

    while IFS= read -r dep; do
      [[ -n "$dep" ]] || continue
      queue+=("$dep")
    done < <(otool -L "$f" | awk '/\/opt\/homebrew\// {print $1}')
  done
}

collect_non_system_deps() {
  local seen_file="$1"
  shift
  local queue=("$@")

  : > "$seen_file"

  while [[ ${#queue[@]} -gt 0 ]]; do
    local f="${queue[0]}"
    queue=("${queue[@]:1}")

    [[ -e "$f" ]] || continue
    grep -Fxq "$f" "$seen_file" && continue
    echo "$f" >> "$seen_file"

    while IFS= read -r dep; do
      [[ -n "$dep" ]] || continue
      case "$dep" in
        /System/*|/usr/lib/*)
          continue
          ;;
      esac
      if [[ "$dep" == @rpath/* ]]; then
        dep="$(resolve_runtime_dep_path "$dep" "$f" || true)"
      fi
      [[ -n "$dep" ]] || continue
      queue+=("$dep")
    done < <(otool -L "$f" | awk 'NR > 1 {print $1}')
  done
}

resolve_runtime_dep_path() {
  local dep="$1"
  local target="$2"
  local base
  base="$(basename "$dep")"
  local target_dir
  target_dir="$(cd "$(dirname "$target")" && pwd)"
  local candidates=(
    "$target_dir/$base"
    "$target_dir/../$base"
    "$target_dir/../../$base"
    "$target_dir/../../../$base"
    "/opt/homebrew/lib/$base"
    "/opt/homebrew/opt/libffi/lib/$base"
    "/usr/local/lib/$base"
    "/usr/local/opt/libffi/lib/$base"
  )
  local cand
  for cand in "${candidates[@]}"; do
    if [[ -f "$cand" ]]; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  echo "WARNING: Could not resolve runtime dependency $dep for $target" >&2
  return 1
}

runtime_loader_ref() {
  local target="$1"
  local runtime_lib="$2"
  local base="$3"
  local target_dir rel
  target_dir="$(cd "$(dirname "$target")" && pwd)"
  rel="$(python3 - "$target_dir" "$runtime_lib" <<'PY'
import os
import sys
target_dir, runtime_lib = sys.argv[1], sys.argv[2]
print(os.path.relpath(runtime_lib, target_dir))
PY
)"
  if [[ "$rel" == "." ]]; then
    printf '%s\n' "@loader_path/$base"
  else
    printf '%s\n' "@loader_path/$rel/$base"
  fi
}
check_for_unbundled_homebrew_refs() {
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  local APP_FW="$APP_MAC_BIN/Frameworks"
  local bad=0

  echo "Checking for remaining Homebrew references..."

  for f in "$APP_MAC_BIN/ffmpeg" "$APP_MAC_BIN/ffprobe" "$APP_MAC_BIN/ffplay" "$APP_FW"/*.dylib; do
    [[ -e "$f" ]] || continue
    if otool -L "$f" | awk '{print $1}' | grep -q '^/opt/homebrew/'; then
      echo "ERROR: Unbundled Homebrew reference remains in: $f"
      otool -L "$f" | awk '{print $1}' | grep '^/opt/homebrew/' || true
      bad=1
    fi
  done

  if [[ "$bad" -ne 0 ]]; then
    echo "Bundling failed: some binaries still point to /opt/homebrew/"
    exit 1
  fi
}
bundle_ffmpeg_mac() {
  local BIN_DIR="$REPO_ROOT/bin/mac"
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  local APP_FW="$APP_MAC_BIN/Frameworks"
  local dep_list="$APP_MAC_BIN/.ffmpeg_deps.txt"

  mkdir -p "$APP_MAC_BIN" "$APP_FW"

  cp -f "$BIN_DIR/ffmpeg" "$APP_MAC_BIN/ffmpeg"
  cp -f "$BIN_DIR/ffprobe" "$APP_MAC_BIN/ffprobe"
  if [[ -x "$BIN_DIR/ffplay" ]]; then
    cp -f "$BIN_DIR/ffplay" "$APP_MAC_BIN/ffplay"
  fi
  chmod +x "$APP_MAC_BIN/ffmpeg" "$APP_MAC_BIN/ffprobe"
  if [[ -e "$APP_MAC_BIN/ffplay" ]]; then
    chmod +x "$APP_MAC_BIN/ffplay"
  fi

  local dep_targets=("$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe")
  if [[ -x "$BIN_DIR/ffplay" ]]; then
    dep_targets+=("$BIN_DIR/ffplay")
  fi
  collect_homebrew_deps "$dep_list" "${dep_targets[@]}"

  while IFS= read -r lib; do
    [[ -n "$lib" ]] || continue
    cp -f "$lib" "$APP_FW/"
    chmod 644 "$APP_FW/$(basename "$lib")"
  done < "$dep_list"

  # install_name_tool -add_rpath "@executable_path/Frameworks" "$APP_MAC_BIN/ffmpeg" || true
  # install_name_tool -add_rpath "@executable_path/Frameworks" "$APP_MAC_BIN/ffprobe" || true

  install_name_tool -add_rpath "@executable_path/Frameworks" "$APP_MAC_BIN/ffmpeg"
  install_name_tool -add_rpath "@loader_path/Frameworks" "$APP_MAC_BIN/ffmpeg"
  install_name_tool -add_rpath "@loader_path/Frameworks" "$APP_MAC_BIN/ffprobe"
  if [[ -e "$APP_MAC_BIN/ffplay" ]]; then
    install_name_tool -add_rpath "@executable_path/Frameworks" "$APP_MAC_BIN/ffplay"
    install_name_tool -add_rpath "@loader_path/Frameworks" "$APP_MAC_BIN/ffplay"
  fi
  
  while IFS= read -r lib; do
    [[ -n "$lib" ]] || continue
    local base
    base="$(basename "$lib")"
    install_name_tool -change "$lib" "@executable_path/Frameworks/$base" "$APP_MAC_BIN/ffmpeg" || true
    install_name_tool -change "$lib" "@executable_path/Frameworks/$base" "$APP_MAC_BIN/ffprobe" || true
    if [[ -e "$APP_MAC_BIN/ffplay" ]]; then
      install_name_tool -change "$lib" "@executable_path/Frameworks/$base" "$APP_MAC_BIN/ffplay" || true
    fi
  done < "$dep_list"
}
patch_bundled_dylibs() {
  local APP_FW="$RESOURCES/bin/mac/Frameworks"

  for f in "$APP_FW"/*.dylib; do
    [[ -e "$f" ]] || continue
    while IFS= read -r dep; do
      [[ -n "$dep" ]] || continue
      local depbase
      depbase="$(basename "$dep")"
      if [[ -f "$APP_FW/$depbase" ]]; then
        install_name_tool -change "$dep" "@loader_path/$depbase" "$f" || true
      fi
    done < <(otool -L "$f" | awk '/\/opt\/homebrew\// {print $1}')
    install_name_tool -id "@loader_path/$(basename "$f")" "$f" || true
  done
}
resign_ffmpeg_bundle_mac() {
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  local APP_FW="$APP_MAC_BIN/Frameworks"

  find "$APP_FW" -name '*.dylib' -print0 | while IFS= read -r -d '' f; do
    codesign --force --sign - "$f"
  done

  codesign --force --sign - "$APP_MAC_BIN/ffmpeg"
  codesign --force --sign - "$APP_MAC_BIN/ffprobe"
  if [[ -e "$APP_MAC_BIN/ffplay" ]]; then
    codesign --force --sign - "$APP_MAC_BIN/ffplay"
  fi
}

bundle_runtime_python_dylibs() {
  local RUNTIME_ROOT="$RESOURCES_ABS/runtime-python"
  local RUNTIME_BIN="$RUNTIME_ROOT/bin/python3"
  local RUNTIME_LIB="$RUNTIME_ROOT/lib"
  local dep_list="$RUNTIME_ROOT/.python_deps.txt"

  [[ -x "$RUNTIME_BIN" ]] || return 0
  mkdir -p "$RUNTIME_LIB"

  local targets=("$RUNTIME_BIN")
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    targets+=("$f")
  done < <(find "$RUNTIME_ROOT/lib" \( -name '*.so' -o -name '*.dylib' \) -type f)

  collect_non_system_deps "$dep_list" "${targets[@]}"

  while IFS= read -r lib; do
    [[ -n "$lib" ]] || continue
    local base
    base="$(basename "$lib")"
    [[ -e "$RUNTIME_LIB/$base" ]] || cp -f "$lib" "$RUNTIME_LIB/$base"
    chmod 644 "$RUNTIME_LIB/$base"
  done < "$dep_list"

  while IFS= read -r target; do
    [[ -n "$target" ]] || continue
    local target_loader_prefix
    if [[ "$target" == *"/runtime-python/bin/"* ]]; then
      target_loader_prefix="@executable_path/../lib/"
    else
      target_loader_prefix=""
    fi
    while IFS= read -r dep; do
      [[ -n "$dep" ]] || continue
      case "$dep" in
        /System/*|/usr/lib/*)
          continue
          ;;
      esac
      local resolved_dep="$dep"
      if [[ "$dep" == @rpath/* ]]; then
        resolved_dep="$(resolve_runtime_dep_path "$dep" "$target" || true)"
        [[ -n "$resolved_dep" ]] || continue
      fi
      local base
      base="$(basename "$resolved_dep")"
      local loader_ref="$target_loader_prefix$base"
      if [[ -z "$target_loader_prefix" ]]; then
        loader_ref="$(runtime_loader_ref "$target" "$RUNTIME_LIB" "$base")"
      fi
      install_name_tool -change "$dep" "$loader_ref" "$target" 2>/dev/null || true
      install_name_tool -change "$resolved_dep" "$loader_ref" "$target" 2>/dev/null || true
    done < <(otool -L "$target" | awk 'NR > 1 {print $1}')
    codesign --force --sign - "$target"
  done < <(find "$RUNTIME_ROOT" \( -path "$RUNTIME_ROOT/bin/python3" -o -name '*.so' -o -name '*.dylib' \) -type f)

  while IFS= read -r lib; do
    [[ -n "$lib" ]] || continue
    install_name_tool -id "@loader_path/$(basename "$lib")" "$lib" 2>/dev/null || true
    codesign --force --sign - "$lib"
  done < <(find "$RUNTIME_LIB" -maxdepth 1 -name '*.dylib' -type f)

  codesign --force --sign - "$RUNTIME_BIN"
}

bundle_runtime_python_libffi() {
  local RUNTIME_ROOT="$RESOURCES_ABS/runtime-python"
  local RUNTIME_LIB="$RUNTIME_ROOT/lib"
  local PY_BASE_PREFIX="$1"
  local LIBFFI_SRC=""

  mkdir -p "$RUNTIME_LIB"

  for cand in \
    "$PY_BASE_PREFIX/lib/libffi.8.dylib" \
    "$PY_BASE_PREFIX/lib/libffi."*.dylib \
    "/opt/homebrew/opt/libffi/lib/libffi.8.dylib" \
    "/opt/homebrew/lib/libffi.8.dylib" \
    "/usr/local/opt/libffi/lib/libffi.8.dylib" \
    "/usr/local/lib/libffi.8.dylib"
  do
    if [[ -f "$cand" ]]; then
      LIBFFI_SRC="$cand"
      break
    fi
  done

  if [[ -z "$LIBFFI_SRC" ]]; then
    echo "WARNING: Could not find libffi for bundled runtime python" >&2
    return 0
  fi

  cp -f "$LIBFFI_SRC" "$RUNTIME_LIB/"
  chmod 644 "$RUNTIME_LIB/$(basename "$LIBFFI_SRC")"
  install_name_tool -id "@loader_path/$(basename "$LIBFFI_SRC")" "$RUNTIME_LIB/$(basename "$LIBFFI_SRC")" 2>/dev/null || true

  if [[ -d "$RUNTIME_ROOT/lib/python3.12/lib-dynload" ]]; then
    find "$RUNTIME_ROOT/lib/python3.12/lib-dynload" -name '_ctypes*.so' -type f -print0 | while IFS= read -r -d '' f; do
      install_name_tool -change "@rpath/$(basename "$LIBFFI_SRC")" "@loader_path/../../$(basename "$LIBFFI_SRC")" "$f" 2>/dev/null || true
      install_name_tool -change "@loader_path/../lib/$(basename "$LIBFFI_SRC")" "@loader_path/../../$(basename "$LIBFFI_SRC")" "$f" 2>/dev/null || true
      install_name_tool -change "$LIBFFI_SRC" "@loader_path/../../$(basename "$LIBFFI_SRC")" "$f" 2>/dev/null || true
      codesign --force --sign - "$f"
    done
  fi

  codesign --force --sign - "$RUNTIME_LIB/$(basename "$LIBFFI_SRC")"
}
remove_unneeded_pyside_apps() {
  local roots=(
    "$APP/Contents/Frameworks/PySide6"
    "$APP/Contents/Resources/PySide6"
  )

  for root in "${roots[@]}"; do
    [[ -d "$root" ]] || continue
    rm -rf \
      "$root/Assistant.app" \
      "$root/Designer.app" \
      "$root/Linguist.app" \
      "$root/Assistant__dot__app" \
      "$root/Designer__dot__app" \
      "$root/Linguist__dot__app"
  done
}

build_macos_icns() {
  local src_png="$ICON_PNG"
  local out_icns="$ICON_ICNS"
  local tmp_dir
  local iconset_dir

  if [[ ! -f "$src_png" ]]; then
    echo "WARNING: macOS icon source PNG not found: $src_png"
    return 0
  fi

  tmp_dir="$(mktemp -d /tmp/azantv.XXXXXX)"
  iconset_dir="$tmp_dir/${APP_NAME}.iconset"
  mkdir -p "$iconset_dir"

  sips -z 16 16     "$src_png" --out "$iconset_dir/icon_16x16.png" >/dev/null
  sips -z 32 32     "$src_png" --out "$iconset_dir/icon_16x16@2x.png" >/dev/null
  sips -z 32 32     "$src_png" --out "$iconset_dir/icon_32x32.png" >/dev/null
  sips -z 64 64     "$src_png" --out "$iconset_dir/icon_32x32@2x.png" >/dev/null
  sips -z 128 128   "$src_png" --out "$iconset_dir/icon_128x128.png" >/dev/null
  sips -z 256 256   "$src_png" --out "$iconset_dir/icon_128x128@2x.png" >/dev/null
  sips -z 256 256   "$src_png" --out "$iconset_dir/icon_256x256.png" >/dev/null
  sips -z 512 512   "$src_png" --out "$iconset_dir/icon_256x256@2x.png" >/dev/null
  sips -z 512 512   "$src_png" --out "$iconset_dir/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$src_png" --out "$iconset_dir/icon_512x512@2x.png" >/dev/null

  rm -f "$out_icns"
  iconutil -c icns "$iconset_dir" -o "$out_icns"

  rm -rf "$tmp_dir"
  echo "Built macOS icon: $out_icns"
}

build_ffmpeg_static_mac() {
  echo "Building static-ish ffmpeg/ffprobe/ffplay for macOS..."

  local SRC="$FFMPEG_SRC_DIR"
  local STAGE="$FFMPEG_STAGE_DIR"
  local CONFIG_STAMP="$REPO_ROOT/bin/mac/.ffmpeg-build-config"
  local configure_args=(
    --prefix="$STAGE"
    --disable-shared
    --enable-static
    --enable-ffplay
    --enable-ffmpeg
    --enable-ffprobe
    --disable-doc
    --enable-gpl
    --enable-version3
    --enable-libdav1d
    --enable-libzmq
    --enable-libfreetype
    --enable-libharfbuzz
    --enable-libfontconfig
    --enable-libfribidi
    --enable-libass
    --enable-libx264
    --enable-libx265
    --enable-libvpx
    --enable-libopus
  )
  local config_text
  config_text="$(printf '%s\n' "${configure_args[@]}")"

  if [[ ! -d "$SRC" ]]; then
    echo "ERROR: FFmpeg source dir not found: $SRC"
    echo "Set FFMPEG_SRC_DIR=/path/to/ffmpeg-8.0.1"
    exit 1
  fi

  export HOMEBREW_PREFIX="$(brew --prefix)"
  export PATH="$HOMEBREW_PREFIX/bin:$PATH"
  export PKG_CONFIG="$HOMEBREW_PREFIX/bin/pkg-config"
  export PKG_CONFIG_PATH="$HOMEBREW_PREFIX/lib/pkgconfig:$HOMEBREW_PREFIX/share/pkgconfig:$HOMEBREW_PREFIX/opt/zlib/lib/pkgconfig:$HOMEBREW_PREFIX/opt/bzip2/lib/pkgconfig:$HOMEBREW_PREFIX/opt/libpng/lib/pkgconfig:$HOMEBREW_PREFIX/opt/freetype/lib/pkgconfig:$HOMEBREW_PREFIX/opt/harfbuzz/lib/pkgconfig:$HOMEBREW_PREFIX/opt/fontconfig/lib/pkgconfig:$HOMEBREW_PREFIX/opt/fribidi/lib/pkgconfig:$HOMEBREW_PREFIX/opt/libass/lib/pkgconfig:$HOMEBREW_PREFIX/opt/libvpx/lib/pkgconfig:$HOMEBREW_PREFIX/opt/opus/lib/pkgconfig:$HOMEBREW_PREFIX/opt/x264/lib/pkgconfig:$HOMEBREW_PREFIX/opt/x265/lib/pkgconfig:$HOMEBREW_PREFIX/opt/zeromq/lib/pkgconfig:$HOMEBREW_PREFIX/opt/dav1d/lib/pkgconfig"
  unset PKG_CONFIG_LIBDIR
  unset CPATH LIBRARY_PATH DYLD_LIBRARY_PATH

  mkdir -p "$REPO_ROOT/bin/mac"

  if [[ "$FORCE_FFMPEG_REBUILD" != "1" ]] \
    && [[ -x "$REPO_ROOT/bin/mac/ffmpeg" ]] \
    && [[ -x "$REPO_ROOT/bin/mac/ffprobe" ]] \
    && [[ -x "$REPO_ROOT/bin/mac/ffplay" ]] \
    && [[ -f "$CONFIG_STAMP" ]] \
    && cmp -s "$CONFIG_STAMP" <(printf '%s' "$config_text"); then
    echo "Reusing existing FFmpeg build in $REPO_ROOT/bin/mac (set FORCE_FFMPEG_REBUILD=1 to rebuild)"
    return 0
  fi

  pushd "$SRC" >/dev/null
  if [[ "$FORCE_FFMPEG_REBUILD" == "1" || ! -d "$STAGE" ]]; then
    rm -rf "$STAGE"
    make distclean >/dev/null 2>&1 || true
  fi

  ./configure "${configure_args[@]}"

  make -j"$(sysctl -n hw.ncpu)"
  make install

  if [[ ! -x "$STAGE/bin/ffplay" ]]; then
    echo "ERROR: FFmpeg build completed but did not produce $STAGE/bin/ffplay"
    echo "Check your FFmpeg configure output and dependencies; ffplay may have been disabled or failed to build."
    exit 1
  fi

  cp -f "$STAGE/bin/ffmpeg" "$REPO_ROOT/bin/mac/ffmpeg"
  cp -f "$STAGE/bin/ffprobe" "$REPO_ROOT/bin/mac/ffprobe"
  cp -f "$STAGE/bin/ffplay" "$REPO_ROOT/bin/mac/ffplay"
  chmod +x "$REPO_ROOT/bin/mac/ffmpeg" "$REPO_ROOT/bin/mac/ffprobe" "$REPO_ROOT/bin/mac/ffplay"
  printf '%s' "$config_text" > "$CONFIG_STAMP"

  echo "Built and copied:"
  echo "  $REPO_ROOT/bin/mac/ffmpeg"
  echo "  $REPO_ROOT/bin/mac/ffprobe"
  echo "  $REPO_ROOT/bin/mac/ffplay"

  echo "Linked libraries for ffmpeg:"
  otool -L "$REPO_ROOT/bin/mac/ffmpeg" || true

  echo "Linked libraries for ffprobe:"
  otool -L "$REPO_ROOT/bin/mac/ffprobe" || true

  echo "Linked libraries for ffplay:"
  otool -L "$REPO_ROOT/bin/mac/ffplay" || true

  popd >/dev/null
}

if [[ "$BUILD_FFMPEG_STATIC" == "1" ]]; then
  build_ffmpeg_static_mac
fi

build_macos_icns

echo "Building $APP_NAME app for macOS..."
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier "$APP_BUNDLE_ID" \
  --collect-all PySide6 \
  --hidden-import app_backend \
  desktop_app.py

APP="$(cd dist && pwd)/${APP_NAME}.app"
RESOURCES="$APP/Contents/Resources/azan-tv"
RESOURCES_ABS="$(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")/Contents/Resources/azan-tv"
MACOS="$APP/Contents/MacOS"
APP_RESOURCES_ROOT="$APP/Contents/Resources"
APP_PLIST="$APP/Contents/Info.plist"

if [[ -f "$ICON_ICNS" ]]; then
  cp -f "$ICON_ICNS" "$APP_RESOURCES_ROOT/${APP_NAME}.icns"
fi
if [[ -f "$APP_PLIST" ]]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleName string $APP_NAME" "$APP_PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $APP_NAME" "$APP_PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $APP_BUNDLE_ID" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $APP_BUNDLE_ID" "$APP_PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile ${APP_NAME}.icns" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string ${APP_NAME}.icns" "$APP_PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $RELEASE_VERSION" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $RELEASE_VERSION" "$APP_PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $RELEASE_VERSION" "$APP_PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $RELEASE_VERSION" "$APP_PLIST"
fi

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
  python3 -m venv --copies "$RUNTIME_VENV"
  "$RUNTIME_VENV/bin/python3" -m pip install --upgrade pip setuptools wheel -q
  "$RUNTIME_VENV/bin/python3" -m pip install -r "$REPO_ROOT/stream/requirements-stream.txt" -q
  rm -rf "$RESOURCES_ABS/runtime-python"
  mkdir -p "$RESOURCES_ABS/runtime-python"
  cp -RL "$RUNTIME_VENV"/. "$RESOURCES_ABS/runtime-python/"
  echo "  runtime-python: copied venv"
  PY_RUNTIME_INFO="$("$RUNTIME_VENV/bin/python3" - <<'PY'
import sys
import sysconfig
print(sys.base_prefix)
print(sysconfig.get_path("stdlib"))
print(sysconfig.get_path("platstdlib"))
PY
)"
  PY_BASE_PREFIX="$(printf '%s\n' "$PY_RUNTIME_INFO" | sed -n '1p')"
  STDLIB_SRC="$(printf '%s\n' "$PY_RUNTIME_INFO" | sed -n '2p')"
  PLATSTDLIB_SRC="$(printf '%s\n' "$PY_RUNTIME_INFO" | sed -n '3p')"
  PYVER_DIR="$(basename "$STDLIB_SRC")"
  RUNTIME_LIB_DIR="$RESOURCES_ABS/runtime-python/lib/$PYVER_DIR"
  mkdir -p "$RUNTIME_LIB_DIR"
  python3 - "$STDLIB_SRC" "$RUNTIME_LIB_DIR" <<'PY'
import os
import shutil
import sys
src, dst = sys.argv[1], sys.argv[2]
for name in os.listdir(src):
    if name in {"site-packages", "__pycache__"}:
        continue
    s = os.path.join(src, name)
    d = os.path.join(dst, name)
    if os.path.isdir(s):
        shutil.copytree(s, d, symlinks=False, dirs_exist_ok=True)
    else:
        shutil.copy2(s, d)
PY
  echo "  runtime-python: copied stdlib"
  if [[ -d "$PLATSTDLIB_SRC/lib-dynload" ]]; then
    mkdir -p "$RUNTIME_LIB_DIR/lib-dynload"
    cp -RL "$PLATSTDLIB_SRC/lib-dynload"/. "$RUNTIME_LIB_DIR/lib-dynload/"
    echo "  runtime-python: copied lib-dynload"
  fi
  bundle_runtime_python_dylibs
  echo "  runtime-python: bundled dylibs"
  bundle_runtime_python_libffi "$PY_BASE_PREFIX"
  echo "  runtime-python: bundled libffi"
  AZAN_TV_ROOT="$RESOURCES_ABS" \
  PYTHONHOME="$RESOURCES_ABS/runtime-python" \
  PYTHONPATH="$RESOURCES_ABS/stream:$RESOURCES_ABS/runtime-python/lib/$PYVER_DIR/site-packages" \
  PYTHONNOUSERSITE=1 \
  "$RESOURCES_ABS/runtime-python/bin/python3" -c "import ctypes; print('runtime-python ctypes ok')" >/dev/null
  echo "  runtime-python: ctypes import check passed"
  AZAN_TV_ROOT="$RESOURCES_ABS" \
  PYTHONHOME="$RESOURCES_ABS/runtime-python" \
  PYTHONPATH="$RESOURCES_ABS/stream:$RESOURCES_ABS/runtime-python/lib/$PYVER_DIR/site-packages" \
  PYTHONNOUSERSITE=1 \
  "$RESOURCES_ABS/runtime-python/bin/python3" -c "import numpy; print('runtime-python numpy ok')" >/dev/null
  echo "  runtime-python: numpy import check passed"
  AZAN_TV_ROOT="$RESOURCES_ABS" \
  PYTHONHOME="$RESOURCES_ABS/runtime-python" \
  PYTHONPATH="$RESOURCES_ABS/stream:$RESOURCES_ABS/runtime-python/lib/$PYVER_DIR/site-packages" \
  PYTHONNOUSERSITE=1 \
  "$RESOURCES_ABS/runtime-python/bin/python3" -c "import pandas; print('runtime-python pandas ok')" >/dev/null
  echo "  runtime-python: pandas import check passed"
  AZAN_TV_ROOT="$RESOURCES_ABS" \
  PYTHONHOME="$RESOURCES_ABS/runtime-python" \
  PYTHONPATH="$RESOURCES_ABS/stream:$RESOURCES_ABS/runtime-python/lib/$PYVER_DIR/site-packages" \
  PYTHONNOUSERSITE=1 \
  "$RESOURCES_ABS/runtime-python/bin/python3" -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Berlin'); print('runtime-python zoneinfo ok')" >/dev/null
  echo "  runtime-python: zoneinfo check passed"
  echo "Bundled runtime-python (stream deps)"
fi

if [[ "$REQUIRE_FFPLAY" == "1" && ! -x "$REPO_ROOT/bin/mac/ffplay" ]]; then
  echo "ERROR: ffplay is required for the mac desktop app but was not found at $REPO_ROOT/bin/mac/ffplay"
  echo "Build ffmpeg with ffplay enabled (for example with BUILD_FFMPEG_STATIC=1) or place ffplay there before building."
  exit 1
fi

# Same folder structure as repo: bin/mac, ffplayout/mac (relative paths in app rely on this)
mkdir -p "$RESOURCES/bin/mac"
# Copy all files (not directories) from your repo bin/mac and bin/ (ffmpeg, ffprobe, ffplay, adb, yt-dlp, mediamtx, etc.)
if [[ -d "$REPO_ROOT/bin/mac" ]]; then
  for f in "$REPO_ROOT/bin/mac"/*; do
    [[ -e "$f" ]] || continue
    [[ -d "$f" ]] && continue
    name=$(basename "$f")
    [[ "$name" == "ffmpeg" || "$name" == "ffprobe" || "$name" == "ffplay" ]] && continue
    cp -f "$f" "$RESOURCES/bin/mac/$name"
    [[ -x "$f" ]] && chmod +x "$RESOURCES/bin/mac/$name"
    echo "Bundled bin/mac/$name"
  done
fi
if [[ -d "$REPO_ROOT/bin" ]]; then
  for f in "$REPO_ROOT/bin"/*; do
    [[ -e "$f" ]] || continue
    [[ -d "$f" ]] && continue
    name=$(basename "$f")
    [[ "$name" == "ffmpeg" || "$name" == "ffprobe" || "$name" == "ffplay" ]] && continue
    [[ -e "$RESOURCES/bin/mac/$name" ]] && continue
    cp -f "$f" "$RESOURCES/bin/mac/$name"
    [[ -x "$f" ]] && chmod +x "$RESOURCES/bin/mac/$name"
    echo "Bundled bin/$name -> bin/mac/"
  done
fi
# ffplayout
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
    echo "Downloaded mediamtx (Mac $MTX_ARCH)"
  fi
  for name in yt-dlp mediamtx mediamtx.yml; do
    [[ -f "$REPO_ROOT/bin/mac/$name" ]] && cp -f "$REPO_ROOT/bin/mac/$name" "$RESOURCES/bin/mac/$name"
    [[ -x "$REPO_ROOT/bin/mac/$name" ]] && chmod +x "$RESOURCES/bin/mac/$name"
  done
fi
# Exclude secrets/certs from bundle (do not ship keys/)
rm -f "$RESOURCES/stream/client_secret.json" "$RESOURCES/stream/user-oauth2.json" \
  "$RESOURCES/data/client_secret.json" "$RESOURCES/data/user-oauth2.json" \
  "$RESOURCES/keys/client_secret.json" "$RESOURCES/keys/user-oauth2.json" \
  "$RESOURCES/keys/server.crt" "$RESOURCES/keys/server.key" \
  "$RESOURCES/server.crt" "$RESOURCES/server.key" 2>/dev/null || true

if [[ -x "$REPO_ROOT/bin/mac/ffmpeg" && -x "$REPO_ROOT/bin/mac/ffprobe" ]]; then
  echo "Bundling ffmpeg/ffprobe/ffplay (if available) and dependent dylibs..."
  bundle_ffmpeg_mac
  patch_bundled_dylibs
  resign_ffmpeg_bundle_mac
  check_for_unbundled_homebrew_refs
fi

if [[ -x "$REPO_ROOT/bin/mac/adb" ]]; then
  echo "Bundling adb..."
  cp -f "$REPO_ROOT/bin/mac/adb" "$RESOURCES/bin/mac/adb"
  chmod +x "$RESOURCES/bin/mac/adb"
  xattr -cr "$RESOURCES/bin/mac/adb" || true
  codesign --remove-signature "$RESOURCES/bin/mac/adb" 2>/dev/null || true
  codesign --force --sign - "$RESOURCES/bin/mac/adb"
fi

# Launcher script sets AZAN_TV_ROOT so the app finds stream scripts and config
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
cat > "$MACOS/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export AZAN_TV_ROOT="$DIR/../Resources/azan-tv"
exec "$DIR/azan-tv-bin" "$@"
LAUNCHER
chmod +x "$MACOS/$APP_NAME"
chmod +x "$REAL_BIN"

echo ""
echo "App bundle: $APP"
echo "Open locally: open \"$APP\""
echo "Data folder: ~/Library/Application Support/azan-tv"
echo ""

remove_unneeded_pyside_apps
if find "$RESOURCES_ABS/runtime-python" -type l | grep -q .; then
  echo "ERROR: runtime-python still contains symlinks"
  find "$RESOURCES_ABS/runtime-python" -type l -print
  exit 1
fi

echo "Signing app bundle..."
xattr -cr "$APP" || true
echo "Signing $APP"
ls -ld "$APP"
codesign --force --deep --timestamp --sign - "$APP"

finalize_bundled_adb_mac() {
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  local bundled_adb="$APP_MAC_BIN/adb"
  [[ -x "$bundled_adb" ]] || return 0

  echo "Finalizing bundled adb..."
  xattr -cr "$bundled_adb" || true
  codesign --remove-signature "$bundled_adb" 2>/dev/null || true
  codesign --force --sign - "$bundled_adb"

  echo "Re-signing app bundle after adb finalization..."
  xattr -cr "$APP" || true
  codesign --force --deep --timestamp --sign - "$APP"
}

finalize_bundled_adb_mac

verify_ffmpeg_bundle_mac() {
  shopt -s nullglob
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  local APP_FW="$APP_MAC_BIN/Frameworks"
  local verify_targets=("$APP_MAC_BIN/ffprobe" "$APP_MAC_BIN/ffmpeg")

  [[ -x "$APP_MAC_BIN/ffmpeg" && -x "$APP_MAC_BIN/ffprobe" ]] || return 0
  [[ -d "$APP_FW" ]] || return 0
  if [[ -x "$APP_MAC_BIN/ffplay" ]]; then
    verify_targets+=("$APP_MAC_BIN/ffplay")
  fi

  echo "Verifying bundled dylibs..."
  find "$APP_FW" -name '*.dylib' -print0 | while IFS= read -r -d '' f; do
    codesign --verify --strict --verbose=4 "$f"
  done

  echo "Verifying bundled ffmpeg/ffprobe/ffplay..."
  codesign --verify --strict --verbose=4 "$APP_MAC_BIN/ffmpeg"
  codesign --verify --strict --verbose=4 "$APP_MAC_BIN/ffprobe"
  if [[ -x "$APP_MAC_BIN/ffplay" ]]; then
    codesign --verify --strict --verbose=4 "$APP_MAC_BIN/ffplay"
  fi

  echo "DYLD check:"
  otool -L "$APP_MAC_BIN/ffprobe"

  echo "Checking linked libraries..."
  if otool -L "${verify_targets[@]}" "$APP_FW"/*.dylib \
    | awk '{print $1}' | grep -q '^/opt/homebrew/'; then
    echo "ERROR: remaining /opt/homebrew references found"
    exit 1
  fi

  echo "Running bundled ffprobe/ffmpeg/ffplay..."
  "$APP_MAC_BIN/ffprobe" -version
  "$APP_MAC_BIN/ffmpeg" -version
  if [[ -x "$APP_MAC_BIN/ffplay" ]]; then
    "$APP_MAC_BIN/ffplay" -version
  fi

  codesign --verify --strict --deep --verbose=4 "$APP"

  spctl -a -vv "$APP" || true
}

echo "Verifying bundled ffmpeg/ffprobe/ffplay..."
verify_ffmpeg_bundle_mac

verify_bundled_adb_mac() {
  local APP_MAC_BIN="$RESOURCES/bin/mac"
  [[ -x "$APP_MAC_BIN/adb" ]] || return 0

  echo "Verifying bundled adb..."
  codesign --verify --strict --verbose=4 "$APP_MAC_BIN/adb"
  spctl -a -vv "$APP_MAC_BIN/adb" || true
  otool -L "$APP_MAC_BIN/adb"
  if otool -L "$APP_MAC_BIN/adb" | awk '{print $1}' | grep -Eq '^/opt/homebrew/|^/usr/local/'; then
    echo "ERROR: bundled adb depends on non-system libraries"
    exit 1
  fi
  "$APP_MAC_BIN/adb" version >/dev/null
}

echo "Verifying bundled adb..."
verify_bundled_adb_mac

# Create DMG for installation on another Mac (set SKIP_DMG=1 to skip)
if [[ "${SKIP_DMG:-0}" != "1" ]]; then
  echo "Creating DMG for distribution..."
  DMG_NAME="$APP_NAME"
  DMG_PATH="dist/${RELEASE_FILE_BASENAME}.dmg"
  DMG_TMP="dist/dmg-tmp"
  rm -rf "$DMG_TMP" "$DMG_PATH"
  mkdir -p "$DMG_TMP"
  cp -R "$APP" "$DMG_TMP/"
  ln -s /Applications "$DMG_TMP/Applications"
  hdiutil create -volname "$DMG_NAME" -srcfolder "$DMG_TMP" -ov -format UDZO "$DMG_PATH"
  rm -rf "$DMG_TMP"
  echo ""
  echo "DMG created: $DMG_PATH"
  echo ""
  echo "To install on another Mac:"
  echo "  1. Copy $DMG_PATH to the other Mac (USB, AirDrop, etc.)."
  echo "  2. Double-click AzanTV.dmg to open it."
  echo "  3. Drag AzanTV into the Applications folder (or into the Applications shortcut)."
  echo "  4. Eject the disk image. AzanTV will be in Applications."
fi
