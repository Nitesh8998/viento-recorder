from os import path, system
from sys import platform

from utils.get_file import resource_path


def show_notification_minim(main_app):
    if platform == "win32":
        try:
            from win10toast import ToastNotifier
            toast = ToastNotifier()
            toast.show_toast(
                title="PyMacroRecord",
                msg=main_app.text_content["options_menu"]["settings_menu"]["minimization_toast"],
                duration=3,
                icon_path=resource_path(path.join("assets", "logo.ico"))
            )
        except Exception as e:
            # win10toast can fail on some Python versions/environments.
            print(f"[toast] Windows toast unavailable ({e})")
            pass

    elif "linux" in platform.lower():
        system(f"""notify-send -u normal "PyMacroRecord" "{main_app.text_content["options_menu"]["settings_menu"]["minimization_toast"]}" """)
    elif "darwin" in platform.lower():
        system(f"""osascript -e 'display notification "{main_app.text_content["options_menu"]["settings_menu"]["minimization_toast"]}" with title "PyMacroRecord"'""")
