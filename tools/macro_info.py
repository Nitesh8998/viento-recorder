#!/usr/bin/env python3
"""Inspect PyMacroRecord/Viento macro files (.pmr) without replaying them.

For each macro: event counts by type, nominal replay duration (Eq. 1 schedule, from the
macro's embedded playback speed or --speed), the recording display (resolution, scale),
how many clicks carry focus-guard metadata, and any special key name that the player
would not resolve. Exit status is 1 if any macro has an unresolvable key.

    python tools/macro_info.py final_macros/*.pmr
    python tools/macro_info.py --speed 1 --json macro.pmr
"""
import argparse, collections, json, os, sys

import importlib.util  # noqa: E402

# Load src/utils/replay_timing.py directly: the utils package __init__ pulls in the GUI (tkinter).
_spec = importlib.util.spec_from_file_location(
    "replay_timing", os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "src", "utils", "replay_timing.py"))
_rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rt)
nominal_schedule = _rt.nominal_schedule

# Special keys accepted by the player on Windows (pynput Key members of the win32 backend).
KNOWN_KEYS = {
    "alt", "alt_l", "alt_r", "alt_gr", "backspace", "caps_lock", "cmd", "cmd_l", "cmd_r", "ctrl", "ctrl_l",
    "ctrl_r", "delete", "down", "end", "enter", "esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
    "f10", "f11", "f12", "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20", "f21", "f22", "f23", "f24", "home", "left", "page_down",
    "page_up", "right", "shift", "shift_l", "shift_r", "space", "tab", "up", "media_play_pause",
    "media_volume_mute", "media_volume_down", "media_volume_up", "media_previous", "media_next", "insert",
    "menu", "num_lock", "pause", "print_screen", "scroll_lock",
}


def inspect(path, speed=None):
    with open(path, "r", encoding="utf-8") as fh:
        macro = json.load(fh)
    events = macro.get("events", [])
    settings = macro.get("settings", {}) or {}
    s = speed if speed is not None else (settings.get("Playback", {}) or {}).get("Speed", 1)
    fixed = (settings.get("Others", {}) or {}).get("Fixed_timestamp", 0) or 0
    n, nominal = nominal_schedule(events, s, fixed)
    types = collections.Counter(e.get("type") for e in events)
    presses = [e for e in events if e.get("type", "").endswith("ClickEvent") and e.get("pressed")]
    bad_keys = sorted({e["key"] for e in events if e.get("type") == "keyboardEvent" and isinstance(e.get("key"), str)
                       and "Key." in e["key"] and e["key"].split("Key.", 1)[1] not in KNOWN_KEYS})
    gaps = sorted(e.get("timestamp", 0) for e in events if e.get("type") == "cursorMove")
    return {
        "file": path,
        "events": n,
        "by_type": dict(types),
        "speed": s,
        "fixed_delay_s": fixed,
        "recorded_s": round(sum(abs(e.get("timestamp", 0)) for e in events), 3),
        "nominal_replay_s": round(nominal, 3),
        "median_mouse_move_gap_ms": round(1000 * gaps[len(gaps) // 2], 2) if gaps else None,
        "recording_display": macro.get("recording_display"),
        "clicks": len(presses),
        "clicks_with_focus_metadata": sum(1 for e in presses if e.get("fg_process")),
        "unresolvable_keys": bad_keys,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("macros", nargs="+")
    ap.add_argument("--speed", type=float, default=None, help="override the embedded playback speed")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args(argv)
    rows = [inspect(p, a.speed) for p in a.macros]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            disp = r["recording_display"] or {}
            res = disp.get("resolution") or {}
            print(f"{r['file']}: {r['events']} events {r['by_type']}")
            print(f"  recorded {r['recorded_s']:.1f}s, nominal replay {r['nominal_replay_s']:.1f}s at speed {r['speed']}"
                  f"; median mouse-move gap {r['median_mouse_move_gap_ms']} ms")
            print(f"  display {res.get('width')}x{res.get('height')} @ {disp.get('scale_percent')}%"
                  f"; clicks {r['clicks']} ({r['clicks_with_focus_metadata']} with focus metadata)")
            if r["unresolvable_keys"]:
                print(f"  UNRESOLVABLE KEYS: {r['unresolvable_keys']}")
    return 1 if any(r["unresolvable_keys"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
