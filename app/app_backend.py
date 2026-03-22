#!/usr/bin/env python3
"""
AZAN TV backend for desktop app.

APP_DIR: code/templates shipped with the app.
WORK_DIR: user data (config/media/bin/tmp). On Mac: ~/Library/Application Support/azan-tv.
CACHE_DIR: cache data. On Mac: ~/Library/Caches/azan-tv.
LOGS_DIR: log files. On Mac: ~/Library/Logs/azan-tv; on Linux: ~/.local/state/azan-tv or CACHE_DIR.
Stream file paths are resolved in order: WORK_DIR, CACHE_DIR, LOGS_DIR, then app-bundled.
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, date as date_cls
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
    _default_logs = Path.home() / "Library" / "Logs" / "azan-tv"
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
    _xdg_state = os.environ.get("XDG_STATE_HOME")
    _default_logs = Path(_xdg_state) / "azan-tv" if _xdg_state else Path.home() / ".local" / "state" / "azan-tv"

WORK_DIR = Path(os.environ.get("AZAN_TV_WORKDIR", str(_default_work))).resolve()
CACHE_DIR = Path(os.environ.get("AZAN_TV_CACHEDIR", str(_default_cache))).resolve()
LOGS_DIR = Path(os.environ.get("AZAN_TV_LOGDIR", str(_default_logs))).resolve()

CONFIG_PATH = WORK_DIR / "config.json"
VIDEO_DESC_PATH = WORK_DIR / "video-desc.txt"

# Platform-specific subdirs for bin/ and ffplayout/ (so one repo can hold both Mac and Linux binaries)
_PLATFORM_BIN = "mac" if sys.platform == "darwin" else "linux"

RUN_PROCESS = None
RUN_LOGS = []
RUN_LOCK = threading.Lock()
EVENT_NAMES = ["imsak", "fajr", "sunrise", "dhuhr", "asr", "sunset", "maghrib", "isha", "midnight"]
KNOWN_MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m3u8", ".ts", ".flv"}
RUN_LOG_FILE = "desktop-app-run.log"

_PERSIAN_GREGORIAN_MONTHS = {
    "ژانویه": 1, "ژانويه": 1, "january": 1,
    "فوریه": 2, "فوريه": 2, "february": 2,
    "مارس": 3, "march": 3, "مارچ": 3,
    "آوریل": 4, "آوريل": 4, "اپریل": 4, "آپریل": 4, "april": 4,
    "مه": 5, "می": 5, "may": 5,
    "ژوئن": 6, "ژون": 6, "june": 6,
    "ژوئیه": 7, "ژوئيه": 7, "ژویه": 7, "july": 7,
    "اوت": 8, "آگوست": 8, "august": 8,
    "سپتامبر": 9, "september": 9,
    "اکتبر": 10, "اکتوبر": 10, "october": 10,
    "نوامبر": 11, "نومبر": 11, "november": 11,
    "دسامبر": 12, "december": 12,
}

_HIJRI_MONTHS = {
    "محرم": 1, "محرّم": 1, "muharram": 1, "Muharram": 1,
    "صفر": 2, "safar": 2, "Safar": 2,
    "ربيع الاول": 3, "ربيع الأول": 3, "ربیع الاول": 3, "ربیع‌الاول": 3, "rabi al-awwal": 3, "Rabi al-Awwal": 3,
    "ربيع الآخر": 4, "ربيع الثاني": 4, "ربیع الثانی": 4, "ربیع‌الثانی": 4, "rabi al-thani": 4, "Rabi al-Thani": 4,
    "جمادى الاول": 5, "جمادى الأولى": 5, "جمادی الاول": 5, "جمادی‌الاول": 5, "jumada al-awwal": 5, "Jumada al-Awwal": 5,
    "جمادى الآخر": 6, "جمادى الثانية": 6, "جمادی الثانی": 6, "جمادی‌الثانی": 6, "jumada al-thani": 6, "Jumada al-Thani": 6,
    "رجب": 7, "rajab": 7, "Rajab": 7,
    "شعبان": 8, "sha'ban": 8, "shaaban": 8, "Sha'ban": 8, "Shaaban": 8,
    "رمضان": 9, "ramadan": 9, "Ramadan": 9,
    "شوال": 10, "shawwal": 10, "Shawwal": 10,
    "ذو القعدة": 11, "ذو القعده": 11, "ذیقعده": 11, "ذو‌القعدة": 11, "dhu al-qidah": 11, "Dhu al-Qidah": 11,
    "ذو الحجة": 12, "ذو الحجه": 12, "ذیحجه": 12, "ذو‌الحجة": 12, "dhu al-hijjah": 12, "Dhu al-Hijjah": 12,
}


def _subprocess_path_prefix():
    """Path prefix for subprocess PATH: downloaded executables (WORK_DIR/bin) first, then app/bin/mac or app/bin/linux."""
    work_bin = WORK_DIR / "bin"
    app_bin = APP_DIR / "bin" / _PLATFORM_BIN
    if not app_bin.exists():
        app_bin = APP_DIR / "bin"
    if not app_bin.exists():
        app_bin = REPO_ROOT / "bin" / _PLATFORM_BIN
    if not app_bin.exists():
        app_bin = REPO_ROOT / "bin"
    parts = [str(work_bin), str(app_bin)]
    return os.pathsep.join(parts)


def _clean_subprocess_env(extra=None):
    """
    Environment for external tools launched from bundled app.
    PyInstaller onefile sets LD_LIBRARY_PATH to its temp dir (/tmp/_MEI*),
    which can break host binaries like yt-dlp with relocation errors.
    Prepend WORK_DIR/bin (downloaded executables) and app/bin/mac|linux to PATH so ffprobe, ffmpeg, etc. are found.
    """
    env = os.environ.copy()
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    path_prefix = _subprocess_path_prefix()
    env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def _which_in_app_path(cmd_name):
    """Resolve an executable using the same PATH we give to subprocesses."""
    env = _clean_subprocess_env()
    return shutil.which(cmd_name, path=env.get("PATH", ""))


def _date_from_day_month_year(day, month_name, year, month_map):
    month_name = month_name.strip()
    month_num = month_map.get(month_name)
    if month_num is None:
        key = month_name.replace("\u200c", " ").replace("  ", " ").strip()
        for k, v in month_map.items():
            if k.replace("\u200c", " ").replace("  ", " ").strip() == key:
                month_num = v
                break
        if month_num is None:
            raise ValueError(f"Unknown month name: {month_name!r}")
    return f"{year:04d}/{month_num:02d}/{day:02d}"


def _parse_najaf_date_html(html):
    date_span = re.search(r"<span\s+class=['\"]date['\"]\s*>([\s\S]*?)</span>", html)
    if not date_span:
        raise ValueError("Could not find <span class='date'> in HTML")
    inner = date_span.group(1)
    gregorian_part = re.search(r"^([^<]+)", inner, re.DOTALL)
    if not gregorian_part:
        raise ValueError("Could not find Gregorian date part before <br>")
    gregorian_text = gregorian_part.group(1).replace("<br>", "").replace("<br/>", "").strip()
    g_match = re.match(r"(\d+)\s*/\s*([^/]+?)\s*/\s*(\d+)", gregorian_text)
    if not g_match:
        raise ValueError(f"Gregorian date format not recognized: {gregorian_text!r}")
    g_day, g_month_name, g_year = int(g_match.group(1)), g_match.group(2).strip(), int(g_match.group(3))
    gregorian = _date_from_day_month_year(g_day, g_month_name, g_year, _PERSIAN_GREGORIAN_MONTHS)

    qamari_strong = re.search(r"<strong\s+class=['\"]my-blue['\"]\s*>([^<]+)</strong>", inner)
    if not qamari_strong:
        raise ValueError("Could not find <strong class='my-blue'> in HTML")
    qamari_text = qamari_strong.group(1).strip()
    q_match = re.match(r"(\d+)\s*/\s*([^/]+?)\s*/\s*(\d+)", qamari_text)
    if not q_match:
        raise ValueError(f"Qamari date format not recognized: {qamari_text!r}")
    q_day, q_month_name, q_year = int(q_match.group(1)), q_match.group(2).strip(), int(q_match.group(3))
    qamari = _date_from_day_month_year(q_day, q_month_name, q_year, _HIJRI_MONTHS)
    return {"gregorian": gregorian, "qamari": qamari}


def _hijri_year_from_gregorian_date(d):
    return (d.year - 622) * 33 // 32


def _parse_praytimes_org_islamic_date(html, gregorian_date):
    m = re.search(r'<span\s+class=["\']islamic-date\s+text-muted["\']\s*>([^<]+)</span>', html, re.IGNORECASE)
    if not m:
        raise ValueError("Could not find praytimes.org islamic date span")
    text = m.group(1).strip()
    parts = text.split(None, 1)
    if len(parts) != 2:
        raise ValueError(f"Islamic date format not recognized: {text!r}")
    day = int(parts[0])
    month_name = parts[1].strip()
    year = _hijri_year_from_gregorian_date(gregorian_date)
    return _date_from_day_month_year(day, month_name, year, _HIJRI_MONTHS)


def _fetch_text(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "AzanTV/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def validate_city_name(city_name):
    """
    Validate/resolve a city using the same Nominatim data source as gen_playlist.
    Returns resolved display name, country, lat/lon on success.
    """
    query = (city_name or "").strip()
    if not query:
        return {"ok": False, "message": "City name is required"}
    try:
        url = (
            "https://nominatim.openstreetmap.org/search?"
            + urllib.parse.urlencode(
                {
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                }
            )
        )
        rows = json.loads(_fetch_text(url, timeout=8))
        if not rows:
            return {"ok": False, "message": f'City "{query}" was not found'}
        item = rows[0]
        address = item.get("address") or {}
        country = address.get("country") or (item.get("display_name", "").split(",")[-1].strip() if item.get("display_name") else "")
        return {
            "ok": True,
            "query": query,
            "display_name": item.get("display_name", query),
            "country": country,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "message": f'{item.get("display_name", query)} | Country: {country}',
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}


def _resolve_hijri_day_for_date(g_date):
    cfg, _ = config_get()
    city_aviny = (cfg or {}).get("city_aviny", 2130)
    try:
        body = _fetch_text(f"https://prayer.aviny.com/api/prayertimes/{city_aviny}", timeout=2)
        today_qamari = json.loads(body)["TodayQamari"]
        return int(str(today_qamari).split("/")[2])
    except Exception:
        pass
    try:
        parsed = _parse_najaf_date_html(_fetch_text("https://www.najaf.org/persian/prayer.php?city=united-kingdom_london", timeout=10))
        return int(parsed["qamari"].split("/")[2])
    except Exception:
        pass
    try:
        today_qamari = _parse_praytimes_org_islamic_date(_fetch_text("https://praytimes.org/", timeout=10), g_date)
        return int(today_qamari.split("/")[2])
    except Exception:
        return _gregorian_to_hijri_day(g_date)


def _ensure_workdir():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
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
    # Copy app/bundles (fonts) to WORK_DIR/app/bundles so ffplayout overlay font path (app/bundles/...) resolves.
    app_bundles_src = APP_DIR / "bundles"
    work_bundles_dst = WORK_DIR / "app" / "bundles"
    if app_bundles_src.is_dir() and (not work_bundles_dst.exists() or not (work_bundles_dst / "Vazirmatn-RD-FD-NL-Regular.ttf").exists()):
        work_bundles_dst.parent.mkdir(parents=True, exist_ok=True)
        if work_bundles_dst.exists():
            for f in app_bundles_src.iterdir():
                if f.is_file():
                    dst_f = work_bundles_dst / f.name
                    if not dst_f.exists():
                        try:
                            shutil.copy2(f, dst_f)
                        except PermissionError:
                            shutil.copy(f, dst_f)
        else:
            try:
                shutil.copytree(app_bundles_src, work_bundles_dst)
            except PermissionError:
                work_bundles_dst.mkdir(parents=True, exist_ok=True)
                for f in app_bundles_src.iterdir():
                    if f.is_file():
                        try:
                            shutil.copy2(f, work_bundles_dst / f.name)
                        except PermissionError:
                            shutil.copy(f, work_bundles_dst / f.name)
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
    """Expose app/work/cache/logs dirs for UI display."""
    return {
        "app_dir": str(APP_DIR),
        "work_dir": str(WORK_DIR),
        "cache_dir": str(CACHE_DIR),
        "logs_dir": str(LOGS_DIR),
        "run_log_file": str(LOGS_DIR / RUN_LOG_FILE),
    }


def get_build_info():
    build_info_path = APP_DIR / "build-info.json"
    if not build_info_path.exists():
        return None
    try:
        with open(build_info_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def uninstall_info():
    """Return user-facing uninstall targets and shell commands."""
    app_path = APP_DIR
    work_path = WORK_DIR
    cache_path = CACHE_DIR
    logs_path = LOGS_DIR
    if sys.platform == "darwin":
        commands = [
            f'rm -rf "{work_path}"',
            f'rm -rf "{cache_path}"',
            f'rm -rf "{logs_path}"',
            f'rm -rf "{app_path.parent.parent.parent}"',
        ]
    else:
        commands = [
            f'rm -rf "{work_path}"',
            f'rm -rf "{cache_path}"',
            f'rm -rf "{logs_path}"',
            f'rm -rf "{app_path}"',
        ]
    return {
        "app_dir": str(app_path),
        "work_dir": str(work_path),
        "cache_dir": str(cache_path),
        "logs_dir": str(logs_path),
        "commands": commands,
    }


def _write_run_log_line(line):
    _ensure_workdir()
    log_path = LOGS_DIR / RUN_LOG_FILE
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _log_adb_event(title, message):
    _write_run_log_line(f"[ADB] {title}")
    for line in (message or "").splitlines() or [""]:
        _write_run_log_line(f"[ADB] {line}")


def _log_download_event(title, message):
    _write_run_log_line(f"[yt-dlp] {title}")
    for line in (message or "").splitlines() or [""]:
        _write_run_log_line(f"[yt-dlp] {line}")


def _run_adb(adb_path, args, timeout=15):
    return subprocess.run(
        [adb_path] + list(args),
        cwd=str(WORK_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_subprocess_env(),
    )


def _adb_details(adb_path, args, result):
    cmd = " ".join([adb_path] + list(args))
    return f"cmd: {cmd}\nreturncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}".strip()


def _should_restart_adb_server(message):
    text = (message or "").lower()
    restart_markers = (
        "no route to host",
        "cannot connect",
        "connection refused",
        "connection reset",
        "broken pipe",
        "failed to connect",
        "device offline",
        "more than one device",
    )
    return any(marker in text for marker in restart_markers)


def _restart_adb_server(adb_path):
    kill_res = _run_adb(adb_path, ["kill-server"], timeout=10)
    _log_adb_event("adb kill-server", _adb_details(adb_path, ["kill-server"], kill_res))
    start_res = _run_adb(adb_path, ["start-server"], timeout=10)
    _log_adb_event("adb start-server", _adb_details(adb_path, ["start-server"], start_res))
    return kill_res, start_res


def restart_adb_server():
    """Restart the local adb server and report the result."""
    adb_path = _which_in_app_path("adb")
    if adb_path is None:
        msg = "adb not found in the app bundle or PATH"
        _log_adb_event("adb restart", msg)
        return {"ok": False, "message": msg, "details": msg}
    try:
        kill_res, start_res = _restart_adb_server(adb_path)
        details = (
            f"{_adb_details(adb_path, ['kill-server'], kill_res)}\n\n"
            f"{_adb_details(adb_path, ['start-server'], start_res)}"
        )
        ok = start_res.returncode == 0
        message = "ADB server restarted" if ok else (start_res.stderr.strip() or "adb start-server failed")
        return {"ok": ok, "message": message, "details": details}
    except Exception as e:
        msg = str(e)
        _log_adb_event("adb restart", msg)
        return {"ok": False, "message": msg, "details": msg}


def clean_app_folders():
    """
    Reset to default: remove cache, logs, and the entire work dir (Application Support).
    Work dir is recreated empty; on next use the app will repopulate it from app defaults
    (config templates, video-desc, bundles, keys, etc.).
    Returns (ok: bool, message: str).
    """
    removed = []
    try:
        # Remove and recreate CACHE_DIR entirely
        if CACHE_DIR.exists():
            try:
                shutil.rmtree(CACHE_DIR)
                removed.append(str(CACHE_DIR))
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                (CACHE_DIR / "tmp").mkdir(exist_ok=True)
                (CACHE_DIR / "logs").mkdir(exist_ok=True)
            except OSError as e:
                return False, f"Failed to remove cache: {e}"
        # Remove and recreate LOGS_DIR entirely
        if LOGS_DIR.exists():
            try:
                shutil.rmtree(LOGS_DIR)
                removed.append(str(LOGS_DIR))
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return False, f"Failed to remove logs: {e}"
        # Remove entire work dir (all settings, config, media, bin, tmp, data, etc.) and recreate empty.
        # Next _ensure_workdir() will copy defaults from the app folder.
        if WORK_DIR.exists():
            try:
                shutil.rmtree(WORK_DIR)
                removed.append(str(WORK_DIR))
                WORK_DIR.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return False, f"Failed to remove work dir: {e}"
        return True, f"Reset complete. Removed {len(removed)} folder(s). Settings and files will be restored from app defaults on next use."
    except Exception as e:
        return False, str(e)


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


def _adb_mdns_targets():
    adb_path = _which_in_app_path("adb")
    if adb_path is None:
        return []
    try:
        check_res = _run_adb(adb_path, ["mdns", "check"], timeout=5)
        if check_res.returncode != 0:
            return []
        services_res = _run_adb(adb_path, ["mdns", "services"], timeout=5)
        if services_res.returncode != 0:
            return []
    except Exception:
        return []

    targets = []
    for raw_line in (services_res.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
        if not match:
            continue
        ip = match.group(1)
        port = int(match.group(2))
        service_type = ""
        service_match = re.search(r"(_adb-[\w-]+\._tcp\.?)", line)
        if service_match:
            service_type = service_match.group(1)
        name_part = line[:match.start()].strip()
        if service_type and name_part.endswith(service_type):
            name_part = name_part[: -len(service_type)].strip()
        if not name_part:
            name_part = f"TV {ip}"
        targets.append(
            {
                "ip": ip,
                "port": port,
                "name": name_part,
                "host_name": "",
                "source": "adb-mdns",
                "service_type": service_type,
            }
        )
    return targets


def discover_tv_adb_targets():
    """
    Scan the local /24 for likely TV ADB endpoints and return a short list.
    This does not require an existing ADB connection.
    """
    local_ip = get_local_ip()
    parts = local_ip.split(".")
    if len(parts) != 4 or local_ip == "127.0.0.1":
        return []
    subnet_prefix = ".".join(parts[:3])
    own_ip = local_ip
    candidate_ports = (5555, 6467)

    def _friendly_tv_name(host, host_name):
        raw = (host_name or "").strip()
        if raw:
            short = raw.split(".", 1)[0]
            if short and short.lower() not in ("localhost", host.replace(".", "-")):
                return short
        return ""

    def _probe(host, port):
        try:
            with socket.create_connection((host, port), timeout=0.2):
                try:
                    host_name = socket.gethostbyaddr(host)[0]
                except Exception:
                    host_name = ""
                return {
                    "ip": host,
                    "port": port,
                    "name": _friendly_tv_name(host, host_name),
                    "host_name": host_name,
                    "source": "port-scan",
                    "service_type": "",
                }
        except Exception:
            return None

    results = list(_adb_mdns_targets())
    futures = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for last in range(1, 255):
            host = f"{subnet_prefix}.{last}"
            if host == own_ip:
                continue
            for port in candidate_ports:
                futures.append(pool.submit(_probe, host, port))
        for fut in as_completed(futures):
            item = fut.result()
            if item:
                results.append(item)

    dedup = {}
    for item in results:
        key = item["ip"]
        current = dedup.get(key)
        if current is None:
            dedup[key] = item
            continue
        if not current.get("name") and item.get("name"):
            current["name"] = item["name"]
        if current.get("source") != "adb-mdns" and item.get("source") == "adb-mdns":
            dedup[key] = item
            current = dedup[key]
        if current["port"] != 5555 and item["port"] == 5555:
            current["port"] = item["port"]
            if item.get("service_type"):
                current["service_type"] = item["service_type"]
        if not current.get("host_name") and item.get("host_name"):
            current["host_name"] = item["host_name"]
    for item in dedup.values():
        if not item.get("name"):
            item["name"] = f"TV {item['ip']}"
    return sorted(dedup.values(), key=lambda x: x["ip"])


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
    """Path to program JSON. Resolves template (e.g. stream/network-program-hard.json) to a path under WORK_DIR or app."""
    _ensure_workdir()
    default_name = "network-program-hard.json"
    if not CONFIG_PATH.exists():
        return WORK_DIR / default_name
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    template = cfg.get("program_template", default_name)
    # Config may say "stream/network-program-hard.json" (repo layout); we copy the file to WORK_DIR without stream/
    candidates = [
        WORK_DIR / template,
        WORK_DIR / os.path.basename(template),
        WORK_DIR / default_name,
        STREAM_DIR / template,
        STREAM_DIR / default_name,
    ]
    for p in candidates:
        if p.exists():
            return p
    return WORK_DIR / template


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


def _resolve_youtube_file(config_path, default_basename):
    """Resolve path: try WORK_DIR first, then KEYS_DIR (app keys folder). Returns (resolved_path, exists)."""
    p = Path(config_path).expanduser()
    if p.is_absolute():
        return p, p.exists()
    work_path = WORK_DIR / p
    if work_path.exists():
        return work_path, True
    if KEYS_DIR.exists():
        keys_path = KEYS_DIR / p.name
        if keys_path.exists():
            return keys_path, True
    return work_path, False


def youtube_config_status():
    """Check whether YouTube config files exist for stream/browser modes. Resolves paths: WORK_DIR first, then app keys/ folder."""
    _ensure_workdir()
    cfg, err = config_get()
    if err or cfg is None:
        return {"ok": False, "message": err or "config.json not found", "client_secret_path_resolved": None, "oauth2_path_resolved": None}
    client_secret = cfg.get("client_secrets_file", "client_secret.json")
    oauth_file = cfg.get("oauth2_file", "user-oauth2.json")
    cs_path, cs_exists = _resolve_youtube_file(client_secret, "client_secret.json")
    oauth_path, oauth_exists = _resolve_youtube_file(oauth_file, "user-oauth2.json")
    ok = cs_exists and oauth_exists
    if not ok:
        if not cs_exists:
            msg = f"Missing client secrets: {cs_path} (not in work dir or app keys/)"
        else:
            msg = f"Missing OAuth token file: {oauth_path} (not in work dir or app keys/)"
    else:
        msg = None
    return {
        "ok": ok,
        "client_secret_file": client_secret,
        "oauth2_file": oauth_file,
        "client_secret_path": str(cs_path),
        "oauth2_path": str(oauth_path),
        "client_secret_path_resolved": str(cs_path),
        "oauth2_path_resolved": str(oauth_path),
        "client_secret_exists": cs_exists,
        "oauth2_exists": oauth_exists,
        "message": msg,
    }


def youtube_auth_verify():
    """
    Verify YouTube credentials by connecting to Google (runs live-stream --out check).
    Returns (ok: bool, message: str).
    """
    st = youtube_config_status()
    if not st.get("ok"):
        return False, st.get("message", "YouTube config missing")
    cs = st.get("client_secret_path_resolved")
    oauth = st.get("oauth2_path_resolved")
    if not cs or not oauth:
        return False, "Resolved paths missing"
    cmd = [
        _python_exe(),
        "-u",
        str(STREAM_DIR / "live-stream.py"),
        "--out", "check",
        "--conf", str(CONFIG_PATH),
        "--work-dir", str(WORK_DIR),
        "--client-secrets", cs,
        "--oauth2-file", oauth,
    ]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=15,
            env=_clean_subprocess_env(_python_runtime_env()),
        )
        if r.returncode == 0 and "OK" in (r.stdout or ""):
            return True, "Connected to Google/YouTube"
        err = (r.stderr or "").strip() or (r.stdout or "").strip()
        return False, err or "Connection check failed"
    except subprocess.TimeoutExpired:
        return False, "Connection check timed out"
    except Exception as e:
        return False, str(e)


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
    """Path to ffplayout binary: accept both dedicated ffplayout/ and bundled bin/ layouts."""
    for root in (APP_DIR, REPO_ROOT):
        candidates = [
            root / "ffplayout" / _PLATFORM_BIN / "ffplayout",
            root / "bin" / _PLATFORM_BIN / "ffplayout",
            root / "bin" / "ffplayout",
        ]
        for p in candidates:
            if p.exists():
                return p
        if _PLATFORM_BIN == "linux":
            q = root / "ffplayout" / "target" / "debug" / "ffplayout"
            if q.exists():
                return q
    return APP_DIR / "ffplayout" / _PLATFORM_BIN / "ffplayout"


def install_status():
    _ensure_workdir()
    ffmpeg_path = _which_in_app_path("ffmpeg")
    ffmpeg_ok = ffmpeg_path is not None
    ffplay_path = _which_in_app_path("ffplay")
    ffplay_ok = ffplay_path is not None
    ffplay_msg = ffplay_path or "not found"
    ffplayout_path = _app_ffplayout_bin()
    ffplayout_ok = ffplayout_path.exists()
    mediamtx_path = WORK_DIR / "bin" / "mediamtx"
    mediamtx_ok = mediamtx_path.exists()
    ytdlp_path = WORK_DIR / "bin" / "yt-dlp"
    ytdlp_ok = ytdlp_path.exists()
    rust_ok = shutil.which("cargo") is not None
    return {
        "ffmpeg": {"installed": ffmpeg_ok, "message": ffmpeg_path or "not found"},
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


def _media_glob_base(path):
    """Return media path without its final known media extension."""
    p = (path or "").strip()
    if not p:
        return p
    suffix = Path(p).suffix.lower()
    if suffix in KNOWN_MEDIA_EXTENSIONS:
        return str(Path(p).with_suffix(""))
    return p


def _find_media_file(path):
    """
    Resolve a media file only inside WORK_DIR.

    We match both the exact relative path and any sibling file with the same
    basename and any extension, so a configured `media/foo.mp4` can match
    `media/foo.webm` or `media/foo.mp4.webm`.
    """
    _ensure_workdir()
    rel = (path or "").strip()
    if not rel:
        return None
    exact = WORK_DIR / rel
    if exact.exists():
        return exact
    base_rel = _media_glob_base(rel)
    base_path = WORK_DIR / base_rel
    parent = base_path.parent
    if not parent.exists():
        return None
    for candidate in sorted(parent.glob(base_path.name + ".*")):
        if candidate.is_file():
            return candidate
    return None


def _media_exists(path):
    return _find_media_file(path) is not None


def _download_target_template(output_path):
    """
    yt-dlp output template with its own chosen media extension.

    If the UI asks for `media/foo.mp4`, yt-dlp should receive
    `media/foo.%(ext)s` so it creates `media/foo.webm` instead of
    `media/foo.mp4.webm`. If the UI asks for `media/foo` with no extension, we
    still want yt-dlp to append its chosen extension instead of creating a
    suffixless file.
    """
    out = (output_path or "").strip()
    if not out:
        return out
    return _media_glob_base(out) + ".%(ext)s"


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
        out.append({"path": base, "exists": _media_exists(base)})
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
    hijri_day = _resolve_hijri_day_for_date(today)
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
        exists = _media_exists(rel)
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


def _preferred_quality_sort(preferred_quality):
    """Return yt-dlp sort preference for a target height without forcing an exact match."""
    value = (preferred_quality or "").strip().lower()
    if not value or value == "auto":
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return f"res:{digits}"


def _yt_dlp_cookie_candidates(cookie_browser="", cookie_profile=""):
    browser = (cookie_browser or "").strip().lower()
    profile = (cookie_profile or "").strip()
    if not browser or browser in ("none",):
        return [None]
    if browser == "auto":
        candidates = [
            None,
            "chrome",
            "chromium",
            "brave",
            "edge",
            "firefox",
            "safari",
            "opera",
            "vivaldi",
            "whale",
        ]
    else:
        candidates = [browser]
    result = []
    for candidate in candidates:
        if candidate is None:
            result.append(None)
            continue
        result.append(f"{candidate}:{profile}" if profile else candidate)
    return result


def download_video(url, output_path, progress_callback=None, preferred_quality="720p", cookie_browser="", cookie_profile=""):
    _ensure_workdir()
    target_rel = _download_target_template(output_path)
    out_path = WORK_DIR / target_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ytdlp = WORK_DIR / "bin" / "yt-dlp"
    if not ytdlp.exists():
        return "yt-dlp not installed. Use 'Install yt-dlp' on the Downloads tab."
    progress_template = "AZAN_PROGRESS:%(progress._percent_str)s|%(progress._downloaded_bytes_str)s|%(progress._total_bytes_str)s|%(progress._speed_str)s|%(progress._eta_str)s"
    base_cmd = [
        str(ytdlp),
        "--newline",
        "--progress-template",
        progress_template,
    ]
    quality_sort = _preferred_quality_sort(preferred_quality)
    if quality_sort:
        base_cmd.extend(["-S", quality_sort])
    base_cmd.extend([
        url.strip(),
        "-o",
        str(out_path),
    ])
    last_error = None
    try:
        for cookie_spec in _yt_dlp_cookie_candidates(cookie_browser, cookie_profile):
            cmd = list(base_cmd)
            attempt_label = "no browser cookies"
            if cookie_spec:
                cmd[1:1] = ["--cookies-from-browser", cookie_spec]
                attempt_label = f"browser cookies: {cookie_spec}"
            _log_download_event("start", f"attempt: {attempt_label}\ncmd: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                cwd=str(WORK_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=_clean_subprocess_env(),
            )
            output_lines = []
            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    output_lines.append(line)
                    _log_download_event("output", line)
                    if progress_callback and line.startswith("AZAN_PROGRESS:"):
                        payload = line.split(":", 1)[1]
                        parts = payload.split("|", 4)
                        percent_text = parts[0].strip() if parts else ""
                        match = re.search(r"(\d+(?:\.\d+)?)", percent_text)
                        percent = float(match.group(1)) if match else 0.0
                        downloaded = parts[1].strip() if len(parts) > 1 else ""
                        total = parts[2].strip() if len(parts) > 2 else ""
                        speed = parts[3].strip() if len(parts) > 3 else ""
                        eta = parts[4].strip() if len(parts) > 4 else ""
                        status_parts = [p for p in (downloaded, total and f"/ {total}", speed and f"at {speed}", eta and f"ETA {eta}") if p]
                        progress_callback(
                            {
                                "percent": percent,
                                "status": " ".join(status_parts) if status_parts else percent_text,
                                "output_path": output_path,
                            }
                        )
            try:
                returncode = proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                _log_download_event("finish", f"{attempt_label} timed out")
                return "Download timed out"
            if returncode == 0:
                if progress_callback:
                    progress_callback({"percent": 100.0, "status": "Finished", "output_path": output_path})
                _log_download_event("finish", f"{attempt_label} returncode: {returncode}")
                return None
            trimmed = [ln for ln in output_lines if not ln.startswith("AZAN_PROGRESS:")]
            last_error = "\n".join(trimmed[-10:]) or "yt-dlp failed"
            _log_download_event("finish", f"{attempt_label} returncode: {returncode}\nlast_error:\n{last_error}")
        return last_error or "yt-dlp failed"
    except OSError as e:
        if e.errno == 8:
            _log_download_event("finish", f"OSError: {e}")
            return (
                "yt-dlp binary is for a different platform (e.g. Linux binary on Mac). "
                "Use 'Install yt-dlp' on the Downloads tab to install the correct version for this system."
            )
        _log_download_event("finish", f"OSError: {e}")
        return str(e)


def adb_status(tv_ip, port=5555):
    """Check if adb is connected to tv_ip:port."""
    if not tv_ip:
        return {"ok": False, "connected": False, "message": "TV IP is required", "details": "TV IP is required"}
    adb_path = _which_in_app_path("adb")
    if adb_path is None:
        msg = "adb not found in the app bundle or PATH"
        _log_adb_event("adb devices", msg)
        return {"ok": False, "connected": False, "message": msg, "details": msg}
    target = f"{tv_ip}:{port}"
    try:
        r = _run_adb(adb_path, ["devices"], timeout=10)
        details = _adb_details(adb_path, ["devices"], r)
        _log_adb_event("adb devices", details)
        if r.returncode != 0:
            return {
                "ok": False,
                "connected": False,
                "message": r.stderr.strip() or "adb devices failed",
                "details": details,
            }
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
        return {"ok": True, "connected": connected, "message": f"{target} {state}", "details": details}
    except Exception as e:
        msg = str(e)
        _log_adb_event("adb devices", msg)
        return {"ok": False, "connected": False, "message": msg, "details": msg}


def adb_connect(tv_ip, port=5555):
    """Run adb connect and report result."""
    if not tv_ip:
        return {"ok": False, "connected": False, "message": "TV IP is required", "details": "TV IP is required"}
    adb_path = _which_in_app_path("adb")
    if adb_path is None:
        msg = "adb not found in the app bundle or PATH"
        _log_adb_event("adb connect", msg)
        return {"ok": False, "connected": False, "message": msg, "details": msg}
    target = f"{tv_ip}:{port}"
    try:
        r = _run_adb(adb_path, ["connect", target], timeout=15)
        msg = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        details = _adb_details(adb_path, ["connect", target], r)
        _log_adb_event("adb connect", details)
        if _should_restart_adb_server(msg):
            _log_adb_event("adb connect", f"Restarting adb server after connect error for {target}")
            _restart_adb_server(adb_path)
            retry = _run_adb(adb_path, ["connect", target], timeout=15)
            retry_msg = (retry.stdout or "") + ("\n" + retry.stderr if retry.stderr else "")
            retry_details = _adb_details(adb_path, ["connect", target], retry)
            _log_adb_event("adb connect retry", retry_details)
            r = retry
            msg = retry_msg
            details = f"{details}\n\nretry after adb server restart:\n{retry_details}"
        st = adb_status(tv_ip, port)
        summary = msg.strip().splitlines()[0] if msg.strip() else st.get("message", "")
        if st.get("message"):
            summary = f"{summary} | {st.get('message')}" if summary else st.get("message", "")
        combined_details = details
        if st.get("details"):
            combined_details = f"{details}\n\npost-connect status:\n{st.get('details')}"
        return {
            "ok": r.returncode == 0 and st.get("connected", False),
            "connected": st.get("connected", False),
            "message": summary,
            "details": combined_details,
        }
    except Exception as e:
        msg = str(e)
        _log_adb_event("adb connect", msg)
        return {"ok": False, "connected": False, "message": msg, "details": msg}


# ---------- Run ----------
def _python_exe():
    """Python to run live-stream.py, prefer bundled runtime if available."""
    bundled = APP_DIR / "runtime-python" / "bin" / "python3"
    if bundled.exists() and _bundled_python_is_usable():
        return str(bundled)
    if getattr(sys, "frozen", False):
        return shutil.which("python3") or "python3"
    return sys.executable


def _bundled_python_root():
    root = APP_DIR / "runtime-python"
    return root if root.exists() else None


def _bundled_python_lib_dir():
    root = _bundled_python_root()
    if not root:
        return None
    lib_root = root / "lib"
    if not lib_root.exists():
        return None
    for candidate in sorted(lib_root.glob("python*")):
        if candidate.is_dir():
            return candidate
    return None


def _bundled_python_site_packages():
    lib_dir = _bundled_python_lib_dir()
    if not lib_dir:
        return None
    site_packages = lib_dir / "site-packages"
    return site_packages if site_packages.exists() else None


def _bundled_ca_bundle():
    bundled_site = _bundled_python_site_packages()
    if bundled_site:
        certifi_bundle = bundled_site / "certifi" / "cacert.pem"
        if certifi_bundle.exists():
            return certifi_bundle
    return None


def _bundled_python_is_usable():
    lib_dir = _bundled_python_lib_dir()
    if not lib_dir:
        return False
    return (lib_dir / "encodings").exists()


def _python_runtime_env():
    """Environment for running live-stream.py from the app bundle or source."""
    py_paths = [str(STREAM_DIR)]
    bundled_site = _bundled_python_site_packages()
    if bundled_site:
        py_paths.append(str(bundled_site))
    inherited = os.environ.get("PYTHONPATH", "")
    if inherited:
        py_paths.append(inherited)
    extra = {
        "AZAN_TV_ROOT": str(APP_DIR),
        "AZAN_TV_WORKDIR": str(WORK_DIR),
        "AZAN_TV_CACHEDIR": str(CACHE_DIR),
        "AZAN_TV_LOGDIR": str(LOGS_DIR),
        "PYTHONPATH": os.pathsep.join(py_paths),
        "PYTHONNOUSERSITE": "1",
    }
    bundled_root = _bundled_python_root()
    if bundled_root and _python_exe() == str(bundled_root / "bin" / "python3") and _bundled_python_is_usable():
        extra["PYTHONHOME"] = str(bundled_root)
    ca_bundle = _bundled_ca_bundle()
    if ca_bundle:
        extra["SSL_CERT_FILE"] = str(ca_bundle)
        extra["REQUESTS_CA_BUNDLE"] = str(ca_bundle)
        extra["CURL_CA_BUNDLE"] = str(ca_bundle)
    return extra


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
    found = _which_in_app_path("ffmpeg")
    if found:
        return True, found
    if sys.platform == "darwin":
        return False, "ffmpeg not found in the app bundle or system PATH. Put it in bin/mac before building, or install with: brew install ffmpeg"
    return False, "ffmpeg not found. Please install ffmpeg and ensure it is in PATH."


def _user_data_dirs():
    """Order of user folders to check for stream files: Application Support, Caches, Logs (Mac) or equivalent on Linux."""
    return [WORK_DIR, CACHE_DIR, LOGS_DIR]


def _resolve_stream_file(work_path, app_path):
    """Use file from user folders first (Application Support, Caches, Logs), then app-bundled. Returns path for live-stream args."""
    # Check same relative path under each user dir (work_path is under WORK_DIR; build equivalent under CACHE_DIR, LOGS_DIR)
    work_dir = WORK_DIR
    try:
        rel = work_path.relative_to(work_dir)
    except ValueError:
        rel = work_path.name
    for base in _user_data_dirs():
        candidate = base / rel
        if candidate.exists():
            return str(candidate)
    if app_path.exists():
        return str(app_path)
    return str(work_path)


def run_stream(mode, extra_args=None):
    global RUN_PROCESS, RUN_LOGS
    with RUN_LOCK:
        if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
            return False, "Already running"
    _prepare_runtime_workspace()
    app_ffplayout_bin = _app_ffplayout_bin()
    if mode != "auth":
        ok, msg = check_ffmpeg()
        if not ok:
            return False, msg
        if sys.platform == "darwin" and app_ffplayout_bin.exists():
            ffplayout_bin = app_ffplayout_bin
        else:
            ffplayout_bin = WORK_DIR / "ffplayout" / "target" / "debug" / "ffplayout"
        if not ffplayout_bin.exists():
            return (
                False,
                f"ffplayout binary not found at {ffplayout_bin}. Build ffplayout first or rebuild AppImage with ffplayout bundled.",
            )
    yt = None
    if mode == "stream":
        yt = youtube_config_status()
        if not yt.get("ok"):
            return False, yt.get("message") or "YouTube config missing"
    elif mode == "auth":
        yt = youtube_config_status()
        if not yt.get("client_secret_exists"):
            return False, yt.get("message") or "Client secrets file missing (required for YouTube login). Check work dir or app keys/ folder."
    # live-stream.py uses --work-dir and --tmp-folder (paths = work_dir/tmp_folder/filename)
    stream_args = {
        "work-dir": str(WORK_DIR),
        "tmp-folder": "tmp",
        "ffplayout": str(ffplayout_bin) if mode != "auth" else None,
        "mediamtx": str(WORK_DIR / "bin" / "mediamtx"),
        "mediamtx-config": str(WORK_DIR / "bin" / "mediamtx.yml"),
    }
    if mode in ("stream", "auth") and yt:
        cs_resolved = yt.get("client_secret_path_resolved")
        oauth_resolved = yt.get("oauth2_path_resolved")
        if cs_resolved:
            stream_args["client-secrets"] = cs_resolved
        if oauth_resolved:
            stream_args["oauth2-file"] = oauth_resolved
    cmd = [_python_exe(), "-u", str(STREAM_DIR / "live-stream.py"), "--out", mode, "--conf", str(CONFIG_PATH)]
    for k, v in stream_args.items():
        if v is None or v == "":
            continue
        cmd.append(f"--{k}")
        cmd.append(str(v))
    if extra_args:
        for k, v in extra_args.items():
            if v is None or v == "":
                continue
            cmd.append(f"--{k}")
            cmd.append(str(v))
    RUN_LOGS.clear()
    log_path = LOGS_DIR / RUN_LOG_FILE
    _ensure_workdir()
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] Starting mode={mode}\n")
        f.write("Command: " + " ".join(cmd) + "\n")
        f.write("Work dir: " + str(WORK_DIR) + "\n")
        f.write("App dir: " + str(APP_DIR) + "\n")
        f.write("ffmpeg: " + (str(_which_in_app_path("ffmpeg") or "not found") ) + "\n")
        f.write("ffplay: " + (str(_which_in_app_path("ffplay") or "not found") ) + "\n")
        if mode != "auth":
            f.write("ffplayout: " + str(ffplayout_bin) + "\n")
        f.write("\n")
    try:
        # start_new_session=True so we can kill the whole process group (live-stream + ffplayout + mediamtx)
        kwargs = dict(
            cwd=str(WORK_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_clean_subprocess_env(_python_runtime_env()),
        )
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        _write_run_log_line(f"Spawned PID: {proc.pid}")
        def log_reader():
            global RUN_LOGS
            for line in proc.stdout:
                text = line.rstrip()
                RUN_LOGS.append(text)
                _write_run_log_line(text)
                if len(RUN_LOGS) > 500:
                    RUN_LOGS = RUN_LOGS[-500:]
            rc = proc.wait()
            _write_run_log_line(f"Process exited with code {rc}")
        threading.Thread(target=log_reader, daemon=True).start()
        RUN_PROCESS = proc
        return True, None
    except Exception as e:
        _write_run_log_line("Start failed: " + str(e))
        return False, str(e)


def run_status():
    with RUN_LOCK:
        running = RUN_PROCESS is not None and RUN_PROCESS.poll() is None
        logs = list(RUN_LOGS)
    return {"running": running, "logs": logs, "log_file": str(LOGS_DIR / RUN_LOG_FILE)}


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
