# MouseWatch

Battery monitor for MCHOSE wireless mice via HID protocol.

## Protocol
- Reverse-engineered from MCHOSE WebHID configurator at `mchose.com.cn`
- JS bundles: `index-DSLdqrcq.js` (main logic), `index-Bb0fHRQi.js` (device list UI)
- Feature report `0x11 0x06`: get device status (VID, PID, FW, battery, charge). All data XOR 0xFF. Response after skipping 2 bytes: uint16 VID, uint16 PID, uint32 FW, bit3 connectMode, bit1 connectStatus, bit4 reserved, uint8 batteryLevel, uint8 chargeStatus
- Input report `0xE2`: real-time push from mouse. XOR 0xFF decoded. hidapi includes report ID as byte 0, so: [0]=reportID, [1]=0xE2, [2-3]=sub-type, [4]=chargeStatus, [5]=batteryLevel. WebHID strips the report ID so offsets differ by 1
- Usage page `0xFF01` works on Windows; `0xFF0B` gives read errors
- Dongle VIDs: `0x3837`, `0x41E4`, `0x0BDA`, `0x5253`
- Model identified by inner PID in status response, not dongle PID
- Wired USB: `0x11 0x06` returns all `0xFF` (no battery data). E2 input reports still work via dongle

## Dependencies
- `hidapi` — HID device communication
- `winotify` — Windows toast notifications
- `pystray` + `Pillow` — system tray icon
- `tkinter` — settings/debug windows (stdlib)

## Build
- PyInstaller: `python -m PyInstaller --onefile --noconsole --name MouseWatch mousewatch.py`
- Use `python -m PyInstaller` not bare `pyinstaller` — Microsoft Store Python doesn't put scripts on PATH

## Settings
- Config file: `%LOCALAPPDATA%\MouseWatch\settings.json`
- Loaded on startup; CLI args `--threshold`/`--interval` override config values
- Settings window opens from tray menu, writes config and updates app live
- Fields: `threshold` (1-100, default 20), `reminder_interval` (60-3600s, default 300), `poll_interval` (30-3600s, default 300), `notification_sound` (bool, default true), `device_notifications` (bool, default true), `start_with_windows` (bool, default false)
- Start with Windows: creates/removes `.lnk` via PowerShell `subprocess.run` (not `os.system` — quoting breaks with spaces in paths). Targets `python.exe` + script path when not frozen

## Key lessons
- Stale HID responses return all `0xFF` (decoded to `0x00`). Reject by checking VID/PID == 0. All-zero decoded data fakes `connect_mode=0` (wired) which suppresses low battery notifications — a silent failure mode
- hidapi `read()` includes report ID as byte 0; WebHID `data.buffer` does not. Off-by-one on all field offsets if not accounted for
- First HID feature report read after open returns stale data; do a throwaway read. 50ms delay needed between send/get
- On failed poll, retry up to 5 times with 2s gaps before keeping last good reading
- PowerShell commands with file paths containing spaces: use `subprocess.run(["powershell", "-NoProfile", "-Command", script])` with single quotes inside the script, never `os.system` with nested double quotes
- Windows HID allows multiple concurrent handles to the same device — input listener and poll loop can coexist
