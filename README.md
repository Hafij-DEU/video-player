# Kiln Player

A free, PotPlayer-style media player for Linux. No ads, no account, no
subscription, and no codec packs to download later: every decoder comes in
with the package dependencies when you install it.

Kiln Player is written from scratch in Python with GTK 4, libadwaita and
GStreamer. Decoding is done by FFmpeg (through `gst-libav`) and GStreamer,
with VA-API hardware decoding when the GPU supports it. It contains no code
from PotPlayer.

## Features

- **Formats**: H.264, HEVC/H.265, AV1, VP8/VP9, MPEG-1/2/4, VC-1/WMV, ProRes,
  Theora; AAC, MP3, AC-3, E-AC-3, DTS, TrueHD, FLAC, ALAC, Opus, Vorbis, WMA,
  APE, WavPack; MKV, MP4, MOV, AVI, TS/M2TS, WebM, FLV, OGG and more.
- **Streams**: HTTP, HLS, DASH, RTSP, plus YouTube and other sites when
  `yt-dlp` is installed.
- **Subtitles**: embedded tracks and external `.srt .ass .ssa .vtt .sub .smi`,
  loaded automatically when the name matches the video. Includes delay
  adjustment, track switching and font choice.
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
sudo apt install ./dist/kiln-player_1.0.0_all.deb
```

The package pulls in `gstreamer1.0-libav` and the good, bad and ugly plugin
sets, so every codec is installed at that point.
`gstreamer1.0-plugins-extra` (VA-API) and `yt-dlp` are recommended extras.

Run from the source tree without installing:

```bash
python3 -m kiln_player video.mkv
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
| F6 / F5 / Ctrl+F1 / Tab | Playlist / preferences / media info / status |
| Right-click | Full menu |

## Tests

The GUI end-to-end test generates its own media with `ffmpeg` and drives a
real window:

```bash
Xvfb :77 -screen 0 1280x800x24 &
DISPLAY=:77 GDK_BACKEND=x11 python3 tests/gui_selftest.py
```

## License

GPL-3.0-or-later. See `LICENSE`.
