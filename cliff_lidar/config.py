"""Configuration objects for the cliff LiDAR pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime configuration for one pipeline execution."""

    workspace: Path
    index_path: Path
    region_path: Path | None = None
    lidar_urls_path: Path | None = None
    geology_path: Path | None = None
    quarry_path: Path | None = None
    min_slope: float = 70.0
    min_surface: float = 100.0
    min_height: float = 15.0
    score_slope_weight: float = 0.7
    score_height_cap: float = 50.0
    quarry_distance: float = 1000.0
    delete_mnt: bool = True
    lidar_url_template: str = (
        "ftp://transfert.mffp.gouv.qc.ca/Public/Diffusion/DonneeGratuite/"
        "Foret/IMAGERIE/Produits_derives_LiDAR/{prefix}/{tile}/MNT_{tile}.tif"
    )

    def __post_init__(self) -> None:
        if self.min_slope < 0 or self.min_slope > 90:
            raise ValueError("min_slope must be between 0 and 90 degrees")
        if self.min_surface < 0:
            raise ValueError("min_surface must be positive")
        if self.min_height < 0:
            raise ValueError("min_height must be positive")
        if self.score_slope_weight < 0 or self.score_slope_weight > 1:
            raise ValueError("score_slope_weight must be between 0 and 1")
        if self.score_height_cap <= 0:
            raise ValueError("score_height_cap must be positive")
        if self.quarry_distance < 0:
            raise ValueError("quarry_distance must be positive")


@dataclass(frozen=True)
class Target:
    """Region or custom shape to process."""

    name: str
    mode: str
    region_codes: tuple[str, ...] = field(default_factory=tuple)
    shape_paths: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def for_regions(cls, region_codes: Iterable[str]) -> "Target":
        codes = tuple(str(code) for code in region_codes)
        if not codes:
            raise ValueError("At least one administrative region code is required")
        return cls(name="_".join(codes), mode="region", region_codes=codes)

    @classmethod
    def for_shapes(cls, shape_paths: Iterable[Path]) -> "Target":
        paths = tuple(Path(path) for path in shape_paths)
        if not paths:
            raise ValueError("At least one custom shapefile is required")
        name = "_".join(path.stem for path in paths)
        return cls(name=name, mode="shape", shape_paths=paths)
