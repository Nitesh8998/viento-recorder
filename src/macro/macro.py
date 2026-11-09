from datetime import datetime
import ctypes
import os
from os import getlogin, system
from subprocess import run, DEVNULL
from sys import platform
from threading import Thread
from time import time, sleep
from tkinter import *
from tkinter import messagebox
import queue
from pynput.keyboard import Key # FUTURE SELF: DON'T REMOVE THIS!!
from pynput import mouse, keyboard
from pynput.mouse import Button
from utils.get_key_pressed import getKeyPressed
from utils.keys import vk_nb
from utils.record_file_management import RecordFileManagement
from utils.show_toast import show_notification_minim
from utils.warning_pop_up_save import confirm_save
from utils.replay_timing import timing_mode, nominal_schedule, build_report, format_report


class Macro:
    """Init a new Macro"""

    def __init__(self, main_app):
        self.showEventsOnStatusBar = None
        self.mouseControl = mouse.Controller()
        self.keyboardControl = keyboard.Controller()
        self.record = False
        self.playback = False
        self.macro_events = {}
        self.main_app = main_app
        self.user_settings = self.main_app.settings
        self.main_menu = self.main_app.menu
        self.macro_file_management = RecordFileManagement(self.main_app, self.main_menu)
        self.status_update_queue = queue.Queue()

        self.mouseBeingListened = None
        self.keyboardBeingListened = None
        self.keyboard_listener = None
        self.mouse_listener = None
        self.time = time()
        self.event_delta_time=0
        self.original_display_settings = None
        self._display_settings_saved = False
        self.last_replay_report = None  # timing report of the most recent playback (see utils/replay_timing.py)
        self.focus_guard_log = []

        self.keyboard_listener = keyboard.Listener(
                on_press=self.__on_press, on_release=self.__on_release
            )
        self.keyboard_listener.start()
        
        # Start checking for status updates from background threads
        self._check_status_updates()

    def _check_status_updates(self):
        """Check for status updates from background threads and apply them."""
        try:
            while True:
                message = self.status_update_queue.get_nowait()
                self.main_app.status_text.configure(text=message)
        except queue.Empty:
            pass
        # Schedule next check
        self.main_app.after(100, self._check_status_updates)

    def _update_status_safe(self, message):
        """Safely queue a status update from any thread."""
        try:
            self.status_update_queue.put_nowait(message)
        except queue.Full:
            pass  # Skip if queue is full

    def start_record(self, by_hotkey=False):
        if self.main_app.prevent_record:
            return
        if not by_hotkey:
            if not self.main_app.macro_saved and self.main_app.macro_recorded:
                wantToSave = confirm_save(self.main_app)
                if wantToSave:
                    self.macro_file_management.save_macro()
                elif wantToSave is None:
                    return
        self.macro_events = {"events": []}
        self.macro_events["recording_display"] = self.__get_display_metadata()
        self.record = True
        self.time = time()
        self.event_delta_time=0
        userSettings = self.user_settings.settings_dict
        self.showEventsOnStatusBar = userSettings["Recordings"]["Show_Events_On_Status_Bar"]
        if (
            userSettings["Recordings"]["Mouse_Move"]
            and userSettings["Recordings"]["Mouse_Click"]
        ):
            self.mouse_listener = mouse.Listener(
                on_move=self.__on_move,
                on_click=self.__on_click,
                on_scroll=self.__on_scroll,
            )
            self.mouse_listener.start()
            self.mouseBeingListened = True
        elif userSettings["Recordings"]["Mouse_Move"]:
            self.mouse_listener = mouse.Listener(
                on_move=self.__on_move, on_scroll=self.__on_scroll
            )
            self.mouse_listener.start()
            self.mouseBeingListened = True
        elif userSettings["Recordings"]["Mouse_Click"]:
            self.mouse_listener = mouse.Listener(
                on_click=self.__on_click, on_scroll=self.__on_scroll
            )
            self.mouse_listener.start()
            self.mouseBeingListened = True
        if userSettings["Recordings"]["Keyboard"]:
            self.keyboardBeingListened = True
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["load_text"], state=DISABLED)
        self.main_app.recordBtn.configure(
            image=self.main_app.stopImg, command=self.stop_record
        )
        self.main_app.playBtn.configure(state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_as_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["new_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["load_text"], state=DISABLED)
        if userSettings["Minimization"]["When_Recording"]:
            self.main_app.withdraw()
            Thread(target=lambda: show_notification_minim(self.main_app)).start()
        print("record started")

    def stop_record(self):
        if not self.record:
            return
        userSettings = self.user_settings.settings_dict
        self.record = False
        if self.mouseBeingListened:
            self.mouse_listener.stop()
            self.mouseBeingListened = False
        if self.keyboardBeingListened:
            self.keyboardBeingListened = False
        self.main_app.recordBtn.configure(
            image=self.main_app.recordImg, command=self.start_record
        )
        self.main_app.playBtn.configure(state=NORMAL, command=self.start_playback)
        self.main_menu.file_menu.entryconfig(
            self.main_app.text_content["file_menu"]["save_text"], state=NORMAL, command=self.macro_file_management.save_macro
        )
        self.main_menu.file_menu.entryconfig(
            self.main_app.text_content["file_menu"]["save_as_text"], state=NORMAL, command=self.macro_file_management.save_macro_as
        )
        self.main_menu.file_menu.entryconfig(
            self.main_app.text_content["file_menu"]["new_text"], state=NORMAL, command=self.macro_file_management.new_macro
        )
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["load_text"], state=NORMAL)

        self.main_app.macro_recorded = True
        self.main_app.macro_saved = False

        if userSettings["Minimization"]["When_Recording"]:
            self.main_app.deiconify()

        print("record stopped")

    def start_playback(self):
        userSettings = self.user_settings.settings_dict
        self.last_replay_report = None
        self.playback = True
        self.main_app.playBtn.configure(
            image=self.main_app.stopImg, command=lambda: self.stop_playback(True)
        )
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_as_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["new_text"], state=DISABLED)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["load_text"], state=DISABLED)
        self.main_app.recordBtn.configure(state=DISABLED)
        if userSettings["Minimization"]["When_Playing"]:
            self.main_app.withdraw()
            Thread(target=lambda: show_notification_minim(self.main_app)).start()
        if userSettings["Playback"]["Repeat"]["Interval"] > 0:
            Thread(target=self.__play_interval).start()
        elif userSettings["Playback"]["Repeat"]["For"] > 0:
            Thread(target=self.__play_for).start()
        elif userSettings["Playback"]["Repeat"]["For"] > 0 and userSettings["Playback"]["Repeat"]["Interval"] > 0:
            Thread(target=self.__play_interval).start()
        else:
            Thread(target=self.__play_events).start()
        print("playback started")

    def __play_interval(self):
        userSettings = self.user_settings.settings_dict
        if userSettings["Playback"]["Repeat"]["For"] > 0:
            self.__play_for()
        else:
            self.__play_events()
        timer = time()
        while self.playback:
            sleep(1)
            if time() - timer >= userSettings["Playback"]["Repeat"]["Interval"]:
                if userSettings["Playback"]["Repeat"]["For"] > 0:
                    self.__play_for()
                else:
                    self.__play_events()
                timer = time()


    def __play_for(self):
        userSettings = self.user_settings.settings_dict
        debut = time()
        while self.playback and (time() - debut) < userSettings["Playback"]["Repeat"]["For"]:
            self.__play_events()
        if userSettings["Playback"]["Repeat"]["Interval"] == 0:
            self.stop_playback()

    def __play_events(self):
        global keyToPress
        userSettings = self.user_settings.settings_dict
        click_func = {
            "leftClickEvent": Button.left,
            "rightClickEvent": Button.right,
            "middleClickEvent": Button.middle,
        }
        keyToUnpress = []

        is_infinite = userSettings["Playback"]["Repeat"].get("Infinite", False)

        if userSettings["Playback"]["Repeat"]["For"] > 0:
            repeat_times = 1
        elif is_infinite:
            repeat_times = float('inf')
        else:
            repeat_times = userSettings["Playback"]["Repeat"]["Times"]

        if userSettings["Playback"]["Repeat"]["Scheduled"] > 0:
            now = datetime.now()
            seconds_since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
            secondsToWait = userSettings["Playback"]["Repeat"]["Scheduled"] - seconds_since_midnight
            if secondsToWait < 0:
                secondsToWait = 86400 + secondsToWait  # 86400 + -secondsToWait. Meaning it will happen tomorrow
            sleep(secondsToWait)

        repeat_count = 0
        guard_enabled, guard_timeout = self._focus_guard_settings()
        self.focus_guard_log = []
        if guard_enabled:
            print(f"[focus-guard] enabled (timeout {guard_timeout:.1f}s)")
        # Timing: "relative" (default, original open-loop behaviour) or "absolute" (drift-free schedule).
        mode = timing_mode(userSettings)
        absolute = mode == "absolute"
        speed = userSettings["Playback"]["Speed"]
        n_events, nominal_s = nominal_schedule(self.macro_events["events"], speed, userSettings["Others"]["Fixed_timestamp"])
        if absolute:
            print("[timing] absolute schedule enabled")
        replay_s = 0.0      # time spent replaying events, excluding inter-repetition delays
        guard_hold_s = 0.0  # time clicks were held by the focus guard
        max_lag = 0.0       # largest delay behind schedule (absolute mode only)
        self._buttons_down = set()
        now = time()

        def finish(completed, stopped_at=None):
            # stopped_at: index of the first event not issued in the interrupted repetition
            reps, n_ev, nom = repeat_count, n_events, nominal_s
            if stopped_at is not None:
                part_n, part_nom = nominal_schedule(self.macro_events["events"][:stopped_at], speed,
                                                    userSettings["Others"]["Fixed_timestamp"])
                total_n = repeat_count * n_events + part_n
                nom = (repeat_count * nominal_s + part_nom) / max(total_n, 1) * n_events if n_events else 0.0
                reps = total_n / n_events if n_events else 0
            self.last_replay_report = build_report(
                completed=completed, repetitions=reps, n_events=n_ev, nominal_s=nom,
                actual_s=replay_s, speed=speed, mode=mode, guard_hold_s=guard_hold_s,
                guard_holds=sum(1 for g in self.focus_guard_log if not g["timeout"]),
                guard_timeouts=sum(1 for g in self.focus_guard_log if g["timeout"]),
                max_lag_s=max_lag if absolute else None)
            print(format_report(self.last_replay_report))

        while self.playback and (is_infinite or repeat_count < repeat_times):
            rep_start = time()
            schedule = 0.0  # scheduled offset of the current event from rep_start (absolute mode)
            for events in range(len(self.macro_events["events"])):
                elapsed_time = int(time() - now)
                # Use thread-safe status update
                self._update_status_safe(f"Repeat: {repeat_count + 1}/{repeat_times}, Time elapsed: {elapsed_time}s")
                if not self.playback:
                    self.unPressEverything(keyToUnpress)
                    replay_s += time() - rep_start
                    finish(False, stopped_at=events)
                    return

                if userSettings["Others"]["Fixed_timestamp"] > 0:
                    timeSleep = userSettings["Others"]["Fixed_timestamp"]
                else:
                    timeSleep = (
                            self.macro_events["events"][events]["timestamp"]
                            * (1 / userSettings["Playback"]["Speed"])
                    )
                if timeSleep < 0:
                    timeSleep = abs(timeSleep)
                if absolute:
                    schedule += timeSleep
                    wait = rep_start + schedule - time()
                    if wait > 0:
                        sleep(wait)
                    elif -wait > max_lag:
                        max_lag = -wait
                else:
                    sleep(timeSleep)
                event_type = self.macro_events["events"][events]["type"]

                if event_type == "cursorMove":  # Cursor Move
                    self.mouseControl.position = (
                        self.macro_events["events"][events]["x"],
                        self.macro_events["events"][events]["y"],
                    )

                elif event_type in click_func:  # Mouse Click
                    if self.macro_events["events"][events]["pressed"] and guard_enabled:
                        held = self._focus_guard_wait(self.macro_events["events"][events], events, guard_timeout)
                        guard_hold_s += held
                        if absolute:
                            rep_start += held  # a held click shifts the rest of the schedule
                    self.mouseControl.position = (
                        self.macro_events["events"][events]["x"],
                        self.macro_events["events"][events]["y"],
                    )
                    if self.macro_events["events"][events]["pressed"]:
                        self.mouseControl.press(click_func[event_type])
                        self._buttons_down.add(click_func[event_type])
                    else:
                        self.mouseControl.release(click_func[event_type])
                        self._buttons_down.discard(click_func[event_type])

                elif event_type == "scrollEvent":
                    self.mouseControl.scroll(
                        self.macro_events["events"][events]["dx"],
                        self.macro_events["events"][events]["dy"],
                    )

                elif event_type == "keyboardEvent":  # Keyboard Press,Release
                    if self.macro_events["events"][events]["key"] is not None:
                        try:
                            if "Key." not in self.macro_events["events"][events]["key"]:
                                keyToPress = self.macro_events["events"][events]["key"]
                            else:
                                keyToPress = self._special_key(self.macro_events["events"][events]["key"])
                            if isinstance(keyToPress, str):
                                if ">" in keyToPress:
                                    try:
                                        keyToPress = vk_nb[keyToPress]
                                    except:
                                        keyToPress = None
                            if self.playback:
                                if keyToPress is not None:
                                    if (
                                            self.macro_events["events"][events]["pressed"]
                                            == True
                                    ):
                                        self.keyboardControl.press(keyToPress)
                                        if keyToPress not in keyToUnpress:
                                            keyToUnpress.append(keyToPress)
                                    else:
                                        self.keyboardControl.release(keyToPress)
                        except ValueError as e:
                            messagebox.showerror("Error",
                                                 f"Error during playback \"{e}\". Please open an issue on Github.")
                            self.stop_playback()
                        except Exception as e:
                            messagebox.showerror("Error",
                                                 f"An unexpected error occurred\n{e}")
                            self.stop_playback()


            replay_s += time() - rep_start
            repeat_count += 1

            if userSettings["Playback"]["Repeat"]["Delay"] > 0:
                if is_infinite or repeat_count < repeat_times:
                    sleep(userSettings["Playback"]["Repeat"]["Delay"])

        self.unPressEverything(keyToUnpress)
        finish(repeat_count > 0 if is_infinite else repeat_count >= repeat_times)
        if userSettings["Playback"]["Repeat"]["Interval"] == 0 and userSettings["Playback"]["Repeat"]["For"] == 0 and repeat_count:
            self.stop_playback()
            if userSettings["Minimization"]["When_Playing"]:
                self.main_app.deiconify()

    @staticmethod
    def _special_key(name):
        """Resolve a stored special key such as "Key.ctrl_l" to pynput's Key member.
        Replaces eval() on macro-file content; an unknown name raises AttributeError,
        which the caller reports exactly as before."""
        attr = name.split("Key.", 1)[1]
        if attr not in Key.__members__:
            raise AttributeError(f"unknown key name {name!r}")
        return Key[attr]

    def unPressEverything(self, keyToUnpress):
        for key in keyToUnpress:
            self.keyboardControl.release(key)
        self.mouseControl.release(Button.left)
        self.mouseControl.release(Button.middle)
        # The right button is released only if it is still held (e.g. playback stopped mid-drag):
        # an unconditional right-button release would open a context menu.
        if Button.right in getattr(self, "_buttons_down", ()):
            self.mouseControl.release(Button.right)
        self._buttons_down = set()

    def stop_playback(self, playback_stopped_manually=False):
        self.playback = False
        if not playback_stopped_manually:
            print("playback stopped")
        else:
            print("playback stopped manually")
        userSettings = self.user_settings.settings_dict
        self.main_app.recordBtn.configure(state=NORMAL)
        self.main_app.playBtn.configure(
            image=self.main_app.playImg, command=self.start_playback
        )
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_text"], state=NORMAL)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["save_as_text"], state=NORMAL)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["new_text"], state=NORMAL)
        self.main_menu.file_menu.entryconfig(self.main_app.text_content["file_menu"]["load_text"], state=NORMAL)
        if userSettings["Minimization"]["When_Playing"]:
            self.main_app.deiconify()
        if userSettings["After_Playback"]["Mode"] != "Idle" and not playback_stopped_manually:
            if userSettings["After_Playback"]["Mode"].lower() == "standby":
                if platform == "win32":
                    system("rundll32.exe powrprof.dll, SetSuspendState 0,1,0")
                elif "linux" in platform.lower():
                    system("subprocess.callctl suspend")
                elif "darwin" in platform.lower():
                    system("pmset sleepnow")
            elif userSettings["After_Playback"]["Mode"].lower() == "log off computer":
                if platform == "win32":
                    system("shutdown /l")
                else:
                    system(f"pkill -KILL -u {getlogin()}")
            elif userSettings["After_Playback"]["Mode"].lower() == "turn off computer":
                if platform == "win32":
                    system("shutdown /s /t 0")
                else:
                    system("shutdown -h now")
            elif userSettings["After_Playback"]["Mode"].lower() == "restart computer":
                if platform == "win32":
                    system("shutdown /r /t 0")
                else:
                    system("shutdown -r now")
            elif userSettings["After_Playback"]["Mode"].lower() == "hibernate (if enabled)":
                if platform == "win32":
                    system("shutdown -h")
                elif "linux" in platform.lower():
                    system("systemctl hibernate")
                elif "darwin" in platform.lower():
                    system("pmset sleepnow")
            force_close = True
            self.main_app.quit_software(force_close)

    def import_record(self, record):
        self.__save_original_display_settings_if_needed()
        self.macro_events = record
        self.__apply_recording_display_metadata()

    def restore_original_display_settings(self):
        if not self.__is_windows():
            return
        if not isinstance(self.original_display_settings, dict):
            return

        resolution = self.original_display_settings.get("resolution", {})
        width = resolution.get("width")
        height = resolution.get("height")
        scale_percent = self.original_display_settings.get("scale_percent")

        if isinstance(width, int) and isinstance(height, int):
            print(f"[display] Restoring original resolution: {width}x{height}")
            self.__set_windows_resolution(width, height)
        if isinstance(scale_percent, int):
            print(f"[display] Restoring original scale: {scale_percent}%")
            self.__set_windows_scale_percent(scale_percent)

    def __get_display_metadata(self):
        width = None
        height = None
        scale_percent = 100
        try:
            width = self.main_app.winfo_screenwidth()
            height = self.main_app.winfo_screenheight()
        except Exception:
            pass

        if self.__is_windows():
            try:
                # 96 DPI is 100% scale on Windows.
                system_dpi = ctypes.windll.user32.GetDpiForSystem()
                scale_percent = int(round((system_dpi / 96) * 100))
            except Exception:
                pass

        return {
            "resolution": {"width": width, "height": height},
            "scale_percent": scale_percent,
        }

    def __save_original_display_settings_if_needed(self):
        if self._display_settings_saved:
            return
        self.original_display_settings = self.__get_display_metadata()
        self._display_settings_saved = True
        resolution = self.original_display_settings.get("resolution", {})
        print(
            f"[display] Saved original display settings: "
            f"{resolution.get('width')}x{resolution.get('height')}, "
            f"scale {self.original_display_settings.get('scale_percent')}%"
        )

    def __apply_recording_display_metadata(self):
        if not self.__is_windows():
            print("[display] Skipping display apply: non-Windows runtime detected")
            return
        recording_display = self.macro_events.get("recording_display")
        if not isinstance(recording_display, dict):
            print("[display] No recording_display metadata found in macro")
            return

        resolution = recording_display.get("resolution", {})
        width = resolution.get("width")
        height = resolution.get("height")
        scale_percent = recording_display.get("scale_percent")

        if isinstance(width, int) and isinstance(height, int):
            print(f"[display] Applying resolution: {width}x{height}")
            self.__set_windows_resolution(width, height)
        else:
            print("[display] Resolution metadata missing or invalid")

        if isinstance(scale_percent, int):
            print(f"[display] Applying scale: {scale_percent}%")
            self.__set_windows_scale_percent(scale_percent)
        else:
            print("[display] Scale metadata missing or invalid")

    def __is_windows(self):
        # Some Windows Python environments report non-win32 sys.platform values.
        return platform == "win32" or os.name == "nt"

    def __set_windows_resolution(self, width, height):
        # NOTE: Resolution change can fail depending on GPU drivers/permissions.
        DM_PELSWIDTH = 0x00080000
        DM_PELSHEIGHT = 0x00100000
        DISP_CHANGE_SUCCESSFUL = 0
        CDS_UPDATEREGISTRY = 0x00000001

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", ctypes.c_wchar * 32),
                ("dmSpecVersion", ctypes.c_ushort),
                ("dmDriverVersion", ctypes.c_ushort),
                ("dmSize", ctypes.c_ushort),
                ("dmDriverExtra", ctypes.c_ushort),
                ("dmFields", ctypes.c_ulong),
                ("dmOrientation", ctypes.c_short),
                ("dmPaperSize", ctypes.c_short),
                ("dmPaperLength", ctypes.c_short),
                ("dmPaperWidth", ctypes.c_short),
                ("dmScale", ctypes.c_short),
                ("dmCopies", ctypes.c_short),
                ("dmDefaultSource", ctypes.c_short),
                ("dmPrintQuality", ctypes.c_short),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", ctypes.c_ushort),
                ("dmBitsPerPel", ctypes.c_ulong),
                ("dmPelsWidth", ctypes.c_ulong),
                ("dmPelsHeight", ctypes.c_ulong),
                ("dmDisplayFlags", ctypes.c_ulong),
                ("dmDisplayFrequency", ctypes.c_ulong),
                ("dmICMMethod", ctypes.c_ulong),
                ("dmICMIntent", ctypes.c_ulong),
                ("dmMediaType", ctypes.c_ulong),
                ("dmDitherType", ctypes.c_ulong),
                ("dmReserved1", ctypes.c_ulong),
                ("dmReserved2", ctypes.c_ulong),
                ("dmPanningWidth", ctypes.c_ulong),
                ("dmPanningHeight", ctypes.c_ulong),
            ]

        try:
            devmode = DEVMODEW()
            devmode.dmSize = ctypes.sizeof(DEVMODEW)
            devmode.dmPelsWidth = width
            devmode.dmPelsHeight = height
            devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
            result = ctypes.windll.user32.ChangeDisplaySettingsW(
                ctypes.byref(devmode), CDS_UPDATEREGISTRY
            )
            if result != DISP_CHANGE_SUCCESSFUL:
                print(f"[display] Could not set resolution to {width}x{height} (code {result})")
            else:
                # Let Windows settle before injecting mouse/keyboard events.
                sleep(1)
        except Exception as e:
            print(f"[display] Failed to set resolution: {e}")

    def __set_windows_scale_percent(self, scale_percent):
        # Windows desktop scale changes are registry-backed and often require sign-out.
        if scale_percent < 100:
            return
        dpi = int(round((scale_percent / 100) * 96))
        script = (
            "$ErrorActionPreference='Stop';"
            f"$dpi={dpi};"
            "$desk='HKCU:\\Control Panel\\Desktop';"
            "Set-ItemProperty -Path $desk -Name LogPixels -Type DWord -Value $dpi;"
            "Set-ItemProperty -Path $desk -Name Win8DpiScaling -Type DWord -Value 1"
        )
        try:
            completed = run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                stdout=DEVNULL,
                stderr=DEVNULL,
                check=False,
            )
            if completed.returncode != 0:
                print(f"[display] Could not set scale to {scale_percent}%")
        except Exception as e:
            print(f"[display] Failed to set scale percent: {e}")

    # ------------------------------------------------------------------
    # Focus guard (optional, disabled by default).
    # At record time each click stores the executable name of the process
    # owning the foreground window. At replay time, if the guard is enabled,
    # a click is held until that process owns the foreground window again,
    # for at most `timeout` seconds. All other events keep their recorded
    # timing. Every hold and every timeout is logged.
    # Enable with userSettings["Others"]["Focus_guard"] = true (timeout in
    # userSettings["Others"]["Focus_guard_timeout"]), or with the environment
    # variables VIENTO_FOCUS_GUARD=1 and VIENTO_FOCUS_GUARD_TIMEOUT=<seconds>.
    # ------------------------------------------------------------------
    def _focus_guard_settings(self):
        others = self.user_settings.settings_dict.get("Others", {})
        enabled = bool(others.get("Focus_guard", False))
        timeout = float(others.get("Focus_guard_timeout", 5.0))
        env_on = os.environ.get("VIENTO_FOCUS_GUARD")
        if env_on is not None:
            enabled = env_on.strip().lower() in ("1", "true", "yes", "on")
        env_to = os.environ.get("VIENTO_FOCUS_GUARD_TIMEOUT")
        if env_to:
            try:
                timeout = float(env_to)
            except ValueError:
                pass
        return enabled and self.__is_windows(), max(0.0, timeout)

    def _foreground_process_name(self):
        """Executable name (lower case) of the process owning the foreground window, or None."""
        if not self.__is_windows():
            return None
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return None
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not handle:
                return None
            try:
                size = ctypes.c_ulong(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return None
                return os.path.basename(buf.value).lower()
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return None

    def _focus_guard_wait(self, event, index, timeout):
        """Hold a click until the recorded foreground process is in front again (bounded by timeout).
        Returns the time the click was held, in seconds."""
        expected = event.get("fg_process")
        if not expected:
            return 0.0  # macro recorded without guard metadata
        current = self._foreground_process_name()
        if current is None or current == expected:
            return 0.0
        start = time()
        while self.playback and time() - start < timeout:
            sleep(0.02)
            current = self._foreground_process_name()
            if current == expected:
                held = time() - start
                self.focus_guard_log.append({"event": index, "expected": expected, "held_s": round(held, 3), "timeout": False})
                print(f"[focus-guard] event {index}: held {held:.2f}s for {expected}")
                return held
        if not self.playback:
            return time() - start  # playback stopped while holding; not a timeout
        self.focus_guard_log.append({"event": index, "expected": expected, "found": current,
                                     "held_s": round(time() - start, 3), "timeout": True})
        print(f"[focus-guard] event {index}: TIMEOUT waiting for {expected} (foreground: {current})")
        return time() - start

    def __record_event(self,e):
        e['timestamp'] = self.event_delta_time
        self.macro_events["events"].append(e)

    def __get_event_delta_time(self):
        timenow=time()
        self.event_delta_time = timenow - self.time
        self.time=timenow

    def __on_move(self, x, y):
        self.__get_event_delta_time()
        self.__record_event(
            {"type": "cursorMove", "x": x, "y": y}
        )
        if self.showEventsOnStatusBar:
            self._update_status_safe(f"cursorMove {x} {y}")

    def __on_click(self, x, y, button, pressed):
        self.__get_event_delta_time()
        button_event = "unknownButtonClickEvent"
        if button == Button.left:
            button_event = "leftClickEvent"
        elif button == Button.right:
            button_event = "rightClickEvent"
        elif button == Button.middle:
            button_event = "middleClickEvent"
        click_event = {
            "type": button_event,
            "x": x,
            "y": y,
            "pressed": pressed
        }
        if pressed:
            # Focus-guard metadata: process that owns the foreground window at click time.
            fg_proc = self._foreground_process_name()
            if fg_proc:
                click_event["fg_process"] = fg_proc
        self.__record_event(click_event)
        if self.showEventsOnStatusBar:
            self._update_status_safe(f"{button_event} {x} {y} {pressed}")

    def __on_scroll(self, x, y, dx, dy):
        self.__get_event_delta_time()
        self.__record_event(
            {"type": "scrollEvent", "dx": dx, "dy": dy}
        )
        if self.showEventsOnStatusBar:
            self._update_status_safe(f"scrollEvent {dx} {dy}")

    def __on_press(self, key):
        self.__get_event_delta_time()
        keyPressed = getKeyPressed(self.keyboard_listener, key)
        if self.keyboardBeingListened:
            self.__record_event(
                {
                    "type": "keyboardEvent",
                    "key": keyPressed,
                    "pressed": True,
                }
            )
        if self.showEventsOnStatusBar:
            self._update_status_safe(f"keyboardEvent {keyPressed} pressed")

    def __on_release(self, key):
        self.__get_event_delta_time()
        keyPressed = getKeyPressed(self.keyboard_listener, key)
        if self.keyboardBeingListened:
            self.__record_event(
                {
                    "type": "keyboardEvent",
                    "key": keyPressed,
                    "pressed": False,
                }
            )
        if self.showEventsOnStatusBar:
            self._update_status_safe(f"keyboardEvent {keyPressed} released")
