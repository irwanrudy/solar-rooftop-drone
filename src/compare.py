"""Pencocokan poligon hasil SAM dengan denah Overture, dan metrik pergeseran.

Fungsi murni (tanpa torch). Satu atap sering dipecah SAM menjadi beberapa
segmen, jadi pencocokan dilakukan many-to-one: segmen ditetapkan ke denah
dengan tumpang tindih terbesar, segmen satu denah digabung, lalu IoU dihitung.
Indeks `overture` harus numerik (hasil `gpd.read_file`).
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def _valid_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Salinan dengan geometri diperbaiki (make_valid) agar operasi overlay aman."""
    out = gdf.copy()
    if len(out):
        out["geometry"] = out.geometry.make_valid()
    return out


def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    """Intersection-over-Union dua geometri (0 jika gabungannya kosong)."""
    from shapely.validation import make_valid

    a = a if a.is_valid else make_valid(a)
    b = b if b.is_valid else make_valid(b)
    union = a.union(b).area
    return float(a.intersection(b).area / union) if union else 0.0


def assign_segments(
    overture: gpd.GeoDataFrame, segments: gpd.GeoDataFrame, min_overlap: float = 0.5
) -> pd.Series:
    """Tetapkan tiap segmen ke denah Overture dengan irisan terbesar.

    Segmen ditetapkan bila `luas(irisan) / luas(segmen) >= min_overlap`.
    Mengembalikan Series (indeks = indeks segmen) berisi indeks denah, atau NaN.
    """
    out = pd.Series(np.nan, index=segments.index, dtype="float64")
    if overture.empty or segments.empty:
        return out
    ov, seg = _valid_gdf(overture), _valid_gdf(segments)
    tree = ov.sindex
    for seg_idx, geom in seg.geometry.items():
        if geom.is_empty or geom.area == 0:
            continue
        best, best_share = None, 0.0
        for pos in tree.query(geom, predicate="intersects"):
            share = ov.geometry.iloc[pos].intersection(geom).area / geom.area
            if share > best_share:
                best, best_share = ov.index[pos], share
        if best is not None and best_share >= min_overlap:
            out[seg_idx] = best
    return out


@dataclass
class MatchResult:
    """Hasil pencocokan: tabel per denah, penetapan segmen, dan segmen tanpa denah."""

    per_overture: pd.DataFrame
    assignment: pd.Series
    sam_only: pd.Index


def match(
    overture: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    min_overlap: float = 0.5,
    match_iou: float = 0.5,
) -> MatchResult:
    """Cocokkan segmen SAM dengan denah Overture (many-to-one)."""
    ov, seg = _valid_gdf(overture), _valid_gdf(segments)
    assignment = assign_segments(ov, seg, min_overlap)
    rows = []
    for ov_idx, geom in ov.geometry.items():
        members = assignment.index[assignment == ov_idx]
        if len(members) == 0:
            rows.append((ov_idx, 0, 0.0, 0.0, False))
            continue
        union = unary_union(list(seg.geometry.loc[members]))
        value = iou(geom, union)
        rows.append((ov_idx, len(members), round(float(union.area), 2), value, value >= match_iou))
    per = pd.DataFrame(
        rows, columns=["overture_idx", "n_segments", "union_area_m2", "iou", "matched"]
    ).set_index("overture_idx")
    per = per.astype({"n_segments": int, "union_area_m2": float, "iou": float, "matched": bool})
    return MatchResult(per, assignment, assignment.index[assignment.isna()])


def comparison_summary(
    overture: gpd.GeoDataFrame, segments: gpd.GeoDataFrame, result: MatchResult
) -> dict:
    """Ringkasan perbandingan. Kategori denah: cocok / kurang_cocok / hanya_overture."""
    per = result.per_overture
    matched = per["matched"]
    with_seg = per["n_segments"] > 0
    ious = per.loc[matched, "iou"]
    a_ov = float(overture.geometry.area.sum()) if len(overture) else 0.0
    # luas gabungan: segmen SAM bisa bersarang (atap utuh + bidang-bidangnya)
    a_sam = float(_valid_gdf(segments).union_all().area) if len(segments) else 0.0
    return {
        "cocok": int(matched.sum()),
        "kurang_cocok": int((with_seg & ~matched).sum()),
        "hanya_overture": int((~with_seg).sum()),
        "hanya_sam": int(len(result.sam_only)),
        "median_iou": round(float(ious.median()), 3) if len(ious) else 0.0,
        "luas_overture_m2": round(a_ov, 1),
        "luas_sam_m2": round(a_sam, 1),
        "selisih_luas_pct": round(100 * (a_sam - a_ov) / a_ov, 1) if a_ov else 0.0,
    }


def centroid_offsets(overture: gpd.GeoDataFrame, guided: gpd.GeoDataFrame) -> pd.DataFrame:
    """Pergeseran pusat (meter, CRS metrik) SAM dipandu terhadap denah Overture.

    Hanya indeks yang ada di kedua tabel. Kolom: dx, dy, d (jarak).
    """
    common = overture.index.intersection(guided.index)
    oc = overture.geometry.loc[common].centroid
    gc = guided.geometry.loc[common].centroid
    out = pd.DataFrame({"dx": gc.x - oc.x, "dy": gc.y - oc.y}, index=common)
    out["d"] = np.hypot(out["dx"], out["dy"])
    return out


def offset_summary(offsets: pd.DataFrame) -> dict:
    """Ringkasan pergeseran. `bias_ratio` ~1: seragam satu arah; ~0: acak (heuristik)."""
    if offsets.empty:
        return {"median_geser_m": 0.0, "rata_dx_m": 0.0, "rata_dy_m": 0.0, "bias_ratio": 0.0}
    mean_vec = float(np.hypot(offsets["dx"].mean(), offsets["dy"].mean()))
    mean_d = float(offsets["d"].mean())
    return {
        "median_geser_m": round(float(offsets["d"].median()), 2),
        "rata_dx_m": round(float(offsets["dx"].mean()), 2),
        "rata_dy_m": round(float(offsets["dy"].mean()), 2),
        "bias_ratio": round(mean_vec / mean_d, 3) if mean_d else 0.0,
    }
