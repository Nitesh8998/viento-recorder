"""Replay timing model and per-replay timing report.

A macro is a list of events, each carrying the delay ``timestamp`` (seconds) since the
previous event. With playback speed factor ``s`` the nominal replay schedule is

    T_nominal = (1/s) * sum_i delta_i        (or N * fixed_delay when a fixed delay is set)

and the measured session time is T_replay = T_nominal + N * eps, where eps is the mean
per-event overhead (event injection plus sleep granularity). The report below gives
T_replay, T_nominal and eps for every replay, so these figures of merit are produced by
the tool itself rather than reconstructed afterwards.

Timing modes (``userSettings["Others"]["Timing_mode"]`` or env ``VIENTO_TIMING``):
  * ``relative`` (default): open loop, every event waits its own delay after the previous
    event was issued. This is the original PyMacroRecord behaviour; overheads accumulate.
  * ``absolute``: every event waits until its scheduled time t0 + sum of delays so far,
    so overheads do not accumulate; time spent in focus-guard holds shifts the schedule.
"""
import os

TIMING_MODES = ("relative", "absolute")


def timing_mode(settings_dict):
    others = (settings_dict or {}).get("Others", {}) or {}
    mode = str(others.get("Timing_mode", "relative")).strip().lower()
    env = os.environ.get("VIENTO_TIMING")
    if env:
        mode = env.strip().lower()
    return mode if mode in TIMING_MODES else "relative"


def event_delay(event, speed, fixed_timestamp=0):
    """Delay before ``event`` exactly as the player computes it."""
    if fixed_timestamp and fixed_timestamp > 0:
        d = fixed_timestamp
    else:
        d = event.get("timestamp", 0) * (1 / speed)
    return abs(d)


def nominal_schedule(events, speed, fixed_timestamp=0):
    """Return (number of events, nominal duration in seconds) of one repetition."""
    n = len(events)
    total = sum(event_delay(e, speed, fixed_timestamp) for e in events)
    return n, total


def build_report(*, completed, repetitions, n_events, nominal_s, actual_s, speed, mode,
                 guard_hold_s=0.0, guard_holds=0, guard_timeouts=0, max_lag_s=None):
    """Summarise one playback (all repetitions). ``actual_s`` excludes inter-repetition delays."""
    issued = n_events * repetitions
    nominal_total = nominal_s * repetitions
    excess = actual_s - nominal_total - guard_hold_s
    report = {
        "completed": bool(completed),
        "timing_mode": mode,
        "speed": speed,
        "repetitions": repetitions,
        "events_per_repetition": n_events,
        "nominal_s": round(nominal_total, 3),
        "replay_s": round(actual_s, 3),
        "focus_guard_hold_s": round(guard_hold_s, 3),
        "focus_guard_holds": guard_holds,
        "focus_guard_timeouts": guard_timeouts,
        "excess_s": round(excess, 3),
        "excess_pct": round(100.0 * excess / nominal_total, 2) if nominal_total > 0 else None,
        "overhead_ms_per_event": round(1000.0 * excess / issued, 4) if issued else None,
    }
    if max_lag_s is not None:
        report["max_lag_s"] = round(max_lag_s, 4)
    return report


def format_report(r):
    s = (f"[timing] {'completed' if r['completed'] else 'stopped'}; mode {r['timing_mode']}; "
         f"T_replay {r['replay_s']:.3f}s vs nominal {r['nominal_s']:.3f}s "
         f"(excess {r['excess_s']:+.3f}s")
    if r.get("excess_pct") is not None:
        s += f", {r['excess_pct']:+.2f}%"
    if r.get("overhead_ms_per_event") is not None:
        s += f", {r['overhead_ms_per_event']:.3f} ms/event"
    s += ")"
    if r.get("focus_guard_holds") or r.get("focus_guard_timeouts"):
        s += f"; focus guard {r['focus_guard_holds']} holds ({r['focus_guard_hold_s']:.2f}s), {r['focus_guard_timeouts']} timeouts"
    if "max_lag_s" in r:
        s += f"; max lag {1000 * r['max_lag_s']:.1f} ms"
    return s
