"""Built-in audio test signals for the 3.5mm player.

Generated live by mpv through ffmpeg's lavfi sources (av://lavfi:...), so
nothing is stored on the card and they play until stopped. Tones peak at
-20 dBFS; white noise is -20 dBFS RMS; set levels at the console.
"""

A = "0.1"   # -20 dBFS peak for sine tones


def _tone(hz):
    return f"{A}*sin(2*PI*{hz}*t)"


# Sweep 20 Hz -> 20 kHz (log) over 20 s, repeating. t-20*floor(t/20) restarts
# the sweep every 20 s without commas (which lavfi would treat as a separator).
_SWEEP = f"{A}*sin(2*PI*400/log(1000)*(exp((t-20*floor(t/20))*log(1000)/20)-1))"

# (id, label, lavfi graph). Everything is true stereo ("left|right"), so a
# tone is exactly -20 dBFS on each channel (mpv would lower a mono source
# by 3 dB when spreading it over two channels). Noise: same noise on both.
SIGNALS = [
    ("pink", "Pink noise", "anoisesrc=color=pink:amplitude=0.25,pan=stereo|c0=c0|c1=c0"),
    ("white", "White noise (-20 dBFS RMS)", "anoisesrc=color=white:amplitude=0.1732,pan=stereo|c0=c0|c1=c0"),
    ("1k", "1 kHz tone (-20 dBFS)", f"aevalsrc={_tone(1000)}|{_tone(1000)}:s=48000"),
    ("100", "100 Hz tone (-20 dBFS)", f"aevalsrc={_tone(100)}|{_tone(100)}:s=48000"),
    ("10k", "10 kHz tone (-20 dBFS)", f"aevalsrc={_tone(10000)}|{_tone(10000)}:s=48000"),
    ("left", "Left only: 1 kHz", f"aevalsrc={_tone(1000)}|0:s=48000"),
    ("right", "Right only: 1 kHz", f"aevalsrc=0|{_tone(1000)}:s=48000"),
    ("sweep", "Sweep 20 Hz to 20 kHz (20 s, repeats)", f"aevalsrc={_SWEEP}|{_SWEEP}:s=48000"),
]


def get(signal_id):
    """(label, mpv URL) for a signal id, or None."""
    for sid, label, graph in SIGNALS:
        if sid == signal_id:
            return label, "av://lavfi:" + graph
    return None
