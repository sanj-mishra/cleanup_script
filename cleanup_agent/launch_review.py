#!/usr/bin/env python3
"""Helper invoked by the cleanup-agent notification's click action.

Opens a new Terminal window and runs `python3 -m cleanup_agent.review`
inside it. Called via terminal-notifier's `-execute` flag from notify.py.

Lives in its own module so we don't have to nest osascript quoting inside
Python inside a shell string inside another shell string. That way, paths
containing spaces (like `/Users/foo/My Projects/...`) don't blow up the
notification click."""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    # Inner command for Terminal to execute. Quoted for paths with spaces.
    # The \" escapes are for AppleScript's string literal.
    inner_cmd = (
        f'cd \\"{PROJECT_ROOT}\\" && '
        f'\\"{sys.executable}\\" -m cleanup_agent.review'
    )
    apple_script = (
        f'tell application "Terminal"\n'
        f'  activate\n'
        f'  do script "{inner_cmd}"\n'
        f'end tell'
    )
    subprocess.run(["osascript", "-e", apple_script])


if __name__ == "__main__":
    main()
