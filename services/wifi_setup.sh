#!/bin/bash
set -e
cd "$(dirname "$0")/.."
source secrets.env

# Safe to re-run: an existing profile is updated in place (never
# duplicated, never deleted), so a live wifi/hotspot session isn't cut.
# Changes take effect the next time that connection comes up.
upsert() {
    local name="$1"; shift
    if nmcli -g NAME connection show | grep -Fxq "$name"; then
        sudo nmcli connection modify "$name" "$@"
    else
        sudo nmcli connection add type wifi con-name "$name" "$@" >/dev/null
    fi
}

# $WIFI_SSID (optional): a network to know from day one, e.g. your travel
# router. Preferred over other saved networks when several are in range.
# Leave it blank to add networks only from the web UI.
if [ -n "${WIFI_SSID:-}" ] && [ "$WIFI_SSID" != "changeme" ]; then
    upsert "$WIFI_SSID" \
        connection.interface-name wlan0 802-11-wireless.ssid "$WIFI_SSID" \
        connection.autoconnect yes connection.autoconnect-priority 10 \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$WIFI_PASSWORD"
fi
[ -n "${FALLBACK_SSID:-}" ] && [ "$FALLBACK_SSID" != "changeme" ] || { echo "Set FALLBACK_SSID in secrets.env"; exit 1; }

# $FALLBACK_SSID: fallback hotspot, connects if no primary connection (the watchdog brings it up manually)
upsert "$FALLBACK_SSID" \
    connection.interface-name wlan0 802-11-wireless.ssid "$FALLBACK_SSID" \
    connection.autoconnect no \
    802-11-wireless.mode ap 802-11-wireless.band bg \
    ipv4.method shared ipv4.addresses "10.1.1.10/24" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$FALLBACK_PASSWORD"

echo "Wifi profiles configured."
