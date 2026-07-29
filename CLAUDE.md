# MouseWatch

Battery monitor for wireless mice via HID protocol. Runs on Windows and Linux.

Supported protocols/devices in current codebase:
- MCHOSE (multiple models via inner PID mapping)
- ATK A9 Plus (dongle + wired IDs recognized)

## Architecture (current)
- `src/mousewatch/mchose_protocol.py`: MCHOSE-only protocol implementation.
- `src/mousewatch/protocols.py`: protocol adapter abstraction + registry + ATK implementation.
- `src/mousewatch/common.py`: shared runtime logic (polling/listener/reconnect) and shared notification helpers.
- `src/mousewatch/device_ids.py`: centralized USB VID/PID catalog used by all protocols.

Protocol abstraction introduced:
- `MouseProtocolAdapter` contract used by runtime flows.
- `MchoseProtocolAdapter` wraps MCHOSE-specific behavior.
- `AtkProtocolAdapter` implements ATK-specific behavior.
- `mousewatch.py` now supports `--protocol auto|mchose|atk`.
- Diagnostic probe mode: `--probe` prints candidate interfaces and query/frame results.

## MCHOSE protocol
- Reverse-engineered from MCHOSE WebHID configurator at `mchose.com.cn`
- JS bundles: `index-DSLdqrcq.js` (main logic), `index-Bb0fHRQi.js` (device list UI)
- Feature report `0x11 0x06`: get device status (VID, PID, FW, battery, charge). All data XOR 0xFF. Response after skipping 2 bytes: uint16 VID, uint16 PID, uint32 FW, bit3 connectMode, bit1 connectStatus, bit4 reserved, uint8 batteryLevel, uint8 chargeStatus
- Input report `0xE2`: real-time push from mouse. XOR 0xFF decoded. hidapi includes report ID as byte 0, so: [0]=reportID, [1]=0xE2, [2-3]=sub-type, [4]=chargeStatus, [5]=batteryLevel. WebHID strips the report ID so offsets differ by 1
- Usage page `0xFF01` works on Windows; `0xFF0B` gives read errors
- Dongle VIDs: `0x3837`, `0x41E4`, `0x0BDA`, `0x5253`
- Model identified by inner PID in status response, not dongle PID
- Wired USB: `0x11 0x06` returns all `0xFF` (no battery data). E2 input reports still work via dongle

## ATK protocol (implemented)
- Source basis: `libatk-rs` command framing and behavior.
- Vendor/Product IDs recognized:
	- `VID 0x373B, PID 0x10C9` (NANO dongle)
	- `VID 0x373B, PID 0x1115` (wired mouse)
- Query command currently used:
	- Report ID: `0x08`
	- Command frame length: `0x10` bytes
	- Command ID: `0x04` (GetBatteryLevel)
	- Frame checksum: `0x55 - (sum(report_id + frame fields) & 0xFF)`
- Response parsing currently used:
	- `data[0]`: battery percent
	- `data[1]`: charge status
	- `data[2] / 10.0`: voltage
	- `data_len` respected for field availability
- Interface selection note (Linux): the working battery interface for A9 Plus dongle has been observed at `usage_page=0x000C, usage=0x0001, iface=1`; other interfaces may enumerate but not answer battery query.

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
- udev rules needed for non-root access include:
	- `KERNEL=="hidraw*", ATTRS{idVendor}=="3837", MODE="0666", TAG+="uaccess"`
	- `KERNEL=="hidraw*", ATTRS{idVendor}=="373B", MODE="0666", TAG+="uaccess"`

## Device ID catalog
- All USB VID/PID constants are centralized in `src/mousewatch/device_ids.py`.
- `mchose_protocol.py` imports MCHOSE IDs from that catalog.
- `protocols.py` imports ATK IDs from that catalog.
- Goal: adding a new vendor/device starts with one file update.

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
- PyInstaller: `python -m PyInstaller --onefile --noconsole --name MouseWatch src/mousewatch/mousewatch.py`
- Use `python -m PyInstaller` not bare `pyinstaller` — Microsoft Store Python doesn't put scripts on PATH

## Key lessons
- Stale HID responses return all `0xFF` (decoded to `0x00`). Reject by checking VID/PID == 0. All-zero decoded data fakes `connect_mode=0` (wired) which suppresses low battery notifications — a silent failure mode
- hidapi `read()` includes report ID as byte 0; WebHID `data.buffer` does not. Off-by-one on all field offsets if not accounted for
- First HID feature report read after open returns stale data; do a throwaway read. 50ms delay needed between send/get
- On failed poll, retry up to 5 times with 2s gaps before keeping last good reading
- PowerShell commands with file paths containing spaces: use `subprocess.run(["powershell", "-NoProfile", "-Command", script])` with single quotes inside the script, never `os.system` with nested double quotes
- Windows HID allows multiple concurrent handles to the same device — input listener and poll loop can coexist
- Linux `pystray._xorg` backend reports `HAS_MENU=False` — right-click menus do not work; this is why PySide6 is used on Linux instead
- `QSystemTrayIcon` tray title must be ASCII-safe; em dash (`-`) in place of non-ASCII punctuation avoids xorg latin-1 encoder issues
- Qt dialogs must never be created from a non-main thread; use Qt signals to marshal state changes back to the main thread
- `subprocess.CREATE_NO_WINDOW` does not exist on Linux; use `getattr(subprocess, "CREATE_NO_WINDOW", 0)` for cross-platform safety
- ATK path stability after wired/wireless transitions:
	- Never switch paths via unordered set iteration.
	- Keep protocol adapter ordering for candidate paths.
	- On query failure, actively probe alternate candidate interfaces and switch to first successful responder.
