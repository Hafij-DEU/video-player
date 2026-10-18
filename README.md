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
- **Subtitles**: embedded tracks and external `.srt .ass .ssa .vtt .sub .smi`.
  Picked up automatically from the video's folder or a `Subs`/`Subtitles`
  subfolder: same name, name plus language (`movie.en.srt`), the same episode
  code (`S01E02`, `1x02`, `Ep02`), or the only subtitle next to the only video.
  All subtitles found are listed under Subtitles › *Subtitle files in this
  folder*. Show **two subtitles at once** (Subtitles › *Second subtitle*), at
  the top or above the first. Modern box or classic outline style, white,
  yellow or cyan, four sizes, adjustable height (Alt+Up / Alt+Down); in
  fullscreen they rise above the controls. Delay adjustment and Whisper too.
- **Speech to subtitles**: Subtitles › *Generate subtitles (Whisper)…* turns
  the speech in the current file into `<name>.whisper.srt` beside it, offline,
  and loads it. Choose the model (tiny 78 MB, base 148 MB, small 488 MB),
  the spoken language, and optional translation to English in Preferences.
- **Audio**: track switching, 10-band equalizer with presets, volume up to 200%,
  audio delay, and visualization for music.
- **Playback**: speed 0.1×–8× with pitch correction, A-B repeat, frame stepping
  forward and back, chapters, resume where you left off, shuffle, and a repeat
  button that cycles play once / repeat file / repeat playlist.
- **Record a portion**: press Record (Ctrl+R) to start and again to stop, or
  set A and B, and save just that part to a new file. *Fast* copies the streams
  losslessly and cuts at the nearest keyframe. *Precise* re-encodes to MP4 and
  cuts on the exact frame. Works for YouTube too, through yt-dlp. Needs `ffmpeg`.
- **Saved playlists** (Ctrl+B): save YouTube search results (one video with the
  bookmark button, or all results at once) or the current queue into named
  playlists kept inside the player. Play any of them later from any item,
  rename, reorder, remove items, or delete the whole playlist. Stored in
  `~/.local/share/astra-player/playlists.json`.
- **Picture in picture** (Ctrl+P): a small borderless window. Drag the video
  to move it and the corner grip to resize it. Hover to show its buttons: back
  10 s, play/pause, forward 10 s, back to the window (or double-click / Esc),
  back to fullscreen (or Enter), and close. On GNOME, press Alt+Space › Always
  on Top to pin it above other windows.
- **Fullscreen**: a compact, see-through control panel centred at the bottom
  (back 10 s, previous, play, next, forward 10 s, volume) with the other options
  in the top bar. Hover the seek bar for a **preview frame**. A **clock** shows in
  a corner in fullscreen (Menu › Clock: in fullscreen, always, or off).
- **Save streams** (Ctrl+S): download the whole video (YouTube and other sites via
  yt-dlp) or record a live stream until you stop it (Playback › Cancel saving).
- **Unsupported files** just say "Unsupported file" instead of a technical error.
- **Updates**: checks GitHub once a day and offers one-click updates; apt then
  also installs any new recommended extras (switch it off in Preferences).
- **Video**: brightness, contrast, saturation and hue; rotate and flip
  (follows phone rotation tags); aspect ratio presets; GLSL pixel shaders
  (sharpen, soften, grayscale, sepia, night vision and more); screenshots.
- **Playlist**: adds the rest of the folder automatically, reads and writes
  M3U/M3U8/PLS, plays whole folders including subfolders (button, Ctrl+F, drag
  a folder in, or *Open With* on a folder in Files), takes drag and drop.
- **Desktop**: MPRIS (media keys, GNOME/KDE media controls), screensaver
  inhibit while playing, single-window mode.
- PotPlayer-style hotkeys (press **F1** in the app for the full list).

## Install

```bash
./packaging/build-deb.sh
sudo apt install ./dist/astra-player_1.7.1_all.deb
```

The package pulls in `gstreamer1.0-libav` and the good, bad and ugly plugin
sets, so every codec is installed at that point.
`gstreamer1.0-plugins-extra` (VA-API), `yt-dlp` and `whisper.cpp` are
recommended extras.

### YouTube says “Sign in to confirm you’re not a bot”

YouTube sometimes rate-limits a connection (HTTP 429) and then refuses
anonymous playback. When that happens, Astra Player asks once whether it may
use your YouTube login from a browser on this computer (Brave, Chrome,
Chromium, Edge, Firefox, Opera or Vivaldi). Pick one and press **Allow**: the
video starts again where it was. If that browser isn't signed in, Astra Player
tries your other browsers by itself, and remembers the one that works. yt-dlp
reads the cookies on this computer and sends them only to YouTube. Nothing is
read before you allow it, and you can change or turn off the choice, or use a
`cookies.txt` export, in Preferences › YouTube.

If no browser works, sign in to YouTube in one of them and play the video
again, or wait a few hours: the limit is lifted by itself.

For Chrome-based browsers yt-dlp needs the `secretstorage` Python module to
open the GNOME keyring. Astra Player checks for it and, if its own yt-dlp
lacks it, uses a system yt-dlp that has it:

```bash
sudo apt install python3-secretstorage      # for the apt yt-dlp and Astra Player's own copy
pipx inject yt-dlp secretstorage            # for a pipx yt-dlp
```

### Keeping yt-dlp current

YouTube changes often, and an old yt-dlp is a common reason for playback to
fail. Turn on Preferences › YouTube › *Keep yt-dlp up to date* (or tick the box
in the sign-in dialog) and Astra Player downloads the official yt-dlp
(about 3 MB) from [its GitHub releases](https://github.com/yt-dlp/yt-dlp/releases),
checks it against the release's `SHA2-256SUMS`, and keeps it in
`~/.local/share/astra-player/bin`. It then looks for a new release once a week
and uses that copy in place of the system one. Astra Player always asks, with
the size, before the first download. On a computer without yt-dlp, opening a
YouTube link offers the same download.

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
| Ctrl+L | Repeat: once / file / playlist |
| Ctrl+R, Ctrl+Shift+R | Record start/stop and save; save A-B segment |
| Ctrl+P | Picture in picture |
| Ctrl+B | Saved playlists |
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

The unit tests need no display and no network. The YouTube test parses canned
`yt-dlp` output from `tests/fixtures/`, and checks the browser fallback order,
which yt-dlp is chosen, the weekly update schedule and the checksum check
against a local stand-in for GitHub. The GUI test drives the sign-in dialog
with a stand-in yt-dlp. No test reads browser cookies or writes to
`~/.local/share`:

```bash
python3 -m unittest tests/test_whisper.py tests/test_youtube.py
```

The speech-recognition checks in both tests run only when a speech engine and a
downloaded model are present. They use the spoken sample from the `whisper.cpp`
package, or the WAV file named by `ASTRA_SPEECH_WAV`. Otherwise they are
skipped. The tests never download a model.

## License

GPL-3.0-or-later. See `LICENSE`.
