#!/usr/bin/env python3
"""Minimal test web UI — talks to the persistent mpv instances over IPC."""
from pathlib import Path
import json
from flask import Flask, jsonify, request, send_from_directory
from mpv_ipc import MpvIPC, MpvIPCError
import subprocess
from cec_control import power_on as cec_power_on_fn, power_off as cec_power_off_fn, custom as cec_custom_fn, CEC_DEVICES

def get_ip(iface):
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", iface], text=True)
        return out.split()[3].split("/")[0]
    except Exception:
        return None

def service_active(name):
    r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
    return r.stdout.strip() == "active"

MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"
SOCKETS = {"video": "/tmp/vtg-display.sock", "audio": "/tmp/vtg-audio.sock", "image": "/tmp/vtg-display.sock"}
MEDIA_FOLDERS = {"video": MEDIA_DIR / "video", "audio": MEDIA_DIR / "audio"}
IMAGE_FOLDERS = {
    "1080p": MEDIA_DIR / "images_1080p",
    "4k": MEDIA_DIR / "images_4k",
}

app = Flask(__name__, static_folder=str(Path(__file__).resolve().parent / "static"))

def get_mpv(target):
    if target not in SOCKETS:
        raise ValueError(f"Unknown target: {target}")
    return MpvIPC(SOCKETS[target])

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
    if target == "image":
        folder = IMAGE_FOLDERS.get(request.args.get("resolution", "1080p"))
    else:
        folder = MEDIA_FOLDERS.get(target)
    files = sorted(f.name for f in folder.iterdir() if f.is_file()) if folder and folder.exists() else []
    return jsonify({"success": True, "files": files})

@app.route("/api/load/<target>", methods=["POST"])
def load(target):
    data = request.json or {}
    mode = data.get("mode", "folder")
    folder = IMAGE_FOLDERS.get(data.get("resolution", "1080p")) if target == "image" else MEDIA_FOLDERS.get(target)
    if not folder:
        return jsonify({"success": False, "message": "Unknown target/resolution"}), 400
    try:
        mpv = get_mpv(target)
        if mode == "single":
            filename = data.get("filename")
            if not filename:
                mpv.close()
                return jsonify({"success": False, "message": "No filename given"}), 400
            mpv.loadfile(str(folder / filename))
            mpv.close()
            return jsonify({"success": True})
        files = sorted(f for f in folder.iterdir() if f.is_file())
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
OSD_DEFAULTS = {"enabled": True, "show_ip": True, "show_web_url": True, "show_errors": True, "show_ssid": True, "show_datetime": True, "show_now_playing": True, "show_audio_track": True, "custom_message": ""}

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
    return jsonify({"success": True})

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
        return jsonify({"success": True, "width": w, "height": h, "fps": fps, "output": "HDMI-A-2 (auto-selected)"})
    except MpvIPCError as e:
        return jsonify({"success": False, "message": str(e)}), 503

@app.route("/api/system/reboot", methods=["POST"])
def system_reboot():
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
    try:
        subprocess.run(["sudo", "/usr/bin/systemctl", "restart", unit], check=True, capture_output=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": e.stderr.decode() if e.stderr else str(e)}), 500

@app.route("/api/system/wifi-check", methods=["POST"])
def wifi_check_now():
    try:
        subprocess.run(["/bin/bash", "/home/vtg/vtg_gen2/services/wifi_fallback.sh"], timeout=45)
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

@app.route("/api/cec/<device>/volume_up", methods=["POST"])
def cec_volume_up(device):
    return jsonify({"success": False, "message": "Not yet validated — try the custom command box first."})

@app.route("/api/cec/<device>/volume_down", methods=["POST"])
def cec_volume_down(device):
    return jsonify({"success": False, "message": "Not yet validated — try the custom command box first."})

@app.route("/api/cec/<device>/mute", methods=["POST"])
def cec_mute(device):
    return jsonify({"success": False, "message": "Not yet validated — try the custom command box first."})

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