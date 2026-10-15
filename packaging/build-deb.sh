#!/bin/sh
# Build dist/astra-player_<version>_all.deb from this checkout.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/astra_player/__init__.py")
PKG=astra-player
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/lib/$PKG" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/$PKG"

# Application code (no caches, no bundled icon dir: the icon goes to hicolor).
tar -C "$ROOT" --exclude='__pycache__' --exclude='*.pyc' --exclude='astra_player/icons' \
  -cf - astra_player | tar -C "$STAGE/usr/lib/$PKG" -xf -

cat > "$STAGE/usr/bin/astra-player" <<'SH'
#!/bin/sh
export PYTHONPATH="/usr/lib/astra-player${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m astra_player "$@"
SH
chmod 755 "$STAGE/usr/bin/astra-player"

install -m 644 "$ROOT/data/io.github.hafij.AstraPlayer.desktop" "$STAGE/usr/share/applications/"
install -m 644 "$ROOT/astra_player/icons/hicolor/scalable/apps/io.github.hafij.AstraPlayer.svg" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/"
install -m 644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/$PKG/copyright"

SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTL
Package: $PKG
Version: $VERSION
Section: video
Priority: optional
Architecture: all
Maintainer: Hafij-BGE <mdhafijur.rahman@ogr.deu.edu.tr>
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.14), gir1.2-adw-1 (>= 1.5),
 gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gir1.2-graphene-1.0,
 gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad,
 gstreamer1.0-plugins-ugly, gstreamer1.0-libav, gstreamer1.0-gtk4, gstreamer1.0-gl
Replaces: kiln-player
Conflicts: kiln-player
Recommends: gstreamer1.0-plugins-extra, gstreamer1.0-pipewire, yt-dlp, whisper.cpp, ffmpeg
Suggests: libggml0-backend-vulkan
Homepage: https://github.com/Hafij-DEU/video-player
Description: free media player with every codec built in
 Astra Player is a PotPlayer-style video and music player for Linux.
 It plays nearly every format through FFmpeg (gst-libav) and GStreamer:
 H.264, HEVC, AV1, VP9, MPEG-2, VC-1, ProRes, AAC, AC-3, E-AC-3, DTS,
 TrueHD, FLAC, Opus and more, in MKV, MP4, AVI, TS, WebM and others.
 .
 Features: VA-API hardware decoding, embedded and external subtitles
 with sync, audio track switching, 10-band equalizer, speed control with
 pitch correction, A-B repeat, frame stepping, chapters, color
 adjustment, GLSL pixel shaders, rotation, aspect ratio control,
 screenshots, playlists, resume, streams and web video via yt-dlp, and
 MPRIS media-key support. No ads, no account, no extra downloads.
 .
 With whisper.cpp installed it can also make subtitles from speech,
 offline. The speech model is only downloaded after you confirm it.
CTL

cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
SH
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
sed -i 's/= configure/= remove/' "$STAGE/DEBIAN/postrm"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

find "$STAGE/usr" -type d -exec chmod 755 {} +
find "$STAGE/usr/lib" "$STAGE/usr/share" -type f -exec chmod 644 {} +

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT" >/dev/null
echo "$OUT"
