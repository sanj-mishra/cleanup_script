#!/usr/bin/env python3
"""Install, uninstall, or check status of the cleanup-agent launchd job.

Runs notify.py weekly. Defaults to Mondays 5pm.

The generated plist bakes in the current Python interpreter
(`sys.executable`) and the project's working directory, so install from
the environment you actually want the scheduled run to use."""
import argparse
import subprocess
import sys
from pathlib import Path

LABEL = "com.cleanup-agent.notify"
PLIST_NAME = f"{LABEL}.plist"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>cleanup_agent.notify</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>{weekday}</integer>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/cleanup-agent.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/cleanup-agent.err</string>
</dict>
</plist>
"""

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def install(weekday=1, hour=17, minute=0):
    """Write the plist and load it via launchctl."""
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = PLIST_DIR / PLIST_NAME
    plist_path.write_text(
        PLIST_TEMPLATE.format(
            label=LABEL,
            python=sys.executable,
            workdir=str(PROJECT_ROOT),
            weekday=weekday,
            hour=hour,
            minute=minute,
        )
    )
    # Unload first in case it's already loaded — avoids duplicate-load errors.
    subprocess.run(
        ["launchctl", "unload", str(plist_path)], capture_output=True
    )
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(
            f"warning: launchctl load returned {result.returncode}: "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )

    print(f"installed: {plist_path}")
    print(f"will run: {DAYS[weekday]} at {hour:02d}:{minute:02d}")
    print(f"logs: /tmp/cleanup-agent.log  /tmp/cleanup-agent.err")


def uninstall():
    plist_path = PLIST_DIR / PLIST_NAME
    if not plist_path.exists():
        print(f"not installed ({plist_path} doesn't exist)")
        return
    subprocess.run(
        ["launchctl", "unload", str(plist_path)], capture_output=True
    )
    plist_path.unlink()
    print(f"uninstalled: {plist_path}")


def status():
    plist_path = PLIST_DIR / PLIST_NAME
    if not plist_path.exists():
        print("not installed")
        return
    print(f"plist: {plist_path}")
    result = subprocess.run(
        ["launchctl", "list", LABEL], capture_output=True, text=True
    )
    if result.returncode == 0:
        print("status: loaded")
        print(result.stdout.strip())
    else:
        print("status: plist present but not loaded by launchctl")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    install_p = sub.add_parser("install", help="Generate plist and load")
    install_p.add_argument(
        "--weekday", type=int, default=1,
        help="0=Sun, 1=Mon, ..., 6=Sat (default: 1, Monday)",
    )
    install_p.add_argument(
        "--hour", type=int, default=17,
        help="0–23 (default: 17, 5pm)",
    )
    install_p.add_argument(
        "--minute", type=int, default=0,
        help="0–59 (default: 0)",
    )

    sub.add_parser("uninstall", help="Unload and remove plist")
    sub.add_parser("status", help="Show install/load state")

    args = parser.parse_args()
    if args.cmd == "install":
        install(args.weekday, args.hour, args.minute)
    elif args.cmd == "uninstall":
        uninstall()
    elif args.cmd == "status":
        status()


if __name__ == "__main__":
    main()
