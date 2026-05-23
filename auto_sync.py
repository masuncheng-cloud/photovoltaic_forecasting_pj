#!/usr/bin/env python3
"""
Auto-sync script: monitors photovoltaic_forecasting_pj for changes
and automatically commits + pushes to GitHub.

Usage:
    python3 auto_sync.py                    # Run in background
    python3 auto_sync.py --once              # Single sync check
    python3 auto_sync.py --install-service   # Install as systemd service (auto-start on boot)
"""

import os
import sys
import time
import subprocess
import argparse
from pathlib import Path

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")

# Files/dirs to ignore (no sync)
IGNORE_PATTERNS = {
    ".git/objects",
    ".git/logs",
    ".git/refs/remotes",
    ".git/hooks",
    ".git/HEAD",
    ".git/index",
    "__pycache__",
    ".pyc",
    ".DS_Store",
    "*.pyc",
    "*.pyo",
    ".ipynb_checkpoints",
    "output/pv_pipeline/metrics",  # Skip large metrics folder
    "output/pv_pipeline/figures",
    "output/pv_pipeline/figures_dashboard",
    ".venv",
    "venv",
    "env",
    "node_modules",
}

# Git command (use /bin/git to avoid issues)
GIT = "/bin/git"


def should_ignore(rel_path: str) -> bool:
    for pattern in IGNORE_PATTERNS:
        if pattern.startswith("*"):
            if rel_path.endswith(pattern[1:]):
                return True
        elif pattern in rel_path:
            return True
    return False


def get_all_files(root: Path):
    """Get all tracked + untracked files with modification times."""
    files = {}

    # Tracked files
    try:
        result = subprocess.run(
            [GIT, "ls-files"],
            cwd=root, capture_output=True, text=True, timeout=10
        )
        for f in result.stdout.strip().split("\n"):
            if f:
                p = root / f
                if p.exists():
                    files[f] = p.stat().st_mtime
    except Exception as e:
        print(f"[auto-sync] Failed to list tracked files: {e}")

    # Untracked files (not ignored by git)
    try:
        result = subprocess.run(
            [GIT, "ls-files", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, timeout=10
        )
        for f in result.stdout.strip().split("\n"):
            if f and not should_ignore(f):
                p = root / f
                if p.exists():
                    files[f] = p.stat().st_mtime
    except Exception as e:
        print(f"[auto-sync] Failed to list untracked files: {e}")

    return files


def has_changes(root: Path) -> bool:
    """Check if there are uncommitted changes."""
    result = subprocess.run(
        [GIT, "status", "--porcelain"],
        cwd=root, capture_output=True, text=True, timeout=10
    )
    lines = [l for l in result.stdout.strip().split("\n") if l]
    # Filter out ignored files
    changed = [l for l in lines if not should_ignore(l.split(maxsplit=1)[-1].strip())]
    return bool(changed)


def auto_commit_push(root: Path, reason: str = ""):
    """Run git add + commit + push."""
    print(f"[auto-sync] Detected changes{': ' + reason if reason else ''}")

    # git add all
    result = subprocess.run(
        [GIT, "add", "-A"],
        cwd=root, capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"[auto-sync] git add failed: {result.stderr}")
        return False

    # Check if anything was actually staged
    status = subprocess.run(
        [GIT, "diff", "--cached", "--quiet"],
        cwd=root, capture_output=True, text=True, timeout=10
    )

    if status.returncode == 0:
        print("[auto-sync] Nothing to commit (all changes ignored)")
        return False

    # Commit with timestamp message
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"Auto-sync: {timestamp}"
    if reason:
        message += f" ({reason})"

    result = subprocess.run(
        [GIT, "commit", "-m", message],
        cwd=root, capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"[auto-sync] git commit failed: {result.stderr}")
        return False

    print(f"[auto-sync] Committed: {message}")

    # Push
    result = subprocess.run(
        [GIT, "push", "origin", "main"],
        cwd=root, capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"[auto-sync] git push failed: {result.stderr}")
        return False

    print("[auto-sync] Pushed to GitHub successfully!")
    return True


def run_watchdog(root: Path, interval: float = 3.0, debounce: int = 5):
    """
    Poll-based file watcher.
    - interval: check every N seconds
    - debounce: wait N consecutive detections before committing
    """
    print(f"[auto-sync] Starting watch on {root}")
    print(f"[auto-sync] Debounce: {debounce} detections, interval: {interval}s")
    print("[auto-sync] Press Ctrl+C to stop")

    last_state = get_all_files(root)
    consecutive_changes = 0

    try:
        while True:
            time.sleep(interval)
            current_state = get_all_files(root)

            changed_files = []
            for path, mtime in current_state.items():
                if path not in last_state or last_state[path] != mtime:
                    if not should_ignore(path):
                        changed_files.append(path)

            if changed_files:
                consecutive_changes += 1
                print(f"[auto-sync] {len(changed_files)} file(s) changed (detection #{consecutive_changes})")
                if consecutive_changes >= debounce:
                    reason = ", ".join(changed_files[:5])
                    if len(changed_files) > 5:
                        reason += f" ... (+{len(changed_files)-5} more)"
                    auto_commit_push(root, reason)
                    consecutive_changes = 0
                    last_state = current_state
            else:
                if consecutive_changes > 0:
                    consecutive_changes -= 1
                last_state = current_state

    except KeyboardInterrupt:
        print("\n[auto-sync] Stopped.")


def install_systemd_service():
    """Install as a systemd user service (auto-start on boot)."""
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)

    service_content = f"""[Unit]
Description=Auto-sync photovoltaic_forecasting_pj to GitHub

[Service]
Type=simple
WorkingDirectory={PROJECT_ROOT}
ExecStart=/usr/bin/python3 {__file__}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""

    service_file = service_dir / "auto-sync-pv.service"
    service_file.write_text(service_content)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "auto-sync-pv.service"], check=False)
    subprocess.run(["systemctl", "--user", "start", "auto-sync-pv.service"], check=False)

    print(f"[auto-sync] Systemd service installed!")
    print(f"  Service file: {service_file}")
    print(f"  Enable:  systemctl --user enable auto-sync-pv.service")
    print(f"  Start:   systemctl --user start  auto-sync-pv.service")
    print(f"  Status:  systemctl --user status auto-sync-pv.service")
    print(f"  Logs:    journalctl --user -u auto-sync-pv.service -f")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-sync photovoltaic_forecasting_pj to GitHub")
    parser.add_argument("--once", action="store_true", help="Single sync check then exit")
    parser.add_argument("--interval", type=float, default=3.0, help="Check interval in seconds (default: 3)")
    parser.add_argument("--debounce", type=int, default=5, help="Debounce count (default: 5)")
    parser.add_argument("--install-service", action="store_true", help="Install as systemd service")
    parser.add_argument("--no-daemon", action="store_true", help="Run without daemon mode")
    args = parser.parse_args()

    if args.install_service:
        install_systemd_service()
        sys.exit(0)

    if args.once:
        if has_changes(PROJECT_ROOT):
            auto_commit_push(PROJECT_ROOT, "one-time sync")
        else:
            print("[auto-sync] No changes detected.")
        sys.exit(0)

    if args.no_daemon:
        run_watchdog(PROJECT_ROOT, interval=args.interval, debounce=1)
    else:
        run_watchdog(PROJECT_ROOT, interval=args.interval, debounce=args.debounce)
