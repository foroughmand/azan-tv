import sys, subprocess, os, shutil
import time, json
from datetime import datetime, timedelta
import argparse
import threading
import webbrowser
import time
import signal
import argparse
from threading import Event
import threading
import http.server
import socketserver

try:
    from persiantools import digits
except Exception:
    class _DigitsFallback:
        @staticmethod
        def en_to_fa(s):
            return s
    digits = _DigitsFallback()

CLIENT_SECRETS_FILE = 'keys/client_secret.json'
OAUTH2_FILE = "keys/user-oauth2.json"

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtubepartner"]
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CONTENT_ID_API_SERVICE_NAME = "youtubePartner"
CONTENT_ID_API_VERSION = "v1"
INVALID_CREDENTIALS = "Invalid Credentials"


def get_authenticated_service(flags=None):
    # Import YouTube auth libraries lazily so tv/desktop modes do not require them.
    from oauth2client.file import Storage
    from oauth2client.client import flow_from_clientsecrets
    from oauth2client.tools import run_flow
    from googleapiclient.discovery import build
    import httplib2

    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
        scope=" ".join(YOUTUBE_SCOPE),
        message="MISSING_CLIENT_SECRETS_MESSAGE")

    storage = Storage(OAUTH2_FILE)
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        # Pass flags so run_flow does not re-parse sys.argv (which has --out/--conf and would error).
        credentials = run_flow(flow, storage, flags)

#   return build(API_SERVICE_NAME, API_VERSION,
#     http=credentials.authorize(httplib2.Http()))


    youtube = build(API_SERVICE_NAME, API_VERSION,
        http=credentials.authorize(httplib2.Http()))

    youtube_partner = build(CONTENT_ID_API_SERVICE_NAME,
        CONTENT_ID_API_VERSION, http=credentials.authorize(httplib2.Http()),
        static_discovery=False)

    return (youtube, youtube_partner)

def get_content_owner_id(youtube_partner):
    from apiclient.errors import HttpError

    try:
        content_owners_list_response = youtube_partner.contentOwners().list(
            fetchMine=True
        ).execute()
    except HttpError as e:
        print(e.content)
        if INVALID_CREDENTIALS in e.content:
            print("Your request is not authorized by a Google Account that "
                "is associated with a YouTube content owner. Please delete 'credential file' and "
                "re-authenticate with an account that is associated "
                "with a content owner." )
            exit(1)
        else:
            raise

# Get the video ID from your channel
def get_video_id():
    # Here you can implement code to get the video ID, for example using the YouTube Data API
    # return "my video ID from https"
    return "BPE7NdaGEE0"

# Create a live stream
def create_live_stream(youtube, title, description):
    request = youtube.liveStreams().insert(
        part="snippet,cdn,contentDetails,status",
        body={
            "snippet": {
                "title": title,
                "description": description
            },
            "cdn": {
                "frameRate": "variable",
                "ingestionType": "rtmp",
                "resolution": "variable"
            },
            "contentDetails": {
                "enableAutoStart": True,
                "isReusable": True,
                "monitorStream": {
                    "enableMonitorStream": True
                }
            }
        }
    )
    response = request.execute()
    # print(response)
    return response["id"], response["cdn"]["ingestionInfo"]["ingestionAddress"] + "/" + response["cdn"]["ingestionInfo"]["streamName"]

def del_live_stream(youtube, stream_id):
    request = youtube.liveStreams().delete(
        id = stream_id
    )
    response = request.execute()

def create_live_broadcast(youtube, video_id, stream_id, title, description, thumbnails, privacy = "unlisted"):
    request = youtube.liveBroadcasts().insert(
        part="snippet,status,contentDetails",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": (datetime.now() + timedelta(minutes=0)).isoformat(),  # Schedule the broadcast for 1 minutes later
                "thumbnails": {
                    "default": {
                        "url": thumbnails
                    }
                }
            },
            "status": {
                "privacyStatus": privacy
            },
            "contentDetails": {
                "enableAutoStart": False,
                "enableDvr": True,
                "latencyPreference": "ultraLow"
            }
        }
    )
    response = request.execute()
    # print(response)
    broadcast_id = response["id"]

    # Bind the stream to the live broadcast
    bind_request = youtube.liveBroadcasts().bind(
        part="id,snippet",
        id=broadcast_id,
        streamId=stream_id
    )
    bind_response = bind_request.execute()

    return broadcast_id

