# Viento recorder

Viento turns a recorded desktop session into a repeatable benchmark. A person uses
their applications as they normally would while the recorder captures every mouse
and keyboard event with its timing. Replaying the recording later reproduces the
same interaction, on the same or another Windows machine, while you measure the
system with the tools of your choice (HWiNFO, Windows performance counters, a
power meter, ...).

This is the recorder and replay engine used in the Viento study of benchmarking on
Windows 11 hybrid-core systems. It is built on
[PyMacroRecord](https://github.com/LOUDO56/PyMacroRecord) 1.4.2 by LOUDO56 and keeps
its user interface and macro format. The upstream README is kept in
[UPSTREAM_README.md](UPSTREAM_README.md).

## What was added to PyMacroRecord

| Feature | Purpose | Default |
|---|---|---|
| Display normalization | Each macro stores the screen resolution and Windows scale it was recorded at; both are applied before replay and restored afterwards. | on |
| Batch mode | Replays a list of macros unattended, one after another, with an optional time limit per macro. | – |
| Replay validation | For each macro you can name the application process; the run is PASS if the application has exited within a few seconds of the last event (the recorded session closes it) and FAIL otherwise. | – |
| Monitor hook | Starts any command-line telemetry tool before each macro and stops it afterwards, writing to one file per run. | off |
| Timing report | Every replay reports its duration against the schedule given by the recording (see *Timing*). | on |
| Absolute timing mode | Keeps every event on the recorded schedule instead of letting small delays accumulate. | off |
| Focus guard | Holds a click until the application that had the foreground when it was recorded is in the foreground again. | off |
| `tools/macro_info.py` | Summarises macro files without replaying them. | – |
| Safer macro loading | Special keys (`Key.ctrl_l`, ...) are looked up by name; a macro file can no longer execute code. | – |

With every optional feature left off, replay behaves as in the original recorder.

## Where the changes are

| File | Change |
|---|---|
| `src/macro/macro.py` | Display metadata at record time and display switching before replay; focus guard; timing modes and the timing report; safe key lookup; release of buttons still held when playback stops. |
| `src/utils/replay_timing.py` | New. Nominal schedule, timing modes and the timing report. |
| `src/utils/batch_config.py` | New. Batch-list parsing (text or JSON), output folders and the monitor command line. |
| `src/windows/main/main_app.py` | Batch mode: queueing, monitor start and stop, time limit, replay validation, summaries. |
| `src/main.py` | Command-line options (`--batch_mode`, `--batch_list`, `--test_type`); per-monitor DPI awareness. |
| `src/utils/user_settings.py` | Defaults for the new settings (`Focus_guard`, `Focus_guard_timeout`, `Timing_mode`, display restore). |
| `src/utils/get_file.py` | Resources are found relative to `src/`, so the program starts from any folder. |
| `tools/macro_info.py` | New. Inspects macro files. |
| `tests/` | New. Headless tests of the replay loop and the batch-list parser. |

Everything else is PyMacroRecord 1.4.2 unchanged.

## Requirements

- Windows 10 or 11. Recording and plain replay also work on Linux and macOS, as in
  PyMacroRecord, but display normalization and the focus guard use Windows APIs
  and are skipped elsewhere.
- Python 3.9 or newer.

```
pip install -r requirements.txt
python src/main.py
```

The program can be started from any folder. Settings are stored in
`%LOCALAPPDATA%\PyMacroRecord\userSettings.json`.

## Recording a session

1. Set the display to the resolution and scale you want to benchmark with. Use a
   single display.
2. Bring the system to the state the session should start from, for example with
   the application closed. Turn off notifications so no pop-up ends up in the
   recording.
3. Press the record button and use the application as you normally would.
4. End the session by closing the application. This leaves the system in the same
   state for the next run and lets replay validation check that the session
   completed.
5. Stop the recording and save it (`Ctrl+S`). Macros are plain JSON files (`.pmr`).

A recording contains everything that was typed. Do not record passwords or other
private data in macros that you intend to share.

## Replaying

- **Interactively:** load a macro (`Ctrl+L`) and press play. `F3` stops playback.
- **From the command line:** `python src/main.py path\to\session.pmr` opens the
  program with the macro loaded.
- **In batch mode:** see below.

Playback options (speed, repetitions, delay between repetitions) are under
*Options > Playback* and are saved inside the macro.

Before the first event is replayed, the recorder switches the display to the
resolution and scale stored in the macro and waits for it to settle. When the
program exits, the original settings are restored (*Options > Settings > Restore
original display on exit*). Windows applies some scale changes only after signing out and
in again; if the scale of the target machine differs from the recording, set it
once by hand.

## Batch mode

```
python src/main.py --batch_mode --batch_list examples\batch_example.json
python src/main.py --batch_mode --batch_list examples\batch_example.json --test_type run2
```

A batch list is either a text file with one macro per line
(`examples/batch_example.txt`) or a JSON file. The examples expect the recordings
in a `macros` folder next to `examples`:

```json
{
  "entries": [
    {"path": "../macros/word_session.pmr", "app": "WINWORD.EXE"},
    "../macros/photo_session.pmr"
  ],
  "data_dump_path": "C:/viento_runs",
  "test_type": "pluggedIn_bestPerf",
  "delay_between_macros": 15,
  "app_exit_timeout": 5,
  "limit_runs": true,
  "max_time": 600,
  "monitor_command": ["typeperf", "\\Processor(_Total)\\% Processor Time",
                      "-si", "1", "-f", "CSV", "-y", "-o", "{output}"],
  "clear_app_caches": false
}
```

| Key | Meaning | Default |
|---|---|---|
| `entries` | Macros to play, in order. Either a path or `{"path": ..., "app": ...}`, where `app` is the process to check after the run. Relative paths are resolved against the folder of the list file. | – |
| `data_dump_path`, `test_type` | Output goes to `<data_dump_path>/<test_type>/`. `--test_type` on the command line overrides the file. | none |
| `delay_between_macros` | Pause between two macros, in seconds. | 15 |
| `app_exit_timeout` | Time the application may take to exit after the last replayed event before the run counts as FAIL, in seconds. | 5 |
| `limit_runs`, `max_time` | Stop a macro after `max_time` seconds. | off |
| `monitor_command` | Command started 5 s before each macro and stopped after it. `{output}` becomes `<data_dump_path>/<test_type>/<name>.csv`, `{name}` the run name (the `app` without `.exe`, or the macro file name). | none |
| `monitor_cwd` | Working folder of the monitor. | folder of the command |
| `clear_app_caches` | After the batch, delete Word and Excel AutoRecovery files and Illustrator caches, so the next batch does not start with recovery prompts. Only enable this on a dedicated benchmarking machine. | off |

The monitor is stopped with a console interrupt (Ctrl+C), followed by Ctrl+Break,
terminate and kill if it does not exit. Its console output is written to
`monitor_<name>_stdout.txt` and `monitor_<name>_stderr.txt` in the output folder.

At the end of a batch the program writes `macro_summary.txt` and
`macro_summary.json` to the output folder and exits. For every macro the summary
holds the PASS/FAIL result, start and end time, the timing report and the
focus-guard log.

## A typical measurement

1. On the machine under test, install the applications used in the recordings at
   the same versions, and set the power plan and other system settings you want to
   measure under.
2. Copy the macros to a `macros` folder and check them:
   `python tools\macro_info.py macros\*.pmr`.
3. Write a batch list naming each macro, the application process to validate, the
   output folder and, optionally, a telemetry command (`monitor_command`). If the
   telemetry tool cannot be started from the command line, start it by hand
   before the batch.
4. Run the batch, for example three times with different `--test_type` values.
   Leave the machine alone while it runs.
5. Check `macro_summary.txt`: every run should be PASS, and the timing excess
   should be similar across repetitions. A run that is FAIL, or whose excess stands
   out, did not reproduce the session and should be repeated before its telemetry
   is used.
6. Compare systems on the measured quantities (for example energy per session or
   the distribution of package power) only where the difference is larger than the
   spread between repetitions on the same machine.

## Timing

A macro stores, for every event, the delay δ<sub>i</sub> since the previous
event. With playback speed *s* the recording defines the nominal schedule

    T_nominal = (1/s) · Σ δ_i

and a replay of *N* events takes

    T_replay = T_nominal + N · ε

where ε is the average cost of issuing one event (injecting it and waking from
the sleep before it). Every replay prints a line such as

```
[timing] completed; mode relative; T_replay 612.418s vs nominal 598.025s (excess +14.393s, +2.41%, 0.531 ms/event)
```

| Field | Meaning |
|---|---|
| `replay_s`, `nominal_s` | Measured duration and nominal schedule, excluding pauses between repetitions. |
| `excess_s`, `excess_pct` | `replay_s − nominal_s` minus time held by the focus guard. |
| `overhead_ms_per_event` | ε, the excess divided by the number of events. |
| `focus_guard_holds`, `focus_guard_timeouts`, `focus_guard_hold_s` | See *Focus guard*. |
| `max_lag_s` | Absolute mode only: the furthest the replay fell behind its schedule. |

A large excess means that the machine could not keep up with the input stream,
which is itself a useful observation when comparing two systems.

Two timing modes are available:

- `relative` (default): each event waits its recorded delay after the previous one
  was issued, as in PyMacroRecord. The per-event cost accumulates over the session.
- `absolute`: each event waits until its scheduled time from the start of the
  replay, so the per-event cost does not accumulate. Time spent in a focus-guard
  hold shifts the rest of the schedule.

Select the mode with `"Others": {"Timing_mode": "absolute"}` in
`userSettings.json` or, for one run, `set VIENTO_TIMING=absolute`.

## Focus guard

Replay is open loop: the recorder does not look at the screen. On a machine slower
than the one used for recording, a click can arrive before the window it was meant
for. With the focus guard enabled, every recorded click remembers which
application had the foreground at that moment, and during replay the click is
held until that application is in the foreground again, for at most a timeout.
Other events keep their recorded timing. Every hold and every timeout is printed
and stored in the batch summary.

```
set VIENTO_FOCUS_GUARD=1
set VIENTO_FOCUS_GUARD_TIMEOUT=5
```

or `"Others": {"Focus_guard": true, "Focus_guard_timeout": 5}` in
`userSettings.json`. Only macros recorded with this version carry the
foreground information; for older macros the guard has no effect.

## Macro files

A `.pmr` file is JSON:

```json
{
  "events": [
    {"type": "cursorMove", "x": 812, "y": 455, "timestamp": 0.0081},
    {"type": "leftClickEvent", "x": 812, "y": 455, "pressed": true,
     "timestamp": 0.4312, "fg_process": "winword.exe"},
    {"type": "keyboardEvent", "key": "Key.ctrl_l", "pressed": true, "timestamp": 0.2104},
    {"type": "scrollEvent", "dx": 0, "dy": -1, "timestamp": 0.0503}
  ],
  "recording_display": {"resolution": {"width": 1920, "height": 1080}, "scale_percent": 100},
  "settings": {"Playback": {"Speed": 1, "Repeat": {"Times": 1}}}
}
```

`timestamp` is the delay in seconds since the previous event. Coordinates are
physical pixels: the recorder runs as a per-monitor DPI-aware process.

To check macros before a long batch:

```
python tools\macro_info.py macros\*.pmr
```

prints the number of events by type, the recorded and nominal replay duration, the
recording display, how many clicks carry focus-guard information, and any key the
player would not recognise (exit status 1). Use `--json` for machine-readable
output and `--speed` to override the speed stored in the macro.

## Tests

```
python -m unittest discover -s tests -v
```

The tests run the replay loop and the batch-list parser without a display:
the user interface is stubbed and the mouse and keyboard are replaced by
recorders. On Linux without a display, set `PYNPUT_BACKEND=dummy`.

## Limitations

- A macro acts on the user interface. It replays correctly on another machine when
  the software environment matches the recording: the same application versions,
  window layout, and display resolution and scale. The processor and the rest of
  the hardware may differ.
- One display. Multi-monitor layouts are not normalized.
- Live content (web pages, video calls) differs between runs by nature; repeat
  such sessions and compare the spread between replays.

## Citing

If you use this tool in your research, please cite:

N. Narayana GS, A. Yue, S. Mehta, and X. Martorell, "Viento ⇒ Opening Windows to
Benchmarking Methodology on Modern Client Systems."

The citation is also available in [CITATION.cff](CITATION.cff).

## License

GNU General Public License v3.0, as PyMacroRecord. See [LICENSE.md](LICENSE.md).
The user interface, macro format and the original recorder are the work of
LOUDO56 and the PyMacroRecord contributors.
