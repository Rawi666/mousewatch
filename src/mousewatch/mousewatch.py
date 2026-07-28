"""MouseWatch - Battery monitor for MCHOSE wireless mice."""

import argparse
import os
import sys
import time

from common import Common
from hid_protocol import (
    MOUSE_DB,
    autodetect,
    find_mchose_devices,
    find_wired_mchose,
    pick_model,
    query_battery,
    safe_notify,
)
from mw_platform import IS_LINUX, IS_WINDOWS
from qt_tray_app import QtTrayApp
from settings_store import load_settings
from tray_app import TrayApp


def run_cli(model, hid_path, args):
    """Original CLI poll loop."""
    print(f"\nMonitoring MCHOSE {model}")
    print(f"  Threshold:  {args.threshold}%")
    print(f"  Interval:   {args.interval}s")
    if args.once:
        print("  Mode:       single query")
    print()

    notified_at = None

    while True:
        resp = query_battery(hid_path)
        if resp is None:
            print(f"[{time.strftime('%H:%M:%S')}] Failed to read battery "
                  "(mouse asleep or disconnected)")
        else:
            level, charging = Common.status_from_response(resp)
            status = "Charging" if charging else "Wireless"
            print(f"[{time.strftime('%H:%M:%S')}] Battery: {level}%  ({status})")

            if level <= args.threshold and not charging and notified_at != level:
                notified_at = level
                msg = f"MCHOSE {model} battery is at {level}%"
                print(f"  >> LOW BATTERY ALERT: {msg}")
                safe_notify("MouseWatch - Low Battery", msg)
            elif level > args.threshold:
                notified_at = None

        if args.once:
            break

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


def main():
    parser = argparse.ArgumentParser(
        description="MouseWatch - Battery monitor for MCHOSE wireless mice"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=int,
        default=None,
        help="Battery percentage to trigger alert (default: from config or 20)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        default=None,
        help="Polling interval in seconds (default: from config or 300)",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Mouse model name (skip auto-detection)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Query battery once and exit (CLI mode)",
    )
    parser.add_argument(
        "--nogui",
        action="store_true",
        help="Run in CLI mode (no system tray)",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Running from autostart (GUI waits for tray availability)",
    )
    args = parser.parse_args()
    stdin_is_interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())

    if (IS_LINUX and not args.nogui and not args.autostart
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))):
        print("No desktop session detected; switching to CLI mode (--nogui).")
        args.nogui = True

    # Load persisted settings, then let CLI args override
    settings = load_settings()
    if args.threshold is not None:
        settings["threshold"] = args.threshold
    if args.interval is not None:
        settings["poll_interval"] = args.interval

    if settings["threshold"] < 1 or settings["threshold"] > 100:
        print("Error: threshold must be between 1 and 100")
        sys.exit(1)

    # --once implies --nogui
    if args.once:
        args.nogui = True

    # ── Detect mouse ──
    hid_path = None
    resp = None
    model = args.model

    if model and model not in MOUSE_DB:
        print(f"Unknown model '{model}'. Use one of:")
        for name in sorted(MOUSE_DB.keys()):
            print(f"  {name}")
        sys.exit(1)

    if args.nogui:
        # CLI mode: interactive detection with prompts
        print("MouseWatch - MCHOSE Battery Monitor")
        print("=" * 40)

        if model is None:
            print("\nSearching for MCHOSE mouse...")
            result = autodetect(Common)
            if result:
                model, hid_path, resp = result
                print(f"  Detected: MCHOSE {model}")
                print(f"  Battery:  {resp['battery_level']}%")
                charging = resp["charge_status"] != 0 or resp["connect_mode"] == 0
                print(f"  Status:   {'Charging' if charging else 'Wireless'}")
                if stdin_is_interactive and not args.once:
                    print()
                    confirm = input("Is this correct? [Y/n] ").strip().lower()
                    if confirm and confirm != "y":
                        model = pick_model()
                        hid_path = None
            else:
                print("  No MCHOSE mouse detected automatically.")
                if args.once:
                    print("  Hint: if you see 'HID error: open failed', fix Linux hidraw permissions first.")
                    sys.exit(1)
                if not stdin_is_interactive:
                    print("  Cannot prompt for model selection in a non-interactive session.")
                    print("  Re-run interactively or pass --model to force a specific mouse model.")
                    sys.exit(1)
                model = pick_model()
    else:
        # GUI mode: silent auto-detection
        if model is None:
            result = autodetect(Common)
            if result:
                model, hid_path, resp = result
            else:
                wired = find_wired_mchose()
                if wired:
                    # Start in wired mode — no battery data yet,
                    # input listener will pick up E2 reports.
                    name = wired["name"].replace("MCHOSE ", "")
                    model = name or "Unknown"
                    hid_path = wired["path"]
                    resp = {
                        "battery_level": 0,
                        "charge_status": 1,
                        "connect_mode": 0,
                    }
                else:
                    msg = ("No MCHOSE mouse detected. Make sure it's connected "
                           "via the 2.4GHz dongle.")
                    safe_notify("MouseWatch", msg)
                    sys.exit(1)

    # ── Find HID path if not yet resolved ──
    if hid_path is None:
        devices = find_mchose_devices()
        for dev in devices:
            resp = Common.query_after_throwaway(dev["path"])
            if resp:
                hid_path = dev["path"]
                break
        if hid_path is None:
            msg = (f"Could not find HID device for MCHOSE {model}. "
                   "Make sure the mouse is connected via the 2.4GHz dongle.")
            if args.nogui:
                print(f"\n{msg}")
            else:
                safe_notify("MouseWatch", msg)
            sys.exit(1)

    # Get fresh reading for initial state (needed when HID path was found via manual pick)
    if resp is None:
        resp = Common.query_after_throwaway(hid_path)
        if resp is None:
            resp = Common.query_battery_retry(hid_path)
        if resp is None:
            msg = "Failed to read battery status."
            if args.nogui:
                print(msg)
            else:
                safe_notify("MouseWatch", msg)
            sys.exit(1)

    if args.nogui:
        # CLI mode uses threshold/interval from settings
        args.threshold = settings["threshold"]
        args.interval = settings["poll_interval"]
        run_cli(model, hid_path, args)
    else:
        if IS_WINDOWS:
            app = TrayApp(model, hid_path, resp, settings)
        else:
            app = QtTrayApp(model, hid_path, resp, settings, is_autostart=args.autostart)
        app.run()


if __name__ == "__main__":
    main()
