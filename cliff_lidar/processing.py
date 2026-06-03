"""Core processing for cliff detection from DEM tiles."""

from __future__ import annotations

import datetime as dt
import os
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterstats import zonal_stats
from shapely.geometry import shape

try:
    import fiona

    fiona.supported_drivers["KML"] = "rw"
except ImportError:  # pragma: no cover - fiona is normally pulled by geopandas
    pass

try:
    from osgeo import gdal
except ImportError:  # pragma: no cover - depends on local GDAL packaging
    import gdal  # type: ignore

from .config import PipelineConfig, Target


TILE_SUFFIXES = {
    "202": "NE",
    "201": "NO",
    "102": "SE",
    "101": "SO",
}

_LIDAR_URL_CACHE: dict[Path, dict[str, str]] = {}


def run_pipeline(config: PipelineConfig, target: Target) -> Path | None:
    """Run the full pipeline for one target and return the merged output path."""

    start = dt.datetime.now()
    selected_area, tile_codes = select_tiles(config, target)
    total_tiles = len(tile_codes)
    tile_codes = limit_tiles(config, tile_codes)
    output_dir = config.workspace / target.name
    output_dir.mkdir(parents=True, exist_ok=True)

    if len(tile_codes) != total_tiles:
        print(f"Processing target {target.name} with {len(tile_codes)}/{total_tiles} tiles")
    else:
        print(f"Processing target {target.name} with {len(tile_codes)} tiles")
    processed = 0
    for tile_code in tile_codes:
        processed += 1
        remaining = len(tile_codes) - processed
        process_tile(config, tile_code, output_dir, remaining)

    merged = merge_outputs(config, target, selected_area, output_dir)
    elapsed = dt.datetime.now() - start
    print(f"Cliffs identified for {target.name} in {elapsed}")
    return merged


def describe_target(config: PipelineConfig, target: Target) -> None:
    """Print selected tiles and URL coverage without running raster processing."""

    selected_area, all_tile_codes = select_tiles(config, target)
    tile_codes = limit_tiles(config, all_tile_codes)
    print(f"Target {target.name}: {len(selected_area)} area feature(s), {len(all_tile_codes)} tile(s)")
    if len(tile_codes) != len(all_tile_codes):
        print(f"Limited to first {len(tile_codes)} tile(s) by --max-tiles")

    if target.mode == "region" and "RES_CO_REG" in selected_area.columns:
        regions = selected_area[["RES_CO_REG", "RES_NM_REG"]].drop_duplicates()
        for row in regions.itertuples(index=False):
            print(f"Region {row.RES_CO_REG}: {row.RES_NM_REG}")

    urls = load_lidar_urls(config.lidar_urls_path)
    if urls:
        covered = sum(1 for tile_code in tile_codes if tile_code in urls)
        print(f"LiDAR URL coverage: {covered}/{len(tile_codes)} tile(s)")

    for tile_code in tile_codes:
        suffix = "" if not urls else (" ok" if tile_code in urls else " missing-url")
        print(f"{tile_code}{suffix}")


