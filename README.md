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
bin/yt-dlp https://www.youtube.com/watch?v=ZM1VANg8H9E -o media/timer
bin/yt-dlp https://www.youtube.com/watch?v=y07yhEFsMeU -o media/dua-sahar
bin/yt-dlp https://www.youtube.com/watch?v=_hT_db_WqMo -o media/dua-abuzar-thomali
bin/yt-dlp https://telewebion.com/episode/0x5fbb24f -o media/pre-azan-sobh
bin/yt-dlp https://www.aparat.com/v/g661dhy -o media/azan-moazzenzadeh
bin/yt-dlp https://telewebion.com/episode/0xec0945e -o media/namaz-sobh-mr-makarem
bin/yt-dlp https://www.youtube.com/watch?v=xXHBlHoGCNg -o media/azoma-albala
bin/yt-dlp https://www.youtube.com/watch?v=A_jjHZgXLws -o media/quran-maryam
bin/yt-dlp https://www.youtube.com/watch?v=5k2hw5I9ULk -o media/ya-zaljalal
# bin/yt-dlp -o media/namaz-zohr
bin/yt-dlp https://telewebion.com/episode/0x5282c43 -o media/doa-noor
bin/yt-dlp https://www.youtube.com/watch?v=us7h-oKCrtA -o media/quran-taha-abkar
bin/yt-dlp https://www.youtube.com/watch?v=e-KygsbNVGk -o media/asma-alhosna
bin/yt-dlp https://www.youtube.com/watch?v=zP7TepK7eAs -o media/nature
# https://www.youtube.com/watch?v=K4TYdm34c7g
bin/yt-dlp https://www.youtube.com/watch?v=psZQ8oacGds -o media/ya-ali-ya-azim
bin/yt-dlp https://www.youtube.com/watch?v=Wg6ZtFidpmo -o media/allahomma-laka-somna
# https://www.aparat.com/v/vpudb9r
bin/yt-dlp https://telewebion.com/episode/0x1bd9a01 -o media/dua-faraj
bin/yt-dlp https://www.youtube.com/watch?v=0A3fqGjYFkE -o media/doa-iftitah
```
