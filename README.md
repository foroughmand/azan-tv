# AZAN TV on Youtube or on Smart TVs
With this repository you can create a streaming program with specified program for pre- and post-azan. This will use the program and location information to fetch the actual timing of the events and then with ffplay it creates an stream. Then, the stream could be sent to a live TV program, or could be played locally on Smart TV / mobile phones. 

# End-user easy execution of the released app (Persian)

<div dir="rtl">

## نرم‌افزار شبکه تلویزیونی اوقات شرعی — نسخه مک

یک نسخه کاربرپسندتر از نرم‌افزار آماده شده است. با این نرم‌افزار می‌توانید برنامه اوقات نماز را (شامل چند برنامه قبل و بعد از اذان‌ها) پخش کنید:

- روی **کامپیوتر**
- روی **تلویزیون هوشمند**
- روی **یوتیوب** (و سپس روی هر دستگاهی که یوتیوب پخش می‌کند، به‌صورت هم‌زمان)

---

## چگونه استفاده کنیم؟

**۱. دانلود.**  
نرم‌افزار را از اینجا دانلود کنید.

**۲. نصب.**  
فایل DMG را باز کنید. در پنجره بازشده، آیکون نرم‌افزار را بگیرید و به پوشه «Applications» (برنامه‌ها) که همان‌جا نمایش داده می‌شود بکشید و رها کنید.

**۳. (اختیاری)**  
می‌توانید درایو ایجادشده را ببندید و فایل DMG را از پوشه دانلودها حذف کنید.

**۴. اجرا.**  
برنامه را اجرا کنید.

**۵. تنظیم شهر و عنوان (Config).**  
برگه **Config** را باز کنید:

- در **City** نام شهر خود را به انگلیسی وارد کنید (نرم‌افزار با این نام مکان شهر را پیدا می‌کند).
- در **Title** در صورت تمایل می‌توانید عنوان را به نام شهر خود تغییر دهید (این عنوان در پخش زنده یوتیوب نمایش داده می‌شود).
- **Description** توضیحات برنامه یوتیوب را مشخص می‌کند.

سپس دکمه **Save config** را بزنید.

**۶. دانلود ویدئوهای امروز (Status).**  
به برگه **Status** بروید و دکمه **Download these** را بزنید. صبر کنید تا ویدئوهای برنامه امروز دانلود شوند.

**۷. پخش روی کامپیوتر (Run).**  
به برگه **Run** بروید و دکمه **Start** را بزنید. برنامه اذان‌گاهی روی کامپیوتر شما پخش می‌شود: میزان باقی‌مانده تا اذان بعدی و فاصله از اذان قبلی نمایش داده می‌شود و در زمان هر برنامه، ویدئوی مربوطه پخش می‌شود (مثلاً قبل از اذان مغرب: یک جزء قرآن، یک سوره، اسماءالحسنی؛ پس از اذان مغرب: چند دعا؛ و برنامه‌های کوتاه پیش و پس از اذان صبح و ظهر).

**۸. فعال‌سازی حالت توسعه‌دهنده روی تلویزیون.**  
برای پخش روی تلویزیون هوشمند، ابتدا تلویزیون را در حالت Developer قرار دهید:

- به **Settings → Device Preferences → About** بروید و هفت بار روی **Build number** بزنید تا Developer Options باز شود.
- به **Settings → Developer options** بروید و **USB Debugging** (در صورت نیاز) و **Wireless debugging** را فعال کنید.

**۹. پخش روی تلویزیون.**  
در نرم‌افزار:

- از **Run mode** گزینه **tv** را انتخاب کنید.
- دکمه **Scan TVs** را بزنید، نام تلویزیون خود را در لیست انتخاب کنید، سپس **ADB Connect** را بزنید و درخواست‌های اجازه روی کامپیوتر و تلویزیون را تأیید کنید.
- در سمت راست باید وضعیت **connected** نمایش داده شود. در غیر این صورت **Restart ADB** را بزنید یا IP تلویزیون را بررسی کنید.
- دکمه **Start** را بزنید و صبر کنید تا برنامه روی تلویزیون نمایش داده شود. در صورت مشکل، **Stop** و دوباره **Start** را امتحان کنید.

</div>

# Setup
Download the codes
```
git clone git@github.com:foroughmand/azan-tv.git
cd azan-tv
```

