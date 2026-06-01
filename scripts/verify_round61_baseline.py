#!/usr/bin/env python3
"""
verify_round61_baseline.py
=========================
复核 Round61 稳定基线是否可恢复。

检查：
1. Git tag 和 commit 是否存在
2. manifest 文件是否存在
3. 关键文件的 SHA256 是否与 manifest 一致
4. 所有 baseline 产物是否可读
"""

from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output/pv_pipeline/baselines/round61"
OUT_DIR = ROOT / "output/pv_pipeline"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def sha256(path):
    p = Path(path)
    if not p.exists():
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except Exception as e:
        return f"ERROR: {e}"


def main():
    print("=" * 60)
    print("Round61 稳定基线复核")
    print("=" * 60)

    rows = []
    passed = 0
    failed = 0
    issues = []

    # ── 1. Git checks ────────────────────────────────────────────────
    print("\n[1] Git 检查")
    branch = git("git branch --show-current")
    commit = git("git rev-parse HEAD")
    tag = "round61-stable-20260601"
    tag_commit = git(f"git rev-list -n 1 {tag}")

    print(f"  分支: {branch}")
    print(f"  当前 commit: {commit}")
    print(f"  Tag: {tag}")
    print(f"  Tag commit: {tag_commit}")

    tag_ok = (tag_commit != "ERROR" and tag_commit != "")
    print(f"  Tag 存在: {'PASS' if tag_ok else 'FAIL'}")

    if not tag_ok:
        issues.append(f"Git tag '{tag}' 不存在！")
        failed += 1
    else:
        passed += 1

    # ── 2. Manifest files ──────────────────────────────────────────
    print("\n[2] Manifest 文件检查")
    manifest_json = BASE / "round61_baseline_manifest.json"
    manifest_csv = BASE / "round61_baseline_files.csv"
    stable_doc = ROOT / "docs/Round61_稳定基线说明.md"

    for f in [manifest_json, manifest_csv, stable_doc]:
        ok = f.exists()
        status = "PASS" if ok else "FAIL"
        if not ok:
            issues.append(f"关键文件缺失: {f.relative_to(ROOT)}")
            failed += 1
        else:
            passed += 1
        print(f"  {status} {f.relative_to(ROOT)}")

    # ── 3. SHA256 check ────────────────────────────────────────────
    print("\n[3] SHA256 完整性检查")
    if not manifest_csv.exists():
        print("  [SKIP] manifest CSV 不存在，跳过 SHA256 检查")
    else:
        import pandas as pd
        mdf = pd.read_csv(manifest_csv)

        for _, r in mdf.iterrows():
            path_str = r["path"]
            expected_sha = r["sha256"]
            p = ROOT / path_str

            if not p.exists():
                print(f"  FAIL {path_str}: 文件不存在")
                issues.append(f"文件不存在: {path_str}")
                failed += 1
                rows.append({
                    "path": path_str,
                    "status": "FAIL",
                    "reason": "file missing",
                    "expected_sha": expected_sha,
                    "actual_sha": "N/A",
                })
                continue

            actual_sha = sha256(p)
            match = (str(actual_sha) == str(expected_sha))
            status = "PASS" if match else "FAIL"
            reason = "" if match else f"sha256 mismatch (expected {str(expected_sha)[:8]}..., got {str(actual_sha)[:8]}...)"

            if not match:
                issues.append(f"SHA256 不一致: {path_str}")
                failed += 1
            else:
                passed += 1

            rows.append({
                "path": path_str,
                "status": status,
                "reason": reason,
                "expected_sha": str(expected_sha),
                "actual_sha": str(actual_sha),
            })
            print(f"  {status} {path_str}")

    # ── 4. Verify prediction column ────────────────────────────────
    print("\n[4] 预测列检查")
    try:
        import pandas as pd
        eval_pkl = ROOT / "output/pv_pipeline/baselines/round61/distributed_predictions_final_eval.pkl"
        if eval_pkl.exists():
            df = pd.read_pickle(eval_pkl)
            pred_cols = [c for c in df.columns if "pred" in c.lower() and "final" in c.lower()]
            has_final = "power_pred_final" in df.columns
            print(f"  PASS  eval pkl 可读, columns with 'pred' and 'final': {pred_cols}")
            print(f"  power_pred_final 存在: {has_final}")
            if has_final:
                passed += 1
            else:
                issues.append("power_pred_final 列不存在")
                failed += 1
        else:
            print(f"  FAIL  eval pkl 不存在")
            issues.append("baseline eval pkl 不存在")
            failed += 1
    except Exception as e:
        print(f"  FAIL  读取 pkl 失败: {e}")
        issues.append(f"读取 pkl 失败: {e}")
        failed += 1

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"复核结果: {passed} PASS | {failed} FAIL")
    print(f"{'='*60}")

    # Save CSV report
    import pandas as pd
    rows_df = pd.DataFrame(rows)
    csv_path = OUT_DIR / "baselines/round61/round61_baseline_verify_report.csv"
    rows_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[INFO] CSV 报告: {csv_path}")

    # Generate markdown report
    tag_on_main = git(f"git log --oneline main | head -1")
    tag_on_exp = git(f"git log --oneline experiment/model-structure-round62 | head -1")

    md = f"""# Round63_Round61基线复核报告

## 复核结果

| 项目 | 内容 | 状态 |
|------|------|:----:|
| 当前分支 | `{branch}` | {'✓' if 'experiment' in branch else '○'} |
| 当前 commit | `{commit[:8]}` | ✓ |
| Round61 tag | `{tag}` | {'✓' if tag_ok else '✗'} |
| Tag commit | `{tag_commit[:8]}` | {'✓' if tag_ok else '✗'} |
| manifest.json | `{manifest_json.name}` | {'✓' if manifest_json.exists() else '✗'} |
| manifest.csv | `{manifest_csv.name}` | {'✓' if manifest_csv.exists() else '✗'} |
| 基线说明 | `docs/Round61_稳定基线说明.md` | {'✓' if stable_doc.exists() else '✗'} |

## SHA256 完整性

| 状态 | 数量 |
|:----:|-----:|
| PASS | {passed} |
| FAIL | {failed} |

## 失败项

"""

    if failed == 0:
        md += "> 所有检查通过。Round61 基线可恢复。\n"
    else:
        md += f"> 发现 {failed} 个问题：\n\n"
        for issue in issues:
            md += f"- {issue}\n"

    md += f"""
## 详细 SHA256

详细 SHA256 对比见: `output/pv_pipeline/baselines/round61/round61_baseline_verify_report.csv`

## 结论

**{'PASS - Round61 基线可恢复' if failed == 0 else 'FAIL - 需要修复后继续'}**
"""
    md_path = ROOT / "docs/Round63_Round61基线复核报告.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[INFO] 报告: {md_path}")

    if failed > 0:
        print(f"\n[FAIL] 发现 {failed} 个问题，请修复后继续！")
        sys.exit(1)
    else:
        print(f"\n[PASS] Round61 基线验证通过！")
        sys.exit(0)


if __name__ == "__main__":
    main()