def select_tiles(config: PipelineConfig, target: Target) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Load the processing area and return normalized LiDAR tile names."""

    index = read_vector(config.index_path)

    if target.mode == "region":
        if config.region_path is None:
            raise ValueError("region_path is required when processing administrative regions")
        area = read_vector(config.region_path)
        area = area[area["RES_CO_REG"].astype(str).isin(target.region_codes)]
    elif target.mode == "tile":
        index = index.copy()
        index["tile_code"] = index["No_tuile2"].apply(normalize_tile_name)
        area = index[index["tile_code"].isin(target.tile_codes)]
        missing = sorted(set(target.tile_codes) - set(area["tile_code"]))
        if missing:
            raise ValueError(f"Tile code(s) not found in index: {', '.join(missing)}")
    elif target.mode == "shape":
        frames = [read_vector(path) for path in target.shape_paths]
        area = pd.concat(frames, ignore_index=True)
        area = gpd.GeoDataFrame(area, geometry="geometry", crs=frames[0].crs)
    else:
        raise ValueError(f"Unknown target mode: {target.mode}")

    if area.empty:
        raise ValueError(f"No geometry found for target {target.name}")

    area = area.to_crs(index.crs)
    if target.mode == "tile":
        tile_names = list(area["tile_code"])
    else:
        tiles = gpd.overlay(index, area, how="intersection")
        tile_names = [normalize_tile_name(value) for value in tiles["No_tuile2"].dropna()]
    return area, sorted(set(tile_names))


def limit_tiles(config: PipelineConfig, tile_codes: list[str]) -> list[str]:
    """Apply an optional tile limit while preserving deterministic order."""

    if config.max_tiles is None:
        return tile_codes
    return tile_codes[: config.max_tiles]


def normalize_tile_name(value: object) -> str:
    """Convert index tile names to the naming convention used by MNT files."""

    raw = str(value).strip().upper()
    suffix = raw[-3:]
    if suffix not in TILE_SUFFIXES:
        raise ValueError(f"Unexpected tile suffix {suffix!r} in {raw!r}")
    return f"{raw[:-3]}{TILE_SUFFIXES[suffix]}"


def process_tile(config: PipelineConfig, tile_name: str, output_dir: Path, remaining: int) -> Path | None:
    """Process one DEM tile into per-tile cliff outputs."""

    start = dt.datetime.now()
    shp_path = output_dir / f"falaises_region_{tile_name}.shp"
    kml_path = output_dir / f"falaises_region_{tile_name}.kml"
    mnt_path = output_dir / f"MNT_{tile_name}.tif"
    slopes_path = output_dir / f"slopes_{tile_name}.tif"
    aspect_path = output_dir / f"aspect_{tile_name}.tif"

    if shp_path.exists():
        print(f"{tile_name} already done")
        return shp_path

    print(f"Processing tile {tile_name}")
    if not mnt_path.exists():
        try:
            download_mnt(config, tile_name, mnt_path)
        except RuntimeError as exc:
            print(exc)
            return None
    else:
        print("DEM already downloaded, processing")

    try:
        gdal.DEMProcessing(str(slopes_path), str(mnt_path), "slope")
        gdal.DEMProcessing(str(aspect_path), str(mnt_path), "aspect")

        cliffs = extract_candidate_cliffs(config, mnt_path, slopes_path)
        if cliffs.empty:
            print(f"No cliffs found in tile {tile_name}")
            return None

        cliffs = add_orientation(cliffs, aspect_path)
        cliffs = add_average_slope(cliffs, slopes_path)
        cliffs = add_priority_score(cliffs, config)
        cliffs["tuile"] = tile_name
        cliffs.to_file(shp_path, driver="ESRI Shapefile")
        cliffs.to_file(kml_path, driver="KML")

        elapsed = dt.datetime.now() - start
        print(f"Tile {tile_name} processed in {elapsed}, {remaining} tiles remaining")
        return shp_path
    finally:
        remove_if_exists(slopes_path)
        remove_if_exists(aspect_path)
        if config.delete_mnt:
            remove_if_exists(mnt_path)


def download_mnt(config: PipelineConfig, tile_name: str, destination: Path) -> None:
    """Download a DEM tile using the configured source URL."""

    url = mnt_url_for_tile(config, tile_name)
    print(f"Downloading MNT_{tile_name}.tif")
    try:
        urlretrieve(url, destination, reporthook=download_progress_hook(tile_name))
        print()
    except Exception as exc:  # noqa: BLE001 - keep download failures contextual
        print()
        remove_if_exists(destination)
        raise RuntimeError(f"DEM is not available for tile {tile_name}: {url}") from exc


def download_progress_hook(tile_name: str):
    """Return a urlretrieve progress hook that prints compact download progress."""

    state = {"last_percent": -1, "last_mebibytes": -1}

    def report(block_count: int, block_size: int, total_size: int) -> None:
        downloaded = block_count * block_size
        if total_size > 0:
            percent = min(100, int(downloaded * 100 / total_size))
            if percent < state["last_percent"] + 5 and percent != 100:
                return
            state["last_percent"] = percent
            message = (
                f"\rMNT_{tile_name}.tif: {percent:3d}% "
                f"({format_byte_count(downloaded)} / {format_byte_count(total_size)})"
            )
        else:
            mebibytes = downloaded // (1024 * 1024)
            if mebibytes < state["last_mebibytes"] + 10:
                return
            state["last_mebibytes"] = mebibytes
            message = f"\rMNT_{tile_name}.tif: {format_byte_count(downloaded)} downloaded"
        print(message, end="", flush=True)

    return report


def format_byte_count(value: int) -> str:
    """Format byte counts for human-readable progress logs."""

    mebibytes = value / (1024 * 1024)
    if mebibytes < 1024:
        return f"{mebibytes:.1f} MB"
    return f"{mebibytes / 1024:.2f} GB"


def mnt_url_for_tile(config: PipelineConfig, tile_name: str) -> str:
    """Return the best known DEM URL for one normalized tile."""

    tile_name = tile_name.upper()
    urls = load_lidar_urls(config.lidar_urls_path)
    if tile_name in urls:
        return urls[tile_name]
    return config.lidar_url_template.format(prefix=tile_name[:3], tile=tile_name)


def load_lidar_urls(path: Path | None) -> dict[str, str]:
    """Load official DEM URLs keyed by normalized tile name."""

    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    resolved = path.resolve()
    if resolved in _LIDAR_URL_CACHE:
        return _LIDAR_URL_CACHE[resolved]

    table = pd.read_csv(resolved, encoding="utf-8-sig")
    required = {"Feuillet20K", "MNT"}
    if not required.issubset(table.columns):
        missing = ", ".join(sorted(required - set(table.columns)))
        raise ValueError(f"Missing LiDAR URL column(s): {missing}")

    urls = {
        str(row.Feuillet20K).strip().upper(): str(row.MNT).strip()
        for row in table.itertuples(index=False)
        if pd.notna(row.Feuillet20K) and pd.notna(row.MNT)
    }
    _LIDAR_URL_CACHE[resolved] = urls
    return urls


def extract_candidate_cliffs(
    config: PipelineConfig,
    mnt_path: Path,
    slopes_path: Path,
) -> gpd.GeoDataFrame:
    """Extract steep, tall enough polygons from a slope raster."""

    with rasterio.open(slopes_path) as raster:
        slope_band = raster.read(1)
        steep_band = np.where(slope_band >= config.min_slope, 1, 0).astype("uint8")

        if not np.any(steep_band):
            return empty_geodataframe(raster.crs)

        mask = steep_band == 1
        polygons = [
            shape(geometry)
            for geometry, value in features.shapes(steep_band, mask=mask, transform=raster.transform)
            if value == 1
        ]
        gdf = gpd.GeoDataFrame(geometry=polygons, crs=raster.crs)

    gdf["surface"] = gdf.geometry.area
    gdf = gdf[gdf["surface"] > config.min_surface].copy()
    if gdf.empty:
        return gdf

    gdf["hauteur"] = [
        raster_height(geometry, mnt_path)
        for geometry in gdf.geometry
    ]
    gdf = gdf[gdf["hauteur"] > config.min_height].copy()
    if gdf.empty:
        return gdf

    gdf["surface"] = gdf["surface"].round(3)
    gdf["hauteur"] = gdf["hauteur"].round(3)
    return gdf


def raster_height(geometry, raster_path: Path) -> float:
    """Return max minus min elevation for one geometry."""

    stats = zonal_stats(geometry, raster_path, stats=["min", "max"], nodata=0, all_touched=True)
    minimum = stats[0].get("min")
    maximum = stats[0].get("max")
    if minimum is None or maximum is None:
        return 0.0
    return float(maximum - minimum)


def add_orientation(gdf: gpd.GeoDataFrame, aspect_path: Path) -> gpd.GeoDataFrame:
    """Add cardinal cliff orientation from median aspect."""

    gdf = gdf.copy()
    gdf["orientation"] = [
        cardinal_direction(zonal_median(geometry, aspect_path))
        for geometry in gdf.geometry
    ]
    return gdf


def add_average_slope(gdf: gpd.GeoDataFrame, slopes_path: Path) -> gpd.GeoDataFrame:
    """Add mean slope for each cliff polygon."""

    gdf = gdf.copy()
    gdf["pente_moy"] = [
        zonal_mean(geometry, slopes_path)
        for geometry in gdf.geometry
    ]
    return gdf


def add_priority_score(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Rank candidates with slope weighted ahead of raw height."""

    gdf = gdf.copy()
    slopes = pd.to_numeric(gdf["pente_moy"], errors="coerce").fillna(config.min_slope)
    heights = pd.to_numeric(gdf["hauteur"], errors="coerce").fillna(0)

    slope_span = max(90.0 - config.min_slope, 1.0)
    slope_part = ((slopes - config.min_slope) / slope_span).clip(0, 1)
    height_part = (heights / config.score_height_cap).clip(0, 1)
    slope_weight = config.score_slope_weight

    score = (slope_weight * slope_part + (1 - slope_weight) * height_part) * 100
    gdf["score"] = score.round(1)
    gdf["priorite"] = np.select(
        [gdf["score"] >= 75, gdf["score"] >= 50],
        ["A", "B"],
        default="C",
    )
    return gdf


