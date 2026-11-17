#!/usr/bin/env python3
"""Persistent OSD updater. Sets mpv's built-in status-message OSD line
on the display output. Controlled by state/osd_config.json."""
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from mpv_ipc import MpvIPC, MpvIPCError
import system_mode
import display_info
import netcheck

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "state" / "osd_config.json"
SECRETS_PATH = BASE_DIR / "secrets.env"
DISPLAY_SOCKET = "/tmp/vtg-display.sock"
AUDIO_SOCKET = "/tmp/vtg-audio.sock"
PORT = 5000
POLL_SECONDS = 2
MAX_MESSAGE_LEN = 80
MAX_NAME_LEN = 22   # OSD lines are cut off past ~45 characters

DEFAULT_CONFIG = {
    "enabled": True,
    "show_datetime": False,
    "show_ip": True,
    "show_ssid": True,
    "show_web_url": True,
    "show_now_playing": False,
    "show_audio_track": False,
    "show_errors": True,
    "show_mode": True,
    "show_display": False,
    "show_display_mode": False,
    "custom_message": "",
}

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)

def get_fallback_ssid():
    try:
        with open(SECRETS_PATH) as f:
            for line in f:
                if line.startswith("FALLBACK_SSID="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return None

def get_ip(iface):
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", iface], text=True, timeout=5)
        return out.split()[3].split("/")[0]
    except Exception:
        return None

def get_wifi_ssid():
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], text=True, timeout=5
        )
        for line in out.strip().split("\n"):
            parts = line.split(":")
            if len(parts) == 2 and parts[1] == "wlan0":
                return parts[0]
    except Exception:
        pass
    return None

def service_active(name):
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False

def fmt_time(t):
    if t is None:
        return "--:--"
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def now_playing(sock):
    try:
        mpv = MpvIPC(sock, connect_timeout=1)
    except MpvIPCError:
        return "not running"
    try:
        s = mpv.status()
    finally:
        mpv.close()
    name = s.get("filename")
    if not name:
        return "nothing loaded"
    if len(name) > MAX_NAME_LEN:
        name = name[:MAX_NAME_LEN - 3] + "..."
    state = "paused" if s.get("pause") else "playing"
    if s.get("duration"):
        return f"{name} ({fmt_time(s.get('time-pos'))} / {fmt_time(s.get('duration'))}) {state}"
    return f"{name} {state}"

# mpv's OSD doesn't wrap: at 1080p only ~45 characters fit on a line,
# so every line here is kept short.

WIFI_DECISION_AT = 35   # wifi_fallback.sh runs ~30s after boot, takes a few seconds

def mode_lines(mode):
    if mode == "prot":
        return ["Mode: READ-ONLY (safe to unplug)"]
    if mode == "debug":
        return ["Mode: DEBUG (logs kept this boot)"]
    lines = ["Mode: MAINTENANCE (SD card writable)"]
    left = system_mode.maint_seconds_left()
    if left is not None:
        lines.append(f"Read-only in {int(left) // 60}:{int(left) % 60:02d} if idle")
    return lines

def build_status_text(cfg):
    custom = (cfg.get("custom_message") or "").strip()
    if custom:
        return custom[:MAX_MESSAGE_LEN]

    lines = []
    mode = system_mode.current_mode()
    if cfg.get("show_mode", True):
        lines += mode_lines(mode)
    if cfg.get("show_datetime", False):
        lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))

    ssid = get_wifi_ssid()
    fallback = get_fallback_ssid()
    on_hotspot = bool(ssid and fallback and ssid == fallback)
    port = f":{PORT}" if cfg.get("show_web_url", True) else ""
    if cfg.get("show_ip", True):
        eth, wlan = get_ip("eth0"), get_ip("wlan0")
        lines.append(f"eth0: {eth + port if eth else 'not connected'}")
        if on_hotspot:
            lines.append(f"Hotspot wifi: {ssid}")
            lines.append(f"Web UI: {wlan or '10.1.1.10'}{port}")
        elif wlan:
            lost = ssid and netcheck.router_ok() is False
            lines.append(f"wlan0: {wlan}{port}{' (no router)' if lost else ''}")
        else:
            wait = WIFI_DECISION_AT - system_mode.uptime()
            lines.append(f"wlan0: searching, hotspot in {int(wait)}s" if wait > 0
                         else "wlan0: not connected")
    if cfg.get("show_ssid", True) and not (on_hotspot and cfg.get("show_ip", True)):
        lines.append(f"SSID: {ssid}{' (hotspot)' if on_hotspot else ''}" if ssid else "SSID: not connected")
    if cfg.get("show_display", False) or cfg.get("show_display_mode", False):
        dinfo = display_info.info()
        if cfg.get("show_display", False):
            lines.append(f"Display: {display_info.short_label(dinfo)}")
        if cfg.get("show_display_mode", False):
            lines.append(f"Native: {display_info.native_label(dinfo)}")
            forced = display_info.saved_mode(dinfo["connector"])
            if forced:
                lines.append(f"Output: {forced['label']} (forced)")
    if cfg.get("show_now_playing", False):
        lines.append(f"Video: {now_playing(DISPLAY_SOCKET)}")
    if cfg.get("show_audio_track", False):
        lines.append(f"Audio: {now_playing(AUDIO_SOCKET)}")
    if cfg.get("show_errors", True):
        if mode != "prot" and not cfg.get("show_mode", True):
            lines += mode_lines(mode)   # never hide a writable card
        for svc in ("vtg-display.service", "vtg-audio.service", "vtg-web.service"):
            if not service_active(svc):
                lines.append(f"ERROR: {svc} not running")
    return "\n".join(lines)

def main():
    while True:
        cfg = load_config()
        text = build_status_text(cfg) if cfg.get("enabled", True) else ""
        try:
            mpv = MpvIPC(DISPLAY_SOCKET, connect_timeout=1)
            mpv.set_property("osd-status-msg", text)
            mpv.close()
        except MpvIPCError:
            pass
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()