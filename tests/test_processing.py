from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from cliff_lidar.config import PipelineConfig, Target
from cliff_lidar.processing import (
    add_priority_score,
    format_byte_count,
    limit_tiles,
    mnt_url_for_tile,
    normalize_tile_name,
)


def make_config(tmp_path: Path, **overrides) -> PipelineConfig:
    values = {
        "workspace": tmp_path / "output",
        "index_path": tmp_path / "index.zip",
        "lidar_urls_path": None,
    }
    values.update(overrides)
    return PipelineConfig(**values)


def test_normalize_tile_name_uses_lidar_cardinal_suffix_and_uppercase() -> None:
    assert normalize_tile_name("21e13202") == "21E13NE"
    assert normalize_tile_name("31H01201") == "31H01NO"
    assert normalize_tile_name("31H01102") == "31H01SE"
    assert normalize_tile_name("31H01101") == "31H01SO"


def test_mnt_url_prefers_lidar_csv(workspace_tmp: Path) -> None:
    csv_path = workspace_tmp / "URL_Lidar.csv"
    csv_path.write_text(
        "Feuillet20K,MNT\n"
        "21E13NE,https://example.test/MNT_21E13NE.tif\n",
        encoding="utf-8",
    )
    config = make_config(workspace_tmp, lidar_urls_path=csv_path)

    assert mnt_url_for_tile(config, "21e13ne") == "https://example.test/MNT_21E13NE.tif"


def test_mnt_url_falls_back_to_template(workspace_tmp: Path) -> None:
    config = make_config(workspace_tmp)

    assert mnt_url_for_tile(config, "21E13NE").endswith("/21E/21E13NE/MNT_21E13NE.tif")


def test_format_byte_count_for_download_progress() -> None:
    assert format_byte_count(12 * 1024 * 1024) == "12.0 MB"
    assert format_byte_count(2 * 1024 * 1024 * 1024) == "2.00 GB"


def test_target_for_tiles_normalizes_codes() -> None:
    target = Target.for_tiles(["31j01se"])

    assert target.name == "tiles_31J01SE"
    assert target.mode == "tile"
    assert target.tile_codes == ("31J01SE",)


def test_limit_tiles_keeps_first_selected_tiles(workspace_tmp: Path) -> None:
    config = make_config(workspace_tmp, max_tiles=2)

    assert limit_tiles(config, ["A", "B", "C"]) == ["A", "B"]


def test_priority_score_weights_slope_ahead_of_height(workspace_tmp: Path) -> None:
    config = make_config(workspace_tmp, min_slope=70, score_slope_weight=0.7, score_height_cap=50)
    candidates = gpd.GeoDataFrame(
        {
            "hauteur": [15.0, 100.0],
            "pente_moy": [85.0, 70.0],
        },
        geometry=[box(0, 0, 1, 1), box(2, 0, 3, 1)],
        crs="EPSG:32198",
    )

    scored = add_priority_score(candidates, config)

    assert scored.loc[0, "score"] > scored.loc[1, "score"]
    assert scored.loc[0, "priorite"] == "B"
    assert scored.loc[1, "priorite"] == "C"
