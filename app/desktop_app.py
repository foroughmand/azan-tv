#!/usr/bin/env python3
"""
AZAN TV — desktop app (Qt/PySide6) with full Unicode support for Persian text.
"""
import json
import os
import sys
from pathlib import Path

# Set project root when running as PyInstaller bundle (layout: app root contains stream/ and data/)
if getattr(sys, "frozen", False) and "AZAN_TV_ROOT" not in os.environ:
    _exe_dir = Path(sys.executable).resolve().parent
    _parent = _exe_dir.parent
    if (_parent / "stream" / "config.json").exists():
        os.environ["AZAN_TV_ROOT"] = str(_parent)
        os.chdir(_parent)
    elif (_parent / "config.json").exists():
        os.environ["AZAN_TV_ROOT"] = str(_parent)
        os.chdir(_parent)
    else:
        os.environ["AZAN_TV_ROOT"] = str(_exe_dir)
        os.chdir(_exe_dir)

import app_backend as backend

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QTextOption, QDesktopServices, QClipboard
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QFormLayout,
    QProgressBar,
    QGridLayout,
    QScrollArea,
    QGroupBox,
    QCheckBox,
    QStackedWidget,
    QSizePolicy,
)


class DownloadOneWorker(QThread):
    """Run a single download in the background so the UI stays responsive."""
    finished = Signal(object)  # str | None: error message or None on success
    progress = Signal(float, str)

    def __init__(self, url, output_path, preferred_quality="720p", cookie_browser="", cookie_profile="", parent=None):
        super().__init__(parent)
        self.url = url
        self.output_path = output_path
        self.preferred_quality = preferred_quality
        self.cookie_browser = cookie_browser
        self.cookie_profile = cookie_profile

    def run(self):
        def _progress(info):
            self.progress.emit(float(info.get("percent") or 0.0), info.get("status", ""))

        err = backend.download_video(
            self.url,
            self.output_path,
            progress_callback=_progress,
            preferred_quality=self.preferred_quality,
            cookie_browser=self.cookie_browser,
            cookie_profile=self.cookie_profile,
        )
        self.finished.emit(err)


class DownloadQueueWorker(QThread):
    """Download multiple items in sequence without blocking the UI."""
    file_started = Signal(int, int, str)
    file_progress = Signal(int, float, str)
    overall_progress = Signal(int, int)
    finished = Signal(object)

    def __init__(self, tasks, preferred_quality="720p", cookie_browser="", cookie_profile="", parent=None):
        super().__init__(parent)
        self.tasks = list(tasks)
        self.preferred_quality = preferred_quality
        self.cookie_browser = cookie_browser
        self.cookie_profile = cookie_profile

    def run(self):
        total = len(self.tasks)
        completed = 0
        self.overall_progress.emit(0, total)
        for idx, (url, out) in enumerate(self.tasks, start=1):
            self.file_started.emit(idx, total, out)

            def _progress(info, file_idx=idx):
                self.file_progress.emit(file_idx, float(info.get("percent") or 0.0), info.get("status", ""))

            err = backend.download_video(
                url,
                out,
                progress_callback=_progress,
                preferred_quality=self.preferred_quality,
                cookie_browser=self.cookie_browser,
                cookie_profile=self.cookie_profile,
            )
            if err:
                self.finished.emit({"ok": False, "completed": completed, "total": total, "file": out, "error": err})
                return
            completed += 1
            self.overall_progress.emit(completed, total)
            self.file_progress.emit(idx, 100.0, "Finished")
        self.finished.emit({"ok": True, "completed": completed, "total": total})


def _json_dump(obj):
    return json.dumps(obj, indent=4, ensure_ascii=False)


def _json_load(text, err_callback=None):
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        if err_callback:
            err_callback(str(e))
        return None, str(e)


def _make_text_edit(placeholder="", rtl=False):
    te = QTextEdit()
    te.setPlaceholderText(placeholder)
    te.setAcceptRichText(False)
    if rtl:
        opt = QTextOption()
        opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
        te.document().setDefaultTextOption(opt)
    return te


def _show_scrollable_text_dialog(parent, title, text):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(820, 420)
    lo = QVBoxLayout(dlg)
    view = QTextEdit()
    view.setReadOnly(True)
    view.setPlainText(text or "")
    lo.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dlg.accept)
    lo.addWidget(buttons)
    dlg.exec()


