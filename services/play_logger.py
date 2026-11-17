#!/usr/bin/env python3
"""Persistent play log for the display player (HDMI video + images).

Writes one line per event to state/playlog.log: what started, how long it
ran, and why it ended (finished, early end, web UI command, error, player
shutdown/crash, power loss). Also logs HDMI connect/disconnect.

Size is capped: 2 MB per file, 3 old copies kept (8 MB max).
"""
import glob
import json
import logging
import os
import signal
import socket
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from mpv_ipc import MpvIPC, MpvIPCError
import system_mode

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
LOG_PATH = STATE_DIR / "playlog.log"
CHECKPOINT_PATH = STATE_DIR / "playlog.current"  # last known file/position
CMD_MARKER = Path("/tmp/vtg-last-cmd")            # written by web_api.py
SOCKET = "/tmp/vtg-display.sock"

MAX_BYTES = 2_000_000
BACKUPS = 3
POLL_SECONDS = 2
CHECKPOINT_SECONDS = 30   # how often to save position (for power-loss reports)
MARKER_WINDOW = 10        # a web command this recent explains a stop
EARLY_MARGIN = 5          # ending more than this many seconds short = early
CLEAN_STOP = "LOGGER  stopped cleanly"


def setup_log():
    STATE_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUPS)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log = logging.getLogger("playlog")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    return log


def fmt(t):
    if t is None:
        return "?"
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 4096))
            lines = f.read().splitlines()
        return lines[-1].decode(errors="replace") if lines else ""
    except OSError:
        return None


def hdmi_status():
    out = {}
    for f in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status")):
        try:
            out[f.split("/")[-2].split("-", 1)[1]] = Path(f).read_text().strip()
        except OSError:
            pass
    return out


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def is_image(name):
    return bool(name) and os.path.splitext(name)[1].lower() in IMAGE_EXT


def recent_command():
    """Web UI command issued in the last few seconds, if any."""
    try:
        data = json.loads(CMD_MARKER.read_text())
        if time.time() - data["t"] <= MARKER_WINDOW:
            return data["cmd"]
    except (OSError, ValueError, KeyError):
        pass
    return None


class Tracker:
    def __init__(self, log):
        self.log = log
        self.file = None
        self.dur = None
        self.pos = None
        self.started = None
        self.hdmi = hdmi_status()
        self.connected = False
        self.pending_play = False
        self.next_checkpoint = 0
        self.repeat_key = None   # collapse repeated identical failures
        self.repeat_count = 0

    def out(self, msg):
        if self.repeat_count:
            self.log.info(f"        (previous failure repeated {self.repeat_count} more times)")
        self.repeat_key, self.repeat_count = None, 0
        self.log.info(msg)

    def summary(self):
        ran = fmt(time.monotonic() - self.started) if self.started else "?"
        return f"{self.file}  ran {ran}, pos {fmt(self.pos)} / {fmt(self.dur)}"

    def pick_up_current(self, poll):
        """Logger (re)connected while something may already be playing."""
        try:
            name = poll.get_property("filename")
        except MpvIPCError:
            name = None
        if name:
            self.file = name
            try:
                self.dur = poll.get_property("duration")
                self.pos = poll.get_property("time-pos")
            except MpvIPCError:
                pass
            self.started = time.monotonic() - (self.pos or 0)
            # Logged on the next poll; if the file is still loading, its
            # file-loaded event lands first and this becomes one line.
            self.pending_play = not is_image(name)

    def handle(self, ev, poll):
        kind = ev.get("event")
        if kind == "start-file":
            try:
                self.file = os.path.basename(poll.get_property("path") or "") or None
            except MpvIPCError:
                self.file = None
            self.dur, self.pos, self.started = None, None, time.monotonic()
        elif kind == "file-loaded":
            try:
                self.file = poll.get_property("filename") or self.file
                self.dur = poll.get_property("duration")
            except MpvIPCError:
                pass
            # Logged on the next poll, not now: files that fail instantly
            # (no display) then produce only one collapsible FAILED line.
            self.pending_play = not is_image(self.file)
        elif kind == "end-file":
            self.end(ev.get("reason"), ev.get("file_error"))

    def end(self, reason, file_error):
        self.pending_play = False
        cmd = recent_command()
        if reason == "eof" and is_image(self.file):
            return  # slideshow advancing normally; don't flood the log
        if reason == "eof":
            if self.pos is not None and self.dur and self.dur - self.pos > EARLY_MARGIN:
                why = "EARLY END: stopped short of the end (read/decode error in the file)"
            else:
                why = "finished (reached end of file)"
        elif reason == "stop":
            why = f"stopped by command: {cmd or 'not from the web UI (vtgctl or other IPC client)'}"
        elif reason == "quit":
            why = f"player shut down ({cmd or 'service stop/restart or reboot'})"
        elif reason == "error":
            key = file_error
            if key == self.repeat_key:
                self.repeat_count += 1
                return
            why = f"FAILED: {file_error or 'unknown error'} (no display connected, or unplayable file)"
            self.out(f"END     {self.summary()}  -> {why}")
            self.repeat_key = key
            return
        else:
            why = reason or "unknown"
        self.out(f"END     {self.summary()}  -> {why}")
        self.file, self.pos, self.dur, self.started = None, None, None, None

    def poll(self, poll):
        try:
            p = poll.get_property("time-pos")
            if p is not None:
                self.pos = p
        except MpvIPCError:
            pass
        if self.pending_play:
            self.pending_play = False
            self.out(f"PLAYING {self.file}  (length {fmt(self.dur)})")
        now = hdmi_status()
        if now != self.hdmi:
            playing = f"  (playing {self.file} at {fmt(self.pos)})" if self.file else ""
            self.out(f"HDMI    {self.hdmi} -> {now}{playing}")
            self.hdmi = now
        if time.monotonic() >= self.next_checkpoint:
            self.next_checkpoint = time.monotonic() + CHECKPOINT_SECONDS
            self.checkpoint()

    def checkpoint(self):
        tmp = CHECKPOINT_PATH.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"file": self.file, "pos": self.pos, "dur": self.dur}))
            os.replace(tmp, CHECKPOINT_PATH)
        except OSError:
            pass


