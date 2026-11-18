#!/bin/bash
# Unified video/image display player. Single persistent mpv instance,
# controlled entirely via IPC. Defaults to looping the video folder on boot.
#
# Auto-detect: at startup, picks whichever HDMI port has a display
# connected and routes both video AND audio to it (audio follows video).
# Prefers HDMI-A-2 if both are connected.
#
# HDMI watchdog: if the set of connected HDMI ports changes (cable moved,
# display plugged in, TV off/on), this script exits and systemd restarts
# it. That re-picks the port and re-reads the display's resolution, so
# the player never sits in a state that can't reach the screen.
#
# No display at startup: mpv starts idle (no playlist) instead of failing
# through every file; the watchdog restarts it once a display appears.

SOCKET=/tmp/vtg-display.sock
MEDIA_DIR="$(cd "$(dirname "$0")/.." && pwd)/media"
VIDEO_EXT="mp4|m4v|mkv|mov|avi|ts|m2ts|mpg|mpeg|webm|wmv"
POLL=2       # seconds between HDMI checks
DEBOUNCE=3   # a change must last this long before restarting

shopt -s nullglob nocaseglob extglob
export LC_COLLATE=C  # same file order as the web UI's "Play folder"
rm -f "$SOCKET"

# Last volume set in the web UI (state/volume_<player>), else 100
saved_volume() {
    local v
    v=$(cat "$(dirname "$MEDIA_DIR")/state/volume_$1" 2>/dev/null)
    [[ "$v" =~ ^[0-9]{1,3}$ ]] && [ "$v" -le 100 ] && echo "$v" || echo 100
}

port_connected() {
    for f in /sys/class/drm/card*-"$1"/status; do
        [ "$(cat "$f" 2>/dev/null)" = "connected" ] && return 0
    done
    return 1
}

hdmi_state() {
    local s=""
    for f in /sys/class/drm/card*-HDMI-A-*/status; do
        s+="$(basename "$(dirname "$f")")=$(cat "$f" 2>/dev/null) "
    done
    echo "$s"
}

START_STATE="$(hdmi_state)"
FILES=()
if port_connected "HDMI-A-2"; then
    CONNECTOR="HDMI-A-2"; AUDIO_CARD="vc4hdmi1"
elif port_connected "HDMI-A-1"; then
    CONNECTOR="HDMI-A-1"; AUDIO_CARD="vc4hdmi0"
else
    CONNECTOR="HDMI-A-2"; AUDIO_CARD="vc4hdmi1"
fi

if port_connected "$CONNECTOR"; then
    # Only real video files; stray files (Thumbs.db, ._ files) are skipped
    FILES=("$MEDIA_DIR"/video/*.@($VIDEO_EXT))
    echo "VTG display: using $CONNECTOR, audio on $AUDIO_CARD, ${#FILES[@]} video file(s)"
else
    echo "VTG display: no display connected, starting idle; will restart when one is plugged in"
fi
echo "$CONNECTOR" > /tmp/vtg-display-connector  # read by the web UI

# Forced output mode (web UI: Display panel). Format: "<index> <edid-sha1> <label>".
# Only used if it was picked for THIS display (same EDID) and the index
# still exists; anything else means auto (the display's preferred mode).
DRM_MODE=()
MODE_FILE="$(dirname "$MEDIA_DIR")/state/display_mode"
if [ -r "$MODE_FILE" ] && port_connected "$CONNECTOR"; then
    read -r M_IDX M_SHA M_LABEL < "$MODE_FILE"
    if [[ "${M_IDX:-}" =~ ^[0-9]+$ ]]; then
        DRM_DIR=$(ls -d /sys/class/drm/card*-"$CONNECTOR" 2>/dev/null | head -1)
        EDID_SHA=$(sha1sum "$DRM_DIR/edid" 2>/dev/null | cut -d' ' -f1)
        N_MODES=$(grep -c . "$DRM_DIR/modes" 2>/dev/null)
        if [ "$M_SHA" = "$EDID_SHA" ] && [ "$M_IDX" -lt "${N_MODES:-0}" ]; then
            DRM_MODE=(--drm-mode="$M_IDX")
            echo "VTG display: forcing output mode $M_LABEL (mode $M_IDX)"
        else
            echo "VTG display: saved output mode is for a different display, using auto"
        fi
    fi
fi

mpv --idle=yes \
    --keep-open=yes \
    --input-ipc-server="$SOCKET" \
    --fullscreen \
    --no-osc \
    --no-osd-bar \
    --osd-level=3 \
    --hwdec=auto \
    --vo=gpu \
    --gpu-context=drm \
    --drm-connector="$CONNECTOR"     "${DRM_MODE[@]}" \
    --scale=bilinear \
    --cscale=bilinear \
    --dscale=bilinear \
    --video-sync=display-resample \
    --audio-device="alsa/hdmi:CARD=$AUDIO_CARD,DEV=0" \
    --audio-fallback-to-null=yes \
    --volume="$(saved_volume video)" \
    --image-display-duration=5 \
    --loop-playlist=inf \
    --quiet \
    --msg-level=vo=error \
    "${FILES[@]}" &
MPV_PID=$!

# Pass systemd's stop signal on to mpv and exit cleanly
trap 'kill -TERM "$MPV_PID" 2>/dev/null; wait "$MPV_PID"; exit 0' TERM INT

while kill -0 "$MPV_PID" 2>/dev/null; do
    sleep "$POLL" & wait $!
    [ "$(hdmi_state)" = "$START_STATE" ] && continue
    sleep "$DEBOUNCE" & wait $!
    NOW="$(hdmi_state)"
    if [ "$NOW" != "$START_STATE" ]; then
        echo "VTG display: HDMI changed [$START_STATE] -> [$NOW], restarting player"
        kill -TERM "$MPV_PID" 2>/dev/null
        wait "$MPV_PID"
        exit 0   # systemd (Restart=always) starts us again
    fi
done

# mpv exited on its own (crash): report its code; systemd restarts us
wait "$MPV_PID"
exit $?
