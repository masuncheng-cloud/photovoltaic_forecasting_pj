#!/usr/bin/env python3
"""
光伏预测结果综合分析脚本
- 计算每个站点的真实值/预测值统计
- 标注最好的5个、最差的5个站点
- 标注0值过多或样本数过少的站点
"""

import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline/metrics")

def load_and_process(path):
    df = pd.read_csv(path)
    cols = list(df.columns)
    real_cols = [c for c in cols if c.endswith("_总出力值")]
    pred_cols = [c for c in cols if c.endswith("_预测")]
    # 确保顺序一致（去掉后缀后名称一致）
    real_cols_sorted = sorted(real_cols)
    pred_cols_sorted = sorted(pred_cols)

    # 从列名中提取站点名
    def station_name(c, suffix):
        return c.replace(suffix, "")

    real_stations = {station_name(c, "_总出力值"): c for c in real_cols_sorted}
    pred_stations = {station_name(c, "_预测"): c for c in pred_cols_sorted}

    # 取交集，保证顺序一致
    common = sorted(real_stations.keys() & pred_stations.keys())
    real_ordered = [real_stations[s] for s in common]
    pred_ordered = [pred_stations[s] for s in common]

    return df, common, real_ordered, pred_ordered


def compute_metrics(series_true, series_pred):
    """计算各类指标"""
    t = np.array(series_true, dtype=float)
    p = np.array(series_pred, dtype=float)

    # 只用非零真值计算相对误差类指标
    nonzero = t != 0
    mae = np.mean(np.abs(t - p))
    rmse = np.sqrt(np.mean((t - p) ** 2))
    mse = np.mean((t - p) ** 2)

    # 非零样本的相对误差
    if nonzero.sum() > 0:
        rel_mae = np.mean(np.abs(t[nonzero] - p[nonzero]) / np.abs(t[nonzero]))
        rel_rmse = np.sqrt(np.mean(((t[nonzero] - p[nonzero]) / np.abs(t[nonzero])) ** 2))
    else:
        rel_mae = np.nan
        rel_rmse = np.nan

    # 零值比例
    zero_rate = np.mean(t == 0)

    # 非零样本比例
    nonzero_rate = np.mean(t != 0)

    # 非零样本数
    n_nonzero = int(nonzero.sum())
    n_total = len(t)

    # 预测偏离：真值>某阈值但预测<阈值的比例（用1MW作为阈值）
    threshold = 1.0
    high_true = t >= threshold
    if high_true.sum() > 0:
        under_pred_pct = np.mean(p[high_true] < threshold * 0.5)  # 预测严重偏低比例
    else:
        under_pred_pct = np.nan

    # 相关系数
    if len(t) > 1:
        corr = np.corrcoef(t, p)[0, 1]
    else:
        corr = np.nan

    return {
        "MAE": mae,
        "RMSE": rmse,
        "MSE": mse,
        "Rel_MAE": rel_mae,
        "Rel_RMSE": rel_rmse,
        "Zero_Rate": zero_rate,
        "NonZero_Rate": nonzero_rate,
        "N_NonZero": n_nonzero,
        "N_Total": n_total,
        "UnderPred_Pct": under_pred_pct,
        "Corr": corr,
        "True_Mean": np.mean(t),
        "True_Std": np.std(t),
        "True_Max": np.max(t),
        "Pred_Mean": np.mean(p),
        "Pred_Std": np.std(p),
        "Pred_Max": np.max(p),
    }


def get_zero_samples(series_true, series_pred, time_col):
    """找出真实值为0但预测值不为0的典型样本"""
    t = np.array(series_true, dtype=float)
    p = np.array(series_pred, dtype=float)
    times = np.array(time_col)
    idx = (t == 0) & (p > 0.1)
    if idx.sum() > 0:
        rows = []
        for i in np.where(idx)[0][:10]:  # 最多取10条
            rows.append((times[i], float(t[i]), float(p[i])))
        return rows
    return []


