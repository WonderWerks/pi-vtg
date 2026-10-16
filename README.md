# pi-vtg

A Raspberry Pi 4 video and audio test generator for AV technicians. Plug it into a display, power it on, and it starts looping test video on HDMI and test audio on the 3.5mm jack with no interaction. A web UI on port 5000 gives full control from any phone or laptop on the network.

<!-- Photo: the unit in its case, connected to a display -->

## Features

- **Boots straight into test signals.** Video loops on HDMI and audio loops on the 3.5mm jack within seconds of power-on.
- **HDMI auto-detect.** Video and HDMI audio go to whichever HDMI port has a display connected.
- **Video, image, and audio test modes**, each with play/pause/stop, next/previous, looping, and volume/mute.
- **Image slideshows** from separate 1080p and 4K folders, with adjustable time per image.
- **Mono Output toggle** that sums L+R so both channels carry the same signal (useful for feeding mono XLR inputs from the TRS jack).
- **On-screen display (OSD)** showing IP addresses, SSID, web UI port, and service errors. Optional date/time, now-playing, and audio track lines. A custom message box displays any text on screen.
- **HDMI-CEC** power on/off and raw `cec-ctl` commands, per port or both.
- **Dependable networking.** Ethernet is always DHCP. Wifi joins your network if it's available, otherwise the Pi broadcasts its own hotspot at a fixed address (`10.1.1.10`).
- **Swap media by dropping files in folders.** The web UI dropdowns populate from whatever is in them.

## Hardware

| Item | Notes |
|---|---|
| Raspberry Pi 4 | Tested on 4GB and 1GB models |
| microSD card | 16GB or larger |
| Power supply | Official 5V 3A USB-C recommended |
| Micro-HDMI to HDMI cable | One is enough; the port is auto-detected |
| Ethernet cable | For setup; optional afterwards |
| 3.5mm audio cable | Optional, for line-level audio testing |

The Pi 4 has two micro-HDMI ports. In this project:

| Pi port | Linux name | Notes |
|---|---|---|
| Next to the USB-C power port | `HDMI-A-1` | Used if it's the only one connected |
| Next to the 3.5mm audio jack | `HDMI-A-2` | Preferred when both or neither are connected |

## Installation

These steps take a blank microSD card to a working unit. Run every command on the Pi over SSH unless noted.

### 1. Flash the OS (on your computer)

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

- **Device:** Raspberry Pi 4
- **OS:** Raspberry Pi OS (other) > **Raspberry Pi OS Lite (64-bit)**
- **Customisation settings:**
  - **Hostname:** something unique per unit, e.g. `vtg` or `vtg2`. Two units with the same hostname on one network will conflict.
  - **Username:** `vtg` (**required**: the service files expect `/home/vtg/pi-vtg`)
  - **Password:** your choice
  - **Wireless LAN:** leave this off; wifi is configured in step 5
  - **Locale/timezone:** set yours (the OSD clock uses it)
  - **Services:** enable SSH with password authentication

### 2. Connect and update

Connect the Pi to your network with Ethernet, power it on, and give it a minute. From your computer:

```bash
ssh vtg@vtg.local
```

Use your hostname in place of `vtg`. If `.local` names don't resolve on your network, find the Pi's IP in your router and use `ssh vtg@<ip>`.

