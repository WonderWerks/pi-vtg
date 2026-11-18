# pi-vtg

A Raspberry Pi 4 video and audio test generator for AV technicians. Plug it into a display, power it on, and it starts looping test video on HDMI and test audio on the 3.5mm jack with no interaction. A web UI on port 5000 gives full control from any phone or laptop on the network.

<!-- Photo: the unit in its case, connected to a display -->

## Features

- **Boots straight into test signals.** Video loops on HDMI and audio loops on the 3.5mm jack within seconds of power-on.
- **HDMI auto-detect.** Video and HDMI audio go to whichever HDMI port has a display connected. Plugging in, unplugging, or moving the cable restarts the player on the correct port.
- **Video, image, and audio test modes**, each with play/pause/stop, next/previous, looping, and volume/mute.
- **Image slideshows** with adjustable time per image.
- **Projector alignment patterns** (grid, framing, overscan, focus, grayscale, solid fields) for common aspect ratios, drawn at the display's current resolution.
- **Built-in audio test signals**: pink and white noise, 100 Hz / 1 kHz / 10 kHz tones, left-only and right-only channel ID, and a 20 Hz to 20 kHz sweep, generated live (no files needed).
- **Mono Output toggle** that sums L+R so both channels carry the same signal.
- **On-screen display (OSD)** showing the SD card mode, IP addresses, SSID, web UI port, and service errors. Optional date/time, now-playing, audio track, and display (EDID) lines. A custom message box displays any text on screen.
- **Display info and output control.** Reads the display's EDID (maker, model, preferred mode, supported modes, HDMI audio) and can force any output resolution/refresh the display offers.
- **HDMI-CEC** power on/off and raw `cec-ctl` commands, per port or both.
- **Dependable networking.** Ethernet is always DHCP. Wifi joins a saved network if one is in range, otherwise the Pi broadcasts its own hotspot at a fixed address (`10.1.1.10`). Networks can be added, joined, and forgotten from the web UI.
- **SD card protection.** In normal use the SD card is read-only, so pulling the power can't corrupt it. A Maintenance mode makes it writable for adding media and updates, and switches back on its own when left idle.
- **Swap media by dropping files in folders.** The web UI dropdowns populate from whatever is in them.

## Hardware

