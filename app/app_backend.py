#!/usr/bin/env python3
"""
AZAN TV backend for desktop app.

APP_DIR: code/templates shipped with the app.
WORK_DIR: user data (config/media/bin/logs/tmp), persisted independently.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

# App root: when bundled, AZAN_TV_ROOT points to bundle resources; when running from source, parent of app/ (this file lives in app/).
_app_dir_candidate = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get("AZAN_TV_ROOT", str(_app_dir_candidate))).resolve()
# Repo root (parent of app/ when running from source) for ffplayout/bin not shipped inside app/
REPO_ROOT = _app_dir_candidate.parent if _app_dir_candidate.name == "app" else APP_DIR
# Stream scripts and templates; data (video-desc); keys (secrets/certs). When bundled, stream/, data/, keys/ live under APP_DIR.
STREAM_DIR = (APP_DIR / "stream").resolve() if (APP_DIR / "stream").exists() else (REPO_ROOT / "stream").resolve()
DATA_DIR = (APP_DIR / "data").resolve() if (APP_DIR / "data").exists() else (REPO_ROOT / "data").resolve()
KEYS_DIR = (APP_DIR / "keys").resolve() if (APP_DIR / "keys").exists() else (REPO_ROOT / "keys").resolve()

if sys.platform == "darwin":
    _default_work = Path.home() / "Library" / "Application Support" / "azan-tv"
    _default_cache = Path.home() / "Library" / "Caches" / "azan-tv"
else:
    _xdg_data = os.environ.get("XDG_DATA_HOME")
    if _xdg_data:
        _default_work = Path(_xdg_data) / "azan-tv"
    else:
        _default_work = Path.home() / ".local" / "share" / "azan-tv"
    _xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if _xdg_cache:
        _default_cache = Path(_xdg_cache) / "azan-tv"
    else:
        _default_cache = Path.home() / ".cache" / "azan-tv"

WORK_DIR = Path(os.environ.get("AZAN_TV_WORKDIR", str(_default_work))).resolve()
CACHE_DIR = Path(os.environ.get("AZAN_TV_CACHEDIR", str(_default_cache))).resolve()

CONFIG_PATH = WORK_DIR / "config.json"
VIDEO_DESC_PATH = WORK_DIR / "video-desc.txt"

# Platform-specific subdirs for bin/ and ffplayout/ (so one repo can hold both Mac and Linux binaries)
_PLATFORM_BIN = "mac" if sys.platform == "darwin" else "linux"

RUN_PROCESS = None
RUN_LOGS = []
RUN_LOCK = threading.Lock()
EVENT_NAMES = ["imsak", "fajr", "sunrise", "dhuhr", "asr", "sunset", "maghrib", "isha", "midnight"]
KNOWN_MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m3u8", ".ts", ".flv"}


def _clean_subprocess_env(extra=None):
    """
    Environment for external tools launched from bundled app.
    PyInstaller onefile sets LD_LIBRARY_PATH to its temp dir (/tmp/_MEI*),
    which can break host binaries like yt-dlp with relocation errors.
    """
    env = os.environ.copy()
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    if extra:
        env.update(extra)
    return env


def _ensure_workdir():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("media", "bin"):
        (WORK_DIR / name).mkdir(exist_ok=True)
    for name in ("tmp", "logs", "ffplayout.log"):
        cache_sub = CACHE_DIR / name
        cache_sub.mkdir(exist_ok=True)
        work_sub = WORK_DIR / name
        if not work_sub.exists():
            try:
                work_sub.symlink_to(cache_sub, target_is_directory=True)
            except OSError:
                # Fallback when symlinks are unavailable.
                work_sub.mkdir(exist_ok=True)
    # Copy defaults once: stream templates from STREAM_DIR, video-desc from DATA_DIR.
    for fn in ("config.json", "network-program-hard.json", "ffplayout-template.yml"):
        src = STREAM_DIR / fn
        dst = WORK_DIR / fn
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                shutil.copy(src, dst)
    video_desc_src = DATA_DIR / "video-desc.txt"
    if video_desc_src.exists() and not VIDEO_DESC_PATH.exists():
        try:
            shutil.copy2(video_desc_src, VIDEO_DESC_PATH)
        except PermissionError:
            shutil.copy(video_desc_src, VIDEO_DESC_PATH)
    # Copy keys/certs from keys/ to WORK_DIR so config (relative paths) finds them.
    for key_file in ("client_secret.json", "user-oauth2.json", "server.crt", "server.key"):
        src = KEYS_DIR / key_file
        dst = WORK_DIR / key_file
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                shutil.copy(src, dst)
            if key_file in ("server.crt", "server.key"):
                try:
                    dst.chmod(0o600 if key_file == "server.key" else 0o644)
                except OSError:
                    pass
    # Keep ffplayout template path local to WORK_DIR config.
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("ffplayout_template") != "ffplayout-template.yml":
                cfg["ffplayout_template"] = "ffplayout-template.yml"
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent="\t", ensure_ascii=False)
        except Exception:
            pass
    # If helper binaries are bundled with app resources (or at repo root when running from source), copy into WORK_DIR/bin.
    # Prefer platform-specific folder (bin/linux, bin/mac) so one repo can hold both.
    app_bin = APP_DIR / "bin" / _PLATFORM_BIN
    if not app_bin.exists():
        app_bin = APP_DIR / "bin"
    if not app_bin.exists():
        app_bin = REPO_ROOT / "bin" / _PLATFORM_BIN
    if not app_bin.exists():
        app_bin = REPO_ROOT / "bin"
    work_bin = WORK_DIR / "bin"
    for helper in ("yt-dlp", "mediamtx", "mediamtx.yml"):
        src = app_bin / helper
        dst = work_bin / helper
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                shutil.copy(src, dst)
            if helper in ("yt-dlp", "mediamtx"):
                try:
                    dst.chmod(0o755)
                except OSError:
                    pass


def get_paths():
    """Expose app/work dirs for UI display."""
    return {"app_dir": str(APP_DIR), "work_dir": str(WORK_DIR), "cache_dir": str(CACHE_DIR)}


def get_local_ip():
    """Return this machine's local IP (for RTSP host / MediaMTX)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("10.254.254.254", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def get_event_names():
    return list(EVENT_NAMES)