**Repo layout:** **app/** — desktop app (Qt, build scripts, bundles). **stream/** — streaming scripts and config templates (`live-stream.py`, `gen_playlist.py`, `config.json`, `network-program-hard.json`, `ffplayout-template.yml`; generated `playlist4.json`, `ffplayout2.yml`). **data/** — data files (`video-desc.txt`). **keys/** — secrets and certs: `client_secret.json`, `user-oauth2.json`, `server.crt`, `server.key` (place here when running from source; **do not commit** — they are in `.gitignore`). **ffplayout/** and **bin/** stay at repo root. Run builds from **app/**; run the desktop app from repo root with `./run_desktop_app.sh` or from **app/** with `python3 desktop_app.py`.

Install `ffplay`.

The main streaming part is done via ffplayout which we have modified it a little to support customizable text overlay feature of ffmpeg. You can get and build the ffplayout with the following command. For this step, [rust](https://doc.rust-lang.org/cargo/getting-started/installation.html) should be installed. Also, ffplay should be installed, which is currently available as an ubuntu package.
```
git clone git@github.com:foroughmand/ffplayout.git
cd ffplayout
cargo update time
cargo build
cd ..
```

Then, install the Python packages (one command for both stream and desktop app):
```
pip install -r app/requirements.txt
```
Alternatively install stream-only deps with `pip install -r stream/requirements-stream.txt` and app-only with `pip install -r app/requirements-app.txt`.

Put Google auth and TLS files in the **keys/** folder (do not commit them; they are gitignored):

- **client_secret.json** — obtain from [Google Cloud Console](https://console.cloud.google.com/): create a project, enable YouTube access, create [OAuth client credentials](https://cloud.google.com/solutions/sap/docs/abap-sdk/on-premises-or-any-cloud/latest/authentication-oauth-client-credentials#oauth_config_consent), then download the JSON and save it as `keys/client_secret.json`.
- **user-oauth2.json** — created automatically after you complete the YouTube OAuth flow (or copy from another install).
- **server.crt** / **server.key** — optional; for HTTPS redirect or RTMPS. Generate from the desktop app (Installation tab) or with OpenSSL; the app will create them in `keys/` when running from source.


To run the program you need to fill the **media/** folder (in the working directory, e.g. `~/.local/share/azan-tv/media`) with appropriate videos as specified in [stream/network-program-hard.json](stream/network-program-hard.json). Then run:
```
cd stream && python live-stream.py --out desktop --ffplayout ../ffplayout/linux/ffplayout
```
(On macOS use `--ffplayout ../ffplayout/mac/ffplayout`.) Path options default to **tmp/** under the working directory: `--playlist`, `--ffplayout-config`, `--times-info`, `--time-info`, `--translations`, `--stream`. Override with `--work-dir` or pass paths explicitly. The **ffplayout** binary path is required (except for `--out auth`).

Or from repo root: `AZAN_TV_WORKDIR=/path/to/workdir PYTHONPATH=stream python stream/live-stream.py --out desktop --conf /path/to/workdir/config.json --ffplayout /path/to/ffplayout`

Without the `--out` option, the program creates a new live stream on Youtube and its url with be displayed at the end.

# Desktop app (Linux / macOS)
A **native desktop app** (Qt/PySide6) lets you manage installation, downloads, program, config, and run desktop/TV modes — no browser or terminal needed. **Full Unicode support**: Persian and Arabic text display correctly (سحر، صبح، …).

The app uses dedicated **user folders** for data, cache, and logs. When you install the app (e.g. on Mac only the app goes in `/Applications`); the app then uses (and creates when needed):

- **macOS:**  
  - `~/Library/Application Support/azan-tv` — config, media, bin, tmp  
  - `~/Library/Caches/azan-tv` — cache data  
  - `~/Library/Logs/azan-tv` — log files  
- **Linux:**  
  - `~/.local/share/azan-tv` (or `$XDG_DATA_HOME/azan-tv`) — main data  
  - `~/.cache/azan-tv` (or `$XDG_CACHE_HOME/azan-tv`) — cache  
  - `~/.local/state/azan-tv` (or `$XDG_STATE_HOME/azan-tv`) — logs  

When starting a run, paths for playlist, config, and related files are resolved in this order: **Application Support** → **Caches** → **Logs** (if the file exists there); if not in any of these, the app uses files bundled inside the app.

Working folder (Application Support on Mac, share on Linux) contains:
- `config.json` and editable program files (copied from **stream/** templates)
- downloaded media files (`media/`)
- installed helper binaries (`bin/`, e.g. `yt-dlp`, `mediamtx`)
- runtime files (`logs/`, `tmp/`, `ffplayout.log/`; tmp/logs may be symlinked to Caches)
- keys/certs copied from **keys/** when present (`client_secret.json`, `user-oauth2.json`, `server.crt`, `server.key`)

### Platform-specific folders (shared repo for Mac and Linux)

You can keep both Mac and Linux binaries in the same repo:

- **bin/linux/** — `yt-dlp`, `mediamtx`, `mediamtx.yml` for Linux (used by AppImage and when running on Linux).
- **bin/mac/** — same for macOS (used by the Mac .app and when running on a Mac).
- **ffplayout/linux/ffplayout** — Linux ffplayout binary (optional; else the app uses **ffplayout/target/debug/ffplayout** from a local Rust build).
- **ffplayout/mac/ffplayout** — macOS ffplayout binary (optional; else **ffplayout/target/debug/ffplayout** from a Mac build).

The app and build scripts pick the right folder from the current OS. At runtime, binaries are copied into the working folder’s `bin/` and `ffplayout/` as needed.

## Run from source

Install dependencies once, then run from the **app/** directory (or set `AZAN_TV_ROOT` to repo root so the app finds **ffplayout/** and **bin/** at root):

```bash
pip install -r app/requirements.txt
cd app && python3 desktop_app.py
```

From repo root you can use: `AZAN_TV_ROOT="$(pwd)" python3 app/desktop_app.py` so the app finds **ffplayout/** and **bin/** at repo root.

Tabs: **Installation** (status + install yt-dlp / MediaMTX), **Downloads** (media list + download by URL), **Program** (edit program JSON), **Config** (edit config.json), **Run** (desktop / TV + stop + log).

## Build a single executable

From the **app/** directory (install deps once if you haven’t):

```bash
pip install -r app/requirements.txt
cd app && ./build_app.sh
```

This creates **app/dist/azan-tv**.

## Build AppImage

From the **app/** directory (requires **ffplayout** and **bin** at repo root):

```bash
cd app && ./build_appimage.sh
```

This creates **azan-tv-x86_64.AppImage**. The script packages required runtime files and sets:
- `AZAN_TV_ROOT` to bundled app resources inside the AppImage
- `AZAN_TV_WORKDIR` to your persistent data folder (`~/.local/share/azan-tv`)
- Bundled runtime Python dependencies for `live-stream.py`/`gen_playlist.py` from `stream/requirements-stream.txt`

To skip bundling streaming deps and rely on host Python packages:
```bash
cd app && BUNDLE_STREAM_DEPS=0 ./build_appimage.sh
```

## Build for macOS (.app bundle and DMG)

### Pre-steps
Building ffmpeg:
```
# get codes
bin/build/ffmpeg-custom/src/ffmpeg-8.0.1

./configure \
  --prefix="$PWD/stage" \
  --enable-gpl \
  --enable-version3 \
  --enable-shared \
  --disable-static \
  --disable-ffplay \
  --enable-libzmq \
  --enable-libfreetype \
  --enable-libharfbuzz \
  --enable-libfontconfig \
  --enable-libfribidi \
  --enable-libass \
  --enable-libx264 \
  --enable-libx265 \
  --enable-libvpx \
  --enable-libopus \
  --install-name-dir='@rpath' \
  --extra-ldflags='-Wl,-rpath,@executable_path/../Frameworks'

cd stage
ln -sfn lib Frameworks
# test with:
./bin/ffprobe -version

```

### Main

On a Mac, from the **app/** directory (requires **ffplayout** and **bin** at repo root):

```bash
pip install -r app/requirements.txt
cd app && ./build_app_mac.sh
```

This creates **dist/AZAN TV.app**. Open it with `open "dist/AZAN TV.app"` or double-click in Finder. Data is stored in `~/Library/Application Support/azan-tv`.

The build **bundles a Python runtime** with all stream dependencies (same as AppImage), so the .app runs **without** the user installing any Python packages. To skip bundling and use system Python instead: `BUNDLE_STREAM_DEPS=0 ./build_app_mac.sh`.

### What the .app (and DMG) can contain

- **Always included:** The Qt app, `live-stream.py`, `gen_playlist.py`, config/program templates, and (by default) a bundled Python runtime with stream deps so Run works out of the box.
- **Bundled if present:** If you have Mac binaries in the project before building, they are copied into the .app and then into the user’s data folder on first run:
  - **ffplayout** — build for Mac (Rust: `cargo build` in the ffplayout repo) and put the binary at **ffplayout/mac/ffplayout** (or **ffplayout/target/debug/ffplayout**) at repo root; the script will bundle it.
  - **yt-dlp** and **mediamtx** — put Mac builds in **bin/mac/** at repo root, or run:

    ```bash
    cd app && BUNDLE_MAC_BINARIES=1 ./build_app_mac.sh
    ```

  That downloads Mac builds of yt-dlp and mediamtx into `bin/` and bundles them, so the .app (and a DMG you create from it) is **self-contained**: users do not need to install ffplayout, yt-dlp, or mediamtx separately. **ffplayout** must still be built for Mac and placed in the project before building if you want it in the DMG.

### Create a DMG for distribution

After building the .app (and optionally with `BUNDLE_MAC_BINARIES=1`):

```bash
cd app
mkdir -p dist/dmg
cp -R "dist/AZAN TV.app" dist/dmg/
hdiutil create -volname "AZAN TV" -srcfolder dist/dmg -ov -format UDZO "dist/AZAN TV.dmg"
```

Users open the DMG, drag **AZAN TV** to Applications, and run it. The app will copy any bundled yt-dlp/mediamtx into `~/Library/Application Support/azan-tv/bin` on first run. If ffplayout was bundled, it is used from the app bundle.

## Install to application menu (Linux, non-AppImage)

After building from **app/**:

```bash
cd app && ./build_app.sh && ./install_app.sh
```

This installs a launcher under `~/.local/opt/azan-tv` and adds **AZAN TV** to your application menu. Override install locations:

```bash
cd app && AZAN_TV_INSTALL_DIR=/opt/azan-tv AZAN_TV_BIN_DIR=/usr/local/bin sudo ./install_app.sh
```

## Installing mediamtx
Install mediamtx (for low latency version, `--out tv`):
```
wget https://github.com/bluenviron/mediamtx/releases/download/v1.11.3/mediamtx_v1.11.3_linux_amd64.tar.gz
mkdir -p bin
cd bin/
tar xzf ../mediamtx_v1.11.3_linux_amd64.tar.gz
cd ..
```

Connect to tv with `adb` (`192.168.178.61:5555` is the ip of tv):
```
adb connect 192.168.178.61:5555
```

Run the application. Ports are used for TV. (From **stream/** directory.)
```
python live-stream.py --out tv --ffplayout ../ffplayout/linux/ffplayout --rtsp-host 192.168.178.68 --rtsp-port 8554 --tv-name Sony
```
Note that the previous command creates the stream, and also opens the VLC application on tv for playing the stream. For that, the application uses the tv-name option for finding the TV by the chromecast library.

# Output options:

## TV
This will run MediaMTX locally, then opens VLC on the TV playing the MediaMTX url. For this, MediaMTX should be installed locally on `bin/mediamtx`, VLC should be installed on the TV, ADB Debugging should be enabled on the TV, pure-python-adb package should be installed locally.

To install MediaMTX, download the appropriate standalone file from this [reposiotry](https://github.com/bluenviron/mediamtx) and put it as `bin/mediamtx`.
```
wget https://github.com/bluenviron/mediamtx/releases/download/v1.12.0/mediamtx_v1.12.0_linux_amd64.tar.gz
tar xzf mediamtx_v1.12.0_linux_amd64.tar.gz
rm LICENSE
mkdir -p bin/
mv mediamtx mediamtx.yml bin/
```

Install `pure-python-adb` with
```
pip install pure-python-adb
```

### How to Enable ADB on Sony BRAVIA TV (2024+ models):
Enable Developer Options:
* Go to Settings → System → About → Build Number.
* Click "Build Number" 7 times until it says "You are now a developer."

Enable ADB Debugging:
* Go back to Settings → System → Developer Options.
* Find and turn ON:
  * USB Debugging
  * Network Debugging (or ADB over Network).

# Configuration (setting the location)
Configurations are located at file [stream/config.json](stream/config.json) (template); the app copies it to the working folder for editing. 
* `city`: Name of the city. After searching it in map services, lat and long of the city is retrieved and prayer times are retrieved from izhamburg website.
* `city_aviny`: Id of the city in prayer.aviny.com website for retrieving prayer times from this website.
* `source`: Colon separated list of services from which the prayer times are fetched. The options are "prayertimes", "avini", "izhamburg".
* `title`, `description`, `thumbnails`, `privacy`: Settings for the Youtube broadcast.
* `ffplayout_template`: The template file for the ffplayout application. The ffplayout config file will be generated from this template file after injecting the Youtube stream link into it.
* `program_template`: Template file for the program before and after prayer times.

# Setting up the playlist
Suggested download URLs for each media file are in [data/video-desc.txt](data/video-desc.txt) (one or more URLs per path; paths with `{HIJRI_DAY}` are listed as separate entries for days 01..30). The desktop app uses this file to suggest URLs when you click a file in the Downloads tab.

If you obtained the copyright of the files, install [yt-dlp](https://github.com/yt-dlp/yt-dlp), as follows:
```
mkdir -p bin/
wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O bin/yt-dlp
chmod +x bin/yt-dlp
```

Then download files mentioned in the current network program with the following commands
```
bin/yt-dlp https://www.youtube.com/watch?v=ZM1VANg8H9E -f mp4 -o media/timer.mp4
bin/yt-dlp https://www.youtube.com/watch?v=y07yhEFsMeU -f mp4 -o media/dua-sahar.mp4
#bin/yt-dlp https://www.youtube.com/watch?v=_hT_db_WqMo -f mp4 -o media/dua-thomali.mp4
bin/yt-dlp https://www.youtube.com/watch?v=aJgD-438KVY -f mp4 -o media/dua-thomali.mp4
bin/yt-dlp https://telewebion.com/episode/0x5fbb24f -o media/pre-azan-sobh.mp4
bin/yt-dlp https://www.aparat.com/v/g661dhy -o media/azan-moazzenzadeh.mp4
bin/yt-dlp https://telewebion.com/episode/0xec0945e -o media/namaz-sobh-mr-makarem.mp4
bin/yt-dlp https://www.youtube.com/watch?v=xXHBlHoGCNg -f mp4 -o media/azoma-albala.mp4
bin/yt-dlp https://www.youtube.com/watch?v=A_jjHZgXLws -f mp4 -o media/quran-maryam.mp4
bin/yt-dlp https://www.youtube.com/watch?v=5k2hw5I9ULk -f mp4 -o media/ya-zaljalal.mp4
# bin/yt-dlp -o media/namaz-zohr
bin/yt-dlp https://telewebion.com/episode/0x5282c43 -o media/doa-noor.mp4
bin/yt-dlp https://www.youtube.com/watch?v=us7h-oKCrtA -f mp4 -o media/quran-taha-abkar.mp4
bin/yt-dlp https://www.youtube.com/watch?v=e-KygsbNVGk -f mp4 -o media/asma-alhosna.mp4
#bin/yt-dlp https://www.youtube.com/watch?v=zP7TepK7eAs -f mp4 -o media/nature.mp4
bin/yt-dlp https://www.youtube.com/watch?v=3gu9FqQZTBA -f mp4 -o media/nature.mp4
# https://www.youtube.com/watch?v=K4TYdm34c7g
bin/yt-dlp https://www.youtube.com/watch?v=psZQ8oacGds -f mp4 -o media/ya-ali-ya-azim.mp4
bin/yt-dlp https://telewebion.com/episode/0x1b3a9a3 -o media/allahomma-laka-somna.mp4
# bin/yt-dlp https://www.youtube.com/watch?v=Wg6ZtFidpmo -f mp4 -o media/allahomma-laka-somna.mp4
# https://www.aparat.com/v/vpudb9r
bin/yt-dlp https://telewebion.com/episode/0x1bd9a01 -o media/dua-faraj.mp4
bin/yt-dlp https://www.youtube.com/watch?v=0A3fqGjYFkE -f mp4 -o media/doa-iftitah.mp4
```

```
bin/yt-dlp https://www.youtube.com/playlist\?list\=PLqCL0EUK5NXLOZFRhEYRSEauB7d3N1o2r -f mp4 -o "media/%(title)s.mp4"
find media/*Quran*.mp4 | while read a; do b=`echo $a | sed 's/^.*Quran *part *\([0-9]\+\)\.mp4$/\1/i'`; c=$(printf "%02d" $b); mv "$a" "media/quran-j$c.mp4"; done

```
‍‍
