"""Headless tests of the playback loop (macro.Macro.__play_events) with fake input controllers.

No GUI, display or input injection is needed: tkinter and the GUI-only helpers are stubbed,
and mouse/keyboard controllers are replaced by recorders. Run from the PyMacroRecord folder:

    python -m unittest discover -s tests -v

Set PYMACRO_ORIG_SRC to the src/ folder of a previous version to also check that the default
(relative) timing mode issues exactly the same event sequence as that version.
"""
import importlib, os, sys, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, os.pardir, "src")
os.environ.setdefault("PYNPUT_BACKEND", "dummy")  # pynput without a display (Linux CI)


def load_macro_module(src):
    """Import macro/macro.py from `src` with GUI dependencies stubbed."""
    for name in [m for m in sys.modules if m in ("macro", "macro.macro") or m == "utils" or m.startswith("utils.")]:
        del sys.modules[name]
    tk = types.ModuleType("tkinter"); tk.messagebox = types.SimpleNamespace(showerror=lambda *a, **k: None)
    sys.modules["tkinter"] = tk; sys.modules["tkinter.messagebox"] = tk.messagebox
    utils = types.ModuleType("utils"); utils.__path__ = [os.path.join(src, "utils")]; sys.modules["utils"] = utils
    for mod, attrs in {"utils.record_file_management": {"RecordFileManagement": lambda *a: None},
                       "utils.show_toast": {"show_notification_minim": lambda *a: None},
                       "utils.warning_pop_up_save": {"confirm_save": lambda *a: True}}.items():
        m = types.ModuleType(mod); m.__dict__.update(attrs); sys.modules[mod] = m
    pkg = types.ModuleType("macro"); pkg.__path__ = [os.path.join(src, "macro")]; sys.modules["macro"] = pkg
    return importlib.import_module("macro.macro")


class FakeController:
    def __init__(self, log, cost=0.0):
        self.log, self.cost = log, cost
    def _do(self, *ev):
        if self.cost:
            time.sleep(self.cost)  # simulated injection overhead
        self.log.append(ev)
    @property
    def position(self): return (0, 0)
    @position.setter
    def position(self, xy): self._do("move", *xy)
    def press(self, b): self._do("press", str(b))
    def release(self, b): self._do("release", str(b))
    def scroll(self, dx, dy): self._do("scroll", dx, dy)


def settings(mode="relative", speed=1.0):
    return {"Playback": {"Speed": speed, "Repeat": {"Times": 1, "For": 0, "Interval": 0, "Delay": 0, "Scheduled": 0,
                                                   "Infinite": False}},
            "Others": {"Fixed_timestamp": 0, "Focus_guard": False, "Focus_guard_timeout": 5, "Timing_mode": mode},
            "Minimization": {"When_Playing": False}, "After_Playback": {"Mode": "Idle"}}


def make_events(n=60, gap=0.004):
    ev = []
    for i in range(n):
        ev.append({"type": "cursorMove", "x": i, "y": i, "timestamp": gap})
        if i % 15 == 5:
            ev.append({"type": "leftClickEvent", "x": i, "y": i, "pressed": True, "timestamp": gap})
            ev.append({"type": "leftClickEvent", "x": i, "y": i, "pressed": False, "timestamp": gap})
        if i % 20 == 7:
            ev.append({"type": "keyboardEvent", "key": "Key.ctrl_l", "pressed": True, "timestamp": gap})
            ev.append({"type": "keyboardEvent", "key": "a", "pressed": True, "timestamp": gap})
            ev.append({"type": "keyboardEvent", "key": "a", "pressed": False, "timestamp": gap})
            ev.append({"type": "keyboardEvent", "key": "Key.ctrl_l", "pressed": False, "timestamp": gap})
    ev.append({"type": "scrollEvent", "dx": 0, "dy": -1, "timestamp": gap})
    return ev


