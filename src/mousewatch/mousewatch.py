"""MouseWatch - Battery monitor for MCHOSE wireless mice."""

import argparse
import os
import sys
import time

from common import Common
from common import safe_notify
from mw_platform import IS_LINUX, IS_WINDOWS
from protocols import (
    autodetect_any,
    get_protocol_by_key,
    get_protocol_keys,
    get_protocol_order,
)
from qt_tray_app import QtTrayApp
from settings_store import load_settings
from tray_app import TrayApp


def run_cli(protocol, model, hid_path, args):
    """Original CLI poll loop."""
    print(f"\nMonitoring {protocol.format_model_name(model)}")
    print(f"  Threshold:  {args.threshold}%")
    print(f"  Interval:   {args.interval}s")
    if args.once:
        print("  Mode:       single query")
    print()

    notified_at = None

    while True:
        resp = protocol.query_battery(hid_path)
        if resp is None:
            print(f"[{time.strftime('%H:%M:%S')}] Failed to read battery "
                  "(mouse asleep or disconnected)")
        else:
            level, charging = Common.status_from_response(protocol, resp)
            status = "Charging" if charging else "Wireless"
            print(f"[{time.strftime('%H:%M:%S')}] Battery: {level}%  ({status})")

            if level <= args.threshold and not charging and notified_at != level:
                notified_at = level
                msg = f"{protocol.format_model_name(model)} battery is at {level}%"
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