def del_live_broadcast(youtube, broadcast_id):
    request = youtube.liveBroadcasts().delete(
        id = broadcast_id
    )
    response = request.execute()


def get_stream_status(youtube, stream_id):
    request = youtube.liveStreams().list(
        part="id,status",
        id = stream_id
    )
    response = request.execute()
    # print(response["items"])
    return response["items"][0]["status"]["streamStatus"] if len(response["items"]) > 0 else None

def get_broadcast_status(youtube, broadcast_id):
    request = youtube.liveBroadcasts().list(
        part="id,status",
        id =broadcast_id
    )
    response = request.execute()
    # print(response["items"])
    return response["items"][0]["status"]["lifeCycleStatus"] if len(response["items"]) > 0 else None

def wait_for(f, delay = 0.2):
    while True:
        time.sleep(delay)
        if f(): return

def broadcast_transition(youtube, broadcast_id, new_status):
    print(f'Transision to {new_status} ...')
    request = youtube.liveBroadcasts().transition(
        broadcastStatus=new_status,
        id=broadcast_id,
        part="id,status,snippet,contentDetails"
    )
    response = request.execute()
    # print(response)

import socket
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# OTHER METHODS:
#   ffplayout: main method (https://github.com/ffplayout/ffplayout)
#   creating new live: (https://github.com/youtube/api-samples/blob/master/python/add_featured_video.py)
#   python-hls-stream: (https://github.com/cheind/python-hls-stream)
#   A good discussion: (https://obsproject.com/forum/threads/automate-24-7-stream-for-a-scheduled-playlist.85336/page-22)

