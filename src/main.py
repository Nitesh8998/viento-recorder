import argparse
import os
from sys import platform

from windows import MainApp

if platform.lower() == "win32":
    import ctypes
    PROCESS_PER_MONITOR_DPI_AWARE = 2
    ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)


def _default_batch_list_path() -> str:
    # Default to project root's macro_batch_test.txt (this file is in src/)
    here = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(here, os.pardir))
    return os.path.join(project_root, "macro_batch_test.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyMacroRecord launcher")
    parser.add_argument(
        "--batch_mode",
        action="store_true",
        help="Enable batch mode to play a list of macro files",
    )
    parser.add_argument(
        "--batch_list",
        default=_default_batch_list_path(),
        help="Path to batch list (.txt lines or .json config) of .pmr paths",
    )
    parser.add_argument(
        "--test_type",
        default=None,
        help="Override test_type from JSON config file",
    )
    args = parser.parse_args()

    MainApp(batch_mode=args.batch_mode, batch_list=args.batch_list, test_type=args.test_type)
