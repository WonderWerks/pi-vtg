# pi-vtg

A Raspberry Pi 4 video and audio test generator for AV technicians. Plug it into a display, power it on, and it starts looping test video on HDMI and test audio on the 3.5mm jack with no interaction. A web UI on port 5000 gives full control from any phone or laptop on the network.

<!-- Photo: the unit in its case, connected to a display -->

## Features

- **Boots straight into test signals.** Video loops on HDMI and audio loops on the 3.5mm jack within seconds of power-on.
- **HDMI auto-detect.** Video and HDMI audio go to whichever HDMI port has a display connected. Plugging in, unplugging, or moving the cable restarts the player on the right port within a few seconds.
- **Video, image, and audio test modes**, each with play/pause/stop, next/previous, looping, and volume/mute.
- **Image slideshows** with adjustable time per image.
- **Projector alignment patterns** (grid, framing, overscan, focus, grayscale, solid fields) for common aspect ratios, drawn at the display's native resolution.
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
sudo apt install -y git mpv python3-flask python3-pil fonts-dejavu-core v4l-utils
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
mkdir -p ~/pi-vtg/media/{video,audio,images} ~/pi-vtg/state
```

Media files are not included in the repo. Copy your own in from your computer (see [Adding media](#adding-media)). At minimum, put one video in `media/video` and one audio file in `media/audio` so there's something to play on boot.

**Load all your media now, during the build.** Step 9 makes the SD card read-only so the unit survives being unplugged at any time. After that, anything copied in only lives in RAM and disappears at power-off. Adding media later means switching to Maintenance mode first (see [Power-pull protection](#power-pull-protection)).

### 5. Configure wifi

```bash
cd ~/pi-vtg
cp secrets.env.example secrets.env
nano secrets.env
```

Fill in the values:

| Variable | Meaning |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | Optional. A network to know from the start, like your travel router. Leave blank to add networks from the web UI only. |
| `FALLBACK_SSID` / `FALLBACK_PASSWORD` | Required. The hotspot it broadcasts when no saved network is in range (password: 8+ characters) |

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
sudo systemctl enable vtg-display.service vtg-audio.service vtg-osd.service vtg-web.service vtg-playlog.service vtg-mode.service vtg-maint-timeout.service vtg-cec-init.service vtg-wifi-fallback.timer
```

The unit files are symlinked rather than copied, so a `git pull` updates them too.

Keep the players' control sockets in `/tmp` from being auto-deleted (Debian 13 clears `/tmp` files older than 10 days, which would cut the web UI off from the players on a unit left running):

```bash
echo 'x /tmp/vtg-*' | sudo tee /etc/tmpfiles.d/pi-vtg.conf
```

### 7. Allow the web UI's restart and reboot buttons

The web UI runs as `vtg` and needs `sudo` for exactly five commands. Grant only those:

    echo 'vtg ALL=(root) NOPASSWD: /usr/bin/systemctl restart vtg-display.service, /usr/bin/systemctl restart vtg-audio.service, /usr/sbin/reboot, /usr/bin/bash /home/vtg/pi-vtg/services/vtg_mode.sh *, /usr/bin/bash /home/vtg/pi-vtg/services/wifi_ctl.sh *' | sudo tee /etc/sudoers.d/pi-vtg
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

### 9. Turn on power-pull protection (last step)

Until now the SD card has been writable, so shut down properly (`sudo poweroff`) rather than pulling power. This step makes the card read-only and does the final reboot. Only run it once everything works and **all your media is loaded**:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh protect
```

It takes up to a minute, then reboots. Check it took effect:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh status
```

You should see `now=protected next_boot=protected`, and the OSD's top line reads `Mode: PROT`. From here on the unit boots protected every time, and Maintenance mode times out after 5 idle minutes.

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

The unit remembers every wifi network it has joined (from `secrets.env` or the web UI).

