# tools/

- `macro_info.py` summarises macro files without replaying them: events by type, recorded and
  nominal replay duration, recording display, focus-guard coverage of clicks, and special keys
  the player would not recognise (exit status 1). `--json` for machine-readable output, `--speed`
  to override the playback speed stored in the macro.

```
python tools/macro_info.py macros/*.pmr
```
