"""Display / EDID information from the kernel (no root needed).

Reads /sys/class/drm/card*-<connector>/ : status, modes, and the raw EDID
the display sent. Parses the parts an AV tech usually wants: maker, model
name, year, preferred mode, supported modes, HDMI audio support.
"""
import ctypes
import glob
import hashlib
import os
from pathlib import Path

CONNECTOR_FILE = Path("/tmp/vtg-display-connector")   # written by display_player.sh
MODE_FILE = Path(__file__).resolve().parent.parent / "state" / "display_mode"   # read by display_player.sh


def connector():
    try:
        return CONNECTOR_FILE.read_text().strip() or "HDMI-A-2"
    except OSError:
        return "HDMI-A-2"


def _drm_dir(conn):
    hits = glob.glob(f"/sys/class/drm/card*-{conn}")
    return Path(hits[0]) if hits else None


def _read(path, binary=False):
    try:
        return path.read_bytes() if binary else path.read_text().strip()
    except OSError:
        return b"" if binary else ""


def modes(conn=None):
    d = _drm_dir(conn or connector())
    seen, out = set(), []
    for m in _read(d / "modes").splitlines() if d else []:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


# ---- Full mode list with refresh rates -------------------------------------
# sysfs only lists "1920x1080" (no refresh rate). libdrm (installed with mpv)
# gives the same list, in the same order, with timings. The position in this
# list is what mpv's --drm-mode=<N> uses, so forcing by index is exact.

class _ModeInfo(ctypes.Structure):
    _fields_ = [("clock", ctypes.c_uint32),
                ("hdisplay", ctypes.c_uint16), ("hsync_start", ctypes.c_uint16),
                ("hsync_end", ctypes.c_uint16), ("htotal", ctypes.c_uint16), ("hskew", ctypes.c_uint16),
                ("vdisplay", ctypes.c_uint16), ("vsync_start", ctypes.c_uint16),
                ("vsync_end", ctypes.c_uint16), ("vtotal", ctypes.c_uint16), ("vscan", ctypes.c_uint16),
                ("vrefresh", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("name", ctypes.c_char * 32)]

class _Connector(ctypes.Structure):
    _fields_ = [("connector_id", ctypes.c_uint32), ("encoder_id", ctypes.c_uint32),
                ("connector_type", ctypes.c_uint32), ("connector_type_id", ctypes.c_uint32),
                ("connection", ctypes.c_int), ("mmWidth", ctypes.c_uint32), ("mmHeight", ctypes.c_uint32),
                ("subpixel", ctypes.c_int), ("count_modes", ctypes.c_int),
                ("modes", ctypes.POINTER(_ModeInfo)), ("count_props", ctypes.c_int),
                ("props", ctypes.c_void_p), ("prop_values", ctypes.c_void_p),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.c_void_p)]

class _Resources(ctypes.Structure):
    _fields_ = [("count_fbs", ctypes.c_int), ("fbs", ctypes.c_void_p),
                ("count_crtcs", ctypes.c_int), ("crtcs", ctypes.c_void_p),
                ("count_connectors", ctypes.c_int), ("connectors", ctypes.POINTER(ctypes.c_uint32)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.c_void_p),
                ("min_width", ctypes.c_uint32), ("max_width", ctypes.c_uint32),
                ("min_height", ctypes.c_uint32), ("max_height", ctypes.c_uint32)]

DRM_MODE_CONNECTOR_HDMIA = 11


def _hz(m):
    if not (m.clock and m.htotal and m.vtotal):
        return 0.0
    hz = m.clock * 1000.0 / (m.htotal * m.vtotal)
    if m.flags & (1 << 4):   # interlaced
        hz *= 2
    if m.flags & (1 << 5):   # double scan
        hz /= 2
    return hz


def _drm_modes(conn):
    """[(w, h, hz, interlaced, preferred)] from libdrm, or None if unavailable."""
    d = _drm_dir(conn)
    if not d:
        return None
    try:
        lib = ctypes.CDLL("libdrm.so.2")
        lib.drmModeGetResources.restype = ctypes.POINTER(_Resources)
        lib.drmModeGetConnectorCurrent.restype = ctypes.POINTER(_Connector)
        type_id = int(conn.rsplit("-", 1)[1])
        fd = os.open("/dev/dri/" + d.name.split("-", 1)[0], os.O_RDWR | os.O_CLOEXEC)
    except (OSError, AttributeError, ValueError, IndexError):
        return None
    try:
        res = lib.drmModeGetResources(fd)
        if not res:
            return None
        out = None
        try:
            for i in range(res.contents.count_connectors):
                # "Current" = cached list; no re-probe of the display
                c = lib.drmModeGetConnectorCurrent(fd, res.contents.connectors[i])
                if not c:
                    continue
                try:
                    cc = c.contents
                    if cc.connector_type == DRM_MODE_CONNECTOR_HDMIA and cc.connector_type_id == type_id:
                        out = [(m.hdisplay, m.vdisplay, _hz(m), bool(m.flags & (1 << 4)), bool(m.type & (1 << 3)))
                               for m in (cc.modes[j] for j in range(cc.count_modes))]
                finally:
                    lib.drmModeFreeConnector(c)
        finally:
            lib.drmModeFreeResources(res)
        return out
    finally:
        os.close(fd)


