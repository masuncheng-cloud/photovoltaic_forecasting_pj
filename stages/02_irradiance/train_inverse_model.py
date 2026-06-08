from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.inverse_model import prepare_inverse_dataset, train_inverse_model
from pv_forecasting.core.progress import stage_log


def main():
    parser = build_parser("Train central inverse irradiance model")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    stage_log("[3b.1] 加载集中式功率、气象、站点数据")
    site_master = pd.read_csv(paths.tables / "site_master.csv")
    quality = pd.read_csv(paths.tables / "site_quality.csv")
    power_clean = pd.read_pickle(paths.tables / "power_clean.pkl")

    stage_log("[3b.2] 构建辐照反演训练样本")
    inverse_df = prepare_inverse_dataset(power_clean, site_master, quality)
    inverse_df["split"] = inverse_df["year"].apply(
        lambda y: "train" if y <= 2024 else ("valid" if y == 2025 else "test")
    )
    inverse_df.to_pickle(paths.tables / "inverse_train_table.pkl")
    stage_log(
        f"[3b] inverse dataset rows={len(inverse_df):,}, "
        f"train={(inverse_df['split'] == 'train').sum():,}, "
        f"valid={(inverse_df['split'] == 'valid').sum():,}, "
        f"test={(inverse_df['split'] == 'test').sum():,}"
    )

    stage_log("[3b.3] 训练辐照反演模型")
    _, metrics_df, pred_df = train_inverse_model(inverse_df, paths.models / "inverse_model.pkl", paths.metrics / "inverse_metrics.csv")
    pred_df.to_pickle(paths.tables / "inverse_predictions.pkl")
    stage_log("[3b.4] 生成 train/valid/test 预测与指标")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    main()
