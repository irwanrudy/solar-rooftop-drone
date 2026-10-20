"""Utilitas raster dan poligon untuk deteksi atap (tanpa torch).

Menyiapkan citra kerja (di-clip ke AOI, di-reproject ke CRS metrik, diturunkan
resolusinya), membagi citra ke tile, dan mengubah mask SAM menjadi poligon.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_origin
from rasterio.vrt import WarpedVRT
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from compare import iou


def prepare_working_image(
    ortho_path: Path, aoi_geom: BaseGeometry, aoi_crs, dst_crs, gsd_m: float, pad_m: float = 5.0
) -> tuple[np.ndarray, Affine]:
    """Baca ortofoto untuk bounding box AOI pada resolusi `gsd_m` di `dst_crs`.

    Mengembalikan citra (3, H, W) uint8 dan transform-nya. Di luar data valid = 0.
    """
    minx, miny, maxx, maxy = gpd.GeoSeries([aoi_geom], crs=aoi_crs).to_crs(dst_crs).total_bounds
    minx, miny, maxx, maxy = minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m
    width = int(np.ceil((maxx - minx) / gsd_m))
    height = int(np.ceil((maxy - miny) / gsd_m))
    transform = from_origin(minx, maxy, gsd_m, gsd_m)
    with rasterio.open(ortho_path) as src, WarpedVRT(
        src, crs=dst_crs, transform=transform, width=width, height=height,
        resampling=Resampling.average, nodata=0,
    ) as vrt:
        image = vrt.read([1, 2, 3])
    return image, transform


def tile_windows(height: int, width: int, tile: int, overlap: int) -> list[tuple[int, int, int, int]]:
    """Jendela (row0, col0, row1, col1) yang menutup seluruh citra dengan tumpang tindih."""
    step = tile - overlap

    def starts(n: int) -> list[int]:
        if n <= tile:
            return [0]
        s = list(range(0, n - tile, step))
        s.append(n - tile)
        return s

    return [(r, c, min(r + tile, height), min(c + tile, width)) for r in starts(height) for c in starts(width)]


def mask_to_polygons(mask: np.ndarray, transform: Affine) -> list:
    """Ubah mask boolean (H, W) menjadi poligon pada koordinat dunia."""
    return [
        shape(geom)
        for geom, value in features.shapes(mask.astype("uint8"), mask=mask, transform=transform)
        if value == 1
    ]


def dedupe_polygons(gdf: gpd.GeoDataFrame, iou_threshold: float = 0.7) -> gpd.GeoDataFrame:
    """Buang duplikat (IoU >= ambang), pertahankan yang lebih besar. Untuk zona overlap tile."""
    if gdf.empty:
        return gdf.reset_index(drop=True)
    order = gdf.geometry.area.sort_values(ascending=False).index
    sindex = gdf.sindex
    kept: list = []
    kept_set: set = set()
    for idx in order:
        geom = gdf.geometry.loc[idx]
        duplicate = False
        for pos in sindex.query(geom, predicate="intersects"):
            other = gdf.index[pos]
            if other in kept_set and iou(geom, gdf.geometry.loc[other]) >= iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(idx)
            kept_set.add(idx)
    return gdf.loc[kept].reset_index(drop=True)


def clip_to_aoi(gdf: gpd.GeoDataFrame, aoi_geom: BaseGeometry) -> gpd.GeoDataFrame:
    """Potong poligon ke AOI; buang yang kosong; pecah multipart jadi Polygon tunggal."""
    out = gdf[gdf.intersects(aoi_geom)].copy()
    out["geometry"] = out.geometry.intersection(aoi_geom)
    out = out[~out.geometry.is_empty].explode(index_parts=False)
    return out[out.geom_type == "Polygon"].reset_index(drop=True)
