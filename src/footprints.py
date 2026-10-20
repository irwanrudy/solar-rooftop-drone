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

import base64
import math
import shutil
import sys
from pathlib import Path

import duckdb
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.shutil
import shapely
import shapely.geometry
import yaml
from pyproj import CRS, Transformer
from rasterio import features
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))  # agar `import solar` jalan dari mana saja
import solar  # noqa: E402

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


def valid_data_footprint(path: Path, max_px: int = 2000, close_px: int = 3) -> BaseGeometry:
    """Poligon area ortofoto yang benar-benar berisi citra (CRS ortofoto).

    Piksel hitam murni (0,0,0) dianggap tanpa data. Mask dibaca pada
    resolusi rendah (`max_px`), di-polygonize, lubang kecil ditutup, dan
    tepinya dihaluskan (`close_px` piksel) agar tidak bergerigi.
    """
    with rasterio.open(path) as src:
        scale = max_px / max(src.width, src.height)
        shape = (max(1, round(src.height * scale)), max(1, round(src.width * scale)))
        data = src.read(out_shape=shape, resampling=Resampling.nearest)
        transform = src.transform * src.transform.scale(src.width / shape[1], src.height / shape[0])

    valid = (data.sum(axis=0) > 0).astype("uint8")
    polys = [shapely.geometry.shape(g) for g, v in features.shapes(valid, transform=transform) if v == 1]
    if not polys:
        raise ValueError("Ortofoto tidak punya piksel data valid.")
    geom = unary_union([Polygon(p.exterior) for p in polys])  # buang lubang internal
    pix = abs(transform.a)
    geom = geom.buffer(close_px * pix).buffer(-close_px * pix)
    return geom.buffer(0)


def _center(bbox_wgs84: tuple) -> tuple[float, float]:
    """Titik tengah (lon, lat) dari bbox (W, S, E, N)."""
    return (bbox_wgs84[0] + bbox_wgs84[2]) / 2, (bbox_wgs84[1] + bbox_wgs84[3]) / 2


def load_aoi(path: Path) -> gpd.GeoDataFrame:
    """Baca AOI (shapefile/GeoJSON/dll). CRS harus terdefinisi; geometri valid."""
    aoi = gpd.read_file(path)
    if aoi.crs is None:
        raise ValueError(f"AOI tanpa CRS (.prj hilang?): {path}")
    aoi = aoi[~aoi.geometry.is_empty & aoi.geometry.notna()].copy()
    aoi["geometry"] = aoi.geometry.make_valid()
    if aoi.empty:
        raise ValueError(f"AOI kosong: {path}")
    return aoi


def report_ortho_coverage(aoi: gpd.GeoDataFrame, ortho_path: Path, max_px: int, ortho_crs: CRS) -> None:
    """Cetak berapa persen AOI yang tertutup data valid ortofoto (peringatan bila kurang)."""
    valid = gpd.GeoSeries([valid_data_footprint(ortho_path, max_px)], crs=ortho_crs)
    aoi_geom = aoi.to_crs(ortho_crs).union_all()
    share = aoi_geom.intersection(valid.iloc[0]).area / aoi_geom.area
    print(f"Tutupan citra ortofoto di dalam AOI: {share:.1%}")
    if share < 0.98:
        print("PERINGATAN: sebagian AOI tidak punya citra ortofoto; luas atap di sana tidak terverifikasi.")


