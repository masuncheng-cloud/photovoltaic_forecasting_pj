
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PipelinePaths:
    project_root: Path
    data_root: Path
    output_root: Path

    @property
    def year_2023(self) -> Path:
        return self.data_root / "2023"

    @property
    def year_2024(self) -> Path:
        return self.data_root / "2024"

    @property
    def year_2025(self) -> Path:
        return self.data_root / "2025"

    @property
    def power_root(self) -> Path:
        return self.data_root / "power_data"

    @property
    def tcc_strd_root(self) -> Path:
        return self.data_root / "tcc_strd"

    @property
    def tables(self) -> Path:
        return self.output_root / "tables"

    @property
    def models(self) -> Path:
        return self.output_root / "models"

    @property
    def metrics(self) -> Path:
        return self.output_root / "metrics"

    @property
    def figures(self) -> Path:
        return self.output_root / "figures"

    @property
    def logs(self) -> Path:
        return self.output_root / "logs"
