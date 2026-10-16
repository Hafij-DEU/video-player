# Astra Player

*Formerly Kiln Player. Installing Astra Player replaces the `kiln-player`
package and carries over your settings, resume points and Whisper models.*

A free, PotPlayer-style media player for Linux. No ads, no account, no
subscription, and no codec packs to download later: every decoder comes in
with the package dependencies when you install it.

Astra Player is written from scratch in Python with GTK 4, libadwaita and
GStreamer. Decoding is done by FFmpeg (through `gst-libav`) and GStreamer,
with VA-API hardware decoding when the GPU supports it. It contains no code
from PotPlayer.

## Features

- **Formats**: H.264, HEVC/H.265, AV1, VP8/VP9, MPEG-1/2/4, VC-1/WMV, ProRes,
  Theora; AAC, MP3, AC-3, E-AC-3, DTS, TrueHD, FLAC, ALAC, Opus, Vorbis, WMA,
  APE, WavPack; MKV, MP4, MOV, AVI, TS/M2TS, WebM, FLV, OGG and more.
- **Streams**: HTTP, HLS, DASH, RTSP, plus YouTube and other sites when
  `yt-dlp` is installed.
- **YouTube search**: Open › *Search YouTube…* (Ctrl+Y) lists results with
  thumbnails, channel, length and views. Play one or add it to the playlist.
  It uses `yt-dlp`, so it needs no API key and no account. Typing
  `ytsearch:words` in Open URL runs the same search.
- **Subtitles**: embedded tracks and external `.srt .ass .ssa .vtt .sub .smi`,
  loaded automatically when the name matches the video. Includes delay
  adjustment, track switching and font choice.
- **Speech to subtitles**: Subtitles › *Generate subtitles (Whisper)…* turns
  the speech in the current file into `<name>.whisper.srt` beside it, offline,
  and loads it. Choose the model (tiny 78 MB, base 148 MB, small 488 MB),
  the spoken language, and optional translation to English in Preferences.
- **Audio**: track switching, 10-band equalizer with presets, volume up to 200%,
  audio delay, and visualization for music.
- **Playback**: speed 0.1×–8× with pitch correction, A-B repeat, frame stepping
  forward and back, chapters, resume where you left off, repeat and shuffle.
- **Video**: brightness, contrast, saturation and hue; rotate and flip
  (follows phone rotation tags); aspect ratio presets; GLSL pixel shaders
  (sharpen, soften, grayscale, sepia, night vision and more); screenshots.
- **Playlist**: adds the rest of the folder automatically, reads and writes
  M3U/M3U8/PLS, opens folders, takes drag and drop.
- **Desktop**: MPRIS (media keys, GNOME/KDE media controls), screensaver
  inhibit while playing, single-window mode.
- PotPlayer-style hotkeys (press **F1** in the app for the full list).

## Install

```bash
./packaging/build-deb.sh
sudo apt install ./dist/astra-player_1.3.0_all.deb
```

The package pulls in `gstreamer1.0-libav` and the good, bad and ugly plugin
sets, so every codec is installed at that point.
`gstreamer1.0-plugins-extra` (VA-API), `yt-dlp` and `whisper.cpp` are
recommended extras.

### Speech to subtitles

Subtitle generation uses [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
and runs on your own computer. Install one engine:

```bash
sudo apt install whisper.cpp                 # whisper-cli, CPU
sudo apt install libggml0-backend-vulkan     # optional: GPU through Vulkan
```

Without root, the Python binding works too:

```bash
pip install --user --break-system-packages pywhispercpp
```

Astra Player never downloads anything on its own. The first time you generate
subtitles it asks before it fetches the chosen model from huggingface.co, and
the dialog shows the size. Models are checked against their SHA-256 and kept in
`~/.local/share/astra-player/models`. Audio is extracted with `ffmpeg` when it is
installed, otherwise with GStreamer.

Run from the source tree without installing:

```bash
python3 -m astra_player video.mkv
```

## Hotkeys

| Key | Action |
| --- | --- |
| Space | Play / pause |
| Left / Right | Seek 5 s (Ctrl: 30 s, Shift: 1 min) |
| Up / Down, mouse wheel | Volume |
| Enter, double-click | Fullscreen |
| Page Up / Page Down | Previous / next file (Ctrl: chapter) |
| D / F | Previous / next frame |
| X / C / Z | Slower / faster / normal speed |
| `[` `]` `\` | A-B repeat: set A / set B / clear |
| `,` `.` `/` | Subtitle delay − / + / reset |
| Alt+H, Alt+L, Alt+A | Toggle subtitles, next subtitle, next audio track |
| W E / R T / Y U / I O, Q | Brightness / contrast / saturation / hue, reset |
| Ctrl+E | Screenshot |
| Ctrl+O, Ctrl+F, Ctrl+U, Ctrl+V | Open files, folder, URL, clipboard |
| Ctrl+Y | Search YouTube |
| F6 / F5 / Ctrl+F1 / Tab | Playlist / preferences / media info / status |
| Right-click | Full menu |

## Tests

The GUI end-to-end test generates its own media with `ffmpeg` and drives a
real window:

```bash
Xvfb :77 -screen 0 1280x800x24 &
DISPLAY=:77 GDK_BACKEND=x11 dbus-run-session python3 tests/gui_selftest.py
```

`dbus-run-session` keeps the test from handing off to a Astra Player that is
already open on your desktop.

The unit tests need no display and no network. The YouTube search test
parses canned `yt-dlp` output from `tests/fixtures/`:

```bash
python3 -m unittest tests/test_whisper.py tests/test_youtube.py
```

The speech-recognition checks in both tests run only when a speech engine and a
downloaded model are present. They use the spoken sample from the `whisper.cpp`
package, or the WAV file named by `ASTRA_SPEECH_WAV`. Otherwise they are
skipped. The tests never download a model.

## License

GPL-3.0-or-later. See `LICENSE`.
