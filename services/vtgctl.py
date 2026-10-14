#!/usr/bin/env python3
"""Manual test CLI for Phase 1. Usage:
    vtgctl.py video load <file>
    vtgctl.py video pause|play|stop|status
    vtgctl.py audio load <file>
    vtgctl.py audio volume <0-100>
"""
import sys
from mpv_ipc import MpvIPC

SOCKETS = {"video": "/tmp/vtg-display.sock", "audio": "/tmp/vtg-audio.sock"}

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    target, action, *rest = sys.argv[1:]
    mpv = MpvIPC(SOCKETS[target])

    if action == "load":
        mpv.loadfile(rest[0])
    elif action == "pause":
        mpv.pause()
    elif action == "play":
        mpv.play()
    elif action == "toggle":
        mpv.toggle_pause()
    elif action == "stop":
        mpv.stop()
    elif action == "volume":
        mpv.set_volume(rest[0])
    elif action == "mute":
        mpv.set_mute(rest[0].lower() in ("1", "true", "on", "yes"))
    elif action == "status":
        import json
        print(json.dumps(mpv.status(), indent=2))
    else:
        print(f"Unknown action: {action}")

    mpv.close()

if __name__ == "__main__":
    main()
