"""Penyaring kandidat atap hasil SAM (luas, bentuk, kecerahan, vegetasi).

SAM tidak tahu apa itu "atap", jadi pohon, jalan, dan area tanpa data ikut
tersegmentasi. Fungsi di sini murni (tanpa torch). Semua ambang dari config.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio import features
from rasterio.transform import Affine


def compute_exg(image: np.ndarray) -> np.ndarray:
    """Excess Green index (2g - r - b) pada koordinat kromatik; citra (3, H, W)."""
    rgb = image.astype("float32")
    total = rgb.sum(axis=0)
    total[total == 0] = 1.0
    r, g, b = rgb / total
    return (2 * g - r - b).astype("float32")


def zonal_mean(gdf: gpd.GeoDataFrame, band: np.ndarray, transform: Affine) -> pd.Series:
    """Rata-rata nilai `band` (H, W) di dalam tiap poligon; NaN jika di luar citra."""
    height, width = band.shape
    inv = ~transform
    values = []
    for geom in gdf.geometry:
        minx, miny, maxx, maxy = geom.bounds
        c_a, r_a = inv @ (minx, miny)
        c_b, r_b = inv @ (maxx, maxy)
        row0, row1 = int(max(0, np.floor(min(r_a, r_b)))), int(min(height, np.ceil(max(r_a, r_b))))
        col0, col1 = int(max(0, np.floor(min(c_a, c_b)))), int(min(width, np.ceil(max(c_a, c_b))))
        if row1 <= row0 or col1 <= col0:
            values.append(np.nan)
            continue
        sub = band[row0:row1, col0:col1]
        sub_t = transform @ Affine.translation(col0, row0)
        mask = features.geometry_mask([geom], sub.shape, sub_t, invert=True)
        if not mask.any():
            mask = features.geometry_mask([geom], sub.shape, sub_t, invert=True, all_touched=True)
        values.append(float(sub[mask].mean()) if mask.any() else np.nan)
    return pd.Series(values, index=gdf.index, dtype="float64")


def apply_filters(
    gdf: gpd.GeoDataFrame, image: np.ndarray, transform: Affine, cfg: dict
) -> tuple[gpd.GeoDataFrame, dict]:
    """Terapkan penyaring berurutan; kembalikan (kandidat lolos, laporan jumlah per langkah)."""
    report = {"awal": len(gdf)}
    out = gdf
    if out.empty:
        return out, {**report, "lolos_luas": 0, "lolos_solidity": 0,
                     "lolos_kecerahan": 0, "lolos_vegetasi": 0}

    area = out.geometry.area
    out = out[(area >= cfg["min_area_m2"]) & (area <= cfg["max_area_m2"])]
    report["lolos_luas"] = len(out)

    hull = out.geometry.convex_hull.area
    out = out[(out.geometry.area / hull.where(hull > 0, np.nan)) >= cfg["min_solidity"]]
    report["lolos_solidity"] = len(out)

    brightness = image.astype("float32").mean(axis=0)
    out = out[zonal_mean(out, brightness, transform) >= cfg["min_brightness"]]
    report["lolos_kecerahan"] = len(out)

    out = out[zonal_mean(out, compute_exg(image), transform) <= cfg["max_exg"]]
    report["lolos_vegetasi"] = len(out)
    return out.reset_index(drop=True), report
