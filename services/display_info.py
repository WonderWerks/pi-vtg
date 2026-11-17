"""Display / EDID information from the kernel (no root needed).

Reads /sys/class/drm/card*-<connector>/ : status, modes, and the raw EDID
the display sent. Parses the parts an AV tech usually wants: maker, model
name, year, preferred mode, supported modes, HDMI audio support.
"""
import glob
from pathlib import Path

CONNECTOR_FILE = Path("/tmp/vtg-display-connector")   # written by display_player.sh


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


def preferred_size(conn=None):
    """(w, h) of the display's preferred mode, or None."""
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


def short_label(i=None):
    """One short line for the OSD, e.g. 'SAM QN65Q80 (2021)'."""
    i = i or info()
    e = i["edid"]
    if not e:
        return "no EDID" if i["status"] == "connected" else "not connected"
    name = (e["name"] or f"product {e['product_code']}")[:16]
    return f"{e['manufacturer']} {name} ({e['year']})"
