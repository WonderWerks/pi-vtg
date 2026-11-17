"""Read-only checks of protected/maintenance/debug mode (no root needed).
Switching modes and saving files is done by vtg_mode.sh (root, via sudo)."""
from pathlib import Path

CMDLINE = Path("/boot/firmware/cmdline.txt")
DEBUG_FLAG = Path("/boot/firmware/vtg-debug-once")    # debug requested for next boot
DEBUG_BOOT = Path("/run/vtg-debug-boot")              # this boot is the debug boot
MAINT_DEADLINE = Path("/run/vtg-maint-deadline")      # uptime seconds; maint_timeout.sh


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


def current_mode():
    """'prot', 'debug' or 'maint'."""
    if protected_now():
        return "prot"
    return "debug" if DEBUG_BOOT.exists() else "maint"


def uptime():
    return float(Path("/proc/uptime").read_text().split()[0])


def maint_seconds_left():
    """Seconds until maintenance mode auto-protects, or None if not counting."""
    try:
        return max(0.0, float(MAINT_DEADLINE.read_text()) - uptime())
    except (OSError, ValueError):
        return None


def status():
    return {
        "mode": current_mode(),
        "protected_now": protected_now(),
        "protected_next_boot": protected_next_boot(),
        "debug_once": DEBUG_FLAG.exists(),
        "maint_seconds_left": maint_seconds_left(),
    }