class YouTubeSetupWizard(QDialog):
    """Wizard: client secrets path, optional cert generation, then OAuth login."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube setup")
        self.setMinimumSize(500, 400)
        self._parent_app = parent
        self._stack = QStackedWidget()
        self._page = 0

        # Page 0: Client secrets
        p0 = QWidget()
        lo0 = QVBoxLayout(p0)
        lo0.addWidget(QLabel("Step 1: Client secrets file"))
        instr = QLabel(
            "<b>What this is:</b> A JSON file from Google that allows this app to use your YouTube channel for live streaming. "
            "You only need to get it once.<br><br>"
            "<b>How to get it (detailed):</b><br>"
            "1. Open <a href=\"https://console.cloud.google.com/apis/credentials\">Google Cloud Console → Credentials</a>.<br>"
            "2. Select a project (or create one) at the top.<br>"
            "3. Click <b>+ CREATE CREDENTIALS</b> → <b>OAuth client ID</b>.<br>"
            "4. If asked, set the OAuth consent screen: choose <b>External</b>, fill app name and your email, save.<br>"
            "5. Back to Create OAuth client ID: choose <b>Desktop app</b>, give it a name (e.g. AZAN TV), click Create.<br>"
            "6. In the popup, click <b>DOWNLOAD JSON</b> (any filename is fine).<br><br>"
            "<b>Then:</b> Click <b>Choose file</b> below and select the downloaded JSON. The app will copy it into the work folder (and you can also place <tt>client_secret.json</tt> in the <b>keys/</b> folder when running from source)."
        )
        instr.setOpenExternalLinks(True)
        instr.setWordWrap(True)
        instr.setTextFormat(Qt.TextFormat.RichText)
        lo0.addWidget(instr)
        choose_lo = QHBoxLayout()
        self._p0_chosen = QLabel("No file chosen yet.")
        self._p0_chosen.setStyleSheet("color: gray;")
        choose_lo.addWidget(self._p0_chosen)
        btn_choose = QPushButton("Choose client_secret… JSON file")
        def _choose_file():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select YouTube client secrets JSON",
                "",
                "JSON (*.json);;All files (*)",
            )
            if not path:
                return
            cfg, err = backend.config_get()
            if err or not cfg:
                self._p0_status.setText("Could not load config.")
                return
            work_dir = Path(backend.get_paths().get("work_dir", ""))
            dest_name = cfg.get("client_secrets_file", "client_secret.json").strip() or "client_secret.json"
            if not work_dir:
                self._p0_status.setText("Work dir not set.")
                return
            try:
                import shutil
                backend._ensure_workdir()
                src = Path(path).resolve()
                if not src.is_file():
                    self._p0_status.setText("Selected path is not a file.")
                    return
                dest = work_dir / dest_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                cfg["client_secrets_file"] = dest_name
                backend.config_save(cfg)
                self._p0_chosen.setText(f"Copied to {dest}")
                self._p0_chosen.setStyleSheet("")
                self._p0_status.setText("File copied. Click Next to continue.")
                if self._parent_app:
                    data, _ = backend.config_get()
                    if data:
                        self._parent_app._load_config_form(data)
            except Exception as e:
                self._p0_status.setText(f"Error: {e}")
        btn_choose.clicked.connect(_choose_file)
        choose_lo.addWidget(btn_choose)
        lo0.addLayout(choose_lo)
        self._p0_status = QLabel("")
        lo0.addWidget(self._p0_status)
        lo0.addStretch()
        self._stack.addWidget(p0)

        # Page 1: Certificates
        p1 = QWidget()
        lo1 = QVBoxLayout(p1)
        lo1.addWidget(QLabel("Step 2: Certificates (optional)"))
        lo1.addWidget(QLabel("For HTTPS redirect or RTMPS you can generate server.crt and server.key (saved in the keys/ folder when running from source, else in the work folder)."))
        self._cert_status = QLabel("")
        lo1.addWidget(self._cert_status)
        cert_lo = QHBoxLayout()
        btn_gen = QPushButton("Generate server.crt and server.key")
        def _gen_cert():
            ok, msg = backend.generate_self_signed_cert()
            self._cert_status.setText(msg if ok else f"Error: {msg}")
        btn_gen.clicked.connect(_gen_cert)
        cert_lo.addWidget(btn_gen)
        cert_lo.addStretch()
        lo1.addLayout(cert_lo)
        lo1.addStretch()
        self._stack.addWidget(p1)

        # Page 2: OAuth
        p2 = QWidget()
        lo2 = QVBoxLayout(p2)
        lo2.addWidget(QLabel("Step 3: OAuth login"))
        lo2.addWidget(QLabel("Start the login flow. A browser may open, or a URL will appear in the Run tab log — open it and sign in."))
        self._btn_start_oauth = QPushButton("Start OAuth login")
        def _start_and_close():
            if self._parent_app:
                self._parent_app._start_auth_flow()
            self.accept()
        self._btn_start_oauth.clicked.connect(_start_and_close)
        lo2.addWidget(self._btn_start_oauth)
        lo2.addStretch()
        self._stack.addWidget(p2)

        # Buttons
        self._btn_back = QPushButton("Back")
        self._btn_next = QPushButton("Next")
        self._btn_back.clicked.connect(self._go_back)
        self._btn_next.clicked.connect(self._go_next)
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bbox.rejected.connect(self.reject)
        btn_lo = QHBoxLayout()
        btn_lo.addWidget(self._btn_back)
        btn_lo.addWidget(self._btn_next)
        btn_lo.addStretch()
        btn_lo.addWidget(bbox)
        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)
        layout.addLayout(btn_lo)
        self._refresh_p0_display()
        self._update_buttons()

    def _refresh_p0_display(self):
        st = backend.youtube_config_status()
        path_display = st.get("client_secret_path", "") or st.get("client_secret_file", "")
        if path_display:
            self._p0_chosen.setText(path_display)
            self._p0_chosen.setStyleSheet("" if st.get("ok") else "color: #b8860b;")
        else:
            self._p0_chosen.setText("No file chosen yet.")
            self._p0_chosen.setStyleSheet("color: gray;")

    def _update_buttons(self):
        self._btn_back.setVisible(self._page > 0)
        self._btn_next.setVisible(self._page < 2)
        if self._page == 0:
            self._refresh_p0_display()
            st = backend.youtube_config_status()
            if st.get("ok"):
                self._p0_status.setText("Client secrets file found. Click Next to continue.")
            else:
                self._p0_status.setText("Choose the JSON file above (or place client_secret.json in the keys/ folder or work folder), then click Next.")

    def _go_back(self):
        if self._page > 0:
            self._page -= 1
            self._stack.setCurrentIndex(self._page)
            self._update_buttons()

    def _go_next(self):
        if self._page == 0:
            st = backend.youtube_config_status()
            if not st.get("ok"):
                QMessageBox.warning(self, "YouTube setup", st.get("message", "Place client_secret.json in the keys/ folder or work folder (or set path in Config and save)."))
                return
        if self._page < 2:
            self._page += 1
            self._stack.setCurrentIndex(self._page)
            self._update_buttons()


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AZAN TV")
        self.setMinimumSize(700, 500)
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._current_media_items = []
        self._video_desc = {}
        self._program_data = {"program": [], "timer": "media/timer"}
        self._program_groups = []
        self._current_run_mode = None
        self._auth_prompted_url = False
        self._download_worker = None

        self._tab_run()
        self._tab_install()
        self._tab_downloads()
        self._tab_program()
        self._tab_config()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._run_poll_timer = QTimer(self)
        self._run_poll_timer.timeout.connect(self._on_run_poll)

    def _tab_install(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        paths = backend.get_paths()
        lo.addWidget(QLabel(f"App files: {paths['app_dir']}"))
        lo.addWidget(QLabel(f"Working folder: {paths['work_dir']}"))
        lo.addWidget(QLabel(f"Cache/logs folder: {paths['cache_dir']}"))
        build_info = backend.get_build_info() or {}
        build_summary = "Build: unknown"
        if build_info:
            build_summary = (
                f"Build: {build_info.get('build_timestamp_utc', 'unknown')} UTC"
                f" | version {build_info.get('release_version', '?')}"
                f" | arch {build_info.get('target_arch', '?')}"
            )
        lo.addWidget(QLabel(build_summary))
        lo.addWidget(QLabel("Status"))
        self.today_info_label = QLabel("Today: -")
        lo.addWidget(self.today_info_label)
        self.today_warn_label = QLabel("")
        lo.addWidget(self.today_warn_label)
        lo.addWidget(QLabel("Today required files:"))
        self.today_files_text = QTextEdit()
        self.today_files_text.setReadOnly(True)
        self.today_files_text.setMaximumHeight(150)
        lo.addWidget(self.today_files_text)
        btn_lo = QHBoxLayout()
        btn_lo.addWidget(QPushButton("Refresh status", clicked=self._refresh_install))
        btn_lo.addWidget(QPushButton("Download these", clicked=self._download_required_for_today))
        btn_lo.addWidget(QPushButton("Reset to default", clicked=self._clean_app_folders))
        btn_lo.addWidget(QPushButton("Uninstall...", clicked=self._show_uninstall_help))
        btn_lo.addStretch()
        lo.addLayout(btn_lo)
        lo.addWidget(QLabel("Required components"))
        self.install_status_text = QTextEdit()
        self.install_status_text.setReadOnly(True)
        self.install_status_text.setMaximumHeight(180)
        lo.addWidget(self.install_status_text)
        lo.addWidget(QLabel("Install actions are in Downloads (yt-dlp) and Run/TV (MediaMTX)."))
        lo.addWidget(QLabel("ffplayout: build manually (see README). Rust required."))
        self.tabs.addTab(w, "Status")
        self._refresh_install()

    def _clean_app_folders(self):
        paths = backend.get_paths()
        reply = QMessageBox.question(
            self,
            "Reset to default",
            "This will remove all app data and replace it with defaults from the app folder:\n"
            "• Work dir (config, media, bin, settings – everything)\n"
            "• Cache and logs\n\n"
            f"Work dir: {paths['work_dir']}\n"
            f"Cache:    {paths['cache_dir']}\n"
            f"Logs:     {paths['logs_dir']}\n\n"
            "Defaults will be copied from the app on next use. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = backend.clean_app_folders()
        if ok:
            QMessageBox.information(self, "Reset to default", msg)
            self._refresh_install()
        else:
            QMessageBox.critical(self, "Reset to default", msg)

    def _show_uninstall_help(self):
        info = backend.uninstall_info()
        commands = "\n".join(info.get("commands", []))
        QMessageBox.information(
            self,
            "Uninstall AzanTV",
            "For a full uninstall:\n"
            "1. Quit AzanTV.\n"
            "2. Remove the app bundle and user data folders below.\n\n"
            f"App bundle: {info.get('app_dir', '')}\n"
            f"Work dir:   {info.get('work_dir', '')}\n"
            f"Cache dir:  {info.get('cache_dir', '')}\n"
            f"Logs dir:   {info.get('logs_dir', '')}\n\n"
            "Terminal commands:\n"
            f"{commands}\n\n"
            "Note: 'Reset to default' removes user data, but not the app bundle itself.",
        )

    def _refresh_install(self):
        status = backend.install_status()
        lines = [f"  {name}: {'✓' if info.get('installed') else '✗'} {info.get('message') or info.get('path', '')}" for name, info in status.items()]
        self.install_status_text.setPlainText("\n".join(lines))
        req = backend.required_files_for_today()
        self.today_info_label.setText(f"Today: {req.get('date', '-')} | Hijri day: {req.get('hijri_day', '--')}")
        if req.get("error"):
            self.today_warn_label.setText(f"Program warning: {req['error']}")
        else:
            miss = req.get("missing_count", 0)
            self.today_warn_label.setText(
                f"Warning: {miss} required file(s) missing for today." if miss > 0 else "All required files for today are available."
            )
        flines = [f"{'✓' if f['exists'] else '✗'} {f['path']}" for f in req.get("files", [])]
        self.today_files_text.setPlainText("\n".join(flines) if flines else "(none)")

    def _download_required_for_today(self):
        """Switch to Downloads, select missing required files for today, and run the download queue."""
        req = backend.required_files_for_today()
        missing_paths = {f["path"] for f in req.get("files", []) if not f["exists"]}
        if not missing_paths:
            QMessageBox.information(self, "Status", "All required files for today are already available.")
            return
        self.tabs.setCurrentIndex(2)
        self._refresh_media()
        for i in range(self.media_listbox.count()):
            if i < len(self._current_media_items) and self._current_media_items[i]["path"] in missing_paths:
                self.media_listbox.item(i).setCheckState(Qt.CheckState.Checked)
        self._do_download_queue()
        self._refresh_install()

    def _do_install_ytdlp(self):
        err = backend.install_ytdlp()
        if err:
            QMessageBox.critical(self, "Install yt-dlp", err)
        else:
            QMessageBox.information(self, "Install yt-dlp", "Installed successfully.")
            self._refresh_install()

    def _do_install_mediamtx(self):
        err = backend.install_mediamtx()
        if err:
            QMessageBox.critical(self, "Install MediaMTX", err)
        else:
            QMessageBox.information(self, "Install MediaMTX", "Installed successfully.")
            self._refresh_install()

    def _do_install_ffplayout(self):
        err = backend.install_ffplayout()
        if err:
            _show_scrollable_text_dialog(self, "Install ffplayout", err)
        else:
            QMessageBox.information(self, "Install ffplayout", "Installed successfully. You can run desktop/TV/stream now.")

    def _tab_downloads(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.addWidget(QLabel("Media files (from program). {HIJRI_DAY} is expanded to 01..30."))
        self.media_listbox = QListWidget()
        self.media_listbox.currentRowChanged.connect(self._on_media_select)
        lo.addWidget(self.media_listbox)
        btns = QHBoxLayout()
        btns.addWidget(QPushButton("Refresh list", clicked=self._refresh_media))
        btns.addWidget(QPushButton("Select missing", clicked=self._select_missing_media))
        btns.addWidget(QPushButton("Clear selection", clicked=self._clear_media_checks))
        btns.addStretch()
        lo.addLayout(btns)
        lo.addWidget(QLabel("Download selected files (URLs from video-desc.txt, one-by-one):"))
        desc_btn = QPushButton("Restore video-desc.txt from app")
        desc_btn.setToolTip("Copy video-desc.txt from the data/ folder into the work folder, then reload. Use this after you update data/video-desc.txt in the project.")
        def _restore_video_desc():
            ok, msg = backend.restore_video_desc_from_app()
            if ok:
                self._refresh_media()
                self.download_status.setText(msg)
            else:
                QMessageBox.warning(self, "video-desc.txt", msg)
        desc_btn.clicked.connect(_restore_video_desc)
        lo.addWidget(desc_btn)
        form = QFormLayout()
        self.download_url = QComboBox()
        self.download_url.setEditable(True)
        self.download_url.setMinimumWidth(400)
        self.download_url.setToolTip("Optional override URL for single selected item")
        form.addRow("URL:", self.download_url)
        self.download_output = QLineEdit()
        self.download_output.setPlaceholderText("media/name")
        # self.download_output.setMinimumHeight(36)
        self.download_output.setMinimumWidth(420)
        form.addRow("Output:", self.download_output)
        self.download_quality = QComboBox()
        self.download_quality.addItems(["2160p", "1440p", "1080p", "720p", "480p", "360p", "Auto"])
        self.download_quality.setCurrentText("720p")
        self.download_quality.setToolTip("Preferred quality for yt-dlp. This is a soft preference, not a forced exact resolution.")
        form.addRow("Preferred quality:", self.download_quality)
        self.download_use_browser_cookies = QCheckBox("Use browser cookies")
        self.download_use_browser_cookies.setChecked(False)
        self.download_use_browser_cookies.setToolTip("Enable this if yt-dlp should try cookies from an installed browser session.")
        self.download_use_browser_cookies.toggled.connect(self._on_download_cookies_toggled)
        form.addRow("", self.download_use_browser_cookies)
        self.download_cookie_browser = QComboBox()
        self.download_cookie_browser.addItems([
            "Auto",
            "None",
            "Chrome",
            "Chromium",
            "Brave",
            "Edge",
            "Firefox",
            "Safari",
            "Opera",
            "Vivaldi",
            "Whale",
        ])
        self.download_cookie_browser.setCurrentText("Auto")
        self.download_cookie_browser.setToolTip("Auto tries the target computer's available browser cookie stores until one works.")
        form.addRow("Browser cookies:", self.download_cookie_browser)
        self.download_cookie_profile = QLineEdit()
        self.download_cookie_profile.setPlaceholderText("Optional profile/path")
        self.download_cookie_profile.setToolTip("Optional browser profile name or path passed to yt-dlp after the browser name.")
        form.addRow("Cookie profile:", self.download_cookie_profile)
        lo.addLayout(form)
        run_lo = QHBoxLayout()
        self.btn_download_selected = QPushButton("Download selected", clicked=self._do_download_queue)
        self.btn_download_one = QPushButton("Download one", clicked=self._do_download_one)
        self.btn_install_ytdlp = QPushButton("Install yt-dlp", clicked=self._do_install_ytdlp)
        run_lo.addWidget(self.btn_download_selected)
        run_lo.addWidget(self.btn_download_one)
        run_lo.addWidget(self.btn_install_ytdlp)
        run_lo.addStretch()
        lo.addLayout(run_lo)
        lo.addWidget(QLabel("Current file progress:"))
        self.download_file_progress = QProgressBar()
        self.download_file_progress.setRange(0, 100)
        self.download_file_progress.setValue(0)
        lo.addWidget(self.download_file_progress)
        lo.addWidget(QLabel("Overall progress:"))
        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        lo.addWidget(self.download_progress)
        self.download_status = QLabel("Idle")
        lo.addWidget(self.download_status)
        self.tabs.addTab(w, "Downloads")
        self._on_download_cookies_toggled(False)
        self._refresh_media()

    def _refresh_media(self):
        self._video_desc = backend.load_video_desc()
        self._current_media_items = backend.media_list()
        self.media_listbox.clear()
        for m in self._current_media_items:
            status = "✓" if m["exists"] else "✗"
            item = QListWidgetItem(f"  {status}  {m['path']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.media_listbox.addItem(item)
        self.download_progress.setValue(0)
        self.download_file_progress.setValue(0)
        self.download_status.setText("Idle")

    def _on_media_select(self, row):
        if row < 0:
            return
        if row >= len(self._current_media_items):
            return
        path = self._current_media_items[row]["path"]
        self.download_output.setText(path)
        urls = self._video_desc.get(path, [])
        self.download_url.clear()
        self.download_url.addItems(urls)
        if urls:
            self.download_url.setCurrentIndex(0)
        else:
            self.download_url.setEditText("")

    def _select_missing_media(self):
        for i, m in enumerate(self._current_media_items):
            item = self.media_listbox.item(i)
            item.setCheckState(Qt.CheckState.Checked if not m["exists"] else Qt.CheckState.Unchecked)

    def _clear_media_checks(self):
        for i in range(self.media_listbox.count()):
            self.media_listbox.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _selected_media_rows(self):
        rows = []
        for i in range(self.media_listbox.count()):
            if self.media_listbox.item(i).checkState() == Qt.CheckState.Checked:
                rows.append(i)
        return rows

    def _do_download_one(self):
        url = self.download_url.lineEdit().text().strip()
        out = self.download_output.text().strip()
        if not url or not out:
            QMessageBox.warning(self, "Download", "Enter URL and output path.")
            return
        self._start_download_tasks([(url, out)], "Download")

    def _do_download_queue(self):
        rows = self._selected_media_rows()
        if not rows:
            QMessageBox.warning(self, "Download", "Select one or more files in the list first.")
            return
        tasks = []
        override_url = self.download_url.lineEdit().text().strip()
        for r in rows:
            item = self._current_media_items[r]
            out = item["path"]
            # If only one selected and override URL provided, use it; else suggested URL.
            if len(rows) == 1 and override_url:
                url = override_url
            else:
                urls = self._video_desc.get(out, [])
                url = urls[0] if urls else ""
            if not url:
                self.download_status.setText(f"No suggested URL for {out}, skipped.")
                continue
            tasks.append((url, out))
        if not tasks:
            QMessageBox.warning(self, "Download", "No downloadable tasks found (missing URLs).")
            return
        self._start_download_tasks(tasks, "Download queue")

    def _set_download_controls_enabled(self, enabled):
        for widget in (
            self.btn_download_selected,
            self.btn_download_one,
            self.btn_install_ytdlp,
            self.media_listbox,
            self.download_url,
            self.download_output,
            self.download_quality,
            self.download_use_browser_cookies,
        ):
            widget.setEnabled(enabled)
        cookies_enabled = enabled and self.download_use_browser_cookies.isChecked()
        self.download_cookie_browser.setEnabled(cookies_enabled)
        self.download_cookie_profile.setEnabled(cookies_enabled)

    def _on_download_cookies_toggled(self, checked):
        self.download_cookie_browser.setEnabled(checked)
        self.download_cookie_profile.setEnabled(checked)

    def _start_download_tasks(self, tasks, title):
        if self._download_worker is not None and self._download_worker.isRunning():
            QMessageBox.information(self, title, "A download is already running.")
            return
        self._download_title = title
        self.download_progress.setMaximum(max(len(tasks), 1))
        self.download_progress.setValue(0)
        self.download_file_progress.setValue(0)
        self.download_status.setText(f"Preparing {len(tasks)} download(s)...")
        self._set_download_controls_enabled(False)
        self._download_worker = DownloadQueueWorker(
            tasks,
            self.download_quality.currentText(),
            self.download_cookie_browser.currentText() if self.download_use_browser_cookies.isChecked() else "None",
            self.download_cookie_profile.text().strip() if self.download_use_browser_cookies.isChecked() else "",
            self,
        )
        self._download_worker.file_started.connect(self._on_download_file_started)
        self._download_worker.file_progress.connect(self._on_download_file_progress)
        self._download_worker.overall_progress.connect(self._on_download_overall_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_file_started(self, index, total, output_path):
        self.download_file_progress.setValue(0)
        self.download_status.setText(f"Downloading {index}/{total}: {output_path}")

    def _on_download_file_progress(self, index, percent, status):
        self.download_file_progress.setValue(max(0, min(100, int(percent))))
        suffix = f" | {status}" if status else ""
        current = self.download_status.text().split(" | ", 1)[0]
        if not current.startswith("Downloading "):
            current = f"Downloading file {index}"
        self.download_status.setText(f"{current}{suffix}")

    def _on_download_overall_progress(self, completed, total):
        self.download_progress.setMaximum(max(total, 1))
        self.download_progress.setValue(completed)

    def _on_download_finished(self, result):
        completed = int(result.get("completed", 0) or 0)
        total = int(result.get("total", 0) or 0)
        self._set_download_controls_enabled(True)
        self._download_worker = None
        self._refresh_media()
        self._refresh_install()
        self.download_progress.setMaximum(max(total, 1))
        self.download_progress.setValue(completed)
        if result.get("ok"):
            self.download_file_progress.setValue(100 if total else 0)
            self.download_status.setText("All selected downloads finished.")
            QMessageBox.information(self, self._download_title, f"Finished {completed} download(s).")
            return
        self.download_status.setText(f"Failed: {result.get('file', '')}")
        QMessageBox.critical(self, self._download_title, f"Failed for {result.get('file', '')}:\n{result.get('error', 'Unknown error')}")

    def _tab_program(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.addWidget(QLabel("Program editor. All events are visible below. Order is top-to-bottom. Wildcards allowed (e.g. media/quran-j{HIJRI_DAY})."))
        form = QFormLayout()
        self.timer_input = QLineEdit()
        self.timer_input.setPlaceholderText("media/timer")
        form.addRow("Timer source:", self.timer_input)
        lo.addLayout(form)

        # Scroll area containing all events at once (no event selection)
        self.program_scroll = QScrollArea()
        self.program_scroll.setWidgetResizable(True)
        self.program_scroll_content = QWidget()
        self.program_scroll_layout = QVBoxLayout(self.program_scroll_content)
        self.program_scroll.setWidget(self.program_scroll_content)
        lo.addWidget(self.program_scroll)

        top_btns = QHBoxLayout()
        top_btns.addWidget(QPushButton("Refresh media suggestions", clicked=self._refresh_program_media_suggestions))
        top_btns.addStretch()
        lo.addLayout(top_btns)

        lo.addWidget(QPushButton("Save program", clicked=self._save_program))
        self.program_status = QLabel("Idle")
        lo.addWidget(self.program_status)
        data, err = backend.program_get()
        if err:
            QMessageBox.warning(self, "Program", err)
            self._program_data = {"program": [], "timer": "media/timer"}
        else:
            self._program_data = data
        self._build_program_event_groups()
        self.tabs.addTab(w, "Program")

    def _refresh_program_media_suggestions(self):
        media_items = [m["path"].replace(".mp4", "") for m in backend.media_list()]
        for group in self._program_groups:
            group["file_combo"].clear()
            group["file_combo"].addItems(media_items)

    def _build_program_event_groups(self):
        # Ensure program data exists (may not be set yet if called before load)
        program_data = getattr(self, "_program_data", None)
        if not isinstance(program_data, dict):
            program_data = {"program": [], "timer": "media/timer"}
            self._program_data = program_data

        # Clear old groups
        while self.program_scroll_layout.count():
            item = self.program_scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._program_groups = []

        self.timer_input.setText(program_data.get("timer", "media/timer"))
        media_items = [m["path"].replace(".mp4", "") for m in backend.media_list()]
        existing = {e.get("name", ""): e for e in program_data.get("program", [])}
        for event_name in backend.get_event_names():
            event = existing.get(event_name, {"name": event_name, "pre": [], "post": []})
            enabled = event_name in existing
            box = QGroupBox(event_name)
            box_lo = QVBoxLayout(box)
            enabled_cb = QCheckBox("Enabled")
            enabled_cb.setChecked(enabled)
            box_lo.addWidget(enabled_cb)

            lists_lo = QHBoxLayout()
            pre_col = QVBoxLayout()
            pre_col.addWidget(QLabel("Pre files (ordered):"))
            pre_list = QListWidget()
            for s in event.get("pre", []):
                pre_list.addItem(s)
            pre_col.addWidget(pre_list)
            pre_btns = QHBoxLayout()
            pre_btns.addWidget(QPushButton("Up", clicked=lambda _=False, l=pre_list: self._move_item(l, -1)))
            pre_btns.addWidget(QPushButton("Down", clicked=lambda _=False, l=pre_list: self._move_item(l, +1)))
            pre_btns.addWidget(QPushButton("Remove", clicked=lambda _=False, l=pre_list: self._remove_selected(l)))
            pre_col.addLayout(pre_btns)
            lists_lo.addLayout(pre_col)

            post_col = QVBoxLayout()
            post_col.addWidget(QLabel("Post files (ordered):"))
            post_list = QListWidget()
            for s in event.get("post", []):
                post_list.addItem(s)
            post_col.addWidget(post_list)
            post_btns = QHBoxLayout()
            post_btns.addWidget(QPushButton("Up", clicked=lambda _=False, l=post_list: self._move_item(l, -1)))
            post_btns.addWidget(QPushButton("Down", clicked=lambda _=False, l=post_list: self._move_item(l, +1)))
            post_btns.addWidget(QPushButton("Remove", clicked=lambda _=False, l=post_list: self._remove_selected(l)))
            post_col.addLayout(post_btns)
            lists_lo.addLayout(post_col)
            box_lo.addLayout(lists_lo)

            add_lo = QHBoxLayout()
            file_combo = QComboBox()
            file_combo.setEditable(True)
            file_combo.setMinimumWidth(360)
            file_combo.addItems(media_items)
            add_lo.addWidget(QLabel("File/wildcard:"))
            add_lo.addWidget(file_combo)
            add_lo.addWidget(QPushButton("Add to pre", clicked=lambda _=False, c=file_combo, l=pre_list: self._add_from_combo(c, l)))
            add_lo.addWidget(QPushButton("Add to post", clicked=lambda _=False, c=file_combo, l=post_list: self._add_from_combo(c, l)))
            box_lo.addLayout(add_lo)

            self.program_scroll_layout.addWidget(box)
            self._program_groups.append(
                {
                    "name": event_name,
                    "enabled": enabled_cb,
                    "pre_list": pre_list,
                    "post_list": post_list,
                    "file_combo": file_combo,
                }
            )
        self.program_scroll_layout.addStretch()

    def _add_from_combo(self, combo, target_list):
        text = combo.currentText().strip()
        if text:
            target_list.addItem(text)

    def _remove_selected(self, target_list):
        row = target_list.currentRow()
        if row >= 0:
            target_list.takeItem(row)

    def _move_item(self, target_list, delta):
        row = target_list.currentRow()
        if row < 0:
            return
        nrow = row + delta
        if nrow < 0 or nrow >= target_list.count():
            return
        item = target_list.takeItem(row)
        target_list.insertItem(nrow, item)
        target_list.setCurrentRow(nrow)

    def _collect_program_from_groups(self):
        program = []
        for g in self._program_groups:
            if not g["enabled"].isChecked():
                continue
            program.append(
                {
                    "name": g["name"],
                    "pre": [g["pre_list"].item(i).text() for i in range(g["pre_list"].count())],
                    "post": [g["post_list"].item(i).text() for i in range(g["post_list"].count())],
                }
            )
        self._program_data["program"] = program

    def _save_program(self):
        self._collect_program_from_groups()
        self._program_data["timer"] = self.timer_input.text().strip() or "media/timer"
        err = backend.program_save(self._program_data)
        if err:
            QMessageBox.critical(self, "Save program", err)
        else:
            self.program_status.setText("Saved.")

    def _tab_config(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.addWidget(QLabel("Config editor (form-based)."))
        paths = backend.get_paths()
        work_dir_label = QLabel(f"Data folder: {paths.get('work_dir', '')}")
        work_dir_label.setWordWrap(True)
        work_dir_label.setToolTip("To use another folder (e.g. on Mac): quit the app, set AZAN_TV_WORKDIR to your folder, then start the app again.")
        lo.addWidget(work_dir_label)
        _cfg_w = 480  # minimum width for config fields (~2x default)
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        self.cfg_city = QLineEdit()
        self.cfg_city.setMinimumWidth(_cfg_w)
        city_row_widget = QWidget()
        city_row = QHBoxLayout(city_row_widget)
        city_row.setContentsMargins(0, 0, 0, 0)
        city_row.addWidget(self.cfg_city, 1)
        self.btn_check_city = QPushButton("Check city", clicked=self._check_city_name)
        city_row.addWidget(self.btn_check_city)
        form.addRow("City:", city_row_widget)
        self.cfg_city_status = QLabel("City not checked")
        self.cfg_city_status.setWordWrap(False)
        self.cfg_city_status.setMinimumWidth(400)
        form.addRow("Resolved city:", self.cfg_city_status)
        self.cfg_city_aviny = QLineEdit()
        self.cfg_city_aviny.setMinimumWidth(_cfg_w)
        form.addRow("City Aviny ID:", self.cfg_city_aviny)
        self.cfg_source = QLineEdit()
        self.cfg_source.setPlaceholderText("prayertimes:aviny:izhamburg")
        self.cfg_source.setMinimumWidth(_cfg_w)
        form.addRow("Source list:", self.cfg_source)
        self.cfg_title = QLineEdit()
        self.cfg_title.setMinimumWidth(_cfg_w)
        form.addRow("Title:", self.cfg_title)
        self.cfg_description = QTextEdit()
        self.cfg_description.setMinimumWidth(_cfg_w)
        self.cfg_description.setMaximumHeight(20)
        form.addRow("Description:", self.cfg_description)
        self.cfg_thumbnails = QLineEdit()
        self.cfg_thumbnails.setMinimumWidth(_cfg_w)
        form.addRow("Thumbnails URL:", self.cfg_thumbnails)
        self.cfg_privacy = QComboBox()
        self.cfg_privacy.addItems(["private", "unlisted", "public"])
        self.cfg_privacy.setMinimumWidth(_cfg_w)
        form.addRow("Privacy:", self.cfg_privacy)
        self.cfg_ffplayout_template = QLineEdit()
        self.cfg_ffplayout_template.setMinimumWidth(_cfg_w)
        form.addRow("ffplayout template:", self.cfg_ffplayout_template)
        self.cfg_program_template = QLineEdit()
        self.cfg_program_template.setMinimumWidth(_cfg_w)
        form.addRow("Program template:", self.cfg_program_template)
        self.cfg_client_secrets = QLineEdit()
        self.cfg_client_secrets.setPlaceholderText("client_secret.json (in work dir or keys/) or /absolute/path")
        self.cfg_client_secrets.setMinimumWidth(_cfg_w)
        form.addRow("YouTube client secrets file:", self.cfg_client_secrets)
        self.cfg_oauth2 = QLineEdit()
        self.cfg_oauth2.setPlaceholderText("user-oauth2.json (in work dir or keys/) or /absolute/path")
        self.cfg_oauth2.setMinimumWidth(_cfg_w)
        form.addRow("YouTube oauth token file:", self.cfg_oauth2)

        self.cfg_tr = {}
        translation_grid = QGridLayout()
        translation_grid.setHorizontalSpacing(10)
        translation_grid.setVerticalSpacing(4)
        translation_keys = ("imsak", "fajr", "sunrise", "dhuhr", "asr", "sunset", "maghrib", "isha", "midnight")
        for idx, key in enumerate(translation_keys):
            e = QLineEdit()
            e.setMinimumWidth(100)
            self.cfg_tr[key] = e
            row = idx // 3
            col = (idx % 3) * 2
            translation_grid.addWidget(QLabel(f"{key}:"), row, col)
            translation_grid.addWidget(e, row, col + 1)
        translation_widget = QWidget()
        translation_widget.setLayout(translation_grid)
        form.addRow("Translations:", translation_widget)
        lo.addLayout(form)
        lo.addWidget(QPushButton("Save config", clicked=self._save_config))
        self.config_status = QLabel("Idle")
        lo.addWidget(self.config_status)
        data, err = backend.config_get()
        if err:
            QMessageBox.warning(self, "Config", err)
        else:
            self._load_config_form(data)
        self.tabs.addTab(w, "Config")

    def _load_config_form(self, data):
        self.cfg_city.setText(str(data.get("city", "")))
        self.cfg_city_aviny.setText(str(data.get("city_aviny", "")))
        self.cfg_source.setText(str(data.get("source", "")))
        self.cfg_title.setText(str(data.get("title", "")))
        self.cfg_description.setPlainText(str(data.get("description", "")))
        self.cfg_thumbnails.setText(str(data.get("thumbnails", "")))
        privacy = str(data.get("privacy", "unlisted"))
        i = self.cfg_privacy.findText(privacy)
        self.cfg_privacy.setCurrentIndex(i if i >= 0 else 1)
        self.cfg_ffplayout_template.setText(str(data.get("ffplayout_template", "ffplayout-template.yml")))
        self.cfg_program_template.setText(str(data.get("program_template", "network-program-hard.json")))
        self.cfg_client_secrets.setText(str(data.get("client_secrets_file", "client_secret.json")))
        self.cfg_oauth2.setText(str(data.get("oauth2_file", "user-oauth2.json")))
        tr = data.get("translation", {})
        for key, e in self.cfg_tr.items():
            e.setText(str(tr.get(key, "")))

    def _save_config(self):
        try:
            city_aviny = int(self.cfg_city_aviny.text().strip() or "0")
        except ValueError:
            QMessageBox.critical(self, "Save config", "City Aviny ID must be a number.")
            return
        data = {
            "city": self.cfg_city.text().strip(),
            "city_aviny": city_aviny,
            "source": self.cfg_source.text().strip(),
            "title": self.cfg_title.text().strip(),
            "description": self.cfg_description.toPlainText().strip(),
            "thumbnails": self.cfg_thumbnails.text().strip(),
            "privacy": self.cfg_privacy.currentText(),
            "ffplayout_template": self.cfg_ffplayout_template.text().strip() or "ffplayout-template.yml",
            "program_template": self.cfg_program_template.text().strip() or self.cfg_privacy.currentText(),
            "ffplayout_template": self.cfg_ffplayout_template.text().strip() or "ffplayout-template.yml",
            "program_template": self.cfg_program_template.text().strip() or next().strip() or "network-program-hard.json",
            "client_secrets_file": self.cfg_client_secrets.text().strip() or "client_secret.json",
            "oauth2_file": self.cfg_oauth2.text().strip() or "user-oauth2.json",
            "translation": {k: e.text().strip() for k, e in self.cfg_tr.items()},
        }
        backend.config_save(data)
        self.config_status.setText("Saved.")

    def _check_city_name(self):
        city = self.cfg_city.text().strip()
        info = backend.validate_city_name(city)
        if info.get("ok"):
            self.cfg_city_status.setText(info.get("message", "City resolved"))
        else:
            self.cfg_city_status.setText(f"City check failed: {info.get('message', 'Unknown error')}")

    def _tab_run(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(4)
        lo.addWidget(QLabel("Run mode"))
        self.run_mode = QComboBox()
        self.run_mode.addItems(["desktop", "tv", "stream"])
        self.run_mode.currentTextChanged.connect(self._on_run_mode_changed)
        lo.addWidget(self.run_mode)
        self.run_mode_desc = QLabel("")
        lo.addWidget(self.run_mode_desc)

        # TV-only options (hidden when mode is desktop or stream) — two columns
        self.tv_section = QWidget()
        tv_lo = QVBoxLayout(self.tv_section)
        tv_columns = QHBoxLayout()
        form_left = QFormLayout()
        self.tv_adb_ip = QLineEdit()
        self.tv_adb_ip.setPlaceholderText("192.168.1.50")
        form_left.addRow("TV ADB IP:", self.tv_adb_ip)
        self.tv_adb_port = QLineEdit()
        self.tv_adb_port.setText("5555")
        form_left.addRow("TV ADB port:", self.tv_adb_port)
        scan_tv_btn = QPushButton("Scan TVs", clicked=self._scan_tv_targets)
        form_left.addRow("", scan_tv_btn)
        tv_columns.addLayout(form_left)
        form_right = QFormLayout()
        self.rtsp_host = QLineEdit()
        self.rtsp_host.setPlaceholderText("192.168.1.1")
        rtsp_row_widget = QWidget()
        rtsp_row = QHBoxLayout(rtsp_row_widget)
        rtsp_row.setContentsMargins(0, 0, 0, 0)
        rtsp_row.addWidget(self.rtsp_host, 1)
        rtsp_btn = QPushButton("Set to this machine's IP")
        rtsp_row_widget.setSizePolicy(
            rtsp_row_widget.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Minimum,
        )
        def _set_rtsp_host():
            ip = backend.get_local_ip()
            self.rtsp_host.setText(ip)
        rtsp_btn.clicked.connect(_set_rtsp_host)
        rtsp_row.addWidget(rtsp_btn)
        form_right.addRow("RTSP host:", rtsp_row_widget)
        self.rtsp_port = QLineEdit()
        self.rtsp_port.setText("8554")
        form_right.addRow("RTSP port:", self.rtsp_port)
        tv_columns.addLayout(form_right)
        tv_lo.addLayout(tv_columns)
        adb_lo = QHBoxLayout()
        self.btn_adb_status = QPushButton("Check ADB", clicked=self._check_adb)
        self.btn_adb_connect = QPushButton("ADB Connect", clicked=self._connect_adb)
        self.btn_adb_restart = QPushButton("Restart ADB", clicked=self._restart_adb)
        self.adb_status_label = QLabel("ADB status: unknown")
        self.adb_status_label.setWordWrap(True)
        self.adb_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.adb_status_label.setToolTip("Full ADB output is also written to the run log file below.")
        self.btn_install_mediamtx = QPushButton("Install MediaMTX", clicked=self._do_install_mediamtx)
        self.btn_install_ffplayout = QPushButton("Install ffplayout", clicked=self._do_install_ffplayout)
        adb_lo.addWidget(self.btn_adb_status)
        adb_lo.addWidget(self.btn_adb_connect)
        adb_lo.addWidget(self.btn_adb_restart)
        adb_lo.addWidget(self.btn_install_mediamtx)
        adb_lo.addWidget(self.btn_install_ffplayout)
        adb_lo.addWidget(self.adb_status_label)
        adb_lo.addStretch()
        tv_lo.addLayout(adb_lo)
        lo.addWidget(self.tv_section)

        yt_lo = QHBoxLayout()
        self.btn_yt_check = QPushButton("Check YouTube config", clicked=self._check_youtube_cfg)
        self.btn_yt_login = QPushButton("YouTube login (OAuth)", clicked=self._run_youtube_login)
        self.yt_status_label = QLabel("YouTube status: unknown")
        yt_lo.addWidget(self.btn_yt_check)
        yt_lo.addWidget(self.btn_yt_login)
        yt_lo.addWidget(self.yt_status_label)
        yt_lo.addStretch()
        lo.addLayout(yt_lo)

        start_stop_row = QHBoxLayout()
        self.run_btn = QPushButton("Start", clicked=self._run_selected_mode)
        self.stop_btn = QPushButton("Stop", clicked=self._run_stop)
        self.stop_btn.setEnabled(False)
        start_stop_row.addWidget(self.run_btn)
        start_stop_row.addWidget(self.stop_btn)
        start_stop_row.addStretch()
        lo.addLayout(start_stop_row)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status:"))
        self.run_status_label = QLabel("Stopped")
        status_row.addWidget(self.run_status_label)
        status_row.addStretch()
        lo.addLayout(status_row)
        run_paths = backend.get_paths()
        self.run_log_path_label = QLabel(f"Run log file: {run_paths['run_log_file']}")
        self.run_log_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.run_log_path_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        lo.addWidget(self.run_log_path_label)
        self.stream_section = QWidget()
        self.stream_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        stream_sec_lo = QVBoxLayout(self.stream_section)
        stream_sec_lo.setContentsMargins(0, 0, 0, 0)
        stream_sec_lo.setSpacing(2)
        stream_link_row = QHBoxLayout()
        stream_link_row.addWidget(QLabel("Stream link (when live):"))
        self.stream_link_label = QLabel("")
        self.stream_link_label.setOpenExternalLinks(True)
        self.stream_link_label.setWordWrap(False)
        self.stream_link_label.setTextFormat(Qt.TextFormat.RichText)
        stream_link_row.addWidget(self.stream_link_label, 1)
        self.stream_copy_btn = QPushButton("Copy")
        self.stream_copy_btn.clicked.connect(self._copy_stream_url)
        self.stream_copy_btn.setEnabled(False)
        stream_link_row.addWidget(self.stream_copy_btn)
        stream_sec_lo.addLayout(stream_link_row)
        stream_addr_row = QHBoxLayout()
        stream_addr_row.addWidget(QLabel("Stream address:"))
        self.stream_address_label = QLabel("")
        self.stream_address_label.setWordWrap(False)
        self.stream_address_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        stream_addr_row.addWidget(self.stream_address_label, 1)
        stream_sec_lo.addLayout(stream_addr_row)
        lo.addWidget(self.stream_section)
        lo.addWidget(QLabel("Log"))
        self.run_log = _make_text_edit()
        self.run_log.setReadOnly(True)
        lo.addWidget(self.run_log)
        self.tabs.insertTab(0, w, "Run")
        self._load_run_config()
        self._on_run_mode_changed(self.run_mode.currentText())

    def _load_run_config(self):
        """Load TV/RTSP fields from config so they persist."""
        cfg, err = backend.config_get()
        if err or not cfg:
            return
        self.tv_adb_ip.setText((cfg.get("tv_adb_ip") or "").strip())
        self.tv_adb_port.setText((cfg.get("tv_adb_port") or "5555").strip())
        self.rtsp_host.setText((cfg.get("rtsp_host") or "").strip())
        self.rtsp_port.setText((cfg.get("rtsp_port") or "8554").strip())

    def _save_run_config(self):
        """Save TV/RTSP fields to config (call after connect or run TV)."""
        cfg, err = backend.config_get()
        if err or not cfg:
            return
        cfg["tv_adb_ip"] = self.tv_adb_ip.text().strip()
        cfg["tv_adb_port"] = self.tv_adb_port.text().strip() or "5555"
        cfg["rtsp_host"] = self.rtsp_host.text().strip()
        cfg["rtsp_port"] = self.rtsp_port.text().strip() or "8554"
        backend.config_save(cfg)

    def _on_tab_changed(self, index):
        """When switching to Run tab (index 0), refresh ADB status and button states."""
        if index == 0:
            self._update_run_buttons()
            if self.run_mode.currentText() == "tv":
                self._check_adb()

    def _on_run_mode_changed(self, mode):
        is_tv = mode == "tv"
        is_youtube = mode == "stream"
        self.tv_section.setVisible(is_tv)
        self.btn_yt_check.setVisible(is_youtube)
        self.btn_yt_login.setVisible(is_youtube)
        self.yt_status_label.setVisible(is_youtube)
        self.stream_section.setVisible(is_tv or is_youtube)
        if mode == "desktop":
            self.run_mode_desc.setText("Desktop: local playback only. No YouTube required.")
        elif mode == "tv":
            self.run_mode_desc.setText("TV: runs MediaMTX + ffplayout and opens VLC on TV. Requires ADB connection.")
        else:
            self.run_mode_desc.setText("Stream: creates YouTube live stream + broadcast and pushes ffplayout to it.")
        if is_tv:
            self._check_adb()
        elif is_youtube:
            self._check_youtube_cfg()
        self._update_run_buttons()

    def _check_adb(self):
        ip = self.tv_adb_ip.text().strip() or self.rtsp_host.text().strip()
        try:
            port = int(self.tv_adb_port.text().strip() or "5555")
        except ValueError:
            self.adb_status_label.setText("ADB status: invalid port")
            self.adb_status_label.setToolTip("ADB status: invalid port")
            return
        st = backend.adb_status(ip, port)
        message = st.get("message", "")
        details = st.get("details") or message
        self.adb_status_label.setText(f"ADB status: {message}")
        self.adb_status_label.setToolTip(details)

    def _scan_tv_targets(self):
        self.adb_status_label.setText("ADB status: scanning local network...")
        self.adb_status_label.setToolTip("Scanning local network for likely TV ADB endpoints.")
        targets = backend.discover_tv_adb_targets()
        if not targets:
            self.adb_status_label.setText("ADB status: no TV-like ADB targets found")
            self.adb_status_label.setToolTip("No open ADB ports were found on the local /24 network scan.")
            QMessageBox.information(self, "Scan TVs", "No likely TV ADB targets were found on the local network.")
            return
        options = [
            f"{t['name']} | {t['ip']}:{t['port']} | source={t.get('source', '?')}"
            + (f" | host={t['host_name']}" if t.get("host_name") else "")
            + (f" | service={t['service_type']}" if t.get("service_type") else "")
            for t in targets
        ]
        selected, ok = QInputDialog.getItem(self, "Scan TVs", "Choose a TV/device:", options, 0, False)
        if not ok or not selected:
            self.adb_status_label.setText("ADB status: scan cancelled")
            self.adb_status_label.setToolTip("TV scan completed, but no device was chosen.")
            return
        choice = targets[options.index(selected)]
        self.tv_adb_ip.setText(choice["ip"])
        self.tv_adb_port.setText(str(choice["port"]))
        self.adb_status_label.setText(f"ADB status: selected {choice['name']} at {choice['ip']}:{choice['port']}")
        self.adb_status_label.setToolTip(selected)

    def _connect_adb(self):
        ip = self.tv_adb_ip.text().strip() or self.rtsp_host.text().strip()
        try:
            port = int(self.tv_adb_port.text().strip() or "5555")
        except ValueError:
            self.adb_status_label.setText("ADB status: invalid port")
            self.adb_status_label.setToolTip("ADB status: invalid port")
            return
        st = backend.adb_connect(ip, port)
        message = st.get("message", "")
        details = st.get("details") or message
        self.adb_status_label.setText(f"ADB status: {message}")
        self.adb_status_label.setToolTip(details)
        if st.get("connected"):
            self._save_run_config()

    def _restart_adb(self):
        st = backend.restart_adb_server()
        message = st.get("message", "")
        details = st.get("details") or message
        self.adb_status_label.setText(f"ADB status: {message}")
        self.adb_status_label.setToolTip(details)

    def _highlight_youtube_buttons(self, on):
        """Highlight YouTube setup buttons when config is missing so user knows what to click."""
        style = (
            "background-color: #f0b030; font-weight: bold; border: 2px solid #b8860b;"
            if on else ""
        )
        self.btn_yt_login.setStyleSheet(style)
        self.btn_yt_check.setStyleSheet(style)

    def _check_youtube_cfg(self):
        st = backend.youtube_config_status()
        if not st.get("ok"):
            self.yt_status_label.setText(f"YouTube status: {st.get('message', 'Missing config')}")
            self._highlight_youtube_buttons(True)
            return
        # Files exist; verify connection to Google/YouTube
        verify_ok, verify_msg = backend.youtube_auth_verify()
        if verify_ok:
            self.yt_status_label.setText("YouTube status: OK (connected to Google)")
            self._highlight_youtube_buttons(False)
        else:
            self.yt_status_label.setText(f"YouTube status: {verify_msg}")
            self._highlight_youtube_buttons(True)

    def _start_auth_flow(self):
        """Start YouTube OAuth flow (called from wizard or directly)."""
        st = backend.youtube_config_status()
        if not st.get("client_secret_exists"):
            QMessageBox.warning(self, "YouTube login", st.get("message", "Missing client_secret.json. Add it to the work folder or app keys/ folder."))
            return
        self._current_run_mode = "auth"
        self._auth_prompted_url = False
        ok, err = backend.run_stream("auth")
        if not ok:
            QMessageBox.critical(self, "YouTube login", err or "Failed to start OAuth flow")
            return
        self._run_poll_timer.start(1000)

    def _run_youtube_login(self):
        """Open YouTube setup wizard (client secrets, certs, OAuth)."""
        YouTubeSetupWizard(self).exec()
        self._check_youtube_cfg()

    def _run_selected_mode(self):
        mode = self.run_mode.currentText()
        self._current_run_mode = mode
        self._auth_prompted_url = False
        # Check required media files before starting (desktop, tv, stream)
        req = backend.required_files_for_today()
        if req.get("missing_count", 0) > 0:
            missing = [f["path"] for f in req.get("files", []) if not f.get("exists")]
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Run")
            box.setText(
                "Some media files for today's program are missing.\n\nMissing:\n"
                + "\n".join(missing[:20])
                + ("\n..." if len(missing) > 20 else "")
            )
            download_btn = box.addButton("Download required files", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if box.clickedButton() == download_btn:
                self._download_required_for_today()
            return
        if req.get("error") and not req.get("files"):
            QMessageBox.critical(self, "Start", req.get("error", "Could not load program."))
            return
        if mode == "stream":
            yt = backend.youtube_config_status()
            if not yt.get("ok"):
                QMessageBox.critical(
                    self,
                    "Start stream",
                    yt.get("message", "YouTube config missing. Add client_secret.json and complete OAuth (user-oauth2.json) in the work folder or app keys/ folder."),
                )
                return
            verify_ok, verify_msg = backend.youtube_auth_verify()
            if not verify_ok:
                QMessageBox.critical(self, "Start stream", verify_msg)
                return
        if mode == "tv":
            try:
                port = int(self.tv_adb_port.text().strip() or "5555")
            except ValueError:
                QMessageBox.warning(self, "Start TV", "Invalid ADB port.")
                return
            ip = self.tv_adb_ip.text().strip() or self.rtsp_host.text().strip()
            st = backend.adb_status(ip, port)
            if not st.get("connected", False):
                st = backend.adb_connect(ip, port)
                self.adb_status_label.setText(f"ADB status: {st.get('message', '')}")
            if not st.get("connected", False):
                QMessageBox.critical(
                    self,
                    "Start TV",
                    f"ADB is not connected.\n\n{st.get('message', 'Please check TV ADB IP and port.')}",
                )
                return
            self._save_run_config()
        extra = {
            "ip": self.tv_adb_ip.text().strip() or self.rtsp_host.text().strip() or None,
            "rtsp-host": self.rtsp_host.text().strip() or None,
            "rtsp-port": self.rtsp_port.text().strip() or None,
        }
        if mode != "tv":
            extra = None
        ok, err = backend.run_stream(mode, extra)
        if not ok:
            QMessageBox.critical(self, "Start", err or "Failed to start")
        else:
            self._run_was_running = True
            self._run_poll_timer.start(1000)

    def _update_run_buttons(self):
        """Enable Start when stopped, enable Stop when running."""
        running = backend.run_status().get("running", False)
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _run_stop(self):
        backend.run_stop()
        self._run_poll_timer.stop()
        self._update_run_ui()

    def _on_run_poll(self):
        st = backend.run_status()
        was_running = getattr(self, "_run_was_running", False)
        self._run_was_running = st["running"]
        # When process exits unexpectedly, show log in a dialog so user sees the error (e.g. ffmpeg missing)
        if was_running and not st["running"]:
            logs = st.get("logs", [])
            tail = "\n".join(logs[-50:]) if len(logs) > 50 else "\n".join(logs)
            if tail.strip():
                QMessageBox.critical(
                    self,
                    "Run stopped",
                    "Process exited. Last output:\n\n" + tail,
                )
        self._update_run_ui()
        if self._current_run_mode == "auth" and not self._auth_prompted_url:
            import re
            logs = backend.run_status().get("logs", [])
            joined = "\n".join(logs)
            m = re.search(r"https?://\S+", joined)
            if m:
                self._auth_prompted_url = True
                url = m.group(0).rstrip(").,")
                ans = QMessageBox.question(
                    self,
                    "Open authorization URL?",
                    f"Open this URL in your browser?\n\n{url}",
                )
                if ans == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(url))
        if not backend.run_status()["running"]:
            self._run_poll_timer.stop()

    def _copy_stream_url(self):
        url = getattr(self, "_current_stream_url", None)
        if url:
            QApplication.clipboard().setText(url)
            self.stream_copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.stream_copy_btn.setText("Copy"))

    def _update_run_ui(self):
        import re
        st = backend.run_status()
        self.run_status_label.setText("Running" if st["running"] else "Stopped")
        if st.get("log_file"):
            self.run_log_path_label.setText(f"Run log file: {st['log_file']}")
        self._update_run_buttons()
        logs = st["logs"]
        self.run_log.setPlainText("\n".join(logs) or "(no output yet)")
        sb = self.run_log.verticalScrollBar()
        sb.setValue(sb.maximum())
        joined = "\n".join(logs)
        link_url = None
        stream_addr = None
        # YouTube stream link
        m = re.search(r"url=(https://youtu\.be/[^\s)\],]+)", joined)
        if m:
            link_url = m.group(1).rstrip(").,")
        if not link_url:
            m = re.search(r"(https://youtu\.be/[a-zA-Z0-9_-]+)", joined)
            if m:
                link_url = m.group(1)
        # Live RTSP URL (TV mode): "Live url: rtsp://host:port/live. You can open this link."
        if not link_url:
            m_rtsp = re.search(r"\nLive url:\s*\"(rtsp://[^\"]+)\".", joined)
            if m_rtsp:
                link_url = m_rtsp.group(1).strip()
        m2 = re.search(r"stream_url:\s*(\S+)", joined)
        if m2:
            stream_addr = m2.group(1).strip()
        self._current_stream_url = link_url
        self.stream_copy_btn.setEnabled(bool(link_url))
        if link_url:
            self.stream_link_label.setText(f'<a href="{link_url}">{link_url}</a>')
        else:
            self.stream_link_label.setText("(link will appear here when the stream is live)")
        if stream_addr:
            self.stream_address_label.setText(stream_addr)
        else:
            self.stream_address_label.setText("(stream address from output)")

    def closeEvent(self, event):
        self._run_poll_timer.stop()
        backend.run_stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    # Use a font that supports Arabic/Persian (Qt has good Unicode support)
    try:
        from PySide6.QtGui import QFontDatabase
        families = set(QFontDatabase.families())
        for name in ("Noto Sans Arabic", "DejaVu Sans", "FreeSans", "Liberation Sans", "Arial"):
            if name in families:
                app.setFont(QFont(name, 10))
                break
    except Exception:
        pass
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
