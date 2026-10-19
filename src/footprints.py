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

import duckdb
import geopandas as gpd
import rasterio
import shapely
import yaml
from pyproj import CRS, Transformer
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


OVERTURE_S3 = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*"


def fetch_overture_buildings(bbox_wgs84: tuple, release: str = "latest") -> gpd.GeoDataFrame:
    """Unduh building footprints Overture untuk bbox (W, S, E, N) WGS84.

    Query DuckDB langsung ke Parquet Overture di S3 dengan filter bbox, jadi
    hanya bagian file yang relevan yang diunduh (jauh lebih hemat daripada
    membaca seluruh dataset). Hanya kolom atribut sederhana yang disimpan
    agar bisa ditulis ke GeoJSON (kolom struct seperti `names` dibuang).
    """
    if release == "latest":
        from overturemaps import core

        release = core.get_latest_release()
    print(f"Rilis Overture: {release}")

    west, south, east, north = bbox_wgs84
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    df = con.execute(
        f"""
        SELECT id, height, num_floors, class, subtype, geometry
        FROM read_parquet('{OVERTURE_S3.format(release=release)}', hive_partitioning=1)
        WHERE bbox.xmin <= {east} AND bbox.xmax >= {west}
          AND bbox.ymin <= {north} AND bbox.ymax >= {south}
        """
    ).df()
    if df.empty:
        return gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326")

    geom = shapely.from_wkb(df.pop("geometry").map(bytes).values)
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")


def utm_crs_for(lon: float, lat: float) -> CRS:
    """Zona UTM (WGS84) yang mencakup titik lon/lat."""
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def clip_and_measure(gdf: gpd.GeoDataFrame, bounds_wgs84: tuple) -> gpd.GeoDataFrame:
    """Clip footprint ke extent ortofoto, reproject ke UTM, hitung `area_m2`.

    Bangunan yang terpotong tepi ortofoto diberi `is_edge=True` karena
    luasnya hanya sebagian dari luas sebenarnya.
    """
    west, south, east, north = bounds_wgs84
    utm = utm_crs_for((west + east) / 2, (south + north) / 2)
    extent = gpd.GeoSeries([box(west, south, east, north)], crs="EPSG:4326").to_crs(utm).iloc[0]

    gdf = gdf.to_crs(utm)
    gdf = gdf[gdf.geometry.intersects(extent)].copy()
    gdf["is_edge"] = ~gdf.geometry.within(extent)
    gdf["geometry"] = gdf.geometry.intersection(extent)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
    gdf["area_m2"] = gdf.geometry.area.round(2)
    print(f"CRS analisis: {utm.to_string()} (UTM, otomatis)")
    return gdf


def main() -> None:
    cfg = load_config()
    ortho_path = ROOT / cfg["input"]["ortho"]
    if not ortho_path.exists():
        sys.exit(f"Ortofoto tidak ditemukan: {ortho_path}")
    info = read_ortho_info(ortho_path)
    print_ortho_info(info)

    print("\n=== Overture Maps ===")
    print("Mengunduh footprints (butuh internet)...")
    raw = fetch_overture_buildings(info["bounds_wgs84"], cfg["overture"]["release"])
    print(f"Diterima dari Overture: {len(raw)} bangunan")
    buildings = clip_and_measure(raw, info["bounds_wgs84"])
    print(f"Setelah clip ke extent: {len(buildings)} bangunan, "
          f"total {buildings['area_m2'].sum():.1f} m2")


if __name__ == "__main__":
    main()
