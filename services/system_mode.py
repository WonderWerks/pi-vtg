"""Read-only checks of protected/maintenance mode (no root needed).
Switching modes and saving files is done by vtg_mode.sh (root, via sudo)."""
from pathlib import Path

CMDLINE = Path("/boot/firmware/cmdline.txt")
DEBUG_FLAG = Path("/boot/firmware/vtg-debug-once")


def protected_now():
    """True when / is the RAM overlay (SD card read-only)."""
    fstype = None
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) > 2 and parts[1] == "/":
                fstype = parts[2]   # last "/" entry wins (the active one)
    except OSError:
        pass
    return fstype == "overlay"


def protected_next_boot():
    try:
        words = CMDLINE.read_text().split()
        return "boot=overlay" in words or "overlayroot=tmpfs" in words
    except OSError:
        return False


def status():
    return {
        "protected_now": protected_now(),
        "protected_next_boot": protected_next_boot(),
        "debug_once": DEBUG_FLAG.exists(),
    }
