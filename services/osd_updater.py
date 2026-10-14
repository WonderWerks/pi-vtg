#!/usr/bin/env python3
"""Persistent OSD updater. Sets mpv's built-in status-message OSD line
on the display output. Controlled by state/osd_config.json."""
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from mpv_ipc import MpvIPC, MpvIPCError

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "state" / "osd_config.json"
SECRETS_PATH = BASE_DIR / "secrets.env"
DISPLAY_SOCKET = "/tmp/vtg-display.sock"
AUDIO_SOCKET = "/tmp/vtg-audio.sock"
PORT = 5000
POLL_SECONDS = 2
MAX_MESSAGE_LEN = 80
MAX_NAME_LEN = 40

DEFAULT_CONFIG = {
    "enabled": True,
    "show_datetime": True,
    "show_ip": True,
    "show_ssid": True,
    "show_web_url": True,
    "show_now_playing": True,
    "show_audio_track": True,
    "show_errors": True,
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
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", iface], text=True)
        return out.split()[3].split("/")[0]
    except Exception:
        return None

def get_wifi_ssid():
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], text=True
        )
        for line in out.strip().split("\n"):
            parts = line.split(":")
            if len(parts) == 2 and parts[1] == "wlan0":
                return parts[0]
    except Exception:
        pass
    return None

def service_active(name):
    r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
    return r.stdout.strip() == "active"

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

def build_status_text(cfg):
    custom = (cfg.get("custom_message") or "").strip()
    if custom:
        return custom[:MAX_MESSAGE_LEN]

    lines = []
    if cfg.get("show_datetime", True):
        lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    if cfg.get("show_ip", True):
        lines.append(f"eth0: {get_ip('eth0') or 'not connected'}")
        lines.append(f"wlan0: {get_ip('wlan0') or 'not connected'}")
    if cfg.get("show_ssid", True):
        ssid = get_wifi_ssid()
        fallback = get_fallback_ssid()
        if ssid and fallback and ssid == fallback:
            lines.append(f"SSID: {ssid} (FALLBACK HOTSPOT)")
        else:
            lines.append(f"SSID: {ssid or 'not connected'}")
    if cfg.get("show_web_url", True):
        lines.append(f"Web UI port: {PORT}")
    if cfg.get("show_now_playing", True):
        lines.append(f"Display: {now_playing(DISPLAY_SOCKET)}")
    if cfg.get("show_audio_track", True):
        lines.append(f"Audio: {now_playing(AUDIO_SOCKET)}")
    if cfg.get("show_errors", True):
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