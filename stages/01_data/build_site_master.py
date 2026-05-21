from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.site_master import build_site_master


def main():
    parser = build_parser("Build site master")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)
    site_master = build_site_master(paths.power_root)
    site_master.to_csv(paths.tables / "site_master.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] site_master rows={len(site_master)} -> {paths.tables / 'site_master.csv'}")


if __name__ == "__main__":
    main()
