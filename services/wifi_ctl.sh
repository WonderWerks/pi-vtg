#!/bin/bash
# Wifi control for the web UI. Runs as root (via sudo).
#
#   wifi_ctl.sh scan                  list nearby networks (nmcli -t format)
#   wifi_ctl.sh connect <ssid> [hidden]   password on stdin (empty = open network)
#   wifi_ctl.sh forget <name>         delete a saved network
#   wifi_ctl.sh hotspot               switch to the fallback hotspot now
#
# connect is safe to run from the hotspot: if joining fails, the previous
# connection (or the hotspot) is brought back so the unit stays reachable.
# Result of the last connect is written to /tmp/vtg-wifi-result.
# Saved networks are written through to the SD card (protected mode).

set -u
cd "$(dirname "$0")/.."
source secrets.env
WLAN=wlan0
RESULT=/tmp/vtg-wifi-result
SCAN_CACHE=/tmp/vtg-wifi-scan.txt   # written by wifi_fallback.sh before the hotspot starts
NM_DIR=/etc/NetworkManager/system-connections

die() { echo "wifi_ctl: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "must run as root"

persist() { bash services/vtg_mode.sh persist "$NM_DIR" >/dev/null 2>&1; }
active_con() { nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$WLAN" '$2==d {print $1}'; }
profile_exists() { nmcli -g NAME connection show | grep -Fxq "$1"; }
result() { echo "$(date +%s) $*" > "$RESULT"; chmod 644 "$RESULT"; }
# Network name for messages (Imager's profiles are named netplan-wlan0-<SSID>)
ssid_of() { local s; s=$(nmcli --escape no -g 802-11-wireless.ssid connection show "$1" 2>/dev/null); echo "${s:-$1}"; }

case "${1:-}" in
scan)
    nmcli device wifi rescan ifname "$WLAN" >/dev/null 2>&1 && sleep 3
    out=$(nmcli -t -f SSID,SIGNAL,SECURITY device wifi list ifname "$WLAN" 2>/dev/null)
    # In hotspot mode the radio often can't scan; fall back to the boot-time scan
    if [ -z "$(echo "$out" | grep -v '^:')" ] && [ -s "$SCAN_CACHE" ]; then
        out=$(cat "$SCAN_CACHE")
    fi
    echo "$out"
    ;;

connect)
    SSID="${2:-}"; HIDDEN="${3:-}"
    [ -n "$SSID" ] || die "connect: no SSID"
    [ "$SSID" != "$FALLBACK_SSID" ] || die "connect: that is the hotspot's own name"
    IFS= read -r PW || true
    PRIOR=$(active_con)
    # $SSID is a profile name (saved list) or a network name (scan / typed).
    # A network already saved under another profile name (e.g. Imager's
    # netplan-wlan0-<SSID>) reuses that profile instead of adding a duplicate.
    PROFILE="$SSID"
    if ! profile_exists "$PROFILE"; then
        while IFS= read -r c; do
            [ "$c" != "$FALLBACK_SSID" ] || continue
            if [ "$(nmcli --escape no -g 802-11-wireless.ssid connection show "$c" 2>/dev/null)" = "$SSID" ]; then
                PROFILE="$c"; break
            fi
        done < <(nmcli --escape no -g NAME connection show)
    fi
    SHOW=$(ssid_of "$PROFILE")
    result "connecting $SHOW"

    OLD_PSK=""; EXISTED=0
    if profile_exists "$PROFILE"; then
        # Known network: update the password if one was given, then bring it up
        EXISTED=1
        OLD_PSK=$(nmcli --escape no -s -g 802-11-wireless-security.psk connection show "$PROFILE" 2>/dev/null)
        [ -n "$PW" ] && nmcli connection modify "$PROFILE" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PW"
        timeout 45 nmcli --wait 30 connection up "$PROFILE" >/dev/null 2>&1; ok=$?
    else
        args=(device wifi connect "$SSID" ifname "$WLAN" name "$PROFILE")
        [ -n "$PW" ] && args+=(password "$PW")
        [ "$HIDDEN" = hidden ] && args+=(hidden yes)
        timeout 45 nmcli --wait 30 "${args[@]}" >/dev/null 2>&1; ok=$?
    fi

    if [ $ok = 0 ]; then
        nmcli connection modify "$PROFILE" connection.autoconnect yes
        persist
        ip=$(ip -4 -o addr show "$WLAN" | awk '{print $4}' | cut -d/ -f1)
        result "ok connected to $(ssid_of "$PROFILE") at $ip"
        exit 0
    fi

    # Failed: undo, and get the unit reachable again
    if [ $EXISTED = 1 ]; then
        [ -n "$PW" ] && [ -n "$OLD_PSK" ] && nmcli connection modify "$PROFILE" wifi-sec.psk "$OLD_PSK"
    else
        profile_exists "$PROFILE" && nmcli connection delete id "$PROFILE" >/dev/null 2>&1
    fi
    if [ -n "$PRIOR" ] && [ "$PRIOR" != "$PROFILE" ] && timeout 45 nmcli --wait 30 connection up "$PRIOR" >/dev/null 2>&1; then
        result "failed to join $SHOW (wrong password or out of range); back on $(ssid_of "$PRIOR")"
    else
        nmcli connection up "$FALLBACK_SSID" >/dev/null 2>&1
        result "failed to join $SHOW (wrong password or out of range); hotspot $FALLBACK_SSID is back on"
    fi
    exit 1
    ;;

forget)
    NAME="${2:-}"
    [ -n "$NAME" ] || die "forget: no name"
    [ "$NAME" != "$FALLBACK_SSID" ] || die "forget: refusing to delete the hotspot"
    profile_exists "$NAME" || die "forget: no saved network named $NAME"
    was_active=$([ "$(active_con)" = "$NAME" ] && echo 1 || echo 0)
    nmcli connection delete id "$NAME" >/dev/null || die "forget: delete failed"
    persist
    [ "$was_active" = 1 ] && nmcli connection up "$FALLBACK_SSID" >/dev/null 2>&1
    echo "forgot $NAME"
    ;;

hotspot)
    nmcli connection up "$FALLBACK_SSID" >/dev/null || die "could not start hotspot"
    echo "hotspot $FALLBACK_SSID on"
    ;;

*)
    sed -n '2,13p' "$0"; exit 1 ;;
esac
