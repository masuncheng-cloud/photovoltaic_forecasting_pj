#!/usr/bin/env python3
"""
Round97_1 训练进度覆盖审计
扫描关键训练文件中的 .fit() / train() / 循环附近是否有进度反馈机制。
输出 CSV: output/pv_pipeline/validation/round97_1_training_progress_coverage.csv
"""
from __future__ import annotations

import ast
import csv
import re
import sys
from pathlib import Path
from typing import Optional

_SRC = Path(__file__).resolve().parents[1] / "src"
if (_SRC / "pv_forecasting").exists():
    sys.path.insert(0, str(_SRC))


# ── 需要扫描的文件 ────────────────────────────────────────────────────────────
TARGET_FILES = [
    "stages/02_irradiance/train_inverse_model.py",
    "src/pv_forecasting/tasks/inverse_model.py",
    "stages/02_irradiance/train_irradiance_blend.py",
    "src/pv_forecasting/tasks/irradiance_blend.py",
    "stages/03_power/train_distributed_model_v159.py",
    "src/pv_forecasting/tasks/distributed_power_v152.py",
    "scripts/apply_final_calibration.py",
    "scripts/compute_final_metrics.py",
    "scripts/export_interactive_dashboard_data.py",
]

# 进度相关关键词
PROGRESS_KEYWORDS = [
    "progress_iter", "tqdm", "auto tqdm",
    "verbose", "callback", "on_epoch_end",
    "ProgressBar", "pbar", "update_progress",
    "进度", "step", "iter", "count",
]

# 高风险模式：真正的训练/拟合调用
TRAIN_PATTERNS = [
    r"\.fit\(",
    r"\.train\(",
    r"model\.predict\(",
    r"model_ensemble\.predict\(",
    r"build_model\(",
    r"inverse_model\.predict\(",
    r"inverse_model_predict\(",
]

# 中风险模式：长循环
LOOP_PATTERNS = [
    r"\bfor\b",
    r"\bwhile\b",
    r"\.apply\(",
    r"\.apply_async\(",
    r"\.map\(",
    r"\.starmap\(",
]


def _near_code(lines: list[str], lineno: int, window: int = 30) -> str:
    """返回 lineno 前后 window 行的代码片段。"""
    start = max(0, lineno - window)
    end = min(len(lines), lineno + window)
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))


def _has_progress(lines: list[str], lineno: int, window: int = 30) -> bool:
    """判断 lineno 附近 window 行内是否有进度相关关键词。"""
    start = max(0, lineno - window)
    end = min(len(lines), lineno + window)
    chunk = " ".join(lines[start:end]).lower()
    return any(kw.lower() in chunk for kw in PROGRESS_KEYWORDS)


def _detect_loop_size(lines: list[str], lineno: int) -> Optional[str]:
    """尝试从上下文推断循环规模。"""
    start = max(0, lineno - 10)
    end = min(len(lines), lineno + 10)
    for i in range(start, end):
        m = re.search(r"range\s*\(\s*(\d+)", lines[i])
        if m:
            n = int(m.group(1))
            if n >= 1000:
                return f"range({n}) — 大规模"
            elif n >= 100:
                return f"range({n}) — 中规模"
            else:
                return f"range({n}) — 小规模"
        m = re.search(r"len\s*\(\s*([^)]+)\)", lines[i])
        if m:
            return f"len({m.group(1)}) — 需运行时才知道规模"
    return None


def _risk_level(pattern: str, has_progress: bool, loop_size: Optional[str]) -> str:
    if has_progress:
        return "LOW"
    if any(re.match(p, pattern) for p in TRAIN_PATTERNS):
        if loop_size and "大" in loop_size:
            return "HIGH"
        return "MEDIUM"
    if any(re.match(p, pattern) for p in LOOP_PATTERNS):
        if loop_size and "大" in loop_size:
            return "MEDIUM"
        return "LOW"
    return "LOW"


def _suggestion(pattern: str, has_progress: bool, loop_size: Optional[str]) -> str:
    if has_progress:
        return "已覆盖进度反馈"
    if any(re.match(p, pattern) for p in TRAIN_PATTERNS):
        if "大" in (loop_size or ""):
            return "高风险：大规模训练无进度反馈，建议添加 callback 或 progress_iter"
        return "建议添加 progress_iter 或 verbose callback"
    if any(re.match(p, pattern) for p in LOOP_PATTERNS):
        return "建议添加 progress_iter 包装循环"
    return "轻量计算，无需进度反馈"


