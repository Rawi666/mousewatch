# MouseWatch

Battery monitor for MCHOSE wireless mice. Shows battery level in the system tray and sends a Windows notification when battery is low.

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

## Install as startup app

```
install.bat
```

This builds a standalone `MouseWatch.exe` and adds it to Windows startup. Run `uninstall.bat` to remove.

## How it works

Communicates with the mouse via HID feature reports through the 2.4GHz USB dongle. The protocol was reverse-engineered from the MCHOSE web configurator.
