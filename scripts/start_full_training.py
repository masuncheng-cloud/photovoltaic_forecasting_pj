#!/usr/bin/env python3
"""
start_full_training.py
======================
光伏预测训练统一启动脚本。

用法：
    python3 scripts/start_full_training.py
    python3 scripts/start_full_training.py --force

等同于：
    python3 scripts/run_full_pipeline.py --mode full --force
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    extra_args = sys.argv[1:]

    print("=" * 80, flush=True)
    print("FULL TRAINING WILL RUN IN THE FOREGROUND TERMINAL", flush=True)
    print("请不要使用 nohup、&、disown、tmux/screen 后台执行。", flush=True)
    print("训练过程中请保持此终端打开，直到流程完成。", flush=True)
    print("=" * 80, flush=True)

    cmd = [
        sys.executable,
        str(root / "scripts" / "run_full_pipeline.py"),
        "--mode", "full",
    ]
    if "--force" in extra_args or "-f" in extra_args:
        cmd.append("--force")

    print("[START FULL TRAINING] " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(root))


if __name__ == "__main__":
    raise SystemExit(main())
