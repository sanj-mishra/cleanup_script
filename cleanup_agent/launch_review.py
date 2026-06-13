#!/usr/bin/env python3
"""Helper invoked by the cleanup-agent notification's click action.

Opens a new Terminal window and runs `python3 -m cleanup_agent.review`
inside it. Called via terminal-notifier's `-execute` flag from notify.py.

Lives in its own module so we don't have to nest osascript quoting inside
Python inside a shell string inside another shell string. That way, paths
containing spaces (like `/Users/foo/My Projects/...`) don't blow up the
notification click."""
import shlex
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    # Two layers of escaping. First shell-quote the paths (shlex.quote) so
    # the command Terminal runs is shell-safe regardless of spaces, quotes,
    # `$`, or backticks in the project path. Then escape backslashes and
    # double-quotes so the whole command survives being embedded inside the
    # AppleScript `do script "..."` string literal.
    inner_cmd = (
        f"cd {shlex.quote(str(PROJECT_ROOT))} && "
        f"{shlex.quote(sys.executable)} -m cleanup_agent.review"
    )
    escaped = inner_cmd.replace("\\", "\\\\").replace('"', '\\"')
    apple_script = (
        f'tell application "Terminal"\n'
        f'  activate\n'
        f'  do script "{escaped}"\n'
        f'end tell'
    )
    subprocess.run(["osascript", "-e", apple_script])


if __name__ == "__main__":
    main()