def clip_and_measure(
    gdf: gpd.GeoDataFrame,
    extent_geom: BaseGeometry,
    extent_crs: CRS,
    min_area_m2: float = 0.0,
) -> gpd.GeoDataFrame:
    """Clip footprint ke area data ortofoto, reproject ke UTM, hitung `area_m2`.

    `extent_geom` (CRS `extent_crs`) adalah area clip, idealnya poligon data
    valid ortofoto. Bangunan yang terpotong tepi diberi `is_edge=True` karena
    luasnya hanya sebagian dari luas sebenarnya. Serpihan dengan luas di
    bawah `min_area_m2` (artefak clip) dibuang.
    """
    center = gpd.GeoSeries([extent_geom.centroid], crs=extent_crs).to_crs("EPSG:4326").iloc[0]
    utm = utm_crs_for(center.x, center.y)
    extent = gpd.GeoSeries([extent_geom], crs=extent_crs).to_crs(utm).iloc[0]

    gdf = gdf.to_crs(utm)
    gdf = gdf[gdf.geometry.intersects(extent)].copy()
    gdf["is_edge"] = ~gdf.geometry.within(extent)
    gdf["geometry"] = gdf.geometry.intersection(extent)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
    gdf["area_m2"] = gdf.geometry.area.round(2)
    gdf = gdf[gdf["area_m2"] >= min_area_m2].reset_index(drop=True)
    print(f"CRS analisis: {utm.to_string()} (UTM, otomatis)")
    return gdf


