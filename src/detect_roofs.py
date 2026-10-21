"""Deteksi atap dengan SAM dan perbandingan dengan denah Overture (v0.3).

Jalankan dari root project setelah `python src/footprints.py`:
    python src/detect_roofs.py            # jalankan SAM (sekitar 12 menit)
    python src/detect_roofs.py --reuse    # pakai segmen SAM tersimpan, hanya filter dan perbandingan
Semua path dan parameter dibaca dari config.yaml (bagian `sam` dan `compare`).
Hasil adalah kesesuaian antar-metode, BUKAN akurasi (tidak ada data acuan).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

import compare  # noqa: E402
import footprints  # noqa: E402
import roof_filters  # noqa: E402
import roof_raster  # noqa: E402
from sam_backend import SamBackend  # noqa: E402

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


def read_geojson(path: Path, crs) -> gpd.GeoDataFrame:
    """Baca GeoJSON hasil `write_geojson` ke `crs`; berkas kosong menjadi GeoDataFrame kosong."""
    gdf = gpd.read_file(path)
    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    return gdf.to_crs(crs)


def run_guided(
    backend, image: np.ndarray, transform: Affine, crs, overture: gpd.GeoDataFrame, sam_cfg: dict
) -> gpd.GeoDataFrame:
    """SAM dipandu: tiap denah Overture jadi prompt kotak pada crop di sekitarnya.

    Dipilih satu dari tiga mask dengan IoU tertinggi terhadap denah. Denah yang
    tidak menghasilkan mask dilewati (tidak ada barisnya pada hasil).
    """
    _, height, width = image.shape
    inv = ~transform
    gsd = abs(transform.a)
    pad = sam_cfg["guided"]["box_pad_m"] / gsd
    rows = []
    for idx, geom in overture.geometry.items():
        minx, miny, maxx, maxy = geom.bounds
        c0, r1 = inv @ (minx, miny)
        c1, r0 = inv @ (maxx, maxy)
        bx0, by0, bx1, by1 = c0 - pad, r0 - pad, c1 + pad, r1 + pad
        margin = max(20.0, 0.5 * max(bx1 - bx0, by1 - by0))
        crop_r0, crop_r1 = max(0, int(by0 - margin)), min(height, int(np.ceil(by1 + margin)))
        crop_c0, crop_c1 = max(0, int(bx0 - margin)), min(width, int(np.ceil(bx1 + margin)))
        if crop_r1 <= crop_r0 or crop_c1 <= crop_c0:
            continue
        crop = np.ascontiguousarray(image[:, crop_r0:crop_r1, crop_c0:crop_c1].transpose(1, 2, 0))
        box_crop = [
            max(0.0, bx0 - crop_c0), max(0.0, by0 - crop_r0),
            min(crop.shape[1], bx1 - crop_c0), min(crop.shape[0], by1 - crop_r0),
        ]
        masks, scores = backend.predict_box(crop, box_crop)
        crop_transform = transform @ Affine.translation(crop_c0, crop_r0)
        best = None
        for mask, score in zip(masks, scores):
            polys = roof_raster.mask_to_polygons(mask, crop_transform)
            if not polys:
                continue
            poly = max(polys, key=lambda p: p.area)
            value = compare.iou(geom, poly)
            if best is None or value > best[0]:
                best = (value, poly, float(score))
        if best is not None:
            rows.append({"idx": idx, "geometry": best[1], "iou_overture": round(best[0], 3),
                         "sam_score": round(best[2], 3), "area_m2": round(best[1].area, 2)})
    if not rows:
        return gpd.GeoDataFrame({"iou_overture": [], "sam_score": [], "area_m2": []}, geometry=[], crs=crs)
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs).set_index("idx")
    out.index.name = None
    return out


def load_overture_utm(cfg: dict, utm) -> gpd.GeoDataFrame:
    """Baca denah Overture hasil v0.1 (output/buildings.geojson) dalam CRS metrik."""
    path = ROOT / cfg["output"]["dir"] / cfg["output"]["buildings_geojson"]
    if not path.exists():
        sys.exit(f"{path} belum ada. Jalankan dulu: python src/footprints.py")
    return gpd.read_file(path).to_crs(utm)


def main(reuse: bool = False) -> None:
    cfg = footprints.load_config()
    sam_cfg, cmp_cfg = cfg["sam"], cfg["compare"]
    ortho_path = ROOT / cfg["input"]["ortho"]
    if not cfg["input"].get("aoi"):
        sys.exit("v0.3 membutuhkan AOI: isi input.aoi di config.yaml.")
    aoi = footprints.load_aoi(ROOT / cfg["input"]["aoi"])
    info = footprints.read_ortho_info(ortho_path)

    center = aoi.to_crs("EPSG:4326").union_all().centroid
    utm = footprints.utm_crs_for(center.x, center.y)
    aoi_geom = aoi.to_crs(utm).union_all()
    overture = load_overture_utm(cfg, utm)

    print(f"Menyiapkan citra kerja ({sam_cfg['working_gsd_m']} m/piksel, {utm.to_string()})...")
    image, transform = roof_raster.prepare_working_image(
        ortho_path, aoi_geom, utm, utm, sam_cfg["working_gsd_m"]
    )
    print(f"Citra kerja: {image.shape[2]} x {image.shape[1]} piksel")

    out_dir = ROOT / cfg["output"]["dir"]
    raw_path = out_dir / cfg["output"]["sam_raw_geojson"]
    guided_path = out_dir / cfg["output"]["sam_guided_geojson"]
    if reuse:
        missing = [p for p in (raw_path, guided_path) if not p.exists()]
        if missing:
            sys.exit(f"--reuse butuh {missing[0]}; jalankan dulu tanpa --reuse.")
        print("Memakai hasil SAM tersimpan (--reuse); SAM tidak dijalankan.")
        clipped = read_geojson(raw_path, utm)
        guided = read_geojson(guided_path, utm)
        if "overture_idx" in guided:
            guided = guided.set_index("overture_idx")
            guided.index.name = None
    else:
        backend = SamBackend(sam_cfg["model_type"], ROOT / sam_cfg["checkpoint_dir"],
                             sam_cfg["device"], sam_cfg["auto"]["amg"])
        print(f"SAM {sam_cfg['model_type']} di {backend.device}")

        print("Mode mandiri...")
        raw = run_auto(backend, image, transform, utm, sam_cfg)
        clipped = roof_raster.clip_to_aoi(raw, aoi_geom)
        write_geojson(clipped, raw_path)

        print("Mode dipandu Overture...")
        guided = run_guided(backend, image, transform, utm, overture, sam_cfg)
        write_geojson(guided.assign(overture_idx=guided.index), guided_path)

    kept, report = roof_filters.apply_filters(clipped, image, transform, sam_cfg["filters"])
    print(f"Segmen: {report['awal']} -> luas {report['lolos_luas']} -> bentuk {report['lolos_solidity']} "
          f"-> kecerahan {report['lolos_kecerahan']} -> vegetasi {report['lolos_vegetasi']}")
    if kept.empty:
        print("PERINGATAN: tidak ada kandidat atap yang lolos filter. Longgarkan ambang sam.filters.")

    result = compare.match(overture, kept, cmp_cfg["min_overlap"], cmp_cfg["match_iou"])
    kept = kept.assign(overture_idx=result.assignment.values)
    kept["status"] = np.where(kept["overture_idx"].isna(), "hanya_sam", "terkait_overture")
    offsets = compare.centroid_offsets(overture, guided)
    summary = {
        **compare.comparison_summary(overture, kept, result),
        **compare.offset_summary(offsets),
        "denah_dipandu_berhasil": len(guided),
        **{f"filter_{k}": v for k, v in report.items()},
    }

    write_geojson(kept, out_dir / cfg["output"]["sam_auto_geojson"])
    pd.DataFrame([summary]).to_csv(out_dir / cfg["output"]["comparison_csv"], index=False)

    print("\n=== Perbandingan SAM vs Overture (kesesuaian, bukan akurasi) ===")
    for key, value in summary.items():
        print(f"{key:<24}: {value}")

    layers = [
        {"name": "SAM mandiri (kandidat atap)", "gdf": kept, "color": "#2ecc71"},
        {"name": "SAM dipandu Overture", "gdf": guided, "color": "#f1c40f", "show": False},
        {"name": "Hanya SAM (periksa manual)", "gdf": kept[kept["status"] == "hanya_sam"],
         "color": "#ff8800", "weight": 3},
    ]
    map_path = footprints.build_map(overture, ortho_path, info, cfg, aoi, extra_layers=layers)
    print(f"\nPeta: {map_path}")


if __name__ == "__main__":
    main(reuse="--reuse" in sys.argv[1:])
