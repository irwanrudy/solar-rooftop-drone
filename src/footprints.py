"""Ekstraksi building footprints Overture Maps untuk extent sebuah ortofoto.

Alur (v0.1):
    1. Baca ortofoto GeoTIFF -> CRS, resolusi, extent.
    2. Unduh footprints Overture untuk extent tersebut.
    3. Clip ke extent, reproject ke UTM, hitung luas (m2).
    4. Simpan GeoJSON + ringkasan CSV.
    5. Buat peta Folium (footprint di atas ortofoto).

Jalankan dari root project:  python src/footprints.py
Semua path/parameter dibaca dari config.yaml.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import rasterio
import yaml
from pyproj import Transformer
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Baca config.yaml."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_ortho_info(path: Path) -> dict:
    """Ambil metadata ortofoto: CRS, resolusi (m/piksel), extent asli & WGS84.

    Untuk CRS geografis/Web Mercator, resolusi nominal bukan meter di
    permukaan bumi. Untuk EPSG:3857 resolusi dikoreksi dengan cos(lintang)
    agar menjadi meter sebenarnya.
    """
    with rasterio.open(path) as src:
        crs = src.crs
        bounds = src.bounds
        res_x, res_y = src.res
        width, height, count = src.width, src.height, src.count

    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    west, south, east, north = to_wgs84.transform_bounds(*bounds)

    lat_c = (south + north) / 2
    if crs.to_epsg() == 3857:
        scale = math.cos(math.radians(lat_c))
    elif crs.is_geographic:
        raise ValueError("CRS geografis (derajat) belum didukung; reproject ke CRS metrik.")
    else:
        scale = 1.0

    return {
        "crs": crs,
        "bounds": bounds,
        "bounds_wgs84": (west, south, east, north),
        "res_nominal": (res_x, res_y),
        "res_m": (res_x * scale, res_y * scale),
        "size": (width, height),
        "bands": count,
    }


def print_ortho_info(info: dict) -> None:
    """Cetak ringkasan metadata ortofoto."""
    w, s, e, n = info["bounds_wgs84"]
    print("=== Ortofoto ===")
    print(f"CRS        : {info['crs']}")
    print(f"Ukuran     : {info['size'][0]} x {info['size'][1]} piksel, {info['bands']} band")
    print(f"Resolusi   : {info['res_m'][0]:.4f} m/piksel (nominal {info['res_nominal'][0]:.4f})")
    b = info["bounds"]
    print(f"Extent     : {b.left:.2f}, {b.bottom:.2f}, {b.right:.2f}, {b.top:.2f} ({info['crs']})")
    print(f"Extent WGS84: W {w:.6f}  S {s:.6f}  E {e:.6f}  N {n:.6f}")


def main() -> None:
    cfg = load_config()
    ortho_path = ROOT / cfg["input"]["ortho"]
    if not ortho_path.exists():
        sys.exit(f"Ortofoto tidak ditemukan: {ortho_path}")
    info = read_ortho_info(ortho_path)
    print_ortho_info(info)


if __name__ == "__main__":
    main()
