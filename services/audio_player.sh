#!/bin/bash
# Persistent audio-test mpv instance -- 3.5mm jack, no video.

SOCKET=/tmp/vtg-audio.sock
rm -f "$SOCKET"

exec mpv --idle=yes \
    --input-ipc-server="$SOCKET" \
    --no-video \
    --audio-device=alsa/plughw:CARD=Headphones,DEV=0 \
    --loop-playlist=inf \
    --msg-level=vo=error \
    ~/pi-vtg/media/audio/*