On the Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git mpv python3-flask v4l-utils
```

`v4l-utils` provides `cec-ctl`. NetworkManager and Avahi (`.local` names) are already included in Raspberry Pi OS.

### 3. Enable wifi

Wifi stays blocked until a country is set. Use your two-letter country code:

```bash
sudo raspi-config nonint do_wifi_country US
sudo rfkill unblock wifi
```

### 4. Get the code and create the media folders

```bash
git clone https://github.com/WonderWerks/pi-vtg.git ~/pi-vtg
mkdir -p ~/pi-vtg/media/{video,audio,images_1080p,images_4k} ~/pi-vtg/state
```

Media files are not included in the repo. Copy your own in from your computer (see [Adding media](#adding-media)). At minimum, put one video in `media/video` and one audio file in `media/audio` so there's something to play on boot.

### 5. Configure wifi

```bash
cd ~/pi-vtg
cp secrets.env.example secrets.env
nano secrets.env
```

Fill in all four values:

| Variable | Meaning |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | The network the unit should join |
| `FALLBACK_SSID` / `FALLBACK_PASSWORD` | The hotspot it broadcasts if that network isn't found (password: 8+ characters) |

Save (Ctrl+O, Enter, Ctrl+X), then lock down the file and create the wifi profiles:

```bash
chmod 600 secrets.env
bash services/wifi_setup.sh
```

You should see `Wifi profiles configured.`

### 6. Install the services

```bash
for f in ~/pi-vtg/systemd/*; do sudo ln -sf "$f" /etc/systemd/system/; done
sudo systemctl daemon-reload
sudo systemctl enable vtg-display.service vtg-audio.service vtg-osd.service vtg-web.service vtg-cec-init.service vtg-wifi-fallback.timer
```

The unit files are symlinked rather than copied, so a `git pull` updates them too.

### 7. Allow the web UI's restart and reboot buttons

The web UI runs as `vtg` and needs `sudo` for exactly three commands. Grant only those:

    echo 'vtg ALL=(root) NOPASSWD: /usr/bin/systemctl restart vtg-display.service, /usr/bin/systemctl restart vtg-audio.service, /usr/sbin/reboot' | sudo tee /etc/sudoers.d/pi-vtg
    sudo chmod 440 /etc/sudoers.d/pi-vtg
    sudo visudo -cf /etc/sudoers.d/pi-vtg

The last command should print `parsed OK`. Then check device access:

    groups | grep -qw video && groups | grep -qw audio && groups | grep -qw render && echo "groups OK"

### 8. Verify

Connect a display and wait about a minute. You should see your video looping and hear audio on the 3.5mm jack. SSH back in and run:

```bash
systemctl --failed
systemctl status 'vtg-*' --no-pager
```

`systemctl --failed` should list 0 units. Then open the web UI at `http://vtg.local:5000` (or `http://<ip>:5000`).

## Usage

### What happens at boot

| Output | Boot behavior |
|---|---|
| HDMI video + HDMI audio | Loops everything in `media/video` |
| 3.5mm audio | Loops everything in `media/audio` |
| OSD | On, showing IP addresses, SSID, web UI port, and errors |
| Wifi | Decided once per boot (see below) |

Images do not start on boot. Start them from the Images panel in the web UI.

### Wifi behavior

1. At boot, the Pi tries to join `WIFI_SSID`.
2. About 30 seconds after boot, a one-time check runs. If wifi still isn't connected, it gives `WIFI_SSID` one more 15-second try, then starts the `FALLBACK_SSID` hotspot.
3. The decision holds until the next reboot. To retry after changing locations, reboot or press **Run Wifi Check Now** in the System panel.

On the hotspot, the Pi is always at **10.1.1.10**, so the web UI is at `http://10.1.1.10:5000`. The OSD shows `(FALLBACK HOTSPOT)` next to the SSID when it's active. If Ethernet is also connected, hotspot clients get internet access through it.

Ethernet is always DHCP and works regardless of wifi. The web UI and SSH are reachable on both interfaces.

### Web UI

| Panel | What it does |
|---|---|
| Video | Pick a file or play the whole folder; play/pause/stop/next/prev; loop; volume; mute |
| Images | Choose the 1080p or 4K folder; set seconds per image; same transport controls |
| Audio Test | Same controls for the 3.5mm output, plus the Mono Output toggle |
| CEC | Power on/off and raw `cec-ctl` arguments, to either or both HDMI ports |
| OSD | Turn OSD lines on/off; set a custom on-screen message (max 80 characters) |
| System | Restart the display or audio player, run the wifi check, reboot |
| Errors / Debugging | Current display resolution/refresh/port, and any stopped services |

Video and Images share one output. Starting one replaces the other.

### Adding media

Copy files over SFTP using the same login as SSH (port 22). Use [WinSCP](https://winscp.net/) or [FileZilla](https://filezilla-project.org/), or from a terminal:

```bash
scp my_test_video.mp4 vtg@vtg.local:~/pi-vtg/media/video/
```

| Folder | Contents |
|---|---|
| `media/video` | Video files (`.mp4`, `.mkv`, etc.) |
| `media/audio` | Audio files: pink noise, white noise, music (`.mp3`, `.flac`, `.wav`) |
| `media/images_1080p` | 1920x1080 test pattern images |
| `media/images_4k` | 3840x2160 test pattern images |

Keep each folder to media files only. Every file in it is fed to the player, so stray files cause errors in the logs. Files appear in the web UI dropdowns right away. The boot playlists pick up new files on the next restart of that player (System panel or reboot).

## Troubleshooting

```bash
systemctl status 'vtg-*' --no-pager            # every service at a glance
journalctl -u vtg-display -b --no-pager        # one service's log since boot
journalctl -u 'vtg-*' -b -p warning --no-pager # warnings/errors from all services
sudo systemctl restart vtg-display             # restart one service
nmcli connection show --active                 # what wifi is connected to
```

Replace `vtg-display` with `vtg-audio`, `vtg-web`, `vtg-osd`, `vtg-cec-init`, or `vtg-wifi-fallback` as needed.

| Symptom | Check |
|---|---|
| No picture | Moved the HDMI cable to the other port after boot? The port is picked at startup; restart the display player or reboot. |
| No HDMI audio | Same as above: HDMI audio follows the detected port. |
| Web UI unreachable on wifi | Look at the OSD for the current IP and SSID. On the hotspot, use `10.1.1.10:5000`. |
| Hotspot didn't appear | `journalctl -u vtg-wifi-fallback -b` and confirm `secrets.env` values match step 5. |
| `ERROR: ... not running` on the OSD | `journalctl -u <that service> -b` |

A debug CLI talks to the players directly, bypassing the web UI:

```bash
cd ~/pi-vtg/services
python3 vtgctl.py video status
python3 vtgctl.py audio volume 50
```

## Updating

```bash
cd ~/pi-vtg
git pull
sudo systemctl daemon-reload
sudo systemctl restart vtg-display vtg-audio vtg-osd vtg-web
```

## How it works

```
pi-vtg/
├── secrets.env.example   wifi settings template (copy to secrets.env)
├── services/
│   ├── display_player.sh  mpv instance for HDMI video + images, controlled over IPC
│   ├── audio_player.sh    mpv instance for the 3.5mm jack, controlled over IPC
│   ├── mpv_ipc.py         small client for mpv's JSON IPC socket
│   ├── web_api.py         Flask web UI + REST API (port 5000)
│   ├── static/index.html  the web UI page
│   ├── osd_updater.py     refreshes the on-screen status text every 2s
│   ├── cec_control.py     cec-ctl wrapper used by the web UI
│   ├── cec_init.sh        registers both HDMI ports as CEC playback devices
│   ├── wifi_setup.sh      one-time: creates the wifi + hotspot profiles
│   ├── wifi_fallback.sh   boot-time wifi decision
│   └── vtgctl.py          debug CLI
├── systemd/              service and timer units (symlinked into /etc/systemd/system)
├── media/                your media (not in git)
└── state/                saved OSD settings (not in git)
```

Two long-running `mpv` processes do all playback, one for the display and one for the 3.5mm jack. Nothing restarts when you change modes. The web UI and OSD send commands over each player's IPC socket (`/tmp/vtg-display.sock` and `/tmp/vtg-audio.sock`), which keeps switching fast and lets audio and video run independently.

Service units launch scripts through `/bin/bash` instead of relying on executable permissions, so editing the code on Windows doesn't break anything. `.gitattributes` keeps line endings as LF.

## Known limitations

- **One HDMI output at a time.** True simultaneous dual output isn't possible with this design: on the Pi 4's driver, only one process can render to the display hardware at once. Supporting it would take a different architecture.
- **HDMI port is detected at startup.** Moving the cable to the other port needs a player restart or reboot.
- **4K images are scaled** to the display's current mode; the output resolution is not switched.
- **Wifi is decided once per boot.** No automatic switching back if your network appears later.

## Roadmap

- Physical buttons and a small LCD for on-device control
- 3D-printed case
- Separate 4K video playlist
- Dual HDMI output

## License

[MIT](LICENSE)
