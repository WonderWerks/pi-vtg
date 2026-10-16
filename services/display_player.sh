#!/bin/bash
# Unified video/image display player. Single persistent mpv instance,
# controlled entirely via IPC. Defaults to looping the video folder on boot.
#
# Auto-detect: at startup, picks whichever HDMI port has a display
# connected and routes both video AND audio to it (audio follows video).
# Prefers HDMI-A-2 if both/neither are connected. If the cable is moved
# to the other port later, restart this service (or reboot).

SOCKET=/tmp/vtg-display.sock
MEDIA_DIR="$(cd "$(dirname "$0")/.." && pwd)/media"
shopt -s nullglob  # empty folder -> mpv starts idle instead of erroring
rm -f "$SOCKET"

port_connected() {
    for f in /sys/class/drm/card*-"$1"/status; do
        [ -f "$f" ] && [ "$(cat "$f")" = "connected" ] && return 0
    done
    return 1
}

if port_connected "HDMI-A-2"; then
    CONNECTOR="HDMI-A-2"; AUDIO_CARD="vc4hdmi1"
elif port_connected "HDMI-A-1"; then
    CONNECTOR="HDMI-A-1"; AUDIO_CARD="vc4hdmi0"
else
    CONNECTOR="HDMI-A-2"; AUDIO_CARD="vc4hdmi1"
fi

echo "VTG display: using $CONNECTOR, audio on $AUDIO_CARD"
echo "$CONNECTOR" > /tmp/vtg-display-connector  # read by the web UI

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
    --drm-connector="$CONNECTOR" \
    --profile=gpu-hq \
    --scale=bilinear \
    --cscale=bilinear \
    --dscale=bilinear \
    --video-sync=display-resample \
    --audio-device="alsa/hdmi:CARD=$AUDIO_CARD,DEV=0" \
    --image-display-duration=5 \
    --loop-playlist=inf \
    --quiet \
    --msg-level=vo=error \
    "$MEDIA_DIR"/video/*