def list_media_files():
    """List media files currently present in WORK_DIR/media."""
    _ensure_workdir()
    media_dir = WORK_DIR / "media"
    if not media_dir.exists():
        return []
    return sorted(
        str(p.relative_to(WORK_DIR))
        for p in media_dir.rglob("*")
        if p.is_file()
    )


def get_program_path():
    _ensure_workdir()
    if not CONFIG_PATH.exists():
        return WORK_DIR / "network-program-hard.json"
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return WORK_DIR / cfg.get("program_template", "network-program-hard.json")


# ---------- Config ----------
def config_get():
    _ensure_workdir()
    if not CONFIG_PATH.exists():
        return None, "config.json not found"
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f), None


def config_save(data):
    _ensure_workdir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent="\t", ensure_ascii=False)
    return None


def youtube_config_status():
    """Check whether YouTube config files exist for stream/browser modes."""
    _ensure_workdir()
    cfg, err = config_get()
    if err or cfg is None:
        return {"ok": False, "error": err or "config.json not found"}
    client_secret = cfg.get("client_secrets_file", "client_secret.json")
    oauth_file = cfg.get("oauth2_file", "user-oauth2.json")
    cs_path = Path(client_secret).expanduser()
    oauth_path = Path(oauth_file).expanduser()
    if not cs_path.is_absolute():
        cs_path = WORK_DIR / cs_path
    if not oauth_path.is_absolute():
        oauth_path = WORK_DIR / oauth_path
    return {
        "ok": cs_path.exists(),
        "client_secret_file": client_secret,
        "oauth2_file": oauth_file,
        "client_secret_path": str(cs_path),
        "oauth2_path": str(oauth_path),
        "client_secret_exists": cs_path.exists(),
        "oauth2_exists": oauth_path.exists(),
        "message": None if cs_path.exists() else f"Missing client secrets: {cs_path}",
    }


def generate_self_signed_cert(days=365):
    """Generate server.crt and server.key in keys/, then copy to WORK_DIR. Returns (ok, message)."""
    _ensure_workdir()
    # Write to keys/ when present (e.g. running from source) so certs live in the keys folder
    cert_dir = KEYS_DIR if KEYS_DIR.exists() else WORK_DIR
    key_dir = KEYS_DIR if KEYS_DIR.exists() else WORK_DIR
    cert_path = key_dir / "server.crt"
    key_path = key_dir / "server.key"
    if shutil.which("openssl") is None:
        return False, "openssl not found in PATH"
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path), "-out", str(cert_path),
                "-days", str(days), "-nodes",
                "-subj", "/CN=localhost/O=AZAN-TV",
            ],
            cwd=str(key_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=_clean_subprocess_env(),
            check=True,
        )
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        # Copy to WORK_DIR so the stream can use them
        if key_dir != WORK_DIR:
            for p in (cert_path, key_path):
                dst = WORK_DIR / p.name
                shutil.copy2(p, dst)
                if p.name == "server.key":
                    try:
                        dst.chmod(0o600)
                    except OSError:
                        pass
        return True, f"Created {cert_path.name} and {key_path.name} in keys folder"
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip() or "openssl failed"
    except Exception as e:
        return False, str(e)


def program_get():
    path = get_program_path()
    if not path.exists():
        return None, f"Program file not found: {path}"
    with open(path, encoding="utf-8") as f:
        return json.load(f), None


def program_save(data):
    _ensure_workdir()
    path = get_program_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return None


# ---------- Installation ----------
def _check_exe(path_or_cmd):
    if path_or_cmd is None:
        return False, "not configured"
    p = Path(path_or_cmd)
    if p.is_absolute() and p.exists():
        return True, str(p)
    if shutil.which(str(path_or_cmd)):
        return True, "in PATH"
    return False, "not found"


def _app_ffplayout_bin():
    """Path to ffplayout binary: in app resources (bundle) or at repo root (source). On Mac use only ffplayout/mac/ffplayout (never target/debug, which may be Linux)."""
    for root in (APP_DIR, REPO_ROOT):
        p = root / "ffplayout" / _PLATFORM_BIN / "ffplayout"
        if p.exists():
            return p
        if _PLATFORM_BIN == "linux":
            q = root / "ffplayout" / "target" / "debug" / "ffplayout"
            if q.exists():
                return q
    return APP_DIR / "ffplayout" / _PLATFORM_BIN / "ffplayout"  # Mac: return path even if missing so we never run a Linux binary


def install_status():
    _ensure_workdir()
    ffplay_ok, ffplay_msg = _check_exe("ffplay")
    ffplayout_path = _app_ffplayout_bin()
    ffplayout_ok = ffplayout_path.exists()
    mediamtx_path = WORK_DIR / "bin" / "mediamtx"
    mediamtx_ok = mediamtx_path.exists()
    ytdlp_path = WORK_DIR / "bin" / "yt-dlp"
    ytdlp_ok = ytdlp_path.exists()
    rust_ok = shutil.which("cargo") is not None
    return {
        "ffplay": {"installed": ffplay_ok, "message": ffplay_msg},
        "ffplayout": {"installed": ffplayout_ok, "path": str(ffplayout_path)},
        "mediamtx": {"installed": mediamtx_ok, "path": str(mediamtx_path)},
        "yt_dlp": {"installed": ytdlp_ok, "path": str(ytdlp_path)},
        "rust": {"installed": rust_ok, "message": "cargo in PATH" if rust_ok else "not found"},
    }


