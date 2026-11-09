import sys
from os import path

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        # Resolve against the src/ folder, so the program can be started from any working directory
        base_path = path.dirname(path.dirname(path.abspath(__file__)))
    return path.join(base_path, relative_path)
