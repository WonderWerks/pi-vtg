#!/bin/bash
# Persistent audio-test mpv instance -- 3.5mm jack, no video.

SOCKET=/tmp/vtg-audio.sock
MEDIA_DIR="$(cd "$(dirname "$0")/.." && pwd)/media"
AUDIO_EXT="mp3|flac|wav|m4a|aac|ogg|opus|wma|aif|aiff"

shopt -s nullglob nocaseglob extglob  # empty folder -> mpv starts idle
export LC_COLLATE=C  # same file order as the web UI's "Play folder"
rm -f "$SOCKET"

# --audio-fallback-to-null: if the jack can't be opened, keep the playlist
# running silently instead of spinning through every file.
exec mpv --idle=yes \
    --input-ipc-server="$SOCKET" \
    --no-video \
    --audio-device=alsa/plughw:CARD=Headphones,DEV=0 \
    --audio-fallback-to-null=yes \
    --loop-playlist=inf \
    --msg-level=vo=error \
    "$MEDIA_DIR"/audio/*.@($AUDIO_EXT)
