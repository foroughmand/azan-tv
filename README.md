# AZAN TV on Youtube
With this repository you can create a streaming program with specified program for pre- and post-azan.

# Setup
Download the codes
```
git clone git@github.com:foroughmand/azan-tv.git
cd azan-tv
```

The main streaming part is done via ffplayout which we have modified it a little to support customizable text overlay feature of ffmpeg. You can get and build the ffplayout with the following command. For this step, [rust](https://doc.rust-lang.org/cargo/getting-started/installation.html) should be installed.
```
git clone git@github.com:foroughmand/ffplayout.git
cd ffplayout
cargo update time
cargo build
cd ..
```

Then, you need to install the python packages
```
pip install tzfpy geopy requests pandas numpy ffmpeg_python google_auth_oauthlib google-api-python-client google-api-python-client oauth2client
```

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

