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
- `winotify` — Windows toast notifications (confirmed working)
- `pystray` + `Pillow` — system tray icon (planned)

## Build
- PyInstaller: `pyinstaller --onefile --noconsole --name MouseWatch mousewatch.py`

## Notes
- First HID read after open can return stale data; do a throwaway read
- 50ms delay needed between send_feature_report and get_feature_report