def run(mod, events, cfg, cost=0.0, stop_after=None):
    M = mod.Macro
    m = M.__new__(M)
    log = []
    m.mouseControl = FakeController(log, cost); m.keyboardControl = FakeController(log, cost)
    m.user_settings = types.SimpleNamespace(settings_dict=cfg)
    m.macro_events = {"events": events}
    m.playback = True
    m._update_status_safe = lambda *a: None
    m.focus_guard_log = []
    stops = []
    def stop_playback(manual=False):
        m.playback = False; stops.append(manual)
    m.stop_playback = stop_playback
    if not hasattr(m, "_focus_guard_settings"):
        m._focus_guard_settings = lambda: (False, 0)
    if stop_after is not None:
        import threading
        threading.Timer(stop_after, lambda: setattr(m, "playback", False)).start()
    t0 = time.perf_counter()
    m._Macro__play_events()
    return m, log, time.perf_counter() - t0


class PlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_macro_module(SRC)

    def test_relative_mode_report(self):
        ev = make_events()
        m, log, wall = run(self.mod, ev, settings("relative"))
        r = m.last_replay_report
        self.assertTrue(r["completed"]); self.assertEqual(r["timing_mode"], "relative")
        self.assertEqual(r["events_per_repetition"], len(ev))
        self.assertAlmostEqual(r["nominal_s"], 0.004 * len(ev), places=6)
        self.assertGreaterEqual(r["replay_s"], r["nominal_s"])  # open loop never runs ahead
        self.assertLessEqual(abs(r["replay_s"] - wall), 0.05)

    def test_speed_factor_scales_nominal(self):
        ev = make_events(30)
        m, _, _ = run(self.mod, ev, settings("relative", speed=2.0))
        self.assertAlmostEqual(m.last_replay_report["nominal_s"], 0.002 * len(ev), places=6)

    def test_absolute_mode_removes_accumulated_overhead(self):
        ev = make_events(80, gap=0.005)
        cost = 0.002  # 2 ms injection cost per event
        rel, log_r, _ = run(self.mod, ev, settings("relative"), cost=cost)
        ab, log_a, _ = run(self.mod, ev, settings("absolute"), cost=cost)
        self.assertEqual(log_r, log_a)  # same events, same order
        er, ea = rel.last_replay_report["excess_s"], ab.last_replay_report["excess_s"]
        self.assertGreater(er, 0.5 * cost * len(ev))  # overhead accumulates open loop
        self.assertLess(ea, 0.25 * er)                # but not on the absolute schedule
        self.assertIn("max_lag_s", ab.last_replay_report)

    def test_special_keys_resolved_without_eval(self):
        from pynput.keyboard import Key
        for name in ("ctrl_l", "shift", "enter", "esc", "tab", "backspace", "cmd", "alt_l", "f5", "page_down"):
            self.assertIs(self.mod.Macro._special_key(f"Key.{name}"), getattr(Key, name))
        for bad in ("Key.__class__", "Key.ctrl_l; import os", "Key.not_a_key"):
            with self.assertRaises(AttributeError):
                self.mod.Macro._special_key(bad)

    def test_right_button_released_only_if_held(self):
        ev = [{"type": "rightClickEvent", "x": 1, "y": 1, "pressed": True, "timestamp": 0.001},
              {"type": "cursorMove", "x": 2, "y": 2, "timestamp": 0.3},
              {"type": "rightClickEvent", "x": 2, "y": 2, "pressed": False, "timestamp": 0.001}]
        m, log, _ = run(self.mod, ev, settings(), stop_after=0.1)  # stopped while the button is down
        self.assertFalse(m.last_replay_report["completed"])
        self.assertIn(("release", "Button.right"), log)
        m, log, _ = run(self.mod, ev[:1] + [dict(ev[2], timestamp=0.001)], settings())  # pressed and released
        self.assertEqual(log.count(("release", "Button.right")), 1)

    @unittest.skipUnless(os.environ.get("PYMACRO_ORIG_SRC"), "set PYMACRO_ORIG_SRC to compare with a previous version")
    def test_default_mode_matches_previous_version(self):
        ev = make_events(100, gap=0.002)
        _, new_log, _ = run(self.mod, ev, settings("relative"))
        orig = load_macro_module(os.environ["PYMACRO_ORIG_SRC"])
        _, old_log, _ = run(orig, ev, settings("relative"))
        type(self).mod = load_macro_module(SRC)
        self.assertEqual(new_log, old_log)


if __name__ == "__main__":
    unittest.main()