def zonal_median(geometry, raster_path: Path) -> float | None:
    stats = zonal_stats(geometry, raster_path, stats=["median"], nodata=0, all_touched=True)
    value = stats[0].get("median")
    return None if value is None else float(value)


def zonal_mean(geometry, raster_path: Path) -> float | None:
    stats = zonal_stats(geometry, raster_path, stats=["mean"], nodata=0, all_touched=True)
    value = stats[0].get("mean")
    return None if value is None else round(float(value), 3)


def cardinal_direction(value: float | None) -> str | None:
    if value is None or np.isnan(value):
        return None
    value = value % 360
    if value < 22.5 or value >= 337.5:
        return "N"
    if value < 67.5:
        return "NE"
    if value < 112.5:
        return "E"
    if value < 157.5:
        return "SE"
    if value < 202.5:
        return "S"
    if value < 247.5:
        return "SO"
    if value < 292.5:
        return "O"
    return "NO"


def merge_outputs(
    config: PipelineConfig,
    target: Target,
    selected_area: gpd.GeoDataFrame,
    output_dir: Path,
) -> Path | None:
    """Merge per-tile outputs, clip them, remove quarries, and add geology."""

    tile_paths = sorted(
        path for path in output_dir.glob("falaises_region_*.shp")
        if path.stem != f"falaises_region_{target.name}"
    )
    if not tile_paths:
        print("No per-tile cliff outputs to merge")
        return None

    frames = [read_vector(path) for path in tile_paths]
    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    selected_area = selected_area.to_crs(merged.crs)
    merged = gpd.overlay(merged, selected_area, how="intersection")

    if config.quarry_path is not None and config.quarry_path.exists() and config.quarry_distance > 0:
        print("Removing quarries")
        merged = remove_quarry_buffers(merged, config.quarry_path, config.quarry_distance)

    if config.geology_path is not None and config.geology_path.exists():
        print("Joining geology info")
        merged = join_geology(merged, config.geology_path)

    output_path = output_dir / f"falaises_region_{target.name}.shp"
    kml_path = output_dir / f"falaises_region_{target.name}.kml"
    gpkg_path = output_dir / f"falaises_region_{target.name}.gpkg"
    print("Saving merged outputs")
    merged.to_file(output_path, driver="ESRI Shapefile")
    merged.to_file(kml_path, driver="KML")
    merged.to_file(gpkg_path, layer="falaises", driver="GPKG")
    return output_path