| When | What happens |
|---|---|
| Boot | It joins any saved network that's in range. If `WIFI_SSID` is set and in range, that one is preferred. |
| 30 seconds after boot, nothing joined | It starts its own hotspot (`FALLBACK_SSID`) and stays on it until the next reboot. |
| You pick a network in the web UI | It switches to that network now and saves it for next time. If joining fails (wrong password, out of range), it goes back to the previous network or the hotspot within about a minute. |

Typical uses:

- **Known site or travel router:** put it in `secrets.env` (or add it once from the web UI). The unit joins it on its own at every boot.
- **New site:** the unit starts its hotspot. Join the hotspot from your phone, open `http://10.1.1.10:5000`, and pick the site's network in the **Wifi** panel.

On the hotspot the unit is always at **10.1.1.10**, and the OSD shows how to connect: `Hotspot: join wifi "<name>", then open 10.1.1.10:5000`. If Ethernet is also connected, hotspot clients get internet access through it.

Ethernet is always DHCP and works regardless of wifi. The web UI and SSH are reachable on both interfaces.

### Web UI

| Panel | What it does |
|---|---|
| Video | Pick a file or play the whole folder; play/pause/stop/next/prev; loop; volume; mute |
| Images | Pick an image or play the folder as a slideshow; set seconds per image; same transport controls. **Alignment patterns**: grid, screen framing, overscan/safe areas, crosshatch, focus, grayscale steps and solid fields, for any common aspect ratio (16:9, 16:10, 4:3, 5:4, 1.85, 1.90, 2.00, 2.35, 2.39, 21:9, 32:9), drawn at the display's native resolution |
| Audio Test | Same controls for the 3.5mm output, plus the Mono Output toggle |
| CEC | Power on/off and raw `cec-ctl` arguments, to either or both HDMI ports |
| OSD | Turn OSD lines on/off (including the protection mode readout); set a custom on-screen message (max 80 characters) |
| Wifi | Scan and join a network, forget saved networks, switch to the hotspot |
| System | Restart the display or audio player, run the wifi check, sync the unit's clock to your phone/laptop, reboot |
| Power-Pull Protection | Switch Protected / Maintenance / Debug mode; shows the Maintenance countdown |
| Errors / Debugging | Current display resolution/refresh/port, and any stopped services |

Video and Images share one output. Starting one replaces the other.

### Adding media

