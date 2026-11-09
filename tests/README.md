# tests/

Headless tests; no display or input injection is needed.

- `test_playback.py` runs the replay loop with the user interface stubbed and the mouse and
  keyboard replaced by recorders: timing report, speed factor, absolute timing mode, special-key
  lookup, and button release when playback is stopped. Setting `PYMACRO_ORIG_SRC` to the `src/`
  folder of an earlier version also checks that the default mode issues exactly the same event
  sequence as that version.
- `test_batch_config.py` covers batch-list parsing and the monitor command line.

```
python -m unittest discover -s tests -v
```

On Linux without a display, set `PYNPUT_BACKEND=dummy`.