def remove_quarry_buffers(
    cliffs: gpd.GeoDataFrame,
    quarry_path: Path,
    distance: float,
) -> gpd.GeoDataFrame:
    """Remove cliff areas located within a quarry buffer."""

    quarries = read_vector(quarry_path)
    if quarries.empty:
        return cliffs

    metric_crs = cliffs.estimate_utm_crs() or "EPSG:32618"
    quarries = quarries.to_crs(metric_crs)
    buffers = gpd.GeoDataFrame(geometry=quarries.geometry.buffer(distance), crs=metric_crs)
    buffers = buffers.to_crs(cliffs.crs)
    return gpd.overlay(cliffs, buffers, how="difference")


def join_geology(cliffs: gpd.GeoDataFrame, geology_path: Path) -> gpd.GeoDataFrame:
    """Spatially join geology attributes to cliff polygons."""

    geology = read_vector(geology_path).to_crs(cliffs.crs)
    try:
        return gpd.sjoin(cliffs, geology, how="inner", predicate="intersects")
    except TypeError:  # geopandas < 0.10
        return gpd.sjoin(cliffs, geology, how="inner", op="intersects")


def empty_geodataframe(crs) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"surface": [], "hauteur": []}, geometry=[], crs=crs)


def read_vector(path: Path) -> gpd.GeoDataFrame:
    """Read a vector layer from a shapefile or zip archive."""

    if path.suffix.lower() == ".zip":
        return gpd.read_file(vector_zip_uri(path))
    if path.exists():
        return gpd.read_file(path)

    sibling_zip = path.with_suffix(".zip")
    if sibling_zip.exists():
        return gpd.read_file(f"zip://{sibling_zip.resolve().as_posix()}!{path.name}")

    raise FileNotFoundError(path)


def vector_zip_uri(path: Path) -> str:
    """Return a GDAL-readable URI for zipped shapefiles and zipped GeoPackages."""

    resolved = path.resolve().as_posix()
    with zipfile.ZipFile(path) as archive:
        gpkg_names = [name for name in archive.namelist() if name.lower().endswith(".gpkg")]
    if len(gpkg_names) == 1:
        return f"/vsizip/{resolved}/{gpkg_names[0]}"
    return f"zip://{resolved}"


def remove_if_exists(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
