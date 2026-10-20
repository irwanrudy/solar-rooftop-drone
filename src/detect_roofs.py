"""Deteksi atap dengan SAM dan perbandingan dengan denah Overture (v0.3).

Jalankan dari root project setelah `python src/footprints.py`:
    python src/detect_roofs.py
Semua path dan parameter dibaca dari config.yaml (bagian `sam` dan `compare`).
Hasil adalah kesesuaian antar-metode, BUKAN akurasi (tidak ada data acuan).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

import roof_raster  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run_auto(backend, image: np.ndarray, transform: Affine, crs, sam_cfg: dict) -> gpd.GeoDataFrame:
    """SAM otomatis per tile -> poligon di CRS metrik, duplikat zona overlap dibuang."""
    _, height, width = image.shape
    polygons = []
    for row0, col0, row1, col1 in roof_raster.tile_windows(
        height, width, sam_cfg["tile_px"], sam_cfg["overlap_px"]
    ):
        tile = np.ascontiguousarray(image[:, row0:row1, col0:col1].transpose(1, 2, 0))
        tile_transform = transform @ Affine.translation(col0, row0)
        for mask in backend.generate(tile):
            polygons.extend(roof_raster.mask_to_polygons(mask, tile_transform))
    segments = gpd.GeoDataFrame(geometry=polygons, crs=crs)
    return roof_raster.dedupe_polygons(segments, sam_cfg["auto"]["dedupe_iou"])


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    """Tulis GeoJSON WGS84. GeoDataFrame kosong ditulis sebagai FeatureCollection kosong."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.empty:
        path.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    else:
        gdf.to_crs("EPSG:4326").to_file(path, driver="GeoJSON")
