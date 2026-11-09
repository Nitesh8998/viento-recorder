"""Batch lists: which macros to replay, in which order, and how each run is set up.

A batch list is either a text file (one macro per line, optionally followed by
", <process name>") or a JSON file:

    {
      "entries": ["macros/word.pmr", {"path": "macros/chrome.pmr", "app": "chrome"}],
      "data_dump_path": "D:/viento_runs",          # where per-run output goes
      "test_type": "pluggedIn_bestPerf",            # sub-folder of data_dump_path
      "delay_between_macros": 15,                   # seconds between two macros
      "app_exit_timeout": 5,                        # seconds the app may take to exit
      "limit_runs": false, "max_time": 300,         # optional per-macro time limit
      "monitor_command": ["C:/tools/mon.exe", "{output}"],   # optional, see below
      "monitor_cwd": "C:/tools",
      "clear_app_caches": false
    }

Relative macro paths are resolved against the folder of the list file.

The optional monitor is any command-line program that samples telemetry while a
macro plays. It is started before each macro and stopped (console interrupt,
then terminate) after it. In its arguments, "{output}" is replaced by
<data_dump_path>/<test_type>/<name>.csv and "{name}" by the run name (the
expected process name without ".exe", or the macro file name).
"""
import json
from os import path
from sys import platform

DEFAULT_CONFIG = {
    "data_dump_path": None,
    "test_type": None,
    "limit_runs": False,
    "max_time": None,
    "delay_between_macros": 15,
    "app_exit_timeout": 5,
    "monitor_command": None,
    "monitor_cwd": None,
    "monitor_log_prefix": "monitor",
    "clear_app_caches": False,
}
_PATH_KEYS = ("data_dump_path", "monitor_cwd")


def sanitize_path(p):
    """Undo JSON escape accidents (e.g. "\\t" read as a tab) and normalise separators."""
    try:
        if p is None:
            return p
        p = p.replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')
        p = p.replace('/', '\\') if platform.lower() == "win32" else p
        return path.normpath(p)
    except Exception:
        return p


def load_batch_list(list_file_path, test_type_override=None):
    """Return (config, entries). Entries are dicts {"path": ..., "app": ... or None}.
    On a malformed file the entry list is empty."""
    base_dir = path.dirname(path.abspath(list_file_path))
    config = dict(DEFAULT_CONFIG)
    entries = []

    def resolve(p):
        return p if path.isabs(p) else path.normpath(path.join(base_dir, p))

    try:
        if list_file_path.lower().endswith('.json'):
            with open(list_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data:
                        val = data[key]
                        if key in _PATH_KEYS and isinstance(val, str):
                            val = sanitize_path(val)
                        config[key] = val
            items = data.get('entries', data) if isinstance(data, dict) else data
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        entries.append({"path": resolve(item), "app": None})
                    elif isinstance(item, dict) and 'path' in item:
                        entries.append({"path": resolve(item['path']), "app": item.get('app')})
        else:
            with open(list_file_path, 'r', encoding='utf-8-sig') as f:
                for ln in (line.strip() for line in f):
                    if not ln or ln.startswith('#'):
                        continue
                    parts = [p.strip() for p in ln.split(',', 1)]
                    app_name = parts[1] if len(parts) > 1 and parts[1] else None
                    entries.append({"path": resolve(parts[0]), "app": app_name})
    except Exception as e:
        print(f"[batch] Could not read batch list {list_file_path}: {e}")
        entries = []
    if test_type_override:
        config["test_type"] = test_type_override
    return config, entries


def run_name(expected_app=None, macro_path=None):
    """Name used for a run's output files."""
    if expected_app:
        name = expected_app.strip()
        if platform.lower() == "win32" and name.lower().endswith('.exe'):
            name = name[:-4]
        return name
    if macro_path:
        return path.splitext(path.basename(macro_path))[0]
    return "macro_output"


def output_dir(config):
    """<data_dump_path>/<test_type>, or None if either is unset."""
    root, test_type = config.get("data_dump_path"), config.get("test_type")
    if not root or not test_type:
        return None
    return path.join(sanitize_path(root), test_type)


def monitor_invocation(config, expected_app=None, macro_path=None):
    """Return (args, cwd, out_dir, name) for the monitor of one run, or None if no monitor is configured.
    When no output folder is configured, "{output}" arguments are dropped."""
    cmd = config.get("monitor_command")
    if not cmd:
        return None
    if isinstance(cmd, str):
        cmd = [cmd]
    name = run_name(expected_app, macro_path)
    out = output_dir(config)
    out_csv = path.join(out, name + ".csv") if out else None
    args = []
    for a in cmd:
        a = str(a)
        if "{output}" in a:
            if out_csv is None:
                # without an output folder the monitor is launched without its output arguments
                args = args[:1]
                break
            a = a.replace("{output}", out_csv)
        args.append(a.replace("{name}", name))
    cwd = config.get("monitor_cwd") or (path.dirname(args[0]) or None)
    return args, cwd, out, name
