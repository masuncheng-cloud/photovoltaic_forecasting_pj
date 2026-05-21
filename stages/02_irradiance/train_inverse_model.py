from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.inverse_model import prepare_inverse_dataset, train_inverse_model


def main():
    parser = build_parser("Train central inverse irradiance model")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    site_master = pd.read_csv(paths.tables / "site_master.csv")
    quality = pd.read_csv(paths.tables / "site_quality.csv")
    power_clean = pd.read_pickle(paths.tables / "power_clean.pkl")
    inverse_df = prepare_inverse_dataset(power_clean, site_master, quality)
    inverse_df.to_pickle(paths.tables / "inverse_train_table.pkl")
    _, metrics_df, pred_df = train_inverse_model(inverse_df, paths.models / "inverse_model.pkl", paths.metrics / "inverse_metrics.csv")
    pred_df.to_pickle(paths.tables / "inverse_predictions.pkl")
    print(metrics_df)


if __name__ == "__main__":
    main()
