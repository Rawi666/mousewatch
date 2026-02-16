# MouseWatch

Battery monitor for MCHOSE wireless mice. Runs as a Windows system tray application — the tray icon shows the current battery percentage and changes color based on level. Click the icon to refresh and see the latest status. Right-click for settings and other options.

## Supported mice

M7, M7 Pro, M7 Ultra, L7, L7 Pro, L7 Pro+, L7 Ultra, L7 Ultra+, A7, A7 Pro, A7 Ultra, A7 Ultra(RE), A7 V2 Pro, A7 V2 Pro+, A7 V2 Ultra, A7 V2 Ultra+, A7X Ultra, K7 Ultra, A5 V2 Ultra, AX5 V2, G3 Ultra 8K, G3 Ultra 4K

## Quick start

```
pip install -r requirements.txt
python mousewatch.py
```

## Usage

```
python mousewatch.py                # auto-detect mouse, monitor in system tray
python mousewatch.py --once         # print battery once and exit
python mousewatch.py -t 15          # set low battery threshold to 15%
python mousewatch.py -i 60          # poll every 60 seconds
python mousewatch.py -m "L7 Ultra+" # skip auto-detection
```

## Settings

Right-click the tray icon and select "Settings" to configure:

- **Battery threshold** — percentage to trigger low battery alert (1-100%, default 20%)
- **Reminder interval** — minimum time between repeated low battery notifications (default 300s)
- **Poll interval** — how often to check the battery (default 300s)
- **Notification sound** — toggle toast notification sound on/off
- **Start with Windows** — automatically launch on login

Settings are saved to `%LOCALAPPDATA%\MouseWatch\settings.json` and persist across restarts. CLI arguments (`--threshold`, `--interval`) override saved settings when provided.

## Notifications

- **Low battery** — fires when battery drops below threshold (not while charging)
- **Fully charged** — fires once when battery reaches 100% while charging
- **Device connect/disconnect** — notifies when mouse USB state changes (toggleable)
- **Charge state changes** — real-time notification when cable is plugged/unplugged

## Wired mode

If the mouse is connected via USB cable at startup (no dongle), the app launches in charging mode and updates in real-time via HID input reports. Battery percentage polling requires the 2.4GHz dongle.

## Install as startup app

```
install.bat
```

This builds a standalone `MouseWatch.exe` and adds it to Windows startup. Run `uninstall.bat` to remove.

## How it works

Communicates with the mouse via HID through the 2.4GHz USB dongle. Uses two channels:
- **Feature reports** (`0x11 0x06`) — periodic polling for battery level and status
- **Input reports** (`0xE2`) — real-time push notifications for charge state changes

The protocol was reverse-engineered from the MCHOSE web configurator.