def summarize(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Ringkasan: jumlah bangunan, total luas, dan luas min/median/max (m2)."""
    area = gdf["area_m2"] if len(gdf) else pd.Series([0.0])
    rows = {
        "jumlah_bangunan": len(gdf),
        "total_luas_m2": round(float(area.sum()), 2),
        "luas_min_m2": round(float(area.min()), 2),
        "luas_median_m2": round(float(area.median()), 2),
        "luas_max_m2": round(float(area.max()), 2),
    }
    return pd.DataFrame([rows])


def save_outputs(
    gdf: gpd.GeoDataFrame, summary: pd.DataFrame, cfg: dict, scenario_df: pd.DataFrame | None = None
) -> tuple[Path, Path]:
    """Simpan GeoJSON (WGS84), CSV ringkasan, dan (jika ada) CSV skenario energi."""
    out_dir = ROOT / cfg["output"]["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = out_dir / cfg["output"]["buildings_geojson"]
    csv_path = out_dir / cfg["output"]["summary_csv"]
    gdf.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON")
    summary.to_csv(csv_path, index=False)
    if scenario_df is not None:
        scenario_df.to_csv(out_dir / cfg["output"]["scenarios_csv"], index=False)
    return geojson_path, csv_path


def print_scenarios(df: pd.DataFrame, ghi: float, base_name: str) -> None:
    """Cetak tabel skenario energi beserta pengingat bahwa ini screening."""
    print(f"\n=== Estimasi energi (GHI {ghi:.0f} kWh/m2/tahun; skenario dasar: {base_name}) ===")
    cols = ["skenario", "faktor_pemanfaatan", "efisiensi_modul", "performance_ratio",
            "kapasitas_kwp", "energi_mwh_tahun"]
    print(df[cols].to_string(index=False))
    print("Screening berbasis luas: tanpa kemiringan, arah, dan bayangan atap.")


def ortho_overlay_png(path: Path, max_px: int) -> bytes:
    """Downsample ortofoto ke PNG RGBA (piksel hitam murni -> transparan)."""
    with rasterio.open(path) as src:
        scale = max_px / max(src.width, src.height)
        shape = (max(1, round(src.height * scale)), max(1, round(src.width * scale)))
        rgb = src.read([1, 2, 3], out_shape=shape, resampling=Resampling.average)

    alpha = np.where(rgb.sum(axis=0) == 0, 0, 255).astype("uint8")
    rgba = np.concatenate([rgb, alpha[None]]).astype("uint8")
    profile = {"driver": "MEM", "count": 4, "dtype": "uint8",
               "height": shape[0], "width": shape[1]}
    with MemoryFile() as mem_src, MemoryFile() as mem_png:
        with mem_src.open(**{**profile, "driver": "GTiff"}) as tmp:
            tmp.write(rgba)
            rasterio.shutil.copy(tmp, mem_png.name, driver="PNG")
        return mem_png.read()


MAP_TITLE = "Potensi Atap Surya - Screening Awal"
MAP_NOTE_HTML = """
<div style="position:fixed;bottom:22px;left:10px;z-index:9999;max-width:340px;
            background:rgba(255,255,255,.92);padding:8px 10px;border-radius:6px;
            font:12px/1.4 system-ui,sans-serif;color:#222;box-shadow:0 1px 5px rgba(0,0,0,.4)">
  <b>Cara membaca:</b> kotak merah = denah bangunan, garis biru = batas area studi.
  Arahkan kursor ke bangunan untuk melihat luas denahnya.<br>
  <b>Screening awal</b>, bukan desain teknis: luas denah belum berarti luas atap yang bisa dipasangi panel.
  Angka kapasitas dan energi memakai skenario dasar (rentang rendah-tinggi ada di README) dan
  tidak memodelkan kemiringan, arah, atau bayangan atap.<br>
  <span style="color:#555">Ortofoto: OpenAerialMap, Dany Puguh Laksono (UGM), 2019,
  <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank">CC BY 4.0</a>.
  Denah: Overture Maps (ODbL). Peta dasar: &copy; OpenStreetMap.</span>
</div>
"""


def build_map(
    gdf: gpd.GeoDataFrame, ortho_path: Path, info: dict, cfg: dict,
    aoi: gpd.GeoDataFrame | None = None, extra_layers: list[dict] | None = None,
) -> Path:
    """Peta Folium: footprint (+ batas AOI) di atas ortofoto (overlay PNG ringan).

    `extra_layers`: daftar dict {name, gdf, color, weight (opsional), show (opsional)}.
    """
    west, south, east, north = info["bounds_wgs84"]
    png = ortho_overlay_png(ortho_path, cfg["map"]["overlay_max_px"])
    data_uri = "data:image/png;base64," + base64.b64encode(png).decode()

    m = folium.Map(location=[(south + north) / 2, (west + east) / 2],
                   zoom_start=17, max_zoom=21, tiles="OpenStreetMap")
    folium.raster_layers.ImageOverlay(
        image=data_uri, bounds=[[south, west], [north, east]], name="Ortofoto", opacity=1.0
    ).add_to(m)
    fields = {"area_m2": "Luas denah (m2):"}
    if "kwh_year" in gdf:
        fields |= {"eff_area_m2": "Luas efektif (m2):", "kwp": "Kapasitas (kWp):",
                   "kwh_year": "Energi dasar (kWh/thn):"}
    folium.GeoJson(
        gdf.to_crs("EPSG:4326")[["id", "is_edge", *fields, "geometry"]],
        name="Footprint Overture",
        style_function=lambda _: {"color": "#ff3300", "weight": 1.5, "fillOpacity": 0.15},
        tooltip=folium.GeoJsonTooltip(fields=list(fields), aliases=list(fields.values())),
    ).add_to(m)
    view = (west, south, east, north)
    if aoi is not None:
        aoi_wgs = aoi.to_crs("EPSG:4326")
        folium.GeoJson(
            aoi_wgs[["geometry"]], name="AOI",
            style_function=lambda _: {"color": "#00e5ff", "weight": 3, "fill": False},
        ).add_to(m)
        view = tuple(aoi_wgs.total_bounds)
    for layer in extra_layers or []:
        layer_gdf = layer["gdf"]
        if layer_gdf.empty:
            continue
        simple = layer_gdf.copy()
        simple["geometry"] = simple.geometry.simplify(0.3)  # meter, CRS metrik
        folium.GeoJson(
            simple.to_crs("EPSG:4326")[["geometry"]],
            name=layer["name"],
            show=layer.get("show", True),
            style_function=lambda _, c=layer["color"], w=layer.get("weight", 1.5): {
                "color": c, "weight": w, "fillOpacity": 0.1},
        ).add_to(m)
    folium.LayerControl().add_to(m)
    m.fit_bounds([[view[1], view[0]], [view[3], view[2]]])

    m.get_root().header.add_child(folium.Element(f"<title>{MAP_TITLE}</title>"))
    m.get_root().html.add_child(folium.Element(MAP_NOTE_HTML))

    out = ROOT / cfg["output"]["dir"] / cfg["output"]["map_html"]
    m.save(out)
    publish = cfg["output"].get("publish_copy")
    if publish:  # salinan untuk GitHub Pages
        publish_path = ROOT / publish
        publish_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, publish_path)
        print(f"           salinan publikasi: {publish_path}")
    return out


def warn_if_sparse(count: int, threshold: int) -> None:
    """Peringatan jelas jika Overture tidak/sedikit mengembalikan bangunan."""
    if count == 0:
        level = "TIDAK ADA bangunan"
    elif count < threshold:
        level = f"hanya {count} bangunan (di bawah ambang {threshold})"
    else:
        return
    bar = "!" * 70
    print(f"\n{bar}\nPERINGATAN: Overture mengembalikan {level} di area ini.\n"
          "Cakupan Overture di Indonesia bisa bolong. Hasil luas atap tidak\n"
          "bisa diandalkan; pertimbangkan deteksi atap sendiri (roadmap v0.3).\n"
          f"{bar}\n")


def main() -> None:
    cfg = load_config()
    ortho_path = ROOT / cfg["input"]["ortho"]
    if not ortho_path.exists():
        sys.exit(f"Ortofoto tidak ditemukan: {ortho_path}")
    info = read_ortho_info(ortho_path)
    print_ortho_info(info)

    aoi = None
    if cfg["input"].get("aoi"):
        aoi_path = ROOT / cfg["input"]["aoi"]
        if not aoi_path.exists():
            sys.exit(f"AOI tidak ditemukan: {aoi_path}")
        aoi = load_aoi(aoi_path)
        extent_geom, extent_crs = aoi.union_all(), aoi.crs
        query_bbox = tuple(aoi.to_crs("EPSG:4326").total_bounds)
        print(f"\n=== AOI ===\n{aoi_path.name}: {len(aoi)} poligon, "
              f"{aoi.to_crs(utm_crs_for(*_center(query_bbox))).area.sum():,.0f} m2")
    elif cfg["input"].get("clip_to_valid_data", True):
        extent_geom = valid_data_footprint(ortho_path, cfg["input"]["valid_mask_max_px"])
        extent_crs, query_bbox = info["crs"], info["bounds_wgs84"]
    else:
        extent_geom, extent_crs, query_bbox = box(*info["bounds"]), info["crs"], info["bounds_wgs84"]

    if aoi is not None:
        report_ortho_coverage(aoi, ortho_path, cfg["input"]["valid_mask_max_px"], info["crs"])

    print("\n=== Overture Maps ===")
    print("Mengunduh footprints (butuh internet)...")
    raw = fetch_overture_buildings(query_bbox, cfg["overture"]["release"])
    print(f"Diterima dari Overture: {len(raw)} bangunan")
    buildings = clip_and_measure(raw, extent_geom, extent_crs, cfg["overture"]["min_area_m2"])
    print(f"Setelah clip ke {'AOI' if aoi is not None else 'extent'}: "
          f"{len(buildings)} bangunan, total {buildings['area_m2'].sum():.1f} m2")

    warn_if_sparse(len(buildings), cfg["overture"]["min_buildings_warn"])
    scenario_df = None
    solar_cfg = cfg.get("solar", {})
    if solar_cfg.get("enabled"):
        scenarios = solar.scenarios_from_config(solar_cfg)
        base = next(s for s in scenarios if s.name == solar_cfg["base_scenario"])
        ghi = solar_cfg["annual_ghi_kwh_m2"]
        buildings = solar.add_estimates(buildings, base, ghi)
        scenario_df = solar.scenario_table(buildings["area_m2"], scenarios, ghi)
        print_scenarios(scenario_df, ghi, base.name)
    summary = summarize(buildings)
    geojson_path, csv_path = save_outputs(buildings, summary, cfg, scenario_df)
    print("\n=== Ringkasan ===")
    for key, val in summary.iloc[0].items():
        print(f"{key:<18}: {val:,.2f}" if key != "jumlah_bangunan" else f"{key:<18}: {int(val)}")
    print(f"\nTersimpan: {geojson_path}\n           {csv_path}")

    print("Membuat peta Folium...")
    map_path = build_map(buildings, ortho_path, info, cfg, aoi)
    print(f"           {map_path} ({map_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
