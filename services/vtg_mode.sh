#!/bin/bash
# Read-only / maintenance mode for power-pull safety. Runs as root
# (the web UI calls it through sudo).
#
#   Read-only:   SD card is read-only; all writes go to RAM and vanish at
#                power-off. Safe to pull the plug at any time.
#   Maintenance: SD card is writable (add media, git pull, apt upgrade).
#                Shut down properly before removing power.
#   Debug:       writable for ONE boot so logs survive a reboot, then the
#                following boot is read-only again automatically.
#
# Usage:
#   vtg_mode.sh status
#   vtg_mode.sh readonly | maintenance | debug   (switches, then reboots;
#                                                 'protect' = readonly)
#   vtg_mode.sh persist <path>...                (save to the card now)
#   vtg_mode.sh boot                             (run by vtg-mode.service)
#   vtg_mode.sh settime <unix-seconds>           (set the clock)
#
# Uses raspi-config's overlay file system (the supported mechanism).

set -u
BOOT_DIR=/boot/firmware
CMDLINE=$BOOT_DIR/cmdline.txt
DEBUG_FLAG=$BOOT_DIR/vtg-debug-once
ARMED=/etc/pi-vtg-protection-armed   # set by the first "protect" (end of the build)
LOWER=/media/root-ro   # the real SD card root while protected
PERSIST_ALLOWED=(/home/vtg/pi-vtg/state /etc/NetworkManager/system-connections)

die() { echo "vtg_mode: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "must run as root"

now_protected()  { [ "$(findmnt -n -o FSTYPE /)" = "overlay" ]; }
next_protected() { grep -qE '(^| )(boot=overlay|overlayroot=tmpfs)( |$)' "$CMDLINE"; }

boot_rw() {  # /boot/firmware may be write-protected too; open it briefly
    findmnt -n -o OPTIONS "$BOOT_DIR" | grep -qE '(^|,)ro(,|$)' && mount -o remount,rw "$BOOT_DIR"
    return 0
}

set_overlay() {  # 0 = protected next boot, 1 = writable next boot
    raspi-config nonint do_overlayfs "$1" || die "raspi-config do_overlayfs $1 failed"
    sync
}

do_reboot() {
    echo "vtg_mode: rebooting"
    sync
    systemctl reboot
}

persist() {
    [ $# -gt 0 ] || die "persist: no paths given"
    local p a ok paths=()
    for p in "$@"; do
        p=$(realpath -m "$p")
        ok=0
        for a in "${PERSIST_ALLOWED[@]}"; do
            [[ "$p" == "$a" || "$p" == "$a"/* ]] && ok=1
        done
        [ $ok = 1 ] || die "persist: not an allowed path: $p"
        paths+=("$p")
    done

    if ! now_protected; then
        sync          # card is writable; the files are already on it
        return 0
    fi

    findmnt -n "$LOWER" >/dev/null || die "persist: SD card root not found at $LOWER"
    mount -o remount,rw "$LOWER" || die "persist: could not make SD card writable"
    trap 'sync; mount -o remount,ro "$LOWER"' EXIT
    for p in "${paths[@]}"; do
        local dst="$LOWER$p"
        if [ -e "$p" ]; then
            # Copy to a temp name, then swap, so a power cut mid-copy
            # leaves either the old or the new version, never half a file.
            mkdir -p "$(dirname "$dst")"
            rm -rf "$dst.vtgtmp"
            cp -a "$p" "$dst.vtgtmp" || die "persist: copy failed: $p"
            rm -rf "$dst"
            mv "$dst.vtgtmp" "$dst"
        else
            rm -rf "$dst"   # deleted in RAM -> delete on the card too
        fi
        echo "vtg_mode: saved $p"
    done
}

status() {
    local now next debug
    now_protected && now=read-only || now=writable
    next_protected && next=read-only || next=writable
    [ -e "$DEBUG_FLAG" ] && debug=yes || debug=no
    echo "now=$now next_boot=$next debug_once=$debug"
}

case "${1:-}" in
    status)
        status ;;
    readonly|protect)
        boot_rw; rm -f "$DEBUG_FLAG"
        echo "vtg_mode: enabling read-only mode (can take a minute)"
        touch "$ARMED"   # from now on, Maintenance mode times out (maint_timeout.sh)
        set_overlay 0
        do_reboot ;;
    maintenance)
        boot_rw; rm -f "$DEBUG_FLAG"
        set_overlay 1
        do_reboot ;;
    debug)
        boot_rw; touch "$DEBUG_FLAG"; sync
        set_overlay 1
        do_reboot ;;
    persist)
        shift; persist "$@" ;;
    boot)
        # A debug boot: card is writable now; arrange protection for the
        # NEXT boot so it only lasts this one.
        if [ -e "$DEBUG_FLAG" ]; then
            boot_rw; rm -f "$DEBUG_FLAG"; sync
            if ! now_protected; then
                echo "vtg_mode: debug boot (writable, logs kept); read-only again next boot"
                touch /run/vtg-debug-boot   # read by the OSD / web UI / idle timeout
                set_overlay 0
            fi
        fi
        status ;;
    settime)
        # Set the clock from the web UI's browser (seconds since 1970, UTC)
        [[ "${2:-}" =~ ^[0-9]{10}$ ]] || die "settime: expected a Unix timestamp"
        date -s "@$2" >/dev/null || die "settime: date failed"
        date ;;
    *)
        sed -n '2,18p' "$0"; exit 1 ;;
esac