def run_probe(protocol):
    print(f"MouseWatch Probe - {protocol.display_name}")
    print("=" * 40)

    devices = protocol.discover_devices()
    if not devices:
        print("No candidate HID devices found.")
        return 1

    for index, dev in enumerate(devices, 1):
        path = dev.get("path")
        product = dev.get("product_string") or "?"
        pid = dev.get("product_id", 0)
        usage_page = dev.get("usage_page", 0)
        usage = dev.get("usage", 0)
        iface = dev.get("interface_number", "?")
        print(f"\n[{index}] product={product}")
        print(f"    pid=0x{int(pid):04X} usage_page=0x{int(usage_page):04X} usage=0x{int(usage):04X} iface={iface}")

        if path is None:
            print("    path=<missing>")
            continue

        resp = Common.query_after_throwaway(protocol, path, settle_delay=0.05)
        if resp is None:
            print("    query: no response")
            continue

        level, charging = Common.status_from_response(protocol, resp)
        print(f"    query: battery={level}% charging={charging}")

        raw_frame = resp.get("raw_frame")
        if isinstance(raw_frame, list):
            print("    frame:", " ".join(f"{b:02X}" for b in raw_frame))

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="MouseWatch - Battery monitor for wireless mice"
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
        "-p", "--protocol",
        type=str,
        default="auto",
        help=(
            "Mouse protocol to use "
            f"(auto|{'|'.join(get_protocol_keys())})"
        ),
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
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe matching HID interfaces for the selected protocol and exit",
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
    protocol = None

    selected_protocol_key = None if args.protocol == "auto" else args.protocol.strip().lower()
    selected_protocol = None if selected_protocol_key is None else get_protocol_by_key(selected_protocol_key)
    if selected_protocol_key is not None and selected_protocol is None:
        print(f"Unknown protocol '{args.protocol}'. Use one of: auto, {', '.join(get_protocol_keys())}")
        sys.exit(1)

    if selected_protocol is not None:
        protocols = [selected_protocol]
    else:
        protocols = get_protocol_order(None)

    if args.probe:
        if selected_protocol is not None:
            sys.exit(run_probe(selected_protocol))

        exit_code = 0
        for probe_protocol in protocols:
            code = run_probe(probe_protocol)
            if code != 0:
                exit_code = code
            print()
        sys.exit(exit_code)

    if model is not None:
        matching_protocols = [p for p in protocols if p.is_known_model(model)]
        if not matching_protocols:
            print(f"Unknown model '{model}'.")
            if selected_protocol_key is None:
                print("Try one of the known models for your preferred protocol.")
            else:
                assert selected_protocol is not None
                known = selected_protocol.list_models()
                print(f"Known models for {selected_protocol_key}:")
                for name in known:
                    print(f"  {name}")
            sys.exit(1)
        protocol = matching_protocols[0]

    detected = autodetect_any(Common, protocols)
    if detected is not None:
        detected_protocol, detected_model, detected_path, detected_resp = detected
        if protocol is None:
            protocol = detected_protocol
        if model is None:
            model = detected_model
        hid_path = detected_path
        resp = detected_resp

    if protocol is None:
        protocol = protocols[0]

    if args.nogui:
        # CLI mode: interactive detection with prompts
        print("MouseWatch - Battery Monitor")
        print("=" * 40)

        if model is None or hid_path is None or resp is None:
            print(f"\nSearching for {protocol.display_name} mouse...")
            result = protocol.autodetect(Common)
            if result:
                model, hid_path, resp = result
                print(f"  Detected: {protocol.format_model_name(model)}")
                print(f"  Battery:  {resp['battery_level']}%")
                _level, charging = Common.status_from_response(protocol, resp)
                print(f"  Status:   {'Charging' if charging else 'Wireless'}")
                if stdin_is_interactive and not args.once:
                    print()
                    confirm = input("Is this correct? [Y/n] ").strip().lower()
                    if confirm and confirm != "y":
                        model = protocol.pick_model()
                        hid_path = None
                        resp = None
            else:
                print(f"  No {protocol.display_name} mouse detected automatically.")
                if args.once:
                    print("  Hint: if you see 'HID error: open failed', fix Linux hidraw permissions first.")
                    sys.exit(1)
                if not stdin_is_interactive:
                    print("  Cannot prompt for model selection in a non-interactive session.")
                    print("  Re-run interactively or pass --model to force a specific mouse model.")
                    sys.exit(1)
                model = protocol.pick_model()
    else:
        # GUI mode: silent auto-detection
        if model is None or hid_path is None or resp is None:
            result = protocol.autodetect(Common)
            if result:
                model, hid_path, resp = result
            else:
                wired = protocol.find_wired_device()
                if wired:
                    # Start in wired mode — no battery data yet,
                    # input listener will pick up E2 reports.
                    name = (wired["name"] or "").replace(f"{protocol.display_name} ", "")
                    model = name or "Unknown"
                    hid_path = wired["path"]
                    resp = {
                        "battery_level": 0,
                        "charge_status": 1,
                        "connect_mode": 0,
                        "device_online": True,
                    }
                else:
                    if model is None:
                        model = "Unknown"
                    hid_path = None
                    resp = {
                        "battery_level": 0,
                        "charge_status": 0,
                        "connect_mode": 1,
                        "device_online": False,
                    }

    # ── Find HID path if not yet resolved ──
    if hid_path is None and args.nogui:
        devices = protocol.discover_devices()
        for dev in devices:
            resp = Common.query_after_throwaway(protocol, dev["path"])
            if resp:
                hid_path = dev["path"]
                break
        if hid_path is None:
            msg = (f"Could not find HID device for {protocol.format_model_name(model)}. "
                   "Make sure the mouse is connected via the 2.4GHz dongle.")
            if args.nogui:
                print(f"\n{msg}")
            else:
                safe_notify("MouseWatch", msg)
            sys.exit(1)

    # Get fresh reading for initial state (needed when HID path was found via manual pick)
    if resp is None and args.nogui:
        if hid_path is None:
            msg = "Failed to read battery status."
            print(msg)
            sys.exit(1)
        resp = Common.query_after_throwaway(protocol, hid_path)
        if resp is None:
            resp = Common.query_battery_retry(protocol, hid_path)
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
        run_cli(protocol, model, hid_path, args)
    else:
        if IS_WINDOWS:
            app = TrayApp(protocol, model, hid_path, resp, settings, available_protocols=protocols)
        else:
            app = QtTrayApp(
                protocol,
                model,
                hid_path,
                resp,
                settings,
                is_autostart=args.autostart,
                available_protocols=protocols,
            )
        app.run()


if __name__ == "__main__":
    main()