def mode_list(conn=None):
    """Every mode the display offers, in kernel order (index = mpv --drm-mode)."""
    conn = conn or connector()
    d = _drm_dir(conn)
    names = _read(d / "modes").splitlines() if d else []
    drm = _drm_modes(conn)
    out = []
    if drm and len(drm) == len(names):
        for i, (w, h, hz, il, pref) in enumerate(drm):
            out.append({"index": i, "label": f"{w}x{h}{'i' if il else ''}@{hz:.2f}", "preferred": pref})
    else:   # no libdrm: sizes only (still the right index)
        out = [{"index": i, "label": n, "preferred": i == 0} for i, n in enumerate(names)]
    return out


def edid_hash(conn=None):
    raw = edid_bytes(conn)
    return hashlib.sha1(raw).hexdigest() if raw else None


def saved_mode(conn=None):
    """The forced output mode, if one is saved AND it was picked for the display
    connected now (same EDID). Returns {"index", "label"} or None (= auto)."""
    try:
        idx, sha, label = MODE_FILE.read_text().split(None, 2)
        idx = int(idx)
    except (OSError, ValueError):
        return None
    if sha != edid_hash(conn):
        return None
    return {"index": idx, "label": label.strip()}


def size_of(label):
    try:
        w, h = label.split("@")[0].rstrip("i").split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None


def preferred_size(conn=None):
    """(w, h) the player will use: the forced mode if set, else the
    display's preferred mode, else None."""
    forced = saved_mode(conn)
    if forced and size_of(forced["label"]):
        return size_of(forced["label"])
    m = modes(conn)
    if m:
        try:
            w, h = m[0].rstrip("i").split("x")
            return int(w), int(h)
        except ValueError:
            pass
    return None


def edid_bytes(conn=None):
    d = _drm_dir(conn or connector())
    return _read(d / "edid", binary=True) if d else b""


def parse_edid(b):
    if len(b) < 128 or b[:8] != bytes([0, 255, 255, 255, 255, 255, 255, 0]):
        return None
    v = (b[8] << 8) | b[9]
    maker = "".join(chr(((v >> s) & 31) + 64) for s in (10, 5, 0))
    info = {"manufacturer": maker, "product_code": b[10] | (b[11] << 8),
            "year": b[17] + 1990, "edid_version": f"{b[18]}.{b[19]}",
            "name": None, "serial": None, "preferred": None, "hdmi_audio": False,
            "extensions": b[126]}
    for off in (54, 72, 90, 108):
        blk = b[off:off + 18]
        if blk[0] == 0 and blk[1] == 0:            # text descriptor
            raw = blk[5:18].split(b"\n")[0].decode("ascii", "ignore")
            text = "".join(c for c in raw if c.isprintable()).strip() or None
            if blk[3] == 0xFC:
                info["name"] = text
            elif blk[3] == 0xFF:
                info["serial"] = text
        elif off == 54:                             # first detailed timing = preferred
            clock = (blk[0] | (blk[1] << 8)) * 10_000
            hact = blk[2] | ((blk[4] & 0xF0) << 4)
            hblank = blk[3] | ((blk[4] & 0x0F) << 8)
            vact = blk[5] | ((blk[7] & 0xF0) << 4)
            vblank = blk[6] | ((blk[7] & 0x0F) << 8)
            if clock and hact and vact:
                hz = clock / ((hact + hblank) * (vact + vblank))
                info["preferred"] = f"{hact}x{vact}{'i' if blk[17] & 0x80 else ''}@{hz:.2f}"
    for ext in range(info["extensions"]):          # CTA-861 extension: audio flag
        blk = b[128 * (ext + 1):128 * (ext + 2)]
        if len(blk) == 128 and blk[0] == 0x02:
            info["hdmi_audio"] = bool(blk[3] & 0x40)
    return info


def info(conn=None):
    conn = conn or connector()
    d = _drm_dir(conn)
    raw = edid_bytes(conn)
    return {
        "connector": conn,
        "status": _read(d / "status") if d else "unknown",
        "modes": modes(conn),
        "edid_size": len(raw),
        "edid": parse_edid(raw),
    }


def native_label(i=None):
    """Display's preferred (native) mode for the OSD, e.g. '3840x2160@60.00'."""
    i = i or info()
    e = i["edid"]
    return (e and e["preferred"]) or (i["modes"][0] if i["modes"] else "unknown")


def short_label(i=None):
    """One short line for the OSD, e.g. 'SAM QN65Q80 (2021)'."""
    i = i or info()
    e = i["edid"]
    if not e:
        return "no EDID" if i["status"] == "connected" else "not connected"
    name = (e["name"] or f"product {e['product_code']}")[:16]
    return f"{e['manufacturer']} {name} ({e['year']})"
