from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.evaluation import evaluate_city_total, evaluate_data_quality, evaluate_distributed_by_county, evaluate_distributed_by_site, evaluate_pred_by_group, get_top_day_zero_sites, plot_typical_day


def main():
    parser = build_parser("Evaluate full pipeline")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    site_master = pd.read_csv(paths.tables / "site_master.csv")
    power_clean = pd.read_pickle(paths.tables / "power_clean.pkl")
    mapping = pd.read_csv(paths.tables / "power_mapping.csv")
    pred_df = pd.read_pickle(paths.tables / "distributed_predictions.pkl")

    data_quality = evaluate_data_quality(power_clean, mapping, site_master)
    data_quality.to_csv(paths.metrics / "data_quality_metrics.csv", index=False, encoding="utf-8-sig")

    top_zero = get_top_day_zero_sites(power_clean, site_master, top_n=30)
    top_zero.to_csv(paths.metrics / "top_day_zero_sites.csv", index=False, encoding="utf-8-sig")

    by_site = evaluate_distributed_by_site(pred_df, site_master)
    by_site.to_csv(paths.metrics / "distributed_metrics_by_site.csv", index=False, encoding="utf-8-sig")

    by_county = evaluate_distributed_by_county(pred_df)
    by_county.to_csv(paths.metrics / "distributed_metrics_by_county.csv", index=False, encoding="utf-8-sig")

    if "group_key" in pred_df.columns:
        by_group = evaluate_pred_by_group(pred_df, "group_key")
        by_group.to_csv(paths.metrics / "distributed_metrics_by_group.csv", index=False, encoding="utf-8-sig")

    if "scene_label" in pred_df.columns:
        by_scene = evaluate_pred_by_group(pred_df, "scene_label")
        by_scene.to_csv(paths.metrics / "distributed_metrics_by_scene.csv", index=False, encoding="utf-8-sig")

    city = evaluate_city_total(pred_df)
    city.to_csv(paths.metrics / "distributed_metrics_city_total.csv", index=False, encoding="utf-8-sig")

    plot_typical_day(pred_df, paths.figures / "city_total_typical_day.png")
    print(data_quality)
    print(city)


if __name__ == "__main__":
    main()