# Main function
def main(argv):
    global CLIENT_SECRETS_FILE, OAUTH2_FILE

    # Include oauth2client's flags so run_flow() does not parse sys.argv and fail on our --out/--conf.
    try:
        from oauth2client import tools as oauth2_tools
        parser = argparse.ArgumentParser(parents=[oauth2_tools.argparser])
    except Exception:
        parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.today().strftime('%Y-%m-%d'), help='date')
    parser.add_argument('--conf', default='stream/config.json', help='config file')
    parser.add_argument('--out', default='stream', help='Output of ffplayout. Options = "stream", "desktop", "chromecast", "browser", "tv", "auth". "auth" only performs YouTube OAuth login and exits.')
    parser.add_argument('--azans', default=':'.join(['imsak', 'fajr', 'dhuhr', 'maghrib']), help='Colons seperated list of times to be shown in the stream. Options are "imsak", "fajr", "sunrise", "dhuhr", "asr", "sunset", "maghrib", "isha", "midnight".')
    parser.add_argument('--debug-time-diff', type=int, default=0, help='This will be added to the actual time (minutes)')
    parser.add_argument('--ip', type=str, default=get_local_ip(), help='IP used by local http server (for chromecast).')
    parser.add_argument('--port', type=int, default=8080, help='Port used by local http server (for chromecast).')
    parser.add_argument('--tv-name', default="Sony", help='Friendly name of TV for playing on it (for chromecast/TV).')
    parser.add_argument('--rtsp-host', type=str, default=get_local_ip(), help='IP/host where MediaMTX RTSP server runs')
    parser.add_argument('--rtsp-port', type=int, default=8554, help='RTSP port of MediaMTX (usually 8554)')
    args = parser.parse_args(args=argv)

    file_playlist = "playlist4.json"
    file_ffplayout_config = "ffplayout2.yml"
    file_times_info = "azan-times.json"
    work_dir = os.path.abspath(os.environ.get("AZAN_TV_WORKDIR", os.getcwd()))
    file_time_info = "time-info.txt"
    file_translations = "time-translations.txt"
    file_stream = "tmp/stream.m3u8"

    with open(args.conf) as json_file:
        conf = json.load(json_file)
        conf["title"] = conf["title"].replace('{DATE}', args.date)
        conf["description"] = conf["description"].replace('{DATE}', args.date)
        CLIENT_SECRETS_FILE = conf.get("client_secrets_file", CLIENT_SECRETS_FILE)
        OAUTH2_FILE = conf.get("oauth2_file", OAUTH2_FILE)

    if args.out == "auth":
        get_authenticated_service(args)
        print("YouTube authentication successful.")
        return

    # Prefer env; then platform folder (ffplayout/mac on Mac, ffplayout/linux on Linux). On Mac never use target/debug (wrong arch → Exec format error).
    ffplayout_bin = os.environ.get("AZAN_TV_FFPLAYOUT")
    if not ffplayout_bin:
        import platform
        plat = "mac" if platform.system() == "Darwin" else "linux"
        # Check platform-specific folder first (required on Mac; preferred on Linux)
        candidates = [f"ffplayout/{plat}/ffplayout"]
        if plat == "linux":
            candidates.append("ffplayout/target/debug/ffplayout")
        for candidate in candidates:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                ffplayout_bin = candidate
                break
        else:
            ffplayout_bin = None
    if not ffplayout_bin or not (os.path.isfile(ffplayout_bin) and os.access(ffplayout_bin, os.X_OK)):
        if sys.platform == "darwin":
            sys.exit(
                "ffplayout not found for macOS. Put a Mac-built binary at ffplayout/mac/ffplayout\n"
                "(Build with Rust on a Mac: cargo build in the ffplayout repo, then copy target/debug/ffplayout to ffplayout/mac/.)"
            )
        sys.exit("ffplayout not found. Put a binary at ffplayout/linux/ffplayout or ffplayout/target/debug/ffplayout")

    def ffplayout_cmd(output_mode, playlist_path=file_playlist, config_path=file_ffplayout_config):
        """Build ffplayout argv: -p playlist -o MODE --log <work_dir> -c config. Log file will be <work_dir>/ffplayout.log."""
        abs_bin = os.path.abspath(ffplayout_bin) if not os.path.isabs(ffplayout_bin) else ffplayout_bin
        abs_playlist = os.path.abspath(playlist_path)
        abs_config = os.path.abspath(config_path)
        return [
            abs_bin,
            "-p", abs_playlist,
            "-o", output_mode,
            "--log", work_dir,
            "-c", abs_config,
        ]

    proc = None
    update_thread = None
    broadcast_id = None
    stream_id = None
    stream_url = None

    time_translations = None
    # time_translations["{HIJRI_DAY}"] = ;

    # subprocess.run("python gen-playlist.py --date $(date +\"%Y-%m-%d\") --conf network-program-hard.json > playlist4.json".split(' '))
    # with open('playlist4.json', "w") as outfile:
    #    subprocess.run(["python", "gen-playlist.py", "--date", datetime.today().strftime('%Y-%m-%d'), "--conf", "network-program-hard.json"], stdout=outfile)
    import gen_playlist
    gen_playlist_args = ["--date", args.date, "--conf", conf["program_template"], "--out", file_playlist, "--city", conf["city"], "--city_aviny", conf["city_aviny"], "--source", conf["source"], "--times", file_times_info] + (["--translations", file_translations] if time_translations is not None else []) + ["--debug-time-diff", args.debug_time_diff] 
    #+ ["--azan", "imsak:03:00:00,"+"fajr:"+(datetime.now() + timedelta(minutes=-5)).time().strftime('%H:%M:%S')+",dhuhr:12:00:00,"+"maghrib:20:00:00"]
    print(' '.join([str(x) for x in gen_playlist_args]))
    gen_playlist.main(gen_playlist_args)

    # def update_remaining_info_file_thread(of_name, times):
    #     while True:
    #         print(f"running {of_name} {times}")
    #         time.sleep(1)

    class CustomThread(threading.Thread):
        def __init__(self, of_name, times, important_times, conf):
            super(CustomThread, self).__init__()
            self._stopper = threading.Event()
            self.of_name = of_name
            self.times = times
            self.important_times = important_times
            self.of_name_temp = 'temp_thread_time_info.txt'
            self.translation = conf["translation"]
        
        def stop(self):
            self._stopper.set()

        def stopped(self):
            return self._stopper.is_set()

        def run(self):
            def time_to_str(s):
                if type(s) is not str: s = str(s)
                return digits.en_to_fa(s)
            while not self.stopped():
                try:
                    now = datetime.now()
                    # today = now.date()
                    # now = datetime(today.year, today.month, today.day, 0, 0, 0) + timedelta(seconds = int((now.second + now.microsecond / 1000000.0) * (24 * 60)))
                    # now = now - timedelta(minutes=70)
                    now = now + timedelta(minutes=args.debug_time_diff)
                    today = now.date()
                    start = datetime(today.year, today.month, today.day)
                    prev, next, prev_title, next_title = None, None, None, None
                    for t in self.important_times:
                        tt = start + timedelta(seconds = self.times[t])
                        if tt < now and (prev is None or tt > prev): prev, prev_title = tt, t
                        if tt >= now and (next is None or tt < next): next, next_title = tt, t
                    prev_dist = (now - prev).total_seconds() if prev is not None else None
                    next_dist = (next - now).total_seconds() if next is not None else None
                    priv_print = False
                    # print(f"running {start} ({prev})<=({now})<=({next})")
                    result = f"{time_to_str(now.strftime('%Y-%m-%d %H:%M:%S'))}\n"
                    if prev_dist is not None and prev_dist < 60 * 30:
                        priv_print = True
                        result += "از "
                        result += f"{prev_title.capitalize() if prev_title not in self.translation else self.translation[prev_title]}: {time_to_str(timedelta(seconds=int(prev_dist)))}"
                        result += " "
                    if next is not None:
                        result += "تا "
                        result += f"{next_title.capitalize() if next_title not in self.translation else self.translation[next_title]}: {time_to_str(timedelta(seconds=int(next_dist)))}"
                    # print(f"  {prev_title}:{prev_dist} {next_title}:{next_dist} == {result}")
                    with open(self.of_name_temp, 'w') as f:
                        print(result, file=f)
                    os.replace(self.of_name_temp, self.of_name)
                    time.sleep(0.3)
                    # return
                except Exception as e:
                    print('CustomThread', e)
                except:
                    print('ERROR!!!!!')


    update_thread = CustomThread(file_time_info, json.load(open(file_times_info)), args.azans.split(':'), conf)
    update_thread.start()


    def start_http_server(ip, port):
        """Starts a simple HTTP server in a separate thread."""
        from http.server import HTTPServer, SimpleHTTPRequestHandler

        class CORSRequestHandler(SimpleHTTPRequestHandler):
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                super().end_headers()
                
        # handler = http.server.SimpleHTTPRequestHandler
        # with socketserver.TCPServer((ip, port), handler) as httpd:
        #     print(f"🌍 Serving HTTP on http://{ip}:{port}/")
        #     httpd.serve_forever()

        httpd = HTTPServer((ip, port), CORSRequestHandler)
        print(f"🌍 Serving HTTP on http://{ip}:{port}/")
        httpd.serve_forever()

    http_thread = threading.Thread(target=start_http_server, args=(args.ip, args.port), daemon=True)

    youtube, youtube_partner = None, None

    # content_owner_id = get_content_owner_id(youtube_partner)
    try:
        # source: https://stackoverflow.com/a/35083880/9904290
        # Get the video ID
        # video_id = get_video_id()


        # Copy HM_XNiloofar.ttf from bundles/ into work dir so overlay can use it on Linux and Mac
        font_name = "HM_XNiloofar.ttf"
        font_dest = os.path.join(work_dir, font_name)
        if not os.path.isfile(font_dest):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            for src in [
                os.path.join(work_dir, "bundles", font_name),
                os.path.join(script_dir, "bundles", font_name),
                os.path.join(os.getcwd(), "bundles", font_name),
            ]:
                if os.path.isfile(src):
                    try:
                        shutil.copy2(src, font_dest)
                        break
                    except Exception:
                        pass
        ffplayout_template = open(conf["ffplayout_template"], 'r').read()
        # Use only paths inside our work dir (no /var, /usr etc.) so we don't need write access to system dirs
        ffplayout_template = ffplayout_template.replace("/var/lib/ffplayout/playlists", work_dir)
        ffplayout_template = ffplayout_template.replace("/var/log/ffplayout/", work_dir + os.sep)
        ffplayout_template = ffplayout_template.replace("/usr/share/ffplayout/logo.png", "")
        ffplayout_template = ffplayout_template.replace("add_logo: true", "add_logo: false")
        # Use absolute paths under work_dir for font and time-info so overlay works when ffplayout cwd is not work_dir (e.g. Mac bundle)
        if os.path.isfile(font_dest):
            ffplayout_template = ffplayout_template.replace("fontfile: HM_XNiloofar.ttf", "fontfile: " + os.path.abspath(font_dest))
        else:
            ffplayout_template = ffplayout_template.replace("fontfile: HM_XNiloofar.ttf", "fontfile: Helvetica")
        time_info_path = os.path.abspath(os.path.join(work_dir, file_time_info))
        ffplayout_template = ffplayout_template.replace("regex: ==file==time-info.txt", "regex: ==file==" + time_info_path)
        # Debug: overlay paths and log location (check ffplayout.log if overlay is missing)
        print("Overlay: fontfile=" + (os.path.abspath(font_dest) if os.path.isfile(font_dest) else "Helvetica") + " | textfile=" + time_info_path, flush=True)
        print("ffplayout log: " + os.path.join(work_dir, "ffplayout.log"), flush=True)
        # Ensure logo_position exists (required by ffplayout mac/linux binary; old bundled template may lack it)
        if "logo_position:" not in ffplayout_template and "logo_filter:" in ffplayout_template:
            ffplayout_template = ffplayout_template.replace(
                "logo_filter: overlay=W-w-12:12",
                "logo_filter: overlay=W-w-12:12\n  logo_position: overlay=W-w-12:12",
                1,
            )
        elif "logo_position:" not in ffplayout_template and "processing:" in ffplayout_template:
            # Insert after first occurrence of "logo_opacity:" in processing section
            ffplayout_template = ffplayout_template.replace(
                "logo_opacity: 0.7",
                "logo_opacity: 0.7\n  logo_position: overlay=W-w-12:12",
                1,
            )
        # Ensure task.help_text exists (required by ffplayout binary; old bundled template may lack it)
        if "task:\n  enable:" in ffplayout_template and "task:\n  help_text:" not in ffplayout_template:
            ffplayout_template = ffplayout_template.replace(
                "task:\n  enable:",
                "task:\n  help_text: Run custom tasks at playlist start/end or at given time.\n  enable:",
                1,
            )
        with open(file_ffplayout_config, "w") as f:
            # ffplayout_config = ffplayout_template
            # if args.out in ["desktop", "stream", "browser"]:
            #     ffplayout_config = ffplayout_config.replace('-f flv {STREAM_URL}', stream_url if stream_url is not None else '')
            # elif args.out == "chromecast":
            #     ffplayout_config = ffplayout_config.replace('-f hls {STREAM_URL}', stream_url if stream_url is not None else '')
            # else:
            #     raise RuntimeError("Invalid args.out=" + args.out)
            f.write(ffplayout_template)

        # v0.25+ ffplayout must run from its extracted bundle dir (has sibling files it needs)
        ffplayout_cwd = work_dir
        bundle_dir_file = os.path.join(work_dir, "ffplayout_bundle_dir.txt")
        if os.path.isfile(bundle_dir_file):
            try:
                with open(bundle_dir_file, encoding="utf-8") as f:
                    ffplayout_cwd = f.read().strip()
                if os.path.isdir(ffplayout_cwd):
                    pass  # use it
                else:
                    ffplayout_cwd = work_dir
            except Exception:
                ffplayout_cwd = work_dir

        if args.out == "desktop":
            cmd = ffplayout_cmd("desktop")
            print("running ffplayout")
            print(" ".join(cmd), flush=True)
            proc = subprocess.Popen(cmd, shell=False, cwd=ffplayout_cwd)
            print("We will wait for ffplayout", proc)
        # proc.communicate()
        elif args.out in ["stream", "browser"]:
            youtube, youtube_partner = get_authenticated_service(args)
            
            # Create a live stream
            stream_id, stream_url = create_live_stream(youtube, conf["title"], conf["description"])
            print(f"stream_id: {stream_id}, stream_url: {stream_url}", flush=True)

            with open(file_ffplayout_config, "w") as f:
                f.write(ffplayout_template.replace('{STREAM_URL}', ('-f flv ' + stream_url) if stream_url is not None else ''))

            # Create a live broadcast
            broadcast_id = create_live_broadcast(youtube, None, stream_id, conf["title"], conf["description"], conf["thumbnails"], conf["privacy"])
            print(f"broadcast_id: {broadcast_id} url=https://youtu.be/{broadcast_id}", flush=True)

            cmd = ffplayout_cmd("stream")
            print(" ".join(cmd), flush=True)
            proc = subprocess.Popen(cmd, shell=False, cwd=ffplayout_cwd)
            # wait_for_stream_ready(youtube, stream_id)

            wait_for(lambda: get_stream_status(youtube, stream_id) == "active")

            # # Start the live broadcast
            # start_live_broadcast(youtube, broadcast_id, stream_id)
            broadcast_transition(youtube, broadcast_id, "testing")
            wait_for(lambda:get_broadcast_status(youtube, broadcast_id) == "testing")
            broadcast_transition(youtube, broadcast_id, "live")
            wait_for(lambda:get_broadcast_status(youtube, broadcast_id) == "live")

            print("Live broadcast has been successfully started.")

            # if args.out == "chromecast":
            #     # It doesn't work.
            #     try:
            #         # A list of Chromecast devices broadcasting
            #         chromecast_devices = pychromecast.get_chromecasts()

            #         # Initialize a connection to the Chromecast
            #         cast = chromecast_devices[0][0]
            #         # cast = pychromecast.get_chromecast(friendly_name=cast_device)

            #         # Create and register a YouTube controller
            #         yt = YouTubeController()
            #         cast.register_handler(yt)
            #         cast.wait()

            #         print('Waiting for connection ...')
            #         cnt = 0
            #         while cast.socket_client.is_connected == False and cnt < 10:
            #             print(cnt, cast.status, cast.socket_client)
            #             time.sleep(1)
            #             cnt += 1
            #         print('Waiting for connection done')

            #         # Play the video ID we've been given
            #         yt.play_video(broadcast_id)

            #         print("Streaming %s to %s" % (broadcast_id, cast))
            #     except pychromecast.error.PyChromecastError as e:
            #         print(f"We couldn't open chromecast, but use https://youtu.be/{broadcast_id}")    
            
            # elif 
            if args.out == "browser":
                webbrowser.open(f"https://youtu.be/{broadcast_id}", new=0, autoraise=True)
            
            else:
                print(f"Now open this link https://youtu.be/{broadcast_id}")
        elif args.out == "chromecast":
            import pychromecast
            import logging
            logging.basicConfig(level=logging.DEBUG)

            with open(file_ffplayout_config, "w") as f:
                f.write(ffplayout_template.replace('{STREAM_URL}', '-f hls ' + file_stream))
            cmd = ffplayout_cmd("stream")
            print(" ".join(cmd), flush=True)
            proc = subprocess.Popen(cmd, shell=False, cwd=ffplayout_cwd)

            http_thread.start()

            def cast_stream(device_name, stream_url):
                """Finds Chromecast and plays the provided stream URL."""
                print("🔍 Searching for Chromecast devices...")
                chromecasts, browser = pychromecast.get_listed_chromecasts(
                    friendly_names=[device_name], known_hosts=""
                )
                if not chromecasts:
                    print(f'No chromecast with name "{device_name}" discovered')
                    sys.exit(1)

                cast = chromecasts[0]
                # chromecasts, browser = pychromecast.get_chromecasts()

                # Find the correct Chromecast
                # cast = next((cc for cc in chromecasts if cc.cast_info.friendly_name == device_name), None)
                # if not cast:
                #     print(f"❌ Chromecast '{device_name}' not found.")
                #     return

                print(f"✅ Found Chromecast: {cast.cast_info.friendly_name}. Connecting...")
                cast.wait()

                # Play the stream
                print(f"▶ Casting stream: {stream_url}")


                # If an app is running, stop it
                while cast.app_id:
                    print("Stopping current app...")
                    cast.quit_app()
                    time.sleep(1)


                # Get media controller
                mc = cast.media_controller


                # Check current app status
                print(f"Current app ID: {cast.app_id}, Status: {cast.status}")

                # print()
                # print(cast.cast_info)
                # time.sleep(1)
                # print()
                # print(cast.status)
                # print()
                # print(cast.media_controller.status)
                # print()

                # if not cast.is_idle:
                #     print("Killing current running app")
                #     cast.quit_app()
                #     t = 5.0
                #     while cast.status.app_id is not None and t > 0:  # type: ignore[union-attr]
                #         time.sleep(0.1)
                #         t = t - 0.1

                # cast.media_controller.play_media(stream_url, "application/x-mpegURL")
                # cast.media_controller.block_until_active()
                print(f"stream_url: {stream_url}")
                # stream_url = "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"

                cast.play_media(stream_url, "video/mp4")
                mc.block_until_active()  # Wait until the media starts
                # time.sleep(2)  # Give it some time to start
                mc.play()

                # Stop discovery to free resources
                browser.stop_discovery()
                print("✅ Streaming should be playing on your TV!")
            # cast_stream(args.tv_name, f"http://{args.ip}:{args.port}/" + file_stream)
        elif args.out == "tv":
            import pychromecast
            mediamtx_proc = subprocess.Popen(["bin/mediamtx", "bin/mediamtx.yml"])
            time.sleep(2)

            import logging
            logging.basicConfig(level=logging.DEBUG)

            # file_stream = f"rtsp://{args.ip}:{args.port}/live"
            file_stream = f"rtsp://{args.rtsp_host}:{args.rtsp_port}/live"

            with open(file_ffplayout_config, "w") as f:
                f.write(ffplayout_template.replace('{STREAM_URL}', '-f rtsp ' + file_stream))
            cmd = ffplayout_cmd("stream")
            print(" ".join(cmd), flush=True)
            proc = subprocess.Popen(cmd, shell=False, cwd=ffplayout_cwd)

            print(f'Live url: {file_stream}. You can open this link.')

            def find_tv_via_chromecast(device_name):
                """
                Discovers Chromecast devices on the network, returns their IP addresses.
                """
                print(f"Discovering Chromecast devices {device_name}...")
                chromecasts, browser = pychromecast.get_listed_chromecasts(
                    friendly_names=[device_name], known_hosts=""
                )

                if not chromecasts:
                    print(f'No chromecast with name "{device_name}" discovered')
                    sys.exit(1)

                cast = chromecasts[0]

                # tvs = []
                for cc in chromecasts:
                    print(f"Found device: {cc.cast_info.friendly_name} at {cc.cast_info.host}")
                    # tvs[cc.cast_info.friendly_name] = cc.cast_info.host
                    return cc.cast_info.host
                # return tvs
                # return list(tvs.values)


            from ppadb.client import Client as AdbClient

            def play_stream_on_tv_pure(tv_ip, stream_url):
                """
                Connects to the Sony BRAVIA TV over ADB natively from Python and plays a stream URL in VLC.

                Args:
                    tv_ip (str): IP address of the TV (without port, just IP like '192.168.178.61').
                    stream_url (str): The streaming URL to open in VLC.
                """

                # Start ADB client
                client = AdbClient(host="127.0.0.1", port=5037)  # Local adb server

                # Connect to the TV
                print(f"Connecting to {tv_ip}:5555...")
                client.remote_connect(tv_ip, 5555)  # Always port 5555 for adb TCP/IP unless changed

                # Find the device
                devices = client.devices()
                if not devices:
                    raise Exception("No device found. Failed to connect to TV.")

                device = devices[0]
                print(f"Connected to device: {device.serial}")

                # Launch VLC with the stream URL
                # command = (
                #     f"am start -a android.intent.action.VIEW "
                #     f"-d \"{stream_url}\" "
                #     f"-n org.videolan.vlc/.StartActivity"
                # )

                device.shell("am force-stop org.videolan.vlc")
                # Optional: small pause
                time.sleep(0.3)

                command = (
                    "am start -W "
                    "-n org.videolan.vlc/.gui.video.VideoPlayerActivity "
                    "-a android.intent.action.VIEW "
                    "-c android.intent.category.DEFAULT "
                    f"-d '{stream_url}'"
                )

                print(f"Sending command: {command}")
                output = device.shell(command)
                print("Command output:", output)

                # Optional: Disconnect cleanly
                client.remote_disconnect(tv_ip, 5555)
                print("Disconnected from TV.")

            tv_ip = find_tv_via_chromecast(args.tv_name)
            play_stream_on_tv_pure(tv_ip, file_stream)

        proc.wait()
    except KeyboardInterrupt as e:
        print("Done")
    except BaseException as e:
        print(f"Error: {e}")
        raise e
    finally:
        if broadcast_id and (get_broadcast_status(youtube, broadcast_id) in ["live", "testing"]):
            broadcast_transition(youtube, broadcast_id, "complete")
        elif broadcast_id:
            del_live_broadcast(youtube, broadcast_id)
        elif stream_id:
            del_live_stream(youtube, stream_id)
        if proc is not None: 
            proc.terminate()
        if update_thread:
            update_thread.stop()
        if ('mediamtx_proc' in locals() or 'mediamtx_proc' in globals()) and mediamtx_proc is not None:
            mediamtx_proc.terminate()
        # if http_thread:
        #     http_thread.stop()

if __name__ == "__main__":
    main(sys.argv[1:])
