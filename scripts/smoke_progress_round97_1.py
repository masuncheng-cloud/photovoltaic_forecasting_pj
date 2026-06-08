#!/usr/bin/env python3
"""
Round97_1 冒烟测试：验证真实动态进度条是否工作。
不读取任何训练数据，不训练任何模型。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ── bootstrap PYTHONPATH ──────────────────────────────────────────────────────
_SRC = Path(__file__).resolve().parents[1] / "src"
if (_SRC / "pv_forecasting/core/progress.py").exists():
    sys.path.insert(0, str(_SRC))

from pv_forecasting.core.progress import progress_iter


def smoke_progress_iter() -> None:
    """直接测试 progress_iter 是否动态刷新。"""
    print("\n[SMOKE] 测试 1/2: progress_iter() 自身")
    collected = []
    for i, _ in enumerate(progress_iter(range(30), desc="progress_iter_smoke", unit="step")):
        collected.append(i)
        time.sleep(0.015)
    assert collected == list(range(30)), f"数据丢失: {len(collected)}/30"
    print(f"[SMOKE] progress_iter 收集了 30 个样本，数据完整 ✓")


def smoke_child_tqdm() -> None:
    """测试子进程 tqdm 在 PV_PROGRESS_MODE=tqdm 下是否正常运行。"""
    print("\n[SMOKE] 测试 2/2: 子进程 tqdm 继承 stdout")
    code = r'''
import os, sys, time
sys.path.insert(0, %r)
from tqdm.auto import tqdm
for i in tqdm(range(30), desc="child_tqdm_smoke", unit="step", dynamic_ncols=True):
    time.sleep(0.01)
print("child tqdm done")  # 正常退出标志
''' % str(_SRC)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "child_tqdm_smoke.py"
        p.write_text(code, encoding="utf-8")
        env = os.environ.copy()
        env["PV_PROGRESS_MODE"] = "tqdm"
        # tqdm 模式：Popen 不使用 stdout=PIPE，直接继承 stdout
        # 若使用 PIPE，子进程的 tqdm 动画会被打碎
        result = subprocess.run(
            [sys.executable, str(p)],
            check=True,
            env=env,
            # 不 PIPE：让子进程 tqdm 直接写到终端
        )
        print(f"[SMOKE] 子进程 tqdm 退出码={result.returncode} ✓")


def smoke_no_regression() -> None:
    """验证 log 模式仍可 fallback，不破坏旧逻辑。"""
    print("\n[SMOKE] 测试 3/3: log 模式 fallback（无 tqdm）")
    code = r'''
import os, sys
os.environ["PV_PROGRESS_MODE"] = "log"
sys.path.insert(0, %r)
from pv_forecasting.core.progress import progress_iter
collected = []
for x in progress_iter(range(5), desc="log_mode_smoke", unit="it"):
    collected.append(x)
assert collected == list(range(5))
print("log mode ok")
''' % str(_SRC)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "log_mode_smoke.py"
        p.write_text(code, encoding="utf-8")
        result = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, check=True)
        assert "log mode ok" in result.stdout, f"log mode 输出异常: {result.stdout}"
        print(f"[SMOKE] log 模式 fallback 正常 ✓")


def main() -> None:
    os.environ.setdefault("PV_PROGRESS", "1")
    os.environ.setdefault("PV_PROGRESS_MODE", "tqdm")

    print("=" * 60)
    print("Round97_1 进度条冒烟测试")
    print("=" * 60)
    print(f"PV_PROGRESS_MODE={os.getenv('PV_PROGRESS_MODE')}")
    print(f"Python={sys.executable}")
    print()

    smoke_progress_iter()
    smoke_child_tqdm()
    smoke_no_regression()

    print()
    print("=" * 60)
    print("[PASS] Round97_1 进度条冒烟测试全部通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
