"""
mpv_ipc.py
Minimal JSON-IPC client for talking to a persistent mpv instance
over its --input-ipc-server unix socket. No external dependencies.

Used by every player/service in the VTG project so there's exactly
one place that knows how to talk to mpv.
"""

import json
import socket
import time


class MpvIPCError(Exception):
    pass


class MpvIPC:
    def __init__(self, socket_path, connect_timeout=10):
        self.socket_path = socket_path
        self._sock = None
        self._buffer = b""
        self._request_id = 0
        self._connect(connect_timeout)

    def _connect(self, timeout):
        """Retry connecting since mpv creates the socket asynchronously
        on startup -- it may not exist yet the instant we launch it."""
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.socket_path)
                sock.settimeout(2)
                self._sock = sock
                return
            except (FileNotFoundError, ConnectionRefusedError) as e:
                last_err = e
                time.sleep(0.25)
        raise MpvIPCError(
            f"Could not connect to mpv socket at {self.socket_path}: {last_err}"
        )

    def _send_raw(self, payload):
        self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def _read_line(self):
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise MpvIPCError("mpv socket closed unexpectedly")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line

    def command(self, *args):
        """Send an mpv command and return its data field.
        Example: command("set_property", "pause", True)
        """
        self._request_id += 1
        req_id = self._request_id
        self._send_raw({"command": list(args), "request_id": req_id})

        # mpv interleaves event notifications with command replies on
        # the same socket -- skip events until we see our reply.
        for _ in range(50):
            line = self._read_line()
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("request_id") == req_id:
                if resp.get("error") != "success":
                    raise MpvIPCError(f"mpv error: {resp.get('error')}")
                return resp.get("data")
        raise MpvIPCError("No reply from mpv within expected number of reads")

    def get_property(self, name):
        return self.command("get_property", name)

    def set_property(self, name, value):
        return self.command("set_property", name, value)

    def loadfile(self, path, mode="replace"):
        return self.command("loadfile", path, mode)

    def load_playlist(self, paths):
        if not paths:
            raise MpvIPCError("No files to load")
        self.loadfile(paths[0], "replace")
        for p in paths[1:]:
            self.loadfile(p, "append")

    def play(self):
        self.set_property("pause", False)

    def pause(self):
        self.set_property("pause", True)

    def toggle_pause(self):
        current = self.get_property("pause")
        self.set_property("pause", not current)

    def stop(self):
        self.command("stop")

    def next(self):
        self.command("playlist-next")

    def prev(self):
        self.command("playlist-prev")

    def set_volume(self, level):
        level = max(0, min(100, int(level)))
        self.set_property("volume", level)

    def set_mute(self, muted):
        self.set_property("mute", bool(muted))

    def status(self):
        """Best-effort status snapshot. Missing properties (e.g. no file
        loaded yet) are reported as None rather than raising."""
        result = {}
        for prop in (
            "pause",
            "volume",
            "mute",
            "filename",
            "path",
            "duration",
            "time-pos",
            "playlist-pos",
            "playlist-count",
            "core-idle",
            "loop-playlist",
            "loop-file",
            "display-width",
            "display-height",
            "display-fps",
            "image-display-duration",
        ):
            try:
                result[prop] = self.get_property(prop)
            except MpvIPCError:
                result[prop] = None
        return result

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None