def _download_url(url, dest_path, timeout=120):
    """Download url to dest_path using Python (works on Linux and macOS)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "AZAN-TV/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest_path.write_bytes(resp.read())


def install_ytdlp():
    _ensure_workdir()
    bin_dir = WORK_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    out = bin_dir / "yt-dlp"
    if sys.platform == "darwin":
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    else:
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    try:
        _download_url(url, out, timeout=60)
        out.chmod(0o755)
        return None
    except Exception as e:
        return str(e)


def install_mediamtx():
    _ensure_workdir()
    bin_dir = WORK_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    version = "v1.12.0"
    ver_short = version.replace("v", "")
    if sys.platform == "darwin":
        import platform
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
        mtx_arch = f"darwin_{arch}"
    else:
        mtx_arch = "linux_amd64"
    url = f"https://github.com/bluenviron/mediamtx/releases/download/{version}/mediamtx_{ver_short}_{mtx_arch}.tar.gz"
    arc = CACHE_DIR / "mediamtx.tar.gz"
    try:
        _download_url(url, arc, timeout=120)
        subprocess.run(["tar", "xzf", str(arc)], cwd=str(WORK_DIR), check=True, env=_clean_subprocess_env())
        for name in ["mediamtx", "mediamtx.yml"]:
            src = WORK_DIR / name
            if src.exists():
                shutil.move(str(src), str(bin_dir / name))
        if arc.exists():
            arc.unlink()
        return None
    except Exception as e:
        return str(e)


def install_ffplayout():
    """Download ffplayout binary from GitHub releases into work dir (ffplayout/target/debug/ffplayout). Returns None on success, error str otherwise."""
    _ensure_workdir()
    version = "v0.25.7"
    machine = (getattr(__import__("platform"), "machine") or (lambda: "x86_64"))()
    machine_lower = machine.lower() if machine else "x86_64"
    if sys.platform == "darwin":
        if machine_lower in ("arm64", "aarch64"):
            asset = f"ffplayout-{version}_aarch64-apple-darwin.zip"
        else:
            asset = f"ffplayout-{version}_x86_64-apple-darwin.zip"
        url = f"https://github.com/ffplayout/ffplayout/releases/download/{version}/{asset}"
        arc = CACHE_DIR / "ffplayout.zip"
        bundle_dir = WORK_DIR / "ffplayout_bundle"
        work_ffplayout_bin = WORK_DIR / "ffplayout" / "target" / "debug" / "ffplayout"
        work_ffplayout_bin.parent.mkdir(parents=True, exist_ok=True)
        try:
            _download_url(url, arc, timeout=120)
            # Extract full zip so the binary has sibling files it expects (avoids "No such file or directory")
            if bundle_dir.exists():
                shutil.rmtree(bundle_dir)
            bundle_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(arc, "r") as z:
                z.extractall(bundle_dir)
            # Find the dir that contains the ffplayout binary (e.g. ffplayout-0.25.7_x86_64-apple-darwin/)
            bin_dir = None
            for p in bundle_dir.rglob("ffplayout"):
                if p.is_file() and os.access(p, os.X_OK):
                    bin_dir = str(p.parent)
                    shutil.copy2(p, work_ffplayout_bin)
                    work_ffplayout_bin.chmod(0o755)
                    break
            if not bin_dir:
                raise FileNotFoundError(f"ffplayout binary not found inside {asset}")
            (WORK_DIR / "ffplayout_bundle_dir.txt").write_text(bin_dir, encoding="utf-8")
            if arc.exists():
                arc.unlink()
            return None
        except Exception as e:
            return str(e)
    # Linux
    if machine_lower in ("arm64", "aarch64"):
        asset = f"ffplayout-{version[1:]}_aarch64-unknown-linux-gnu.tar.gz"
    else:
        asset = f"ffplayout-{version[1:]}_x86_64-unknown-linux-musl.tar.gz"
    url = f"https://github.com/ffplayout/ffplayout/releases/download/{version}/{asset}"
    arc = CACHE_DIR / "ffplayout.tar.gz"
    work_ffplayout = WORK_DIR / "ffplayout"
    work_ffplayout_bin = work_ffplayout / "target" / "debug" / "ffplayout"
    try:
        _download_url(url, arc, timeout=120)
        work_ffplayout.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "xzf", str(arc)], cwd=str(work_ffplayout), check=True, env=_clean_subprocess_env())
        found = None
        for p in work_ffplayout.rglob("ffplayout"):
            if p.is_file():
                found = p
                break
        if not found:
            raise FileNotFoundError(f"ffplayout binary not found inside {asset}")
        work_ffplayout_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, work_ffplayout_bin)
        work_ffplayout_bin.chmod(0o755)
        if arc.exists():
            arc.unlink()
        return None
    except Exception as e:
        return str(e)


def _expand_hijri_day_paths(paths_set):
    """Expand paths containing {HIJRI_DAY} into 30 entries (01..30)."""
    out = set()
    for p in paths_set:
        if not p or "{HIJRI_DAY}" not in p:
            out.add(p)
            continue
        for day in range(1, 31):
            repl = p.replace("{HIJRI_DAY}", f"{day:02d}")
            out.add(repl)
    return out


def _normalize_media_path(path):
    """
    Normalize media path used by program:
    - expand only actual file extensions
    - if no known extension exists, assume .mp4
    """
    p = (path or "").strip()
    if not p:
        return p
    suffix = Path(p).suffix.lower()
    if suffix in KNOWN_MEDIA_EXTENSIONS:
        return p
    return p + ".mp4"


def media_list():
    _ensure_workdir()
    path = get_program_path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    paths = set()
    paths.add(data.get("timer", "").strip())
    for p in data.get("program", []):
        for x in p.get("pre", []) + p.get("post", []):
            paths.add(x.strip())
    paths = _expand_hijri_day_paths(paths)
    out = []
    for p in sorted(paths):
        if not p:
            continue
        base = _normalize_media_path(p)
        full = WORK_DIR / base
        out.append({"path": base, "exists": full.exists()})
    return out


def _gregorian_to_hijri_day(g_date):
    """
    Civil (tabular) Hijri conversion, sufficient for selecting {HIJRI_DAY} media file.
    Returns Hijri day as int 1..30.
    """
    y, m, d = g_date.year, g_date.month, g_date.day
    if m < 3:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    h_month = (24 * l) // 709
    h_day = l - (709 * h_month) // 24
    _ = 30 * n + j - 30
    return int(max(1, min(30, h_day)))


def required_files_for_today():
    """
    Resolve required media files for today's program (wildcards replaced), and check existence.
    """
    _ensure_workdir()
    today = datetime.now().date()
    hijri_day = _gregorian_to_hijri_day(today)
    program, err = program_get()
    if err or not program:
        return {
            "date": str(today),
            "hijri_day": f"{hijri_day:02d}",
            "files": [],
            "missing_count": 0,
            "error": err or "program not found",
        }
    ordered = []
    seen = set()

    def add_path(p):
        if not p:
            return
        p = p.replace("{HIJRI_DAY}", f"{hijri_day:02d}")
        p = _normalize_media_path(p)
        if p in seen:
            return
        seen.add(p)
        ordered.append(p)

    add_path(program.get("timer", ""))
    for evt in program.get("program", []):
        for p in evt.get("pre", []):
            add_path(p)
        for p in evt.get("post", []):
            add_path(p)

    files = []
    missing = 0
    for rel in ordered:
        exists = (WORK_DIR / rel).exists()
        files.append({"path": rel, "exists": exists})
        if not exists:
            missing += 1
    return {
        "date": str(today),
        "hijri_day": f"{hijri_day:02d}",
        "files": files,
        "missing_count": missing,
        "error": None,
    }


def restore_video_desc_from_app():
    """Copy video-desc.txt from data/ into work dir so the app uses the updated file. Returns (ok, message)."""
    _ensure_workdir()
    src = DATA_DIR / "video-desc.txt"
    if not src.exists():
        return False, "video-desc.txt not found in data folder"
    try:
        shutil.copy(src, VIDEO_DESC_PATH)
        return True, f"Copied to {VIDEO_DESC_PATH}"
    except Exception as e:
        return False, str(e)


def load_video_desc():
    _ensure_workdir()
    """Load video-desc.txt: return dict path -> list of suggested URLs (path normalized with .mp4 if no extension)."""
    result = {}
    if not VIDEO_DESC_PATH.exists():
        return result
    with open(VIDEO_DESC_PATH, encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line or line.startswith("#"):
            continue
        path = line.strip()
        if not path or path.startswith("#"):
            continue
        if "." not in path:
            path = path + ".mp4"
        urls = []
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                i += 1
                break
            if next_line.startswith("#"):
                i += 1
                continue
            if next_line.startswith("http://") or next_line.startswith("https://"):
                urls.append(next_line)
                i += 1
            else:
                break
        if urls:
            result[path] = urls
    return result


def download_video(url, output_path):
    _ensure_workdir()
    out_path = WORK_DIR / output_path.strip()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ytdlp = WORK_DIR / "bin" / "yt-dlp"
    if not ytdlp.exists():
        return "yt-dlp not installed. Use 'Install yt-dlp' on the Downloads tab."
    try:
        r = subprocess.run(
            [str(ytdlp), url.strip(), "-o", str(out_path)],
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=3600,
            env=_clean_subprocess_env(),
        )
        if r.returncode != 0:
            return r.stderr or r.stdout or "yt-dlp failed"
        return None
    except OSError as e:
        if e.errno == 8:
            return (
                "yt-dlp binary is for a different platform (e.g. Linux binary on Mac). "
                "Use 'Install yt-dlp' on the Downloads tab to install the correct version for this system."
            )
        return str(e)
    except subprocess.TimeoutExpired:
        return "Download timed out"


def adb_status(tv_ip, port=5555):
    """Check if adb is connected to tv_ip:port."""
    if not tv_ip:
        return {"ok": False, "connected": False, "message": "TV IP is required"}
    if shutil.which("adb") is None:
        return {"ok": False, "connected": False, "message": "adb not found in PATH"}
    target = f"{tv_ip}:{port}"
    try:
        r = subprocess.run(
            ["adb", "devices"],
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=10,
            env=_clean_subprocess_env(),
        )
        if r.returncode != 0:
            return {"ok": False, "connected": False, "message": r.stderr.strip() or "adb devices failed"}
        # adb devices: "serial\tstate" or "serial  state" per line; header "List of devices attached"
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        connected = False
        state = "not connected"
        for ln in lines:
            if ln.startswith("List of"):
                continue
            # Split on tab or multiple spaces to get serial and state
            parts = ln.split("\t") if "\t" in ln else ln.split()
            serial = (parts[0].strip() if parts else "")
            state_part = (parts[1].strip().lower() if len(parts) >= 2 else "")
            if serial != target:
                continue
            if state_part == "device":
                connected = True
                state = "connected"
            elif "unauthorized" in state_part:
                state = "unauthorized (allow adb on TV)"
            elif "offline" in state_part:
                state = "offline"
            else:
                state = state_part or ln
            break
        return {"ok": True, "connected": connected, "message": f"{target} {state}"}
    except Exception as e:
        return {"ok": False, "connected": False, "message": str(e)}


def adb_connect(tv_ip, port=5555):
    """Run adb connect and report result."""
    if not tv_ip:
        return {"ok": False, "connected": False, "message": "TV IP is required"}
    if shutil.which("adb") is None:
        return {"ok": False, "connected": False, "message": "adb not found in PATH"}
    target = f"{tv_ip}:{port}"
    try:
        r = subprocess.run(
            ["adb", "connect", target],
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=15,
            env=_clean_subprocess_env(),
        )
        msg = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        st = adb_status(tv_ip, port)
        return {"ok": r.returncode == 0 and st.get("connected", False), "connected": st.get("connected", False), "message": msg.strip() or st.get("message", "")}
    except Exception as e:
        return {"ok": False, "connected": False, "message": str(e)}


# ---------- Run ----------
def _python_exe():
    """Python to run live-stream.py, prefer bundled runtime if available."""
    bundled = APP_DIR / "runtime-python" / "bin" / "python3"
    if bundled.exists():
        return str(bundled)
    if getattr(sys, "frozen", False):
        return shutil.which("python3") or "python3"
    return sys.executable


def _prepare_runtime_workspace():
    """Create links/files in WORK_DIR that live-stream.py expects relative to cwd."""
    _ensure_workdir()
    app_ffplayout_bin = _app_ffplayout_bin()
    work_ffplayout = WORK_DIR / "ffplayout"
    work_ffplayout_bin = work_ffplayout / "target" / "debug" / "ffplayout"
    if not app_ffplayout_bin.exists():
        return
    # Platform-specific single binary: always copy so we overwrite wrong-arch binary (e.g. Linux binary on Mac)
    if app_ffplayout_bin.parent.name == _PLATFORM_BIN:
        work_ffplayout_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(app_ffplayout_bin, work_ffplayout_bin)
        try:
            work_ffplayout_bin.chmod(0o755)
        except OSError:
            pass
        return
    if work_ffplayout_bin.exists():
        return
    # Remove stale work ffplayout tree if present
    if work_ffplayout.exists() or work_ffplayout.is_symlink():
        try:
            if work_ffplayout.is_symlink() or work_ffplayout.is_file():
                work_ffplayout.unlink()
            else:
                shutil.rmtree(work_ffplayout)
        except OSError:
            pass
    # Legacy: full tree ffplayout/target/debug/ffplayout — symlink or copy from app dir or repo root
    app_ffplayout = APP_DIR / "ffplayout" if (APP_DIR / "ffplayout").exists() else REPO_ROOT / "ffplayout"
    if not app_ffplayout.exists():
        return
    try:
        work_ffplayout.symlink_to(app_ffplayout, target_is_directory=True)
    except OSError:
        shutil.copytree(app_ffplayout, work_ffplayout, dirs_exist_ok=True)


def check_ffmpeg():
    """Return (True, None) if ffmpeg is in PATH, else (False, message with install hint)."""
    if shutil.which("ffmpeg"):
        return True, None
    if sys.platform == "darwin":
        return False, "ffmpeg not found. Install with: brew install ffmpeg"
    return False, "ffmpeg not found. Please install ffmpeg and ensure it is in PATH."


def run_stream(mode, extra_args=None):
    global RUN_PROCESS, RUN_LOGS
    with RUN_LOCK:
        if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
            return False, "Already running"
    _prepare_runtime_workspace()
    if mode != "auth":
        ok, msg = check_ffmpeg()
        if not ok:
            return False, msg
        ffplayout_bin = WORK_DIR / "ffplayout" / "target" / "debug" / "ffplayout"
        if not ffplayout_bin.exists():
            return (
                False,
                f"ffplayout binary not found at {ffplayout_bin}. Build ffplayout first or rebuild AppImage with ffplayout bundled.",
            )
    if mode == "stream":
        yt = youtube_config_status()
        if not yt.get("ok"):
            return False, yt.get("message") or "YouTube config missing"
    cmd = [_python_exe(), "-u", str(STREAM_DIR / "live-stream.py"), "--out", mode, "--conf", str(CONFIG_PATH)]
    if extra_args:
        for k, v in extra_args.items():
            if v is None or v == "":
                continue
            cmd.append(f"--{k}")
            cmd.append(str(v))
    RUN_LOGS.clear()
    try:
        # start_new_session=True so we can kill the whole process group (live-stream + ffplayout + mediamtx)
        kwargs = dict(
            cwd=str(WORK_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_clean_subprocess_env(
                {
                    "AZAN_TV_ROOT": str(APP_DIR),
                    "AZAN_TV_WORKDIR": str(WORK_DIR),
                    "AZAN_TV_CACHEDIR": str(CACHE_DIR),
                    "PYTHONPATH": os.pathsep.join([str(STREAM_DIR), os.environ.get("PYTHONPATH", "")]),
                }
            ),
        )
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        def log_reader():
            global RUN_LOGS
            for line in proc.stdout:
                RUN_LOGS.append(line.rstrip())
                if len(RUN_LOGS) > 500:
                    RUN_LOGS = RUN_LOGS[-500:]
        threading.Thread(target=log_reader, daemon=True).start()
        RUN_PROCESS = proc
        return True, None
    except Exception as e:
        return False, str(e)


def run_status():
    with RUN_LOCK:
        running = RUN_PROCESS is not None and RUN_PROCESS.poll() is None
        logs = list(RUN_LOGS)
    return {"running": running, "logs": logs}


def run_stop():
    global RUN_PROCESS
    with RUN_LOCK:
        proc = RUN_PROCESS
        RUN_PROCESS = None
    if proc is None:
        return
    if proc.poll() is not None:
        return  # already exited
    try:
        if sys.platform != "win32":
            # Kill whole process group (live-stream.py + ffplayout + mediamtx)
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (ProcessLookupError, OSError):
                pass
    except (ProcessLookupError, OSError):
        pass
