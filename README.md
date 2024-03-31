# AZAN TV on Youtube
With this repository you can create a streaming program with specified program for pre- and post-azan.

# Setup
Download the codes
```
git clone git@github.com:foroughmand/azan-tv.git
cd azan-tv
```

The main streaming part is done via ffplayout which we have modified it a little to support customizable text overlay feature of ffmpeg. You can get and build the ffplayout with the following command.
```
git clone git@github.com:foroughmand/ffplayout.git
cd ffplayout
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
