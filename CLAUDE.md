# MouseWatch

Battery monitor for MCHOSE wireless mice via HID protocol. Runs on Windows and Linux.

## Protocol
- Reverse-engineered from MCHOSE WebHID configurator at `mchose.com.cn`
- JS bundles: `index-DSLdqrcq.js` (main logic), `index-Bb0fHRQi.js` (device list UI)
- Feature report `0x11 0x06`: get device status (VID, PID, FW, battery, charge). All data XOR 0xFF. Response after skipping 2 bytes: uint16 VID, uint16 PID, uint32 FW, bit3 connectMode, bit1 connectStatus, bit4 reserved, uint8 batteryLevel, uint8 chargeStatus
- Input report `0xE2`: real-time push from mouse. XOR 0xFF decoded. hidapi includes report ID as byte 0, so: [0]=reportID, [1]=0xE2, [2-3]=sub-type, [4]=chargeStatus, [5]=batteryLevel. WebHID strips the report ID so offsets differ by 1
- Usage page `0xFF01` works on Windows; `0xFF0B` gives read errors
- Dongle VIDs: `0x3837`, `0x41E4`, `0x0BDA`, `0x5253`
- Model identified by inner PID in status response, not dongle PID
- Wired USB: `0x11 0x06` returns all `0xFF` (no battery data). E2 input reports still work via dongle

## Platform notes
- **Windows**: uses `pystray` + `tkinter` for tray/settings/debug UI; `winotify` for toast notifications
- **Linux**: uses `PySide6` (`QSystemTrayIcon`) for tray/settings/debug UI; `notify-send` for desktop notifications
- Platform detection at module level via `IS_WINDOWS` / `IS_LINUX`; PySide6 imports gated with `if not IS_WINDOWS:`; Qt classes inside same guard so they are never evaluated on Windows

## Dependencies (platform-split)
- `hidapi` — HID device communication (both platforms)
- `Pillow` — tray icon badge rendering (both platforms)
- `winotify` — Windows toast notifications (`sys_platform == "win32"` only)
- `pystray` — Windows system tray (`sys_platform == "win32"` only)
- `PySide6` — Linux system tray + dialogs (`sys_platform != "win32"` only)
- `tkinter` — Windows settings/debug windows (stdlib)

## Linux HID backend
- The `hidapi` pip package bundles a libusb backend (`hid` module) that cannot open hidraw nodes on Linux even with correct permissions
- The same package also ships a `hidraw` module that works correctly on Linux
- At startup, Linux always imports `hidraw as hid`; other platforms import `hid`
- hidraw paths are `/dev/hidraw*`; Linux `hidapi` returns them when enumerated via hidraw backend
- Linux hidapi enumerates with `usage_page=0` (not `0xFF01`); detection allows both
- udev rule needed for non-root access: `KERNEL=="hidraw*", ATTRS{idVendor}=="3837", MODE="0666", TAG+="uaccess"`

## Tray icon badge
- PIL draws a 256×256 RGBA image: thin ellipse outline + centered percentage text
- Color: green if `level > threshold`, red otherwise
- Windows: PIL image passed directly to `pystray.Icon`
- Linux: image downsampled to multiple sizes (16, 22, 24, 32, 48, 64 px) and packaged as a multi-resolution `QIcon`; helps KDE Plasma pick the right size

## Settings
- **Windows** config: `%LOCALAPPDATA%\MouseWatch\settings.json`
- **Linux** config: `~/.config/mousewatch/settings.json` (XDG-aware; respects `XDG_CONFIG_HOME`)
- Loaded on startup; CLI args `--threshold`/`--interval` override config values
- Settings window opens from tray menu (or Qt dialog on Linux), writes config and updates app live
- Fields: `threshold` (1-100, default 20), `reminder_interval` (60-3600s, default 300), `poll_interval` (30-3600s, default 300), `notification_sound` (bool, default true), `device_notifications` (bool, default true), `start_with_windows` (bool, default false)
- Start with Windows (Windows): creates/removes `.lnk` via PowerShell `subprocess.run`
- Start on login (Linux): creates/removes `~/.config/autostart/mousewatch.desktop` (XDG autostart spec)

## Build
- PyInstaller: `python -m PyInstaller --onefile --noconsole --name MouseWatch mousewatch.py`
- Use `python -m PyInstaller` not bare `pyinstaller` — Microsoft Store Python doesn't put scripts on PATH

## Key lessons
- Stale HID responses return all `0xFF` (decoded to `0x00`). Reject by checking VID/PID == 0. All-zero decoded data fakes `connect_mode=0` (wired) which suppresses low battery notifications — a silent failure mode
- hidapi `read()` includes report ID as byte 0; WebHID `data.buffer` does not. Off-by-one on all field offsets if not accounted for
- First HID feature report read after open returns stale data; do a throwaway read. 50ms delay needed between send/get
- On failed poll, retry up to 5 times with 2s gaps before keeping last good reading
- PowerShell commands with file paths containing spaces: use `subprocess.run(["powershell", "-NoProfile", "-Command", script])` with single quotes inside the script, never `os.system` with nested double quotes
- Windows HID allows multiple concurrent handles to the same device — input listener and poll loop can coexist
- Linux `pystray._xorg` backend reports `HAS_MENU=False` — right-click menus do not work; this is why PySide6 is used on Linux instead
- `QSystemTrayIcon` tray title must be ASCII-safe; em dash (`—`) crashes the xorg backend's latin-1 encoder
- Qt dialogs must never be created from a non-main thread; use Qt signals to marshal state changes back to the main thread
- `subprocess.CREATE_NO_WINDOW` does not exist on Linux; use `getattr(subprocess, "CREATE_NO_WINDOW", 0)` for cross-platform safety