def main():
    # ── 读取数据 ──────────────────────────────────────────────────────
    file1 = BASE / "分布式光伏预测_前38座_已标注.csv"
    file2 = BASE / "分布式光伏预测_后40座_已标注.csv"

    df1, stations1, real1, pred1 = load_and_process(file1)
    df2, stations2, real2, pred2 = load_and_process(file2)

    print(f"前38座站点数: {len(stations1)}")
    print(f"后40座站点数: {len(stations2)}")

    # ── 合并所有站点 ──────────────────────────────────────────────────
    all_stations = stations1 + stations2
    all_real = real1 + pred1[:0]  # placeholder
    all_pred = pred1 + pred2

    # 重新构建
    all_data = {}
    for s, r, p in zip(stations1 + stations2,
                        real1 + [df2.columns[0]] * len(stations2),  # need fix
                        pred1 + pred2):
        pass  # structure already correct

    # ── 对每个文件分别计算 ────────────────────────────────────────────
    results = {}

    for df, stations, real_cols, pred_cols in [(df1, stations1, real1, pred1),
                                                 (df2, stations2, real2, pred2)]:
        for s, r_col, p_col in zip(stations, real_cols, pred_cols):
            key = s
            series_true = df[r_col].values
            series_pred = df[p_col].values
            time_col = df["time"].values

            m = compute_metrics(series_true, series_pred)
            m["Zero_Samples"] = get_zero_samples(series_true, series_pred, time_col)
            m["True_Series"] = series_true
            m["Pred_Series"] = series_pred
            m["Time_Series"] = time_col
            results[key] = m

    # ── 综合评分：综合MAE和相对误差 ─────────────────────────────────
    scored = []
    for s, m in results.items():
        mae = m["MAE"]
        rel_mae = m["Rel_MAE"] if not np.isnan(m["Rel_MAE"]) else 10.0
        zero_rate = m["Zero_Rate"]
        n_nonzero = m["N_NonZero"]

        # 综合评分（越小越好）
        # 惩罚：高零值率 + 低样本数 + 高相对误差
        score = mae * (1 + rel_mae * 0.5) * (1 + zero_rate * 0.3) * (1 + max(0, 3000 - n_nonzero) / 10000)
        m["Composite_Score"] = score
        scored.append((s, score, mae, rel_mae, m["Corr"], m["Zero_Rate"], m["N_NonZero"]))

    scored.sort(key=lambda x: x[1])

    # ── 分类 ────────────────────────────────────────────────────────
    best5 = scored[:5]
    worst5 = scored[-5:]

    # 0值过多或样本过少
    zero_heavy = [(s, m) for s, m in results.items()
                  if m["Zero_Rate"] >= 0.60 or m["N_NonZero"] < 2000]
    zero_heavy.sort(key=lambda x: x[1]["Zero_Rate"], reverse=True)

    print("\n" + "=" * 80)
    print("一、预测最好的5个站点")
    print("=" * 80)
    print(f"{'站点名':<30} {'综合评分':>10} {'MAE':>8} {'相对MAE':>10} {'相关系数':>10} {'零值率':>8} {'有效样本':>8}")
    print("-" * 80)
    for s, score, mae, rel_mae, corr, zr, nnz in best5:
        print(f"{s:<30} {score:>10.4f} {mae:>8.4f} {rel_mae:>10.4f} {corr:>10.4f} {zr:>8.2%} {nnz:>8d}")

    print("\n" + "=" * 80)
    print("二、预测最差的5个站点")
    print("=" * 80)
    print(f"{'站点名':<30} {'综合评分':>10} {'MAE':>8} {'相对MAE':>10} {'相关系数':>10} {'零值率':>8} {'有效样本':>8}")
    print("-" * 80)
    for s, score, mae, rel_mae, corr, zr, nnz in worst5:
        print(f"{s:<30} {score:>10.4f} {mae:>8.4f} {rel_mae:>10.4f} {corr:>10.4f} {zr:>8.2%} {nnz:>8d}")

    print("\n" + "=" * 80)
    print("三、0值过多或样本数过少的站点（零值率>=60% 或 有效非零样本<2000）")
    print("=" * 80)
    print(f"{'站点名':<30} {'零值率':>10} {'有效样本':>10} {'MAE':>10} {'相对MAE':>10}")
    print("-" * 80)
    for s, m in zero_heavy:
        print(f"{s:<30} {m['Zero_Rate']:>10.2%} {m['N_NonZero']:>10d} {m['MAE']:>10.4f} {m['Rel_MAE']:>10.4f}")

    # ── 详细真实值/预测值对比（选取典型时段）─────────────────────────
    print("\n" + "=" * 80)
    print("四、各站点真实值 vs 预测值 典型时段对比（选取白天有功时段代表性样本）")
    print("=" * 80)

    for df, stations, real_cols, pred_cols, label in [
        (df1, stations1, real1, pred1, "前38座"),
        (df2, stations2, real2, pred2, "后40座"),
    ]:
        print(f"\n{'─'*80}")
        print(f"▶ {label} ({len(stations)}座)")
        print(f"{'─'*80}")

        for s, r_col, p_col in zip(stations, real_cols, pred_cols):
            true_arr = df[r_col].values.astype(float)
            pred_arr = df[p_col].values.astype(float)
            times = df["time"].values

            # 找白天有功时段（真值>0.5MW）的代表性时间点
            nonzero_mask = true_arr > 0.5
            if nonzero_mask.sum() == 0:
                continue

            # 取该站点有功时段的全部时间点
            nz_indices = np.where(nonzero_mask)[0]
            # 选取最多20个均匀分布的点
            step = max(1, len(nz_indices) // 20)
            selected = nz_indices[::step][:20]

            # 找预测最不准的点（误差最大）
            abs_err = np.abs(true_arr - pred_arr)
            worst_idx = np.argmax(abs_err)

            # 零值误判最多的
            zero_true_nonzero_pred = (true_arr == 0) & (pred_arr > 0.1)
            ztnp_count = zero_true_nonzero_pred.sum()

            m = results[s]

            print(f"\n  【{s}】")
            print(f"    总样本:{len(true_arr)} 有效非零样本:{m['N_NonZero']} 零值率:{m['Zero_Rate']:.1%} "
                  f"MAE:{m['MAE']:.4f} 相对MAE:{m['Rel_MAE']:.4f} 相关系数:{m['Corr']:.4f}")
            print(f"    真值均值:{m['True_Mean']:.4f} 预测均值:{m['Pred_Mean']:.4f} "
                  f"真值峰值:{m['True_Max']:.4f} 预测峰值:{m['Pred_Max']:.4f}")
            if ztnp_count > 0:
                print(f"    ⚠️ 零值误判: 真值为0但预测>0.1MW的点数: {ztnp_count} 个")

            # 显示典型时段对比（选取的代表性点）
            print(f"    {'时间':<20} {'真实值':>10} {'预测值':>10} {'误差':>10} {'相对误差':>10}")
            print(f"    {'-'*60}")
            for i in selected:
                t_val = true_arr[i]
                p_val = pred_arr[i]
                err = p_val - t_val
                rel_err = abs(err / t_val) if t_val != 0 else 0
                print(f"    {str(times[i]):<20} {t_val:>10.4f} {p_val:>10.4f} {err:>+10.4f} {rel_err:>10.2%}")

            # 显示误差最大的点
            if worst_idx in selected:
                print(f"    ⬛ 误差最大点(在代表性样本中已标出)")
            else:
                t_val = true_arr[worst_idx]
                p_val = pred_arr[worst_idx]
                err = p_val - t_val
                rel_err = abs(err / t_val) if t_val != 0 else 0
                print(f"    ⬛ 误差最大点: {str(times[worst_idx]):<20} 真:{t_val:.4f} 预:{p_val:.4f} 误差:{err:+.4f} ({rel_err:.1%})")

    # ── 输出CSV汇总 ──────────────────────────────────────────────────
    rows = []
    for s, m in results.items():
        rows.append({
            "站点名": s,
            "总样本数": m["N_Total"],
            "有效非零样本": m["N_NonZero"],
            "零值率": m["Zero_Rate"],
            "MAE": m["MAE"],
            "RMSE": m["RMSE"],
            "MSE": m["MSE"],
            "相对MAE": m["Rel_MAE"],
            "相对RMSE": m["Rel_RMSE"],
            "相关系数": m["Corr"],
            "真值均值": m["True_Mean"],
            "真值最大值": m["True_Max"],
            "预测均值": m["Pred_Mean"],
            "预测最大值": m["Pred_Max"],
            "综合评分": m["Composite_Score"],
        })

    summary_df = pd.DataFrame(rows).sort_values("综合评分")
    out_path = BASE / "预测质量综合排名.csv"
    summary_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n\n✅ 汇总排名已保存至: {out_path}")


if __name__ == "__main__":
    main()