def session(t):
    events = MpvIPC(SOCKET, connect_timeout=5)
    poll = MpvIPC(SOCKET, connect_timeout=5)
    try:
        events._sock.settimeout(POLL_SECONDS)
        t.connected = True
        t.out("PLAYER  connected")
        t.pick_up_current(poll)
        next_poll = 0
        while True:
            try:
                ev = json.loads(events._read_line(raw_timeout=True))
            except socket.timeout:
                ev = None
            except ValueError:
                ev = None
            if ev:
                t.handle(ev, poll)
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + POLL_SECONDS
                t.poll(poll)
    finally:
        events.close()
        poll.close()


def main():
    log = setup_log()
    prev = last_line(LOG_PATH)
    protected = system_mode.protected_now()
    log.info("LOGGER  started" + ("  (read-only mode: this boot's log is in RAM and is lost at power-off;"
                                  " use Debug mode to keep it)" if protected else "  (writable: log is kept)"))
    # Power-loss detection only on writable boots: in protected mode the
    # card holds a stale log from the last writable session.
    if not protected and prev and CLEAN_STOP not in prev:
        try:
            c = json.loads(CHECKPOINT_PATH.read_text())
            detail = f"; last saved: {c.get('file')} at {fmt(c.get('pos'))} / {fmt(c.get('dur'))}"
        except (OSError, ValueError):
            detail = ""
        log.info(f"POWER   previous session did not shut down cleanly (power loss or crash){detail}")

    def on_sigterm(*_):
        raise SystemExit
    signal.signal(signal.SIGTERM, on_sigterm)

    t = Tracker(log)
    try:
        while True:
            try:
                session(t)
            except (MpvIPCError, OSError):
                if t.connected:  # had a live connection and lost it
                    cause = recent_command() or "player restarted (HDMI change, crash, or service restart)"
                    playing = f" while playing {t.summary()}" if t.file else ""
                    t.out(f"LOST    player connection{playing}  -> {cause}")
                    t.file, t.pos, t.dur, t.started = None, None, None, None
                t.connected = False
            time.sleep(3)
            now = hdmi_status()  # still track HDMI while the player is down
            if now != t.hdmi:
                t.out(f"HDMI    {t.hdmi} -> {now}  (player not running)")
                t.hdmi = now
    finally:
        t.checkpoint()
        log.info(CLEAN_STOP)


if __name__ == "__main__":
    main()
