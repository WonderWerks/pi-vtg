#!/usr/bin/env python3
"""Minimal test web UI — talks to the persistent mpv instances over IPC."""
from pathlib import Path
import json
import time
from flask import Flask, jsonify, request, send_from_directory
from mpv_ipc import MpvIPC, MpvIPCError
import subprocess
from cec_control import power_on as cec_power_on_fn, power_off as cec_power_off_fn, custom as cec_custom_fn, CEC_DEVICES
import system_mode

def get_ip(iface):
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", iface], text=True, timeout=5)
        return out.split()[3].split("/")[0]
    except Exception:
        return None

def service_active(name):
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
SOCKETS = {"video": "/tmp/vtg-display.sock", "audio": "/tmp/vtg-audio.sock", "image": "/tmp/vtg-display.sock"}
MEDIA_FOLDERS = {"video": MEDIA_DIR / "video", "audio": MEDIA_DIR / "audio", "image": MEDIA_DIR / "images"}

# Only these are listed or played; stray files (Thumbs.db, ._ files) are ignored.
# Keep in sync with VIDEO_EXT / AUDIO_EXT in display_player.sh / audio_player.sh.
MEDIA_EXT = {
    "video": {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg", ".webm", ".wmv"},
    "audio": {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aif", ".aiff"},
    "image": {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"},
}

def media_files(folder, target):
    if not folder or not folder.is_dir():
        return []
    exts = MEDIA_EXT.get(target, set())
    return sorted(f for f in folder.iterdir()
                  if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in exts)

app = Flask(__name__, static_folder=str(Path(__file__).resolve().parent / "static"))

WEB_ACTIVITY = Path("/tmp/vtg-web-activity")

@app.before_request
def note_activity():
    """Any web UI action (not the background status polling) counts as
    activity for the maintenance-mode idle timeout (maint_timeout.sh)."""
    if request.method == "POST":
        try:
            WEB_ACTIVITY.write_text(str(int(system_mode.uptime())))
        except OSError:
            pass

def get_mpv(target):
    if target not in SOCKETS:
        raise MpvIPCError(f"Unknown target: {target}")
    # Short timeout: if a player is restarting, fail fast instead of
    # tying up the web server while the UI keeps polling.
    return MpvIPC(SOCKETS[target], connect_timeout=2)

CMD_MARKER = Path("/tmp/vtg-last-cmd")

def mark_command(desc):
    """Note what the web UI just did, so play_logger.py can say why a file stopped."""
    try:
        CMD_MARKER.write_text(json.dumps({"t": time.time(), "cmd": f"web UI: {desc}"}))
    except OSError:
        pass

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/status/<target>")
def status(target):
    try:
        mpv = get_mpv(target)
        data = mpv.status()
        mpv.close()
        return jsonify({"success": True, "status": data})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/media/<target>")
def list_media(target):
    folder = MEDIA_FOLDERS.get(target)
    return jsonify({"success": True, "files": [f.name for f in media_files(folder, target)]})

@app.route("/api/load/<target>", methods=["POST"])
def load(target):
    data = request.json or {}
    mode = data.get("mode", "folder")
    folder = MEDIA_FOLDERS.get(target)
    if not folder:
        return jsonify({"success": False, "message": "Unknown target"}), 400
    if target != "audio":
        mark_command(f"play {target} {'file ' + str(data.get('filename')) if mode == 'single' else 'folder'}")
    try:
        mpv = get_mpv(target)
        files = media_files(folder, target)
        if mode == "single":
            # Must be a file actually in the folder (blocks ../ paths and junk)
            match = [f for f in files if f.name == data.get("filename")]
            if not match:
                mpv.close()
                return jsonify({"success": False, "message": "File not found in media folder"}), 400
            mpv.loadfile(str(match[0]))
            mpv.close()
            return jsonify({"success": True})
        if not files:
            mpv.close()
            return jsonify({"success": False, "message": "No media files in folder"}), 400
        mpv.load_playlist([str(f) for f in files])
        mpv.close()
        return jsonify({"success": True, "count": len(files)})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/control/<target>/<action>", methods=["POST"])
def control(target, action):
    actions = {"play": "play", "pause": "pause", "toggle": "toggle_pause",
               "stop": "stop", "next": "next", "prev": "prev"}
    if action not in actions:
        return jsonify({"success": False, "message": f"Unknown action: {action}"}), 400
    if target != "audio":
        mark_command(f"{action} button ({target})")
    try:
        mpv = get_mpv(target)
        getattr(mpv, actions[action])()
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/speed/image", methods=["POST"])
def set_image_speed():
    try:
        seconds = float((request.json or {}).get("seconds"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid seconds value"}), 400
    try:
        mpv = get_mpv("image")
        mpv.set_property("image-display-duration", seconds)
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

STATE_DIR = MEDIA_DIR.parent / "state"
OSD_CONFIG_PATH = STATE_DIR / "osd_config.json"
OSD_DEFAULTS = {"enabled": True, "show_ip": True, "show_web_url": True, "show_errors": True, "show_ssid": True, "show_datetime": False, "show_now_playing": False, "show_audio_track": False, "show_mode": True, "custom_message": ""}

@app.route("/api/osd/config", methods=["GET"])
def get_osd_config():
    try:
        with open(OSD_CONFIG_PATH) as f:
            cfg = {**OSD_DEFAULTS, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = dict(OSD_DEFAULTS)
    return jsonify({"success": True, "config": cfg})

@app.route("/api/osd/config", methods=["POST"])
def set_osd_config():
    STATE_DIR.mkdir(exist_ok=True)
    cfg = {**OSD_DEFAULTS, **(request.json or {})}
    cfg["custom_message"] = (cfg.get("custom_message") or "")[:80]
    with open(OSD_CONFIG_PATH, "w") as f:
        json.dump(cfg, f)
    ok, msg = persist(OSD_CONFIG_PATH)
    if not ok:
        return jsonify({"success": False, "message": f"Applied, but not saved for next boot: {msg}"}), 500
    return jsonify({"success": True})

MODE_SCRIPT = BASE_DIR / "services" / "vtg_mode.sh"

def persist(*paths):
    """Write these files through to the SD card (needed in protected mode,
    where normal writes only go to RAM)."""
    try:
        r = subprocess.run(["sudo", "/usr/bin/bash", str(MODE_SCRIPT), "persist", *map(str, paths)],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stderr or r.stdout).strip()[-200:]
    except Exception as e:
        return False, str(e)

@app.route("/api/system/time", methods=["GET"])
def get_time():
    return jsonify({"success": True, "epoch": time.time(), "local": time.strftime("%Y-%m-%d %H:%M:%S %Z")})

@app.route("/api/system/time", methods=["POST"])
def set_time():
    """Set the Pi's clock from the browser (handy offline: no RTC, no NTP)."""
    try:
        epoch = int((request.json or {}).get("epoch"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid time"}), 400
    try:
        r = subprocess.run(["sudo", "/usr/bin/bash", str(MODE_SCRIPT), "settime", str(epoch)],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return jsonify({"success": False, "message": r.stderr.strip()[-200:]}), 500
        return jsonify({"success": True, "local": time.strftime("%Y-%m-%d %H:%M:%S %Z")})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/system/mode")
def get_mode():
    return jsonify({"success": True, **system_mode.status()})

@app.route("/api/system/mode/<mode>", methods=["POST"])
def set_mode(mode):
    if mode not in ("protect", "maintenance", "debug"):
        return jsonify({"success": False, "message": "Unknown mode"}), 400
    mark_command(f"switch to {mode} mode (reboot)")
    try:
        # Runs in the background: enabling protection can take a minute, then reboots
        subprocess.Popen(["sudo", "/usr/bin/bash", str(MODE_SCRIPT), mode])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/network")
def network_info():
    return jsonify({
        "success": True,
        "eth0": get_ip("eth0"),
        "wlan0": get_ip("wlan0"),
    })

@app.route("/api/volume/<target>", methods=["POST"])
def set_volume(target):
    try:
        level = int((request.json or {}).get("level"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid level"}), 400
    try:
        mpv = get_mpv(target)
        mpv.set_volume(level)
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/mute/<target>", methods=["POST"])
def set_mute(target):
    muted = bool((request.json or {}).get("muted"))
    try:
        mpv = get_mpv(target)
        mpv.set_mute(muted)
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/loop/<target>", methods=["POST"])
def set_loop(target):
    data = request.json or {}
    loop_type = data.get("type")
    enabled = bool(data.get("enabled"))
    if loop_type not in ("playlist", "file"):
        return jsonify({"success": False, "message": "Invalid loop type"}), 400
    prop_name = "loop-playlist" if loop_type == "playlist" else "loop-file"
    value = "inf" if enabled else "no"
    try:
        mpv = get_mpv(target)
        mpv.set_property(prop_name, value)
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

SYSTEM_SERVICES = ["vtg-display.service", "vtg-audio.service", "vtg-osd.service", "vtg-wifi-fallback.timer"]

@app.route("/api/errors")
def get_errors():
    errors = [f"{svc} not running" for svc in SYSTEM_SERVICES if not service_active(svc)]
    return jsonify({"success": True, "errors": errors})

@app.route("/api/display/info")
def display_info():
    try:
        mpv = get_mpv("video")
        w = mpv.get_property("display-width")
        h = mpv.get_property("display-height")
        fps = mpv.get_property("display-fps")
        mpv.close()
        try:
            output = Path("/tmp/vtg-display-connector").read_text().strip() + " (auto-selected)"
        except OSError:
            output = "unknown"
        return jsonify({"success": True, "width": w, "height": h, "fps": fps, "output": output})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/system/reboot", methods=["POST"])
def system_reboot():
    mark_command("reboot")
    try:
        subprocess.Popen(["sudo", "/usr/sbin/reboot"])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/system/restart/<service>", methods=["POST"])
def restart_service(service):
    allowed = {"display": "vtg-display.service", "audio": "vtg-audio.service"}
    unit = allowed.get(service)
    if not unit:
        return jsonify({"success": False, "message": "Unknown service"}), 400
    if service == "display":
        mark_command("restart display player")
    try:
        subprocess.run(["sudo", "/usr/bin/systemctl", "restart", unit], check=True, capture_output=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": e.stderr.decode() if e.stderr else str(e)}), 500

@app.route("/api/system/wifi-check", methods=["POST"])
def wifi_check_now():
    try:
        r = subprocess.run(["/bin/bash", str(BASE_DIR / "services" / "wifi_fallback.sh")],
                           capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            return jsonify({"success": False, "message": (r.stderr or "wifi check failed")[-200:]}), 500
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ---- Alignment patterns --------------------------------------------------
@app.route("/api/patterns")
def list_patterns():
    import patterns
    return jsonify({"success": True,
                    "patterns": [{"id": k, "label": l} for k, l in patterns.PATTERNS],
                    "aspects": [{"id": k, "label": l} for k, l, _ in patterns.ASPECTS]})

@app.route("/api/pattern", methods=["POST"])
def show_pattern():
    data = request.json or {}
    try:
        import patterns
    except ImportError:
        return jsonify({"success": False, "message": "Pattern support needs python3-pil (sudo apt install python3-pil)"}), 500
    try:
        mpv = get_mpv("image")
        # Draw at the display's real resolution so lines land on real pixels
        w = mpv.get_property("display-width") or 1920
        h = mpv.get_property("display-height") or 1080
        path = patterns.make(data.get("pattern", "grid"), data.get("aspect", "full"), w, h)
        # Per-file options: hold the image until replaced; optionally hide
        # the OSD text so it doesn't sit on top of the pattern.
        opts = "image-display-duration=inf" + (",osd-level=0" if data.get("hide_osd", True) else "")
        mark_command("show alignment pattern")
        try:
            mpv.command("loadfile", str(path), "replace", -1, opts)   # mpv 0.38+
        except MpvIPCError:
            mpv.command("loadfile", str(path), "replace", opts)       # older mpv
        mpv.close()
        return jsonify({"success": True, "size": f"{w}x{h}"})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except (MpvIPCError, OSError) as e:
        return jsonify({"success": False, "message": str(e)}), 503

# ---- Wifi ----------------------------------------------------------------
WIFI_SCRIPT = BASE_DIR / "services" / "wifi_ctl.sh"
WIFI_RESULT = Path("/tmp/vtg-wifi-result")

def nm_split(line):
    """Split one line of `nmcli -t` output on unescaped colons."""
    parts, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch; esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts

def nmcli(*args):
    try:
        return subprocess.run(["nmcli", "-t", *args], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""

def fallback_ssid():
    try:
        for line in (BASE_DIR / "secrets.env").read_text().splitlines():
            if line.startswith("FALLBACK_SSID="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None

def wifi_script(*args, stdin=None, timeout=30):
    r = subprocess.run(["sudo", "/usr/bin/bash", str(WIFI_SCRIPT), *args], input=stdin,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr).strip()

@app.route("/api/wifi")
def wifi_status():
    hotspot = fallback_ssid()
    active = None
    for line in nmcli("-f", "NAME,DEVICE", "connection", "show", "--active").splitlines():
        p = nm_split(line)
        if len(p) == 2 and p[1] == "wlan0":
            active = p[0]
    saved = [p[0] for p in map(nm_split, nmcli("-f", "NAME,TYPE", "connection", "show").splitlines())
             if len(p) == 2 and p[1] == "802-11-wireless" and p[0] != hotspot]
    last = None
    try:
        ts, msg = WIFI_RESULT.read_text().strip().split(" ", 1)
        last = {"age": int(time.time() - int(ts)), "message": msg}
    except (OSError, ValueError):
        pass
    return jsonify({"success": True, "active": active, "is_hotspot": active is not None and active == hotspot,
                    "hotspot": hotspot, "ip": get_ip("wlan0"), "saved": sorted(saved), "last_result": last})

@app.route("/api/wifi/scan")
def wifi_scan():
    try:
        ok, out = wifi_script("scan", timeout=25)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    best = {}
    for line in out.splitlines():
        p = nm_split(line)
        if len(p) < 3 or not p[0]:
            continue  # hidden networks have no name
        try:
            signal = int(p[1])
        except ValueError:
            signal = 0
        if p[0] not in best or signal > best[p[0]]["signal"]:
            best[p[0]] = {"ssid": p[0], "signal": signal, "secure": p[2] not in ("", "--")}
    nets = sorted(best.values(), key=lambda n: -n["signal"])
    return jsonify({"success": True, "networks": nets})

@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.json or {}
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    if not ssid or len(ssid) > 32:
        return jsonify({"success": False, "message": "Enter a network name (max 32 characters)"}), 400
    if password and not 8 <= len(password) <= 63:
        return jsonify({"success": False, "message": "Wifi passwords are 8 to 63 characters"}), 400
    args = ["connect", ssid] + (["hidden"] if data.get("hidden") else [])
    try:
        # Background: switching networks drops this very connection if
        # you're on the hotspot. Password goes via stdin, not the command
        # line, so it never lands in the sudo log.
        p = subprocess.Popen(["sudo", "/usr/bin/bash", str(WIFI_SCRIPT), *args],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(password + "\n")
        p.stdin.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/wifi/forget", methods=["POST"])
def wifi_forget():
    name = (request.json or {}).get("name") or ""
    try:
        ok, msg = wifi_script("forget", name)
    except Exception as e:
        ok, msg = False, str(e)
    return jsonify({"success": ok, "message": msg}), (200 if ok else 400)

@app.route("/api/wifi/hotspot", methods=["POST"])
def wifi_hotspot():
    try:
        subprocess.Popen(["sudo", "/usr/bin/bash", str(WIFI_SCRIPT), "hotspot"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

def cec_devices_for(device):
    if device == "both":
        return list(CEC_DEVICES.keys())
    if device in CEC_DEVICES:
        return [device]
    return []

def cec_aggregate(device, fn):
    devices = cec_devices_for(device)
    if not devices:
        return jsonify({"success": False, "message": "Unknown device"}), 400
    results = {d: fn(d) for d in devices}
    ok = all(r[0] for r in results.values())
    message = "OK" if ok else "; ".join(f"{d}: {r[1][-150:]}" for d, r in results.items() if not r[0])
    return jsonify({"success": ok, "message": message})

@app.route("/api/cec/<device>/power_on", methods=["POST"])
def cec_power_on(device):
    return cec_aggregate(device, cec_power_on_fn)

@app.route("/api/cec/<device>/power_off", methods=["POST"])
def cec_power_off(device):
    return cec_aggregate(device, cec_power_off_fn)

@app.route("/api/cec/<device>/custom", methods=["POST"])
def cec_custom_route(device):
    command = (request.json or {}).get("command", "")
    if not command:
        return jsonify({"success": False, "message": "No command provided"}), 400
    return cec_aggregate(device, lambda d: cec_custom_fn(d, command))

MONO_FILTER = "@mono:lavfi=[pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1]"

@app.route("/api/mono/<target>", methods=["POST"])
def set_mono(target):
    enabled = bool((request.json or {}).get("enabled"))
    try:
        mpv = get_mpv(target)
        try:
            mpv.command("af", "remove", "@mono")
        except MpvIPCError:
            pass
        if enabled:
            mpv.command("af", "add", MONO_FILTER)
        mpv.close()
        return jsonify({"success": True})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)