# MouseWatch

Battery monitor for MCHOSE wireless mice via HID protocol.

## Protocol
- Reverse-engineered from MCHOSE WebHID configurator at `mchose.com.cn`
- JS bundles analyzed: `index-DSLdqrcq.js` (main logic), `index-Bb0fHRQi.js` (device list UI)
- Command `0x11 0x06`: get device status (VID, PID, FW, battery, charge)
- All data bytes XOR 0xFF before send/receive
- Response parsed after skipping report ID + command echo byte (2 bytes)
- Response: uint16 VID, uint16 PID, uint32 FW, bit3 connectMode, bit1 connectStatus, bit4 reserved, uint8 batteryLevel, uint8 chargeStatus
- Usage page `0xFF01` works on Windows; `0xFF0B` gives read errors
- Dongle VIDs: `0x3837`, `0x41E4`, `0x0BDA`, `0x5253`
- Model identified by inner PID in status response, not dongle PID

## Dependencies
- `hidapi` — HID device communication
- `winotify` — Windows toast notifications
- `pystray` + `Pillow` — system tray icon
- `tkinter` — settings window (stdlib)

## Build
- PyInstaller: `python -m PyInstaller --onefile --noconsole --name MouseWatch mousewatch.py`

## Settings
- Config file: `%LOCALAPPDATA%\MouseWatch\settings.json`
- Loaded on startup; CLI args `--threshold`/`--interval` override config values
- Settings window opens from tray menu, writes config and updates app live
- Fields: `threshold` (1-100, default 20), `reminder_interval` (60-3600s, default 300), `poll_interval` (30-3600s, default 300), `notification_sound` (bool, default true), `start_with_windows` (bool, default false)
- Start with Windows: creates/removes `.lnk` in `%APPDATA%\...\Startup\` via PowerShell; targets `python.exe` + script path when not frozen, `sys.executable` when frozen

## Notifications
- Low battery: fires when level <= threshold and not charging, suppressed for `reminder_interval` seconds between repeats
- Fully charged: fires once when battery hits 100% while charging, resets when unplugged or drops below 100%
- Tray icon click: manual refresh — polls fresh data with retries, shows result with timestamp
- Sound toggle: `audio.Default` when on, `audio.Silent` when off

## Notes
- First HID read after open can return stale data; do a throwaway read
- 50ms delay needed between send_feature_report and get_feature_report
- Stale HID responses return all `0xFF` bytes (decoded to all `0x00`); rejected by checking VID/PID == 0
- On failed/stale poll, retries up to 5 times with 2s gaps before falling back to last good reading
