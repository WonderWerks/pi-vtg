#!/bin/bash
# Second HDMI output (HDMI-A-1). Starts idle, no auto-loaded content --
# controlled entirely via IPC.
SOCKET=/tmp/vtg-display-hdmi1.sock
rm -f "$SOCKET"

exec mpv --idle=yes \
    --keep-open=yes \
    --input-ipc-server="$SOCKET" \
    --fullscreen \
    --no-osc \
    --no-osd-bar \
    --osd-level=3 \
    --hwdec=auto \
    --vo=gpu \
    --gpu-context=drm \
    --drm-connector=0.HDMI-A-1 \
    --profile=gpu-hq \
    --scale=bilinear \
    --cscale=bilinear \
    --dscale=bilinear \
    --video-sync=display-resample \
    --audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0 \
    --image-display-duration=5 \
    --loop-playlist=inf \
    --quiet \
    --msg-level=vo=error \
    ~/vtg_gen2/media/no_signal.jpeg