def audit_file(filepath: Path) -> list[dict]:
    """审计单个文件，返回所有命中结果。"""
    if not filepath.exists():
        return []

    # Try AST first, fallback to regex
    try:
        src = filepath.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(filepath))
    except Exception:
        src = filepath.read_text(encoding="utf-8")

    lines = src.splitlines()
    results = []

    # 模式1：基于 AST 的 .fit() / .train() 检测
    try:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_repr = ""
                if isinstance(node.func, ast.Attribute):
                    func_repr = f"{node.func.value.id if isinstance(node.func.value, ast.Name) else ''}.{node.func.attr}"
                elif isinstance(node.func, ast.Name):
                    func_repr = node.func.id

                for pat in TRAIN_PATTERNS:
                    if re.search(pat, func_repr):
                        lineno = node.lineno
                        has_prog = _has_progress(lines, lineno)
                        loop_sz = _detect_loop_size(lines, lineno)
                        results.append({
                            "file": str(filepath.relative_to(filepath.parents[1])),
                            "line": lineno,
                            "pattern": func_repr,
                            "near_progress": "YES" if has_prog else "NO",
                            "near_callback": "YES" if "callback" in " ".join(lines[max(0,lineno-30):lineno+5]).lower() else "NO",
                            "loop_size": loop_sz or "N/A",
                            "risk_level": _risk_level(pat, has_prog, loop_sz),
                            "suggestion": _suggestion(pat, has_prog, loop_sz),
                            "snippet": _near_code(lines, lineno).replace("\n", " || "),
                        })
    except Exception:
        pass

    # 模式2：基于正则的长循环检测（补充 AST 未覆盖的情况）
    for lineno, line in enumerate(lines, start=1):
        # 跳过注释和字符串
        try:
            code_line = ast.parse(line).body[0]
            continue
        except Exception:
            pass
        if line.strip().startswith("#") or not line.strip():
            continue

        for pat in LOOP_PATTERNS:
            if re.search(pat, line) and "progress_iter" not in line and "tqdm" not in line:
                # 避免重复添加
                already = any(r["line"] == lineno and r["pattern"] == pat for r in results)
                if not already:
                    loop_sz = _detect_loop_size(lines, lineno)
                    results.append({
                        "file": str(filepath.relative_to(filepath.parents[1])),
                        "line": lineno,
                        "pattern": f"循环: {line.strip()[:80]}",
                        "near_progress": _has_progress(lines, lineno),
                        "near_callback": "N/A",
                        "loop_size": loop_sz or "需手动确认",
                        "risk_level": _risk_level(pat, _has_progress(lines, lineno), loop_sz),
                        "suggestion": _suggestion(pat, _has_progress(lines, lineno), loop_sz),
                        "snippet": _near_code(lines, lineno).replace("\n", " || "),
                    })
                break

    return results


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "output" / "pv_pipeline" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "round97_1_training_progress_coverage.csv"

    all_results = []
    for rel_path in TARGET_FILES:
        fp = project_root / rel_path
        results = audit_file(fp)
        all_results.extend(results)

    # 按 risk_level 排序：HIGH > MEDIUM > LOW
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_results.sort(key=lambda r: (risk_order.get(r["risk_level"], 3), r["file"], r["line"]))

    fieldnames = ["file", "line", "pattern", "near_progress", "near_callback", "loop_size", "risk_level", "suggestion", "snippet"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    # 汇总打印
    high = [r for r in all_results if r["risk_level"] == "HIGH"]
    medium = [r for r in all_results if r["risk_level"] == "MEDIUM"]
    low = [r for r in all_results if r["risk_level"] == "LOW"]

    print("=" * 70)
    print(f"Round97_1 训练进度覆盖审计")
    print("=" * 70)
    print(f"扫描文件: {len(TARGET_FILES)} 个")
    print(f"总命中:   {len(all_results)} 项")
    print(f"HIGH:     {len(high)} 项 ← 需重点关注")
    print(f"MEDIUM:   {len(medium)} 项")
    print(f"LOW:      {len(low)} 项")
    print(f"输出:     {out_csv}")
    print()

    if high:
        print("【HIGH 风险项】")
        for r in high:
            print(f"  [{r['file']}:{r['line']}] {r['pattern']}")
            print(f"    loop={r['loop_size']}  near_progress={r['near_progress']}")
            print(f"    建议: {r['suggestion']}")
        print()

    if medium:
        print("【MEDIUM 风险项】（前 10 项）")
        for r in medium[:10]:
            print(f"  [{r['file']}:{r['line']}] {r['pattern'][:60]}")
        if len(medium) > 10:
            print(f"  ... 共 {len(medium)} 项，见 CSV")
        print()

    print("✅ 审计完成")


if __name__ == "__main__":
    main()
