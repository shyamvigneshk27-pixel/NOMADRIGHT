#!/usr/bin/env python3
import sys
import argparse
import logging
import time
import threading
import json
from pocketinfer.applications import *
from pocketinfer.applications.registry import ApplicationRegistry
from pocketinfer.boards.base import Board, DummyBoard
from psutil import virtual_memory


def _update_stats(board):
    while True:
        board.memory_text(f"{int(virtual_memory().percent)}%")
        time.sleep(2.0)

def main():
    parser = argparse.ArgumentParser(description="PocketInfer Application Runner")
    parser.add_argument('--log-level', type=str, default='INFO', help='Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)')
    parser.add_argument('--app', type=str, default="HearTheWorld", help='Name of the application to run')
    parser.add_argument('--list-apps', action='store_true', help='List available applications and exit')
    parser.add_argument('--update-app', action='store_true', default=False, help='Install dependencies for the specified application and exit')
    parser.add_argument('--dummy-board', action='store_true', default=False, help='Do not use hardware features - load audio and image from file')
    parser.add_argument('--headless', action='store_true', default=False, help='Use real hardware (trigger button, mic, speaker) but skip the touchscreen LCD/touch UI subprocess - status/text goes to the console log instead. Use this if the touchscreen display or touch controller is unavailable/crashing.')
    parser.add_argument('--audio-file', type=str, help='Path to 16kHz 16-bit wav file to use with dummy board')
    parser.add_argument('--image-file', type=str, help='Path to image file to use with dummy board')
    parser.add_argument('--settings-file', default=None, type=str, help='Path to JSON file with application settings to override defaults')
    parser.add_argument('--setting', default=[], type=str, action='append', help='Override a specific application setting (can be used multiple times, e.g. --setting input_language=hi --setting output_language=en)')
    args = parser.parse_args()
    # Temporary code to test application startup
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    logging.debug(ApplicationRegistry._classes)
    if args.list_apps:
        print("Available applications:")
        for name in ApplicationRegistry._classes.keys():
            print(f"  {name}")
        sys.exit(0)
    app_cls = ApplicationRegistry.get_application(args.app)
    if app_cls is None: 
        logging.error("Application not found")
        sys.exit(1)

    if args.update_app:
        app_cls.update_dependencies()
        sys.exit(0)

    settings = {}
    if args.settings_file:
        with open(args.settings_file, 'r') as f:
            file_settings = json.load(f)
        if not isinstance(file_settings, dict):
            logging.error("Settings file must contain a JSON object (dictionary) at the top level")
            sys.exit(1)
        settings.update(file_settings)

    for setting_str in args.setting:
        if '=' not in setting_str:
            logging.error("Invalid setting format: %s. Must be key=value", setting_str)
            sys.exit(1)
        key, value = setting_str.split('=', 1)
        settings[key] = value

    if not args.dummy_board:
        board = Board.get_board(headless=args.headless)
    else:
        board = DummyBoard(vars(args))
    threading.Thread(target=_update_stats, args=(board,), daemon=True).start()
    board.statusbar("Starting: {}...".format(args.app))
    board.button_led(False)

    app_cls.verify_dependencies()
    logging.info(f"Starting application: {args.app}")
    board.mode_text(f"App {args.app}")
    app = app_cls(board, settings=settings)
    app.start()
    if args.dummy_board:
        # Only run application once
        app.running = False
    while app.running:
        time.sleep(1.0)
    app.stop()
    sys.exit(0)

if __name__ == "__main__":
    main()
