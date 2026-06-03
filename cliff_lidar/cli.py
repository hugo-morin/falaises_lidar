"""Command-line interface for the cliff LiDAR pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import PipelineConfig, Target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect potential cliffs from Quebec LiDAR DEM tiles."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("output"),
        help="Folder used for downloads, temporary rasters, and exported results.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("associated_data/Index_MNT20k.zip"),
        help="Tile index shapefile or zip archive.",
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=Path("associated_data/regions_admin.zip"),
        help="Administrative regions shapefile or zip archive.",
    )
    parser.add_argument(
        "--lidar-urls",
        type=Path,
        default=Path("associated_data/URL_Lidar.csv"),
        help="CSV listing official LiDAR URLs by tile. Missing files fall back to the URL template.",
    )
    parser.add_argument(
        "--geology",
        type=Path,
        default=Path("associated_data/Zone geologique.shp"),
        help="Geology shapefile. Missing files are skipped.",
    )
    parser.add_argument(
        "--quarries",
        type=Path,
        default=Path("associated_data/carrieres.zip"),
        help="Quarry shapefile or zip archive. Missing files are skipped.",
    )
    parser.add_argument("--min-slope", type=float, default=70.0)
    parser.add_argument("--min-surface", type=float, default=100.0)
    parser.add_argument("--min-height", type=float, default=15.0)
    parser.add_argument(
        "--score-slope-weight",
        type=float,
        default=0.7,
        help="Priority score weight given to mean slope, from 0 to 1.",
    )
    parser.add_argument(
        "--score-height-cap",
        type=float,
        default=50.0,
        help="Height in metres where the height part of the priority score reaches its maximum.",
    )
    parser.add_argument("--quarry-distance", type=float, default=1000.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List selected tiles for the target without downloading or processing rasters.",
    )
    parser.add_argument(
        "--max-tiles",
        type=int,
        help="Process only the first N selected tiles, useful for smoke tests.",
    )
    parser.add_argument(
        "--keep-mnt",
        action="store_true",
        help="Keep downloaded DEM files after each tile is processed.",
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--region-code",
        action="append",
        dest="region_codes",
        help="Administrative region code to process. Can be passed more than once.",
    )
    target.add_argument(
        "--tile",
        action="append",
        dest="tiles",
        help="Normalized LiDAR tile code to process, for example 31J01SE. Can be passed more than once.",
    )
    target.add_argument(
        "--shape",
        action="append",
        type=Path,
        dest="shapes",
        help="Custom shapefile to process. Can be passed more than once.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = PipelineConfig(
        workspace=args.workspace,
        index_path=args.index,
        region_path=args.regions,
        lidar_urls_path=args.lidar_urls,
        geology_path=args.geology,
        quarry_path=args.quarries,
        min_slope=args.min_slope,
        min_surface=args.min_surface,
        min_height=args.min_height,
        score_slope_weight=args.score_slope_weight,
        score_height_cap=args.score_height_cap,
        quarry_distance=args.quarry_distance,
        max_tiles=args.max_tiles,
        delete_mnt=not args.keep_mnt,
    )

    if args.region_codes:
        target = Target.for_regions(args.region_codes)
    elif args.tiles:
        target = Target.for_tiles(args.tiles)
    else:
        target = Target.for_shapes(args.shapes)

    from .processing import describe_target, run_pipeline

    if args.dry_run:
        describe_target(config, target)
        return 0

    output = run_pipeline(config, target)
    if output is not None:
        print(f"Merged output: {output}")
    return 0
