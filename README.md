# AZAN TV on Youtube
With this repository you can create a streaming program with specified program for pre- and post-azan.

# Setup
Download the codes
```
git clone git@github.com:foroughmand/azan-tv.git
cd azan-tv
```

Install `ffplay`.

The main streaming part is done via ffplayout which we have modified it a little to support customizable text overlay feature of ffmpeg. You can get and build the ffplayout with the following command. For this step, [rust](https://doc.rust-lang.org/cargo/getting-started/installation.html) should be installed. Also, ffplay should be installed, which is currently available as an ubuntu package.
```
git clone git@github.com:foroughmand/ffplayout.git
cd ffplayout
cargo update time
cargo build
cd ..
```

Then, you need to install the python packages
```
pip install tzfpy geopy requests pandas numpy ffmpeg_python google_auth_oauthlib google-api-python-client google-api-python-client oauth2client pychromecast persiantools 
```

A `client_secret.json` file should be obtained from google auth. You have to create a project on google console, allow youtube access, create an [auth credential](https://cloud.google.com/solutions/sap/docs/abap-sdk/on-premises-or-any-cloud/latest/authentication-oauth-client-credentials#oauth_config_consent), then download the json file.


To run the program you need to fill the [media/](media/) folder with appropriate videos you want to be played as specified in file [network-program-hard.json](network-program-hard.json). If you do thatn, then you can run the code to display the output on your local computer.
```
python live-stream.py --out desktop
```

Without the `--out` option, the program creates a new live stream on Youtube and its url with be displayed at the end.

## Installing mediamtx
Install mediamtx (for low latency version, `--out tv`):
```
wget https://github.com/bluenviron/mediamtx/releases/download/v1.11.3/mediamtx_v1.11.3_linux_amd64.tar.gz
mkdir -p bin
cd bin/
tar xzf ../mediamtx_v1.11.3_linux_amd64.tar.gz
cd ..
```

Run the application
```
python live-stream.py --out tv --port 8554
```

# Configuration (setting the location)
Configurations are located at file [config.json](config.json). 
* `city`: Name of the city. After searching it in map services, lat and long of the city is retrieved and prayer times are retrieved from izhamburg website.
* `city_aviny`: Id of the city in prayer.aviny.com website for retrieving prayer times from this website.
* `source`: Colon separated list of services from which the prayer times are fetched. The options are "prayertimes", "avini", "izhamburg".
* `title`, `description`, `thumbnails`, `privacy`: Settings for the Youtube broadcast.
* `ffplayout_template`: The template file for the ffplayout application. The ffplayout config file will be generated from this template file after injecting the Youtube stream link into it.
* `program_template`: Template file for the program before and after prayer times.

# Setting up the playlist
If you obtained the copyright of the files, you have install [yt-dlp](https://github.com/yt-dlp/yt-dlp), as follows:
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