| Item | Notes |
|---|---|
| Raspberry Pi 4 | Tested on 8GB and 1GB models. 1GB: see [Known limitations](#known-limitations) for 4K |
| microSD card | 16GB or larger |
| Power supply | Official 5V 3A USB-C recommended |
| Micro-HDMI to HDMI cable, or a micro-HDMI to HDMI adapter plus a standard HDMI cable | One is enough; the port is auto-detected |
| Ethernet cable | Recommended for setup |
| 3.5mm audio cable | Optional, for line-level audio testing |
| Case | Any Raspberry Pi 4 case. Preferably one with a fan or heatsink |

The Pi 4 has two micro-HDMI ports. **Use either one**: the unit finds the connected display on its own. If displays are connected to both, it uses the port next to the audio jack. Only one port outputs at a time.

The logs and the web UI's Display panel use the Linux names for the ports:

| Pi port (board label) | Linux name |
|---|---|
| Next to the USB-C power port (HDMI0) | `HDMI-A-1` |
| Next to the 3.5mm audio jack (HDMI1) | `HDMI-A-2` |

## Installation

These steps take a blank microSD card to a working unit. Run every command on the Pi over SSH unless noted.

**Networking at a glance.** The unit deals with up to three networks. Knowing which is which makes the steps below easier:

| Network | What it's for | Needs internet? |
|---|---|---|
| **Setup network** (Ethernet or wifi) | Installing software (`apt`, `git`) during this build, and once more in step 9 | Yes |
| **Control network** (your travel router, shop wifi, or Ethernet) | Reaching the web UI and SSH in the field | No, better without |
| **Hotspot** (the unit's own wifi) | Control when no saved wifi is in range. Always at `10.1.1.10` | No |

The setup network can also be your control network (e.g. a travel router with internet).

### 1. Flash the OS (on your computer)

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

- **Device:** Raspberry Pi 4
- **OS:** Raspberry Pi OS (other) > **Raspberry Pi OS Lite (64-bit)**
- **Customisation settings:**
  - **Hostname:** something unique per unit, e.g. `vtg` or `vtg2`. Two units with the same hostname on one network will conflict.
  - **Username:** `vtg` (**required**: the service files expect `/home/vtg/pi-vtg`)
  - **Password:** your choice
  - **Wireless LAN:** fill it in only if your **setup network** is wifi (see step 2). The control network and the hotspot are configured in step 5.
  - **Locale/timezone:** set yours (the OSD clock uses it)
  - **Services:** enable SSH with password authentication

### 2. Connect and update

The build needs internet. Pick one setup:

| Setup | What to do |
|---|---|
| **Ethernet with internet** (simplest) | Plug in Ethernet. Nothing else needed. |
| **Wifi with internet** (wifi set in Imager in step 1), no Ethernet | Nothing else needed. |
| **Wifi for internet + Ethernet for SSH** on a network with no internet (e.g. a bench or AV switch) | Plug in both, then run the extra command below after logging in. |

A wifi network set in Imager stays saved on the unit and appears in the web UI's saved networks. To remove it later, use **Forget** in the web UI while in Maintenance mode.

Power it on and give it a minute. From your computer:

```bash
ssh vtg@vtg.local
```

Use your hostname in place of `vtg`. If `.local` names don't resolve on your network, find the Pi's IP in your router and use `ssh vtg@<ip>`.

**Wifi for internet + Ethernet for SSH only:** make wifi the internet route. Otherwise Ethernet takes it, and `apt` and `git` fail even though `ping` works. Your SSH session may pause for a few seconds:

```bash
CON=$(nmcli -g GENERAL.CONNECTION device show eth0); sudo nmcli connection modify "$CON" ipv4.never-default yes ipv6.never-default yes && sudo nmcli connection up "$CON"
```

On the Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git mpv ffmpeg python3-flask python3-pil fonts-dejavu-core v4l-utils
```

`v4l-utils` provides `cec-ctl`. `ffmpeg` is used to check video files and to make test images and video (see [Free test media](#free-test-media)). NetworkManager and Avahi (`.local` names) are already included in Raspberry Pi OS.

### 3. Enable wifi

Wifi stays blocked until a country is set. If you set wifi in Imager this is already done (running it again is harmless). Use your two-letter country code:

```bash
sudo raspi-config nonint do_wifi_country US
sudo rfkill unblock wifi
```

### 4. Get the code and create the media folders

```bash
git clone https://github.com/WonderWerks/pi-vtg.git ~/pi-vtg && mkdir -p ~/pi-vtg/media/{video,audio,images} ~/pi-vtg/state
```

Media files are not included in the repo. Copy your own in from your computer with an SFTP app such as FileZilla:

| Folder on the Pi | What goes in it |
|---|---|
| `/home/vtg/pi-vtg/media/video` | Videos (loop on HDMI at boot) |
| `/home/vtg/pi-vtg/media/audio` | Audio files (loop on the 3.5mm jack at boot) |
| `/home/vtg/pi-vtg/media/images` | Still images |

In FileZilla connect to `sftp://vtg.local` (your hostname, or `sftp://<ip>`), username `vtg`, your Imager password, port `22`. Files play in name order, so number them to set the order: `01-`, `02-`, `03-`... [Adding media](#adding-media) has the full details. At minimum, put one video in `media/video` so there's something to play on boot. Audio files are optional: the 3.5mm jack loops `media/audio` at boot, and test signals (noise, tones, sweep) are built into the web UI.

**Load all your media now, during the build.** Step 9 makes the SD card read-only so the unit survives being unplugged at any time. Once in read-only mode, anything copied in only lives in RAM and disappears at power-off. Adding media later means switching to Maintenance mode first (see [SD card protection](#sd-card-protection)).

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

**Put the value in quotes if it contains spaces**, e.g. `WIFI_SSID="Shop Wifi"`. If it contains `$`, a backtick, or `"`, use single quotes instead: `WIFI_PASSWORD='pa$$word'`.

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
echo 'x /tmp/vtg-*' | sudo tee /etc/tmpfiles.d/pi-vtg.conf && echo OK
```

You should see `OK`.

### 7. Allow the web UI's restart, reboot and power-off buttons

The web UI runs as `vtg` and needs `sudo` for exactly six commands. Grant only those:

    echo 'vtg ALL=(root) NOPASSWD: /usr/bin/systemctl restart vtg-display.service, /usr/bin/systemctl restart vtg-audio.service, /usr/sbin/reboot, /usr/sbin/poweroff, /usr/bin/bash /home/vtg/pi-vtg/services/vtg_mode.sh *, /usr/bin/bash /home/vtg/pi-vtg/services/wifi_ctl.sh *' | sudo tee /etc/sudoers.d/pi-vtg
    sudo chmod 440 /etc/sudoers.d/pi-vtg
    sudo visudo -cf /etc/sudoers.d/pi-vtg

The last command should print `parsed OK`. Then check device access:

    groups | grep -qw video && groups | grep -qw audio && groups | grep -qw render && echo "groups OK"

### 8. Note the web UI address

The services are installed but don't start until the reboot in step 9. Print the addresses the web UI will be on:

```bash
for i in eth0 wlan0; do ip -4 -o addr show dev $i 2>/dev/null | awk -v i=$i '{split($4,a,"/"); print i": http://"a[1]":5000"}'; done; echo "or: http://$(hostname).local:5000"
```

The wifi address can change after the reboot if the unit joins a different network or starts its hotspot (`http://10.1.1.10:5000`). The OSD always shows the current address.

### 9. Make the SD card read-only and reboot

Until now the SD card has been writable, so shut down properly (`sudo poweroff`) rather than pulling power. This step makes the card read-only and reboots. The first time, it installs a few system packages, so the setup network must still have internet. Load your media first (step 4); adding it later means switching to Maintenance mode.

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh readonly
```

It takes up to a minute, then reboots. Connect a display: after about a minute your first video plays, with audio on the 3.5mm jack if you added audio files. Open the web UI at the address from step 8, then SSH back in and check:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh status
systemctl --failed
```

You should see `now=read-only next_boot=read-only` and `0 loaded units listed`, and the OSD's top line reads `Mode: READ-ONLY (safe to unplug)`. If anything is missing, see [Troubleshooting](#troubleshooting). From here on the unit boots read-only every time, and Maintenance mode switches back to read-only after 11 minutes 11 seconds of no activity.

## Usage

### What happens at boot

| Output | Boot behavior |
|---|---|
| HDMI video + HDMI audio | Loops everything in `media/video` |
| 3.5mm audio | Loops everything in `media/audio` (silent if the folder is empty) |
| OSD | On, showing the SD card mode, IP addresses, SSID, web UI port, and errors |
| Wifi | Decided once per boot (see below) |

Images do not start on boot. Start them from the Images panel in the web UI.

### Wifi behavior

**Use a wifi network you own and control**, such as a travel router or a dedicated local network, ideally one with no internet connection. The web UI has no login, so anyone on the same network can control the unit. Don't put it on a client's guest or corporate wifi; use the hotspot or Ethernet there instead.

The unit remembers every wifi network it has joined (from `secrets.env`, Raspberry Pi Imager, or the web UI), including the password.

| When | What happens |
|---|---|
| Boot | It joins any saved network that's in range. If `WIFI_SSID` is set and in range, that one is preferred. |
| 30 seconds after boot, nothing joined | It starts its own hotspot (`FALLBACK_SSID`) and stays on it until the next reboot. |
| You pick a network in the web UI | It switches to that network now and saves it for next time. If joining fails (wrong password, out of range), it goes back to the previous network or the hotspot within about a minute. |

Typical uses:

- **Your travel router or shop network:** put it in `secrets.env` (or add it once from the web UI). The unit joins it on its own at every boot.
- **Anywhere else:** the unit starts its hotspot. Join the hotspot from your phone or laptop and open `http://10.1.1.10:5000`.

On the hotspot the unit is always at **10.1.1.10**, and the OSD shows how to connect: `Hotspot wifi: <name>` and `Web UI: 10.1.1.10:5000`. Until the hotspot decision (about 35 seconds after boot) the OSD counts down: `wlan0: searching, hotspot in 23s`. If Ethernet is also connected, hotspot clients get internet access through it.

If the wifi network disappears (e.g. a phone hotspot switched off), the web UI and OSD show it within about 30 seconds (`router not answering` / `(no router)`).

Ethernet is always DHCP and works regardless of wifi. The web UI and SSH are reachable on both interfaces.

### Web UI

| Panel | What it does |
|---|---|
| Top bar | Current mode (READ-ONLY, or MAINTENANCE with its countdown) and IP addresses, always visible |
| Video | Pick a file or play the whole folder; play/pause/stop/next/prev; loop; volume (remembered across restarts); mute |
| Images | Pick an image or play the folder as a slideshow; set seconds per image; same transport controls. **Alignment patterns**: grid, screen framing, overscan/safe areas, crosshatch, focus, grayscale steps and solid fields, for any common aspect ratio (16:9, 16:10, 4:3, 5:4, 1.85, 1.90, 2.00, 2.35, 2.39, 21:9, 32:9), drawn at the display's current resolution |
| Audio Test | Same controls for the 3.5mm output, plus the Mono Output toggle. **Test signals**: pink/white noise, tones, left/right only, and a sweep, generated live; tones peak at -20 dBFS and white noise is -20 dBFS RMS (at volume 100) |
| CEC | Power on/off and raw `cec-ctl` arguments, to either or both HDMI ports |
| OSD | Turn OSD lines on/off (SD card mode, IPs, SSID, now playing, display name and native resolution from EDID, errors); **Clear all** blanks the OSD, **Restore defaults** brings back the standard lines (mode, IPs with port, SSID, errors); set a custom on-screen message (max 80 characters) |
| Display / Errors | Current output mode and port; the display's EDID (maker, model, year, preferred mode, HDMI audio, supported modes) with a download of the raw EDID; **force the output mode** (any resolution/refresh the display offers, saved for that display only, so a different display always starts on auto); any stopped services |
| Wifi | Scan and join a network; connect to or forget saved networks (passwords are stored, so a saved network needs no password); switch to the hotspot |
| System | Restart the video or audio player, sync the unit's clock to your phone/laptop, reboot, power off. After power off, wait for the green light to stop flashing, then unplug; a case fan powered from the Pi keeps spinning until you do. |
| Power-Pull Protection | Switch Read-only / Maintenance / Debug mode; shows the Maintenance countdown |

Video and Images share one output. Starting one replaces the other.

### Adding media

If the unit is in Read-only mode, switch to **Maintenance** first or the files will vanish at power-off (see [SD card protection](#sd-card-protection)). Best practice is to load all media during the initial build.

Copy files over SFTP, using the same login as SSH. In [FileZilla](https://filezilla-project.org/) (or [WinSCP](https://winscp.net/)), fill in the quick-connect bar:

| Field | Value |
|---|---|
| Host | `sftp://vtg.local` (your hostname), or `sftp://<ip>` |
| Username | `vtg` |
| Password | the password you set in Imager |
| Port | `22` |

Accept the host key the first time. Then drag files into `/home/vtg/pi-vtg/media/video`, `.../media/audio`, or `.../media/images`.

From a terminal instead:

```bash
scp my_test_video.mp4 vtg@vtg.local:~/pi-vtg/media/video/
```

**Play order is by file name.** To set the order, start names with a number: `01-`, `02-`, ... `10-`. Use two digits, or `10-` sorts before `2-`. Numbers sort before letters, and capital letters sort before lowercase (`Zebra` plays before `apple`).

| Folder | Contents |
|---|---|
| `media/video` | Video files (`.mp4`, `.mkv`, etc.) |
| `media/audio` | Audio files such as music or program material (`.mp3`, `.flac`, `.wav`). Noise and tones are built in. |
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

#### Free test media

**Video**

| Source | What's there |
|---|---|
| [Jellyfin test videos](https://syd1.mirror.jellyfin.org/test-videos/) | The same short clip in many codecs, resolutions and bit rates. For the Pi 4 pick **HEVC 8-bit** (any resolution up to 4K) or **H.264** (1080p and below). Skip the AV1 and VP9 versions. |
| [Blender open movies](https://studio.blender.org/films/) | Big Buck Bunny, Sintel, Tears of Steel, etc. (Creative Commons). Downloads are often H.264 at 4K; convert them with the ffmpeg line below. |

**Make your own test images and bars-and-tone video.** These come from ffmpeg's built-in generators, so there's nothing to license. Run them on the Pi in Maintenance mode (or on any computer with ffmpeg and copy the files over). Test audio (noise, tones, sweep) is built into the web UI's Audio panel, so no audio files are needed for that.

Images (built-in alignment patterns are in the web UI already; these add standard color bars):

```bash
cd ~/pi-vtg/media/images
ffmpeg -f lavfi -i "smptehdbars=size=1920x1080" -frames:v 1 "SMPTE HD bars 1080p.png"
ffmpeg -f lavfi -i "smptehdbars=size=3840x2160" -frames:v 1 "SMPTE HD bars 4K.png"
ffmpeg -f lavfi -i "testsrc2=size=1920x1080" -frames:v 1 "Test card 1080p.png"
```

Bars-and-tone video (1 minute, 1080p30 H.264 with a 1 kHz tone):

```bash
cd ~/pi-vtg/media/video
ffmpeg -f lavfi -i "smptehdbars=size=1920x1080:rate=30" -f lavfi -i "aevalsrc=0.1*sin(2*PI*1000*t):s=48000" -t 60 -c:v libx264 -pix_fmt yuv420p -c:a aac -ac 2 "Bars and tone 1080p.mp4"
```

For photos and other images, [NASA's image library](https://images.nasa.gov/) is generally public domain, and [Wikimedia Commons](https://commons.wikimedia.org/) lists the license on every file (look for "public domain" or CC0).

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

`vtg-playlog` records every video the display player plays: when it started, how long it ran, and why it stopped. It also logs HDMI connect/disconnect and unclean shutdowns (power pulled). It's capped at 8 MB total (2 MB file + 3 old copies) in `~/pi-vtg/state/`.

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

## SD card protection

The unit is built to be switched off at the wall. SD cards are easily damaged by losing power mid-write, and a damaged card often means a unit that won't boot until it's re-imaged. So in normal use the card is read-only and every change goes to RAM instead.

| Mode | SD card | Unplug anytime? | Use for |
|---|---|---|---|
| **Read-only** (normal) | Read-only; changes are lost at power-off | Yes | Field use |
| **Maintenance** | Writable | No, shut down first | Adding media, updating, changing setup |
| **Debug** | Writable for one boot, then Read-only again | No, shut down first | Keeping the play log and system logs across a reboot |

Switch from the web UI (**Power-Pull Protection** panel) or over SSH:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh maintenance   # or: readonly, debug, status
```

Each switch reboots the unit. The OSD's top line shows the current mode: `Mode: READ-ONLY (safe to unplug)`, `Mode: MAINTENANCE (SD card writable)` or `Mode: DEBUG (logs kept this boot)`.

**Maintenance times out.** If nothing happens for 11 minutes 11 seconds (no web UI actions, no SSH/SFTP session, no `apt` or `git` running), the unit switches back to Read-only on its own and reboots. The OSD counts down: `Read-only in 10:42 if idle`. This keeps a unit that was left in Maintenance safe to unplug.

Settings changed in the web UI (OSD options, output mode, saved wifi networks) are written through to the card even in Read-only mode, so they survive power-off. The play log in Read-only mode lasts only until power-off; use Debug mode to keep it.

**Adding media after the build:** switch to Maintenance, copy the files, then switch back to Read-only.

## Updating

Updates need a writable card. Switch to Maintenance first, update, then switch back to Read-only (which reboots and starts everything fresh). If an update's notes say the sudo permissions changed, re-run [step 7](#7-allow-the-web-uis-restart-reboot-and-power-off-buttons) before switching back:

```bash
sudo bash ~/pi-vtg/services/vtg_mode.sh maintenance
```

After it reboots:

```bash
cd ~/pi-vtg
git pull
sudo systemctl daemon-reload
sudo bash ~/pi-vtg/services/vtg_mode.sh readonly
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
│   ├── vtg_mode.sh        read-only / maintenance / debug mode switching, clock set
│   ├── maint_timeout.sh   maintenance mode: back to read-only after 11:11 idle
│   ├── system_mode.py     reads the current mode (for the web UI and OSD)
│   ├── cec_control.py     cec-ctl wrapper used by the web UI
│   ├── cec_init.sh        registers both HDMI ports as CEC playback devices
│   ├── wifi_setup.sh      one-time: creates the wifi + hotspot profiles
│   ├── wifi_fallback.sh   boot-time wifi decision: any saved network in range, else hotspot
│   ├── wifi_ctl.sh        web UI wifi actions: scan, connect (with rollback), forget, hotspot
│   ├── patterns.py        alignment pattern generator (Pillow)
│   ├── signals.py         built-in audio test signals (noise, tones, sweep)
│   ├── display_info.py    EDID / display mode reader
│   ├── netcheck.py        wifi heartbeat (is the router answering?)
│   └── vtgctl.py          debug CLI
├── systemd/              service and timer units (symlinked into /etc/systemd/system)
├── media/                your media (not in git)
└── state/                saved OSD settings, output mode, play log (not in git)
```

Two long-running `mpv` processes do all playback, one for the display and one for the 3.5mm jack. Nothing restarts when you change modes. The web UI and OSD send commands over each player's IPC socket (`/tmp/vtg-display.sock` and `/tmp/vtg-audio.sock`), which keeps switching fast and lets audio and video run independently.

Service units launch scripts through `/bin/bash` instead of relying on executable permissions, so editing the code on Windows doesn't break anything. `.gitattributes` keeps line endings as LF.

## Known limitations

- **One HDMI output at a time.** True simultaneous dual output isn't possible with this design: on the Pi 4's driver, only one process can render to the display hardware at once. Supporting it would take a different architecture.
- **HDMI changes restart the player.** Plugging in, unplugging, a TV that drops HDMI when turned off, or moving the cable restarts the display player (about 5 to 10 seconds), and playback starts from the top of the video folder. Anything started from the web UI (images, a single file) has to be started again.
- **4K on a 1GB Pi 4 is too slow.** On the 1GB model the 4K test video played at about one-fifth speed (5 seconds to play 1 second). 4K plays smoothly on the 8GB model.
- **Images are scaled** to the current output mode. To show an image pixel-for-pixel, force a matching output mode in the Display panel.
- **Wifi is decided once per boot.** At boot the unit joins any saved network in range, otherwise it starts the hotspot. If a known network appears later, join it from the web UI.
- **WPA2/WPA3 personal and open networks only.** Enterprise (802.1X username/password) networks aren't supported from the web UI.

## Roadmap

- Physical buttons and a small LCD for on-device control
- Signage player mode
- 3D-printed case
- Separate 4K video playlist
- Dual HDMI output
- Raspberry Pi 3B+ support (full-size HDMI; 1080p H.264 only, no HEVC/4K)
- Audio adapter wiring guide: 3.5mm jack to XLR, 1/4" TS/TRS, RCA, and TRRS pinouts

## License

[MIT](LICENSE)
