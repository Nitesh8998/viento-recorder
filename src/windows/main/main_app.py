import copy
import json
import sys
from json import load
from os import path, environ, listdir, remove, walk, makedirs
from os.path import join as join_path
import shutil
from sys import platform, argv
from threading import Thread
from time import time, sleep
from datetime import datetime
from tkinter import *
import subprocess
import signal

from PIL import Image
from pystray import Icon
from pystray import MenuItem

from hotkeys.hotkeys_manager import HotkeysManager
from macro import Macro
from utils.get_file import resource_path
from utils.not_windows import NotWindows
from utils.record_file_management import RecordFileManagement
from utils.replay_timing import format_report
from utils.batch_config import load_batch_list, monitor_invocation, output_dir
from utils.user_settings import UserSettings
from utils.version import Version
from utils.warning_pop_up_save import confirm_save
from windows.main.menu_bar import MenuBar
from windows.others.new_ver_avalaible import NewVerAvailable
from windows.window import Window

if platform.lower() == "win32":
    from tkinter.ttk import *

def deepcopy_dict_missing_entries(dst:dict,src:dict):
# recursively copy entries that are in src but not in dst
    for k,v in src.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(v,dict):
            deepcopy_dict_missing_entries(dst[k],v)

class MainApp(Window):
    """Main windows of the application"""

    def __init__(self, batch_mode:bool=False, batch_list:str=None, test_type:str=None):
        super().__init__("PyMacroRecord", 350, 200)
        self.attributes("-topmost", 1)
        if platform == "win32":
            self.iconbitmap(resource_path(path.join("assets", "logo.ico")))

        self.settings = UserSettings(self)

        self.load_language()

        # For save message purpose
        self.macro_saved = False
        self.macro_recorded = False
        self.current_file = None
        self.prevent_record = False

        self.version = Version(self.settings.settings_dict, self)

        self.menu = MenuBar(self)  # Menu Bar
        self.macro = Macro(self)

        self.validate_cmd = self.register(self.validate_input)

        self.hotkeyManager = HotkeysManager(self)

        self.status_text = Label(self, text='', relief=SUNKEN, anchor=W)
        if self.settings.settings_dict["Recordings"]["Show_Events_On_Status_Bar"]:
            self.status_text.pack(side=BOTTOM, fill=X)

        # Main Buttons (Start record, stop record, start playback, stop playback)

        # Play Button
        self.playImg = PhotoImage(file=resource_path(path.join("assets", "button", "play.png")))

        self.center_frame = Frame(self)
        self.center_frame.pack(expand=True, fill=BOTH)

        # Determine mode: batch vs normal
        self._batch_mode = batch_mode
        self.playBtn = Button(self.center_frame, image=self.playImg, state=DISABLED)

        if batch_mode and batch_list:
            self._start_batch_from_list(batch_list, test_type_override=test_type)
            print(f"Batch mode: playing list {batch_list}")
            if test_type:
                print(f"Test type override: {test_type}")
        else:
            # Fallback: legacy single-arg open (maintain behavior if launched with a file argument)
            if len(argv) > 1:
                arg_path = sys.argv[1]
                if arg_path.lower().endswith('.txt') or arg_path.lower().endswith('.json'):
                    self._start_batch_from_list(arg_path, test_type_override=test_type)
                    print(f"Batch mode (list): playing list {arg_path}")
                    if test_type:
                        print(f"Test type override: {test_type}")
                else:
                    try:
                        with open(sys.argv[1], 'r') as record:
                            loaded_content = load(record)
                        self.macro.import_record(loaded_content)
                        self.playBtn.configure(state=NORMAL, command=self.macro.start_playback)
                        self.macro_recorded = True
                        self.macro_saved = True
                        self.current_file = arg_path
                        print(f"Loaded macro: {self.current_file}")
                    except Exception as e:
                        print(f"Failed to load macro '{arg_path}': {e}")

        
        self.playBtn.pack(side=LEFT, padx=50)

        # Record Button
        self.recordImg = PhotoImage(file=resource_path(path.join("assets", "button", "record.png")))
        self.recordBtn = Button(self.center_frame, image=self.recordImg, command=self.macro.start_record)
        self.recordBtn.pack(side=RIGHT, padx=50)

        # Stop Button
        self.stopImg = PhotoImage(file=resource_path(path.join("assets", "button", "stop.png")))

        record_management = RecordFileManagement(self, self.menu)

        self.bind('<Control-Shift-S>', record_management.save_macro_as)
        self.bind('<Control-s>', record_management.save_macro)
        self.bind('<Control-l>', record_management.load_macro)
        self.bind('<Control-n>', record_management.new_macro)

        self.protocol("WM_DELETE_WINDOW", self.quit_software)
        if platform.lower() != "darwin":
            Thread(target=self.systemTray).start()

        self.attributes("-topmost", 0)

        if platform != "win32" and self.settings.first_time:
            NotWindows(self)

        if self.settings.settings_dict["Others"]["Check_update"]:
            if self.version.new_version != "" and self.version.version != self.version.new_version:
                if time() > self.settings.settings_dict["Others"]["Remind_new_ver_at"]:
                    NewVerAvailable(self, self.version.new_version)
        self.mainloop()

    def _start_batch_from_list(self, list_file_path:str, test_type_override:str=None):
        """Read a batch list (.txt or .json, see utils/batch_config.py) and replay its macros one by one.

        Args:
            list_file_path: Path to the batch list file
            test_type_override: If provided, overrides test_type from the JSON config
        """
        self._batch_config, entries = load_batch_list(list_file_path, test_type_override)
        if not entries:
            print(f"[batch] No macros to play in {list_file_path}")
            return

        self._batch_queue = entries
        self._batch_results = []
        self._record_mgmt = RecordFileManagement(self, self.menu)
        self._monitor_proc = None
        self._monitor_log_threads = []
        self._monitor_log_files = []

        def _start_monitor(expected_app_name:str=None, fallback_macro_path:str=None):
            """Start the configured telemetry monitor for one run; returns True if started or not needed."""
            try:
                invocation = monitor_invocation(self._batch_config, expected_app_name, fallback_macro_path)
                if invocation is None:
                    return True
                args, cwd, out_dir, name = invocation
                prefix = self._batch_config.get("monitor_log_prefix") or "monitor"
                stdout_log = None
                stderr_log = None
                stdout_path = None
                stderr_path = None
                if out_dir:
                    try:
                        makedirs(out_dir, exist_ok=True)
                        stdout_path = path.join(out_dir, f"{prefix}_{name}_stdout.txt")
                        stderr_path = path.join(out_dir, f"{prefix}_{name}_stderr.txt")
                        stdout_log = open(stdout_path, 'a', encoding='utf-8', buffering=1)
                        stderr_log = open(stderr_path, 'a', encoding='utf-8', buffering=1)
                    except Exception as e:
                        print(f"[monitor] Could not prepare output folder: {e}")
                else:
                    print("[monitor] No data_dump_path/test_type configured; monitor output is not redirected")
                # New process group so that a console interrupt can be sent to it
                creationflags = 0
                if platform.lower() == "win32":
                    creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                print(f"[monitor] Starting: {' '.join(args)} (cwd={cwd})")
                self._monitor_proc = subprocess.Popen(
                    args, cwd=cwd, creationflags=creationflags,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )

                def _pipe_reader(pipe, sink_file=None):
                    # Monitor output goes to its log files only, not to the console
                    try:
                        for raw in iter(pipe.readline, b""):
                            line = raw.decode(errors='ignore').rstrip()
                            if line and sink_file is not None:
                                try:
                                    sink_file.write(line + "\n")
                                except Exception:
                                    pass
                    except Exception:
                        pass
                for pipe, sink in ((self._monitor_proc.stdout, stdout_log), (self._monitor_proc.stderr, stderr_log)):
                    if pipe:
                        t = Thread(target=_pipe_reader, args=(pipe, sink), daemon=True)
                        t.start()
                        self._monitor_log_threads.append(t)
                for f in (stdout_log, stderr_log):
                    if f is not None:
                        self._monitor_log_files.append(f)
                if stdout_path or stderr_path:
                    print(f"[monitor] Logging to: {stdout_path or '-'} ; {stderr_path or '-'}")
                print("[monitor] Started")
                return True
            except Exception as e:
                print(f"[monitor] Failed to start: {e}")
                self._monitor_proc = None
                return False

        def _stop_monitor():
            """Stop the monitor: console interrupt (twice), then break, terminate and kill as fallbacks."""
            try:
                if not self._monitor_proc:
                    return
                def _wait_for_exit(timeout_s:float) -> bool:
                    waited = 0.0
                    step = 0.1
                    while waited < timeout_s and self._monitor_proc and self._monitor_proc.poll() is None:
                        sleep(step)
                        waited += step
                    is_exited = self._monitor_proc is None or self._monitor_proc.poll() is not None
                    print(f"[monitor] Wait result: exited={is_exited}, waited={waited:.1f}s")
                    return is_exited

                if platform.lower() == "win32":
                    try:
                        print(f"[monitor] Sending CTRL_C_EVENT (1/2) to PID {self._monitor_proc.pid}")
                        self._monitor_proc.send_signal(signal.CTRL_C_EVENT)
                    except Exception as e:
                        print(f"[monitor] CTRL_C_EVENT (1) failed: {e}")
                    _wait_for_exit(5.0)
                    if self._monitor_proc and self._monitor_proc.poll() is None:
                        try:
                            print(f"[monitor] Sending CTRL_C_EVENT (2/2) to PID {self._monitor_proc.pid}")
                            self._monitor_proc.send_signal(signal.CTRL_C_EVENT)
                        except Exception as e:
                            print(f"[monitor] CTRL_C_EVENT (2) failed: {e}")
                        _wait_for_exit(5.0)
                    # Fallback: try CTRL_BREAK_EVENT
                    if self._monitor_proc and self._monitor_proc.poll() is None:
                        try:
                            print(f"[monitor] Sending CTRL_BREAK_EVENT (fallback) to PID {self._monitor_proc.pid}")
                            self._monitor_proc.send_signal(signal.CTRL_BREAK_EVENT)
                        except Exception as e:
                            print(f"[monitor] CTRL_BREAK_EVENT failed: {e}")
                        _wait_for_exit(5.0)
                else:
                    try:
                        print(f"[monitor] Sending SIGINT (1/2) to PID {self._monitor_proc.pid}")
                        self._monitor_proc.send_signal(signal.SIGINT)
                    except Exception as e:
                        print(f"[monitor] SIGINT (1) failed: {e}")
                    _wait_for_exit(2.0)
                    if self._monitor_proc and self._monitor_proc.poll() is None:
                        try:
                            print(f"[monitor] Sending SIGINT (2/2) to PID {self._monitor_proc.pid}")
                            self._monitor_proc.send_signal(signal.SIGINT)
                        except Exception as e:
                            print(f"[monitor] SIGINT (2) failed: {e}")
                        _wait_for_exit(2.0)
                
                # Last resort: terminate/kill
                if self._monitor_proc and self._monitor_proc.poll() is None:
                    try:
                        print(f"[monitor] Terminating process (fallback) PID {self._monitor_proc.pid}")
                        self._monitor_proc.terminate()
                    except Exception:
                        pass
                    _wait_for_exit(2.0)
                if self._monitor_proc and self._monitor_proc.poll() is None:
                    try:
                        print(f"[monitor] Killing process (final) PID {self._monitor_proc.pid}")
                        self._monitor_proc.kill()
                    except Exception:
                        pass
                print("[monitor] Stop sequence completed")
                # Close any open log files
                try:
                    for f in self._monitor_log_files:
                        try:
                            f.flush()
                            f.close()
                        except Exception:
                            pass
                    self._monitor_log_files = []
                except Exception:
                    pass
            except Exception:
                pass

        def play_next():
            if not hasattr(self, '_batch_queue') or len(self._batch_queue) == 0:
                if hasattr(self, '_batch_mode') and self._batch_mode:
                    # Print summary before closing
                    if hasattr(self, '_batch_results'):
                        print("Batch results:")
                        summary_lines = ["Batch results:"]
                        for item in self._batch_results:
                            app = item.get('app') or '-'
                            start_time = item.get('start_time', 'N/A')
                            end_time = item.get('end_time', 'N/A')
                            duration = item.get('duration', 0)
                            duration_str = f"{duration:.3f}s" if isinstance(duration, (int, float)) else str(duration)
                            result_line = f" - {item['path']} [{app}] => {item['result']}"
                            timestamp_line = f"   Start: {start_time}, End: {end_time}, Duration: {duration_str}"
                            print(result_line)
                            print(timestamp_line)
                            summary_lines.append(result_line)
                            summary_lines.append(timestamp_line)
                            timing = item.get('timing')
                            if timing:
                                timing_line = "   " + format_report(timing)
                                print(timing_line)
                                summary_lines.append(timing_line)
                        
                        # Save summary to file in test_type directory
                        self._save_batch_summary(summary_lines, self._batch_results)
                    # Optionally clear Office/Illustrator recovery files so the next batch starts without recovery prompts
                    if (self._batch_config or {}).get("clear_app_caches"):
                        print("\nClearing application caches...")
                        self._clear_application_caches()
                    # Close app when batch mode finishes
                    self.after(0, lambda: self.quit_software(force=True))
                return
            entry = self._batch_queue.pop(0)
            next_path = entry["path"]
            expected_app = entry.get("app")
            try:
                # Load with settings
                self._record_mgmt.load_macro_from_path(next_path, import_settings=True)
            except Exception:
                # Skip invalid entries and continue
                self.after(0, play_next)
                return

            # Start the monitor if configured, then wait 5 seconds and start playback
            _start_monitor(expected_app_name=expected_app, fallback_macro_path=next_path)
            sleep(5)
            # Record start timestamp
            macro_start_time = datetime.now()
            macro_start_timestamp = macro_start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"Playing macro: {next_path}")
            print(f"  Start time: {macro_start_timestamp}")
            self.macro.start_playback()

            # If limit_runs is enabled, enforce a timeout watchdog for this macro
            limit_enabled = bool((self._batch_config or {}).get("limit_runs"))
            max_time = (self._batch_config or {}).get("max_time")
            if limit_enabled and isinstance(max_time, (int, float)) and max_time > 0:
                start_ts = time()

                def watchdog():
                    # Periodically check elapsed time while playback is active
                    if not self.macro.playback:
                        return
                    elapsed = time() - start_ts
                    if elapsed >= max_time:
                        print(f"[batch] Max time reached ({max_time}s). Stopping playback.")
                        try:
                            # Only stop playback; let normal post-playback flow handle cleanup and next steps
                            self.macro.stop_playback(playback_stopped_manually=False)
                        except Exception:
                            pass
                        return
                    # Re-arm watchdog check
                    self.after(250, watchdog)

                # Kick off the watchdog checks shortly after start
                self.after(250, watchdog)


            report_wait = {"polls": 0}

            def wait_until_done():
                if self.macro.playback:
                    self.after(250, wait_until_done)
                elif self.macro.last_replay_report is None and report_wait["polls"] < 40:
                    # Stopped from outside (watchdog/manual): give the playback thread time to
                    # leave its current event and write the timing report (at most 10 s).
                    report_wait["polls"] += 1
                    self.after(250, wait_until_done)
                else:
                    # Record end timestamp
                    macro_end_time = datetime.now()
                    macro_end_timestamp = macro_end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    duration = (macro_end_time - macro_start_time).total_seconds()
                    print(f"  End time: {macro_end_timestamp}")
                    print(f"  Duration: {duration:.3f} seconds")
                    def record_result(app_name, result):
                        self._batch_results.append({
                            "path": next_path,
                            "app": app_name,
                            "result": result,
                            "start_time": macro_start_timestamp,
                            "end_time": macro_end_timestamp,
                            "duration": duration,
                            "timing": self.macro.last_replay_report,
                            "focus_guard": list(self.macro.focus_guard_log),
                        })
                        # Stop the monitor after the macro completes
                        _stop_monitor()
                        # Proceed to next macro after configurable delay
                        delay_ms = int((self._batch_config or {}).get("delay_between_macros", 15) * 1000)
                        self.after(delay_ms, play_next)

                    if not expected_app:
                        record_result(None, "PASS")
                        return
                    # The recorded session ends by closing the application. The last event only
                    # starts the shutdown, so give the process up to app_exit_timeout seconds to
                    # exit before deciding; the check is polled so the user interface stays responsive.
                    app_name = self._normalize_app_name(expected_app)
                    exit_timeout = float((self._batch_config or {}).get("app_exit_timeout", 5) or 0)
                    exit_deadline = time() + exit_timeout

                    def check_exit():
                        if not self._is_app_running(app_name):
                            print(f"Test PASSED for app '{app_name}' — no process found")
                            record_result(app_name, "PASS")
                        elif time() < exit_deadline:
                            self.after(250, check_exit)
                        else:
                            print(f"Test FAILED for app '{app_name}' — process still running "
                                  f"{exit_timeout:g} s after the replay ended")
                            self._kill_app(app_name)
                            record_result(app_name, "FAIL")
                    check_exit()
            self.after(250, wait_until_done)

            
        # Kick off
        self.after(0, play_next)

    def load_language(self):
        self.lang = self.settings.settings_dict["Language"]
        with open(resource_path(path.join('langs', self.lang + '.json')), encoding='utf-8') as f:
            self.text_content = json.load(f)
        self.text_content = self.text_content["content"]

        if self.lang != "en":
            with open(resource_path(path.join('langs', 'en.json')), encoding='utf-8') as f:
                en = json.load(f)
            deepcopy_dict_missing_entries(self.text_content, en["content"])

    def systemTray(self):
        """Just to show little icon on system tray"""
        image = Image.open(resource_path(path.join("assets", "logo.ico")))
        menu = (
            MenuItem('Show', action=self.deiconify, default=True),
        )
        self.icon = Icon("name", image, "PyMacroRecord", menu)
        self.icon.run()

    def _normalize_app_name(self, name:str) -> str:
        """Normalize app process name: ensure .exe on Windows if not provided."""
        if platform.lower() == "win32":
            lowered = name.lower().strip()
            if not lowered.endswith('.exe'):
                lowered += '.exe'
            return lowered
        return name.strip()

    def _is_app_running(self, app_name:str) -> bool:
        """Return True if a process with app_name is running (Windows)."""
        try:
            if platform.lower() == "win32":
                out = subprocess.check_output(["tasklist"], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                return app_name.lower() in out.decode(errors='ignore').lower()
            else:
                # Fallback for non-Windows
                out = subprocess.check_output(["ps", "-A"]).decode(errors='ignore')
                return app_name.lower() in out.lower()
        except Exception:
            return False

    def _kill_app(self, app_name:str):
        """Force kill app process by name (Windows)."""
        try:
            if platform.lower() == "win32":
                subprocess.call(["taskkill", "/F", "/IM", app_name], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                subprocess.call(["pkill", "-f", app_name])
        except Exception:
            pass

    def _clear_application_caches(self):
        """Clear cache files for Excel, Word, and Adobe Illustrator to prevent recovery prompts."""
        if platform.lower() != "win32":
            print("  Cache clearing is only supported on Windows")
            return
        
        try:
            appdata = environ.get('APPDATA', '')
            localappdata = environ.get('LOCALAPPDATA', '')
            
            if not appdata or not localappdata:
                print("  Could not determine user directories")
                return
            
            cleared_count = 0
            
            # Clear Microsoft Excel AutoRecovery files
            excel_path = join_path(appdata, 'Microsoft', 'Excel')
            if path.exists(excel_path):
                try:
                    # Clear temporary lock files (files starting with ~$)
                    for file in listdir(excel_path):
                        if file.startswith('~$'):
                            file_path = join_path(excel_path, file)
                            if path.isfile(file_path):
                                try:
                                    remove(file_path)
                                    cleared_count += 1
                                except Exception:
                                    pass
                    
                    # Clear AutoRecovery folder if it exists
                    autorecovery_folder = join_path(excel_path, 'AutoRecovery')
                    if path.exists(autorecovery_folder):
                        for root, dirs, files in walk(autorecovery_folder):
                            for file in files:
                                try:
                                    remove(join_path(root, file))
                                    cleared_count += 1
                                except Exception:
                                    pass
                    print(f"  Cleared Excel cache: {excel_path}")
                except Exception as e:
                    print(f"  Failed to clear Excel cache: {e}")
            
            # Clear Microsoft Word AutoRecovery files
            word_path = join_path(appdata, 'Microsoft', 'Word')
            if path.exists(word_path):
                try:
                    # Clear temporary lock files (files starting with ~$)
                    for file in listdir(word_path):
                        if file.startswith('~$'):
                            file_path = join_path(word_path, file)
                            if path.isfile(file_path):
                                try:
                                    remove(file_path)
                                    cleared_count += 1
                                except Exception:
                                    pass
                    
                    # Clear AutoRecovery folder
                    autorecovery_folder = join_path(word_path, 'AutoRecovery')
                    if path.exists(autorecovery_folder):
                        for root, dirs, files in walk(autorecovery_folder):
                            for file in files:
                                try:
                                    remove(join_path(root, file))
                                    cleared_count += 1
                                except Exception:
                                    pass
                    print(f"  Cleared Word cache: {word_path}")
                except Exception as e:
                    print(f"  Failed to clear Word cache: {e}")
            
            # Clear Adobe Illustrator cache files
            # Check in LOCALAPPDATA\Temp\Adobe for Illustrator cache
            adobe_temp_path = join_path(localappdata, 'Temp', 'Adobe')
            if path.exists(adobe_temp_path):
                try:
                    for item in listdir(adobe_temp_path):
                        if 'Illustrator' in item:
                            illustrator_cache = join_path(adobe_temp_path, item)
                            if path.isdir(illustrator_cache):
                                try:
                                    shutil.rmtree(illustrator_cache)
                                    cleared_count += 1
                                    print(f"  Cleared Adobe Illustrator temp cache: {illustrator_cache}")
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"  Failed to clear Adobe Illustrator temp cache: {e}")
            
            # Also check in LOCALAPPDATA\Adobe\Adobe Illustrator [version]
            adobe_path = join_path(localappdata, 'Adobe')
            if path.exists(adobe_path):
                try:
                    for item in listdir(adobe_path):
                        if 'Illustrator' in item:
                            illustrator_path = join_path(adobe_path, item)
                            if path.isdir(illustrator_path):
                                # Look for cache folders
                                cache_folders = ['AICache', 'cache', 'Caches']
                                for cache_folder in cache_folders:
                                    cache_path = join_path(illustrator_path, cache_folder)
                                    if path.exists(cache_path):
                                        try:
                                            shutil.rmtree(cache_path)
                                            cleared_count += 1
                                            print(f"  Cleared Adobe Illustrator cache: {cache_path}")
                                        except Exception:
                                            pass
                except Exception as e:
                    print(f"  Failed to clear Adobe Illustrator cache: {e}")
            
            if cleared_count > 0:
                print(f"  Successfully cleared {cleared_count} cache file(s)/folder(s)")
            else:
                print("  No cache files found to clear")
                
        except Exception as e:
            print(f"  Error during cache clearing: {e}")

    def _save_batch_summary(self, summary_lines, results=None):
        """Save the batch summary to <data_dump_path>/<test_type>/macro_summary.txt and, with results,
        a machine-readable macro_summary.json next to it."""
        try:
            out_dir = output_dir(self._batch_config or {})
            if not out_dir:
                print("  Cannot save summary: data_dump_path or test_type not configured")
                return
            makedirs(out_dir, exist_ok=True)
            summary_file = path.join(out_dir, "macro_summary.txt")
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(summary_lines))
                f.write('\n')
            print(f"  Summary saved to: {summary_file}")
            if results is not None:
                json_file = path.join(out_dir, "macro_summary.json")
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump({"results": results}, f, indent=2, default=str)
                print(f"  Machine-readable summary saved to: {json_file}")
        except Exception as e:
            print(f"  Failed to save summary: {e}")

    def validate_input(self, action, value_if_allowed):
        """Prevents from adding letters on an Entry label"""
        if action == "1":  # Insert
            try:
                float(value_if_allowed)
                return True
            except ValueError:
                return False
        return True

    def quit_software(self, force=False):
        if not self.macro_saved and self.macro_recorded and not force:
            wantToSave = confirm_save(self)
            if wantToSave:
                RecordFileManagement(self, self.menu).save_macro()
            elif wantToSave == None:
                return
        should_restore_display = self.settings.settings_dict.get("Loading", {}).get(
            "Restore_Original_Display_On_Exit", True
        )
        if should_restore_display:
            try:
                self.macro.restore_original_display_settings()
            except Exception as e:
                print(f"[display] Failed to restore original settings: {e}")
        if platform.lower() != "darwin":
            self.icon.stop()
        if platform.lower() == "linux":
            self.destroy()
        self.quit()