If the unit is in Protected mode, switch to **Maintenance** first or the files will vanish at power-off (see [Power-pull protection](#power-pull-protection)). Best practice is to load all media during the initial build.

Copy files over SFTP using the same login as SSH (port 22). Use [WinSCP](https://winscp.net/) or [FileZilla](https://filezilla-project.org/), or from a terminal:

```bash
scp my_test_video.mp4 vtg@vtg.local:~/pi-vtg/media/video/
```

| Folder | Contents |
|---|---|
| `media/video` | Video files (`.mp4`, `.mkv`, etc.) |
| `media/audio` | Audio files: pink noise, white noise, music (`.mp3`, `.flac`, `.wav`) |
| `media/images` | Still images (test patterns, slides); scaled to fit the display |

Only known media extensions are played (video: mp4 m4v mkv mov avi ts m2ts mpg mpeg webm wmv; audio: mp3 flac wav m4a aac ogg opus wma aif aiff; images: png jpg jpeg bmp gif webp tif tiff). Anything else in the folder, like `Thumbs.db` or macOS `._` files, is ignored. Files appear in the web UI dropdowns right away. The boot playlists pick up new files on the next restart of that player (System panel or reboot).

#### Video formats the Pi 4 plays smoothly

The Pi 4 only plays video smoothly when its hardware decoder handles it. Anything else falls back to the CPU and stutters (video and audio).

| Codec | Max resolution / frame rate | Result |
|---|---|---|
| H.264 (AVC) | 1920x1080 @ 60 fps | Smooth (hardware) |
| H.265 (HEVC) | 3840x2160 @ 60 fps | Smooth (hardware) |
| H.264 above 1080p (e.g. 4K) | n/a | Stutters (no hardware support) |
| VP9, AV1, MPEG-2, others | n/a | Stutters above SD (software only) |

For 4K test video, use HEVC. Check a file before copying it over:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate -of csv=p=0 myfile.mp4
```

Convert a 4K H.264 file to 4K HEVC, or to 1080p H.264 (run on any computer with ffmpeg):

```bash
ffmpeg -i in.mp4 -c:v libx265 -preset medium -crf 22 -pix_fmt yuv420p -tag:v hvc1 -c:a aac -b:a 192k out_4k_hevc.mp4
ffmpeg -i in.mp4 -vf scale=1920:-2 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k out_1080p.mp4
```

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
| No picture | Wait about 10 seconds after plugging in; the player restarts on the connected port. Still nothing: `journalctl -u vtg-display -b` and check the cable/adapter. |
| No HDMI audio | HDMI audio follows the video port. Some monitors (DVI adapters, many PC monitors) have no audio; the video still plays. |
| Skips to the next video early | Check the [play log](#play-log). `EARLY END` = damaged file (scan it, see below). `HDMI ... disconnected` before the skip = the display dropped (TV standby, input switch, switcher or extender); the player restarts on reconnect and starts the playlist from the top. |
| Video/audio stutter | The file is a format the Pi 4 can't decode in hardware. See [Video formats](#video-formats-the-pi-4-plays-smoothly). |
| Web UI unreachable on wifi | Look at the OSD for the current IP and SSID. On the hotspot, use `10.1.1.10:5000`. |
| Hotspot didn't appear | `journalctl -u vtg-wifi-fallback -b` and confirm `secrets.env` values match step 5. |
| Joined the wrong network / can't reach the web UI after Connect | Look at the OSD for the SSID and IP. If a Connect fails (wrong password, out of range), the previous network or the hotspot comes back within about a minute. |
| `ERROR: ... not running` on the OSD | `journalctl -u <that service> -b` |

### Play log

`vtg-playlog` records every video the display player plays: when it started, how long it ran, and why it stopped. It also logs HDMI connect/disconnect and unclean shutdowns (power pulled). It's capped at 3 MB total (1 MB file + 2 old copies) in `~/pi-vtg/state/`.

```bash
tail -50 ~/pi-vtg/state/playlog.log
```

| Ending | Meaning |
|---|---|
| `finished (reached end of file)` | Normal |
| `EARLY END` | Stopped short of the end; the file is likely damaged |
| `stopped by command: web UI: next button (video)` | Someone pressed a web UI button |
| `stopped by command: not from the web UI` | A command came from `vtgctl` or another IPC client |
| `FAILED: ...` | Couldn't play: no display connected, or an unplayable file. Repeats are collapsed into one line. |
| `player shut down` / `LOST player connection` | Service restart, reboot, or player crash |
| `POWER previous session did not shut down cleanly` | Power was pulled; shows the last saved file and position (saved every 30s) |

Timestamps come from the Pi's clock. The Pi has no battery clock, so without internet (NTP) the dates will be wrong; the order and durations are still correct.

To check a video file for damage (no output = clean):

```bash
ffmpeg -v error -i ~/pi-vtg/media/video/<file> -f null - 2>&1 | tail
```

A debug CLI talks to the players directly, bypassing the web UI:

```bash
cd ~/pi-vtg/services
python3 vtgctl.py video status
python3 vtgctl.py audio volume 50
```

## Power-pull protection

The unit is built to be switched off at the wall. SD cards are easily damaged by losing power mid-write, and a damaged card often means a unit that won't boot until it's re-imaged. So in normal use the card is read-only and every change goes to RAM instead.

| Mode | SD card | Unplug anytime? | Use for |
|---|---|---|---|
| **Protected** (normal) | Read-only; changes are lost at power-off | Yes | Field use |
| **Maintenance** | Writable | No, shut down first | Adding media, updating, changing setup |
| **Debug** | Writable for one boot, then Protected again | No, shut down first | Keeping the play log and system logs across a reboot |

Switch from the web UI (**Power-Pull Protection** panel) or over SSH:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh maintenance   # or: protect, debug, status
```

Each switch reboots the unit. The OSD's top line shows the current mode: `Mode: PROT`, `Mode: MAINT (SD card writable)` or `Mode: DEBUG (logs for one boot)`.

**Maintenance times out.** If nothing happens for 5 minutes (no web UI actions, no SSH/SFTP session, no `apt` or `git` running), the unit switches back to Protected on its own and reboots. The OSD counts down: `auto-PROT in 4:12`. This keeps a unit that was left in Maintenance safe to unplug.

Settings changed in the web UI (OSD options) are written through to the card even while protected, so they survive power-off. The play log in Protected mode lasts only until power-off; use Debug mode to keep it.

**Adding media after the build:** switch to Maintenance, copy the files, then switch back to Protected.

## Updating

Updates need a writable card. Switch to Maintenance first, update, then switch back:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh maintenance
```

After it reboots:

```bash
cd ~/pi-vtg
git pull
sudo systemctl daemon-reload
sudo systemctl restart vtg-display vtg-audio vtg-osd vtg-web vtg-playlog
sudo bash ~/pi-vtg/services/vtg_mode.sh protect
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
│   ├── play_logger.py     play log: what played, for how long, why it stopped
│   ├── vtg_mode.sh        protected / maintenance / debug mode switching, clock set
│   ├── maint_timeout.sh   maintenance mode: back to protected after 5 idle minutes
│   ├── system_mode.py     reads the current mode (for the web UI and OSD)
│   ├── cec_control.py     cec-ctl wrapper used by the web UI
│   ├── cec_init.sh        registers both HDMI ports as CEC playback devices
│   ├── wifi_setup.sh      one-time: creates the wifi + hotspot profiles
│   ├── wifi_fallback.sh   boot-time wifi decision: any saved network in range, else hotspot
│   ├── wifi_ctl.sh        web UI wifi actions: scan, connect (with rollback), forget, hotspot
│   ├── patterns.py        alignment pattern generator (Pillow)
│   └── vtgctl.py          debug CLI
├── systemd/              service and timer units (symlinked into /etc/systemd/system)
├── media/                your media (not in git)
└── state/                saved OSD settings + play log (not in git)
```

Two long-running `mpv` processes do all playback, one for the display and one for the 3.5mm jack. Nothing restarts when you change modes. The web UI and OSD send commands over each player's IPC socket (`/tmp/vtg-display.sock` and `/tmp/vtg-audio.sock`), which keeps switching fast and lets audio and video run independently.

Service units launch scripts through `/bin/bash` instead of relying on executable permissions, so editing the code on Windows doesn't break anything. `.gitattributes` keeps line endings as LF.

## Known limitations

- **One HDMI output at a time.** True simultaneous dual output isn't possible with this design: on the Pi 4's driver, only one process can render to the display hardware at once. Supporting it would take a different architecture.
- **HDMI changes restart the player.** Plugging in, unplugging, a TV that drops HDMI when turned off, or moving the cable restarts the display player (about 5 to 10 seconds), and playback starts from the top of the video folder. Anything started from the web UI (images, a single file) has to be started again.
- **Images are scaled** to the display's current mode; the output resolution is not switched.
- **Wifi is decided once per boot.** At boot the unit joins any saved network in range, otherwise it starts the hotspot. If a known network appears later, join it from the web UI.
- **WPA2/WPA3 personal and open networks only.** Enterprise (802.1X username/password) networks aren't supported from the web UI.

## Roadmap

- Physical buttons and a small LCD for on-device control
- Signage player mode (scope to be defined)
- 3D-printed case
- Separate 4K video playlist
- Dual HDMI output

## License

[MIT](LICENSE)
