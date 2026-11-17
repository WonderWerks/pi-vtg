"""Wifi heartbeat: is the router on wlan0 actually answering?

NetworkManager can keep showing a network as connected for minutes after
the access point disappears (e.g. a phone hotspot switched off). A quick
ping of the wlan0 gateway catches that within one check. Results are
cached so the web UI and OSD polling cost at most one ping per CACHE_SECONDS.
"""
import subprocess
import time

CACHE_SECONDS = 15
_cache = {"t": 0.0, "ok": None}


def _gateway(iface):
    try:
        out = subprocess.run(["ip", "-4", "route", "show", "default", "dev", iface],
                             capture_output=True, text=True, timeout=3).stdout.split()
        return out[out.index("via") + 1]
    except (Exception, ValueError, IndexError):
        return None


def router_ok(iface="wlan0"):
    """True = router answers, False = no reply, None = no gateway to check."""
    now = time.monotonic()
    if now - _cache["t"] < CACHE_SECONDS:
        return _cache["ok"]
    gw = _gateway(iface)
    ok = None
    if gw:
        try:
            # 2 tries, 1 s each: a busy or lossy link still passes
            r = subprocess.run(["ping", "-n", "-q", "-c", "2", "-W", "1", "-I", iface, gw],
                               capture_output=True, timeout=5)
            ok = r.returncode == 0
        except Exception:
            ok = None
    _cache.update(t=now, ok=ok)
    return ok
