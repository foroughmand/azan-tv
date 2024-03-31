import sys, subprocess, os
import time, json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from oauth2client.file import Storage
from apiclient.errors import HttpError
from oauth2client.client import flow_from_clientsecrets
import httplib2
from oauth2client.tools import argparser, run_flow
import argparse
import threading

CLIENT_SECRETS_FILE = 'client_secret.json'

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtubepartner"]
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CONTENT_ID_API_SERVICE_NAME = "youtubePartner"
CONTENT_ID_API_VERSION = "v1"
INVALID_CREDENTIALS = "Invalid Credentials"


def get_authenticated_service():
    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
        scope=" ".join(YOUTUBE_SCOPE),
        message="MISSING_CLIENT_SECRETS_MESSAGE")

    storage = Storage("user-oauth2.json")
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        # credentials = flow.run_local_server()
        credentials = run_flow(flow, storage, None)

#   return build(API_SERVICE_NAME, API_VERSION,
#     http=credentials.authorize(httplib2.Http()))


    youtube = build(API_SERVICE_NAME, API_VERSION,
        http=credentials.authorize(httplib2.Http()))

    youtube_partner = build(CONTENT_ID_API_SERVICE_NAME,
        CONTENT_ID_API_VERSION, http=credentials.authorize(httplib2.Http()),
        static_discovery=False)

    return (youtube, youtube_partner)

def get_content_owner_id(youtube_partner):
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
                "enableAutoStart": False
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

# OTHER METHODS:
#   ffplayout: main method (https://github.com/ffplayout/ffplayout)
#   creating new live: (https://github.com/youtube/api-samples/blob/master/python/add_featured_video.py)
#   python-hls-stream: (https://github.com/cheind/python-hls-stream)
#   A good discussion: (https://obsproject.com/forum/threads/automate-24-7-stream-for-a-scheduled-playlist.85336/page-22)

# Main function
def main(argv):

    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.today().strftime('%Y-%m-%d'), help='date')
    parser.add_argument('--conf', default='config.json', help='config file')
    parser.add_argument('--out', default='stream', help='Output of ffplayout. Options = "stream", "desktop".')
    parser.add_argument('--azans', default=':'.join(['fajr', 'dhuhr', 'maghrib']), help='Colons seperated list of times to be shown in the stream. Options are "imsak", "fajr", "sunrise", "dhuhr", "asr", "sunset", "maghrib", "isha", "midnight".')
    
    args = parser.parse_args(args=argv)

    file_playlist = "playlist4.json"
    file_ffplayout_config = "ffplayout2.yml"
    file_times_info = "azan-times.json"
    file_time_info = "time-info.txt"

    with open(args.conf) as json_file:
        conf = json.load(json_file)
        conf["title"] = conf["title"].replace('{DATE}', args.date)
        conf["description"] = conf["description"].replace('{DATE}', args.date)

    proc = None
    update_thread = None
    broadcast_id = None
    stream_id = None
    stream_url = None

    # subprocess.run("python gen-playlist.py --date $(date +\"%Y-%m-%d\") --conf network-program-hard.json > playlist4.json".split(' '))
    # with open('playlist4.json', "w") as outfile:
    #    subprocess.run(["python", "gen-playlist.py", "--date", datetime.today().strftime('%Y-%m-%d'), "--conf", "network-program-hard.json"], stdout=outfile)
    import gen_playlist
    gen_playlist.main(["--date", args.date, "--conf", conf["program_template"], "--out", file_playlist, "--city", conf["city"], "--city_aviny", conf["city_aviny"], "--source", conf["source"], "--times", file_times_info])

    # def update_remaining_info_file_thread(of_name, times):
    #     while True:
    #         print(f"running {of_name} {times}")
    #         time.sleep(1)

    class CustomThread(threading.Thread):
        def __init__(self, of_name, times, important_times):
            super(CustomThread, self).__init__()
            self._stopper = threading.Event()
            self.of_name = of_name
            self.times = times
            self.important_times = important_times
            self.of_name_temp = 'temp_thread_time_info.txt'
        
        def stop(self):
            self._stopper.set()

        def stopped(self):
            return self._stopper.is_set()

        def run(self):
            while not self.stopped():
                try:
                    now = datetime.now()
                    # today = now.date()
                    # now = datetime(today.year, today.month, today.day, 0, 0, 0) + timedelta(seconds = int((now.second + now.microsecond / 1000000.0) * (24 * 60)))
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
                    result = f"{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    if prev_dist is not None and prev_dist < 60 * 30:
                        priv_print = True
                        result += f"{prev_title.capitalize()}:{timedelta(seconds=prev_dist)}"
                        result += " <- "
                    if next is not None:
                        result += "-> "
                        result += f"{next_title.capitalize()}:{timedelta(seconds=next_dist)}"
                    # print(f"  {prev_title}:{prev_dist} {next_title}:{next_dist} == {result}")
                    with open(self.of_name_temp, 'w') as f:
                        print(result, file=f)
                    os.replace(self.of_name_temp, self.of_name)
                    time.sleep(0.3)
                    # return
                except Exception as e:
                    print(e)
                except:
                    print('ERROR!!!!!')


    update_thread = CustomThread(file_time_info, json.load(open(file_times_info)), args.azans.split(':'))
    update_thread.start()
    # exit(0)

    youtube, youtube_partner = get_authenticated_service()

    # content_owner_id = get_content_owner_id(youtube_partner)
    try:
        # source: https://stackoverflow.com/a/35083880/9904290
        # Get the video ID
        video_id = get_video_id()

        if args.out == "stream":
            # Create a live stream
            stream_id, stream_url = create_live_stream(youtube, conf["title"], conf["description"])
            print(f"stream_id: {stream_id}, stream_url: {stream_url}")

            # Create a live broadcast
            broadcast_id = create_live_broadcast(youtube, video_id, stream_id, conf["title"], conf["description"], conf["thumbnails"], conf["privacy"])
            print(f"broadcast_id: {broadcast_id} url=https://youtu.be/{broadcast_id}")

        ffplayout_template = open(conf["ffplayout_template"], 'r').read()
        with open(file_ffplayout_config, "w") as f:
            f.write(ffplayout_template.replace('{STREAM_URL}', stream_url if stream_url is not None else ''))
        
        proc = subprocess.Popen(["ffplayout/target/debug/ffplayout", "-p", file_playlist, "-o", args.out, "--log", "ffplayout.log", "-c", file_ffplayout_config], shell=False)
        # proc.communicate()

        if args.out == "stream":
            # wait_for_stream_ready(youtube, stream_id)
            wait_for(lambda: get_stream_status(youtube, stream_id) == "active")

            # # Start the live broadcast
            # start_live_broadcast(youtube, broadcast_id, stream_id)
            broadcast_transition(youtube, broadcast_id, "testing")
            wait_for(lambda:get_broadcast_status(youtube, broadcast_id) == "testing")
            broadcast_transition(youtube, broadcast_id, "live")
            wait_for(lambda:get_broadcast_status(youtube, broadcast_id) == "live")

            print("Live broadcast has been successfully started.")
            print(f"Now you can open https://youtu.be/{broadcast_id}")

        proc.wait()
    except KeyboardInterrupt as e:
        print("Done")
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

if __name__ == "__main__":
    main(sys.argv[1:])
