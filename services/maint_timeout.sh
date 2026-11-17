#!/bin/bash
# Maintenance-mode idle timeout (runs as root, vtg-maint-timeout.service).
# If the card is writable (Maintenance) and nobody has done anything for
# IDLE_LIMIT seconds, switch back to Read-only and reboot, so a unit left
# in Maintenance is safe to unplug again.
#
# Activity = a web UI action (any button/setting change), an SSH or SFTP
# session, or apt/dpkg/git/scp/rsync running. Never fires mid-copy or
# mid-update. Not used on Debug boots (those end at the next reboot).
#
# Times are uptime seconds, not the clock, so a clock sync can't trigger it.

IDLE_LIMIT=671   # 11:11
CHECK=10
DEADLINE_FILE=/run/vtg-maint-deadline     # read by the OSD and web UI
WEB_ACTIVITY=/tmp/vtg-web-activity        # web_api.py writes uptime here on each action
DIR="$(cd "$(dirname "$0")" && pwd)"

rm -f "$DEADLINE_FILE"
[ "$(findmnt -n -o FSTYPE /)" = "overlay" ] && exit 0   # protected: nothing to do
[ -e /run/vtg-debug-boot ] && exit 0                     # debug boot
[ -e /etc/pi-vtg-protection-armed ] || exit 0           # still building: protection never turned on yet

up() { cut -d. -f1 /proc/uptime; }
busy() {
    pgrep -x 'sshd-session|sftp-server|apt|apt-get|dpkg|git|scp|rsync' >/dev/null && return 0
    pgrep -f '^sshd: .+@' >/dev/null   # older OpenSSH names sessions this way
}

last=$(up)
while true; do
    now=$(up)
    busy && last=$now
    w=$(cut -d. -f1 "$WEB_ACTIVITY" 2>/dev/null)
    [[ "$w" =~ ^[0-9]+$ ]] && [ "$w" -gt "$last" ] && [ "$w" -le "$now" ] && last=$w
    deadline=$((last + IDLE_LIMIT))
    echo "$deadline" > "$DEADLINE_FILE"
    if [ "$now" -ge "$deadline" ]; then
        echo "vtg maint-timeout: idle for ${IDLE_LIMIT}s, switching to read-only mode"
        rm -f "$DEADLINE_FILE"
        exec bash "$DIR/vtg_mode.sh" readonly
    fi
    sleep "$CHECK"
done
