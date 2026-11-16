#!/bin/bash
# Boot-time wifi decision (runs once, 30s after boot, as root).
# Join any saved network that's in range; otherwise start the hotspot.
source "$(dirname "$0")/../secrets.env"
FALLBACK_CON="$FALLBACK_SSID"
WLAN_DEV="wlan0"
SCAN_CACHE=/tmp/vtg-wifi-scan.txt   # used by the web UI while on the hotspot

# Clear a stuck/hung connection attempt before doing anything else
nmcli -t -f GENERAL.STATE device show "$WLAN_DEV" | grep -q "connecting" && nmcli device disconnect "$WLAN_DEV"

active_con=$(nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v dev="$WLAN_DEV" '$2==dev {print $1}')

# Already settled on something (NetworkManager auto-joined a saved
# network) -- never touch it again until reboot.
if [ -n "$active_con" ]; then
    exit 0
fi

# Scan once and keep it: the radio can't scan reliably once it's a hotspot
nmcli device wifi rescan ifname "$WLAN_DEV" >/dev/null 2>&1 && sleep 4
nmcli -t -f SSID,SIGNAL,SECURITY device wifi list ifname "$WLAN_DEV" > "$SCAN_CACHE" 2>/dev/null
chmod 644 "$SCAN_CACHE"
in_range=$(cut -d: -f1 "$SCAN_CACHE" | sort -u)

# Try every saved wifi network that's in range (not just secrets.env's)
while IFS= read -r name; do
    [ -z "$name" ] || [ "$name" = "$FALLBACK_CON" ] && continue
    ssid=$(nmcli --escape no -g 802-11-wireless.ssid connection show "$name" 2>/dev/null)
    [ -n "$ssid" ] && grep -Fxq "$ssid" <<< "$in_range" || continue
    if timeout 20 nmcli connection up "$name" >/dev/null 2>&1; then
        exit 0
    fi
done < <(nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless" {print $1}')

nmcli connection up "$FALLBACK_CON" >/dev/null 2>&1
