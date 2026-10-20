import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import roof_raster


def gdf(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs="EPSG:32749")


def test_tile_windows_cover_whole_image_with_overlap():
    wins = roof_raster.tile_windows(100, 100, tile=64, overlap=16)
    cover = np.zeros((100, 100), dtype=int)
    for r0, c0, r1, c1 in wins:
        assert r1 - r0 <= 64 and c1 - c0 <= 64
        cover[r0:r1, c0:c1] += 1
    assert cover.min() >= 1 and cover.max() >= 2


def test_tile_windows_small_image_single_tile():
    assert roof_raster.tile_windows(30, 40, tile=64, overlap=16) == [(0, 0, 30, 40)]


def test_mask_to_polygons_world_coordinates():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:5, 3:7] = True  # baris 2-4, kolom 3-6
    (poly,) = roof_raster.mask_to_polygons(mask, from_origin(100, 50, 2, 2))
    assert poly.bounds == (106.0, 40.0, 114.0, 46.0) and poly.area == pytest.approx(48.0)


def test_dedupe_removes_near_duplicates_keeps_partial_overlaps():
    g = gdf(box(0, 0, 10, 10), box(0, 0, 10, 10), box(50, 0, 60, 10), box(55, 0, 65, 10))
    out = roof_raster.dedupe_polygons(g, iou_threshold=0.7)
    assert len(out) == 3  # duplikat persis dibuang; tumpang tindih IoU 0,33 dipertahankan


def test_clip_to_aoi_cuts_and_drops_outside():
    g = gdf(box(0, 0, 10, 10), box(8, 0, 20, 10), box(100, 100, 110, 110))
    out = roof_raster.clip_to_aoi(g, box(0, 0, 12, 10))
    assert len(out) == 2
    assert out.geometry.area.sum() == pytest.approx(100 + 40)
    assert all(t == "Polygon" for t in out.geom_type)


def test_prepare_working_image_shape_dtype_and_color(tmp_path):
    path = tmp_path / "ortho.tif"
    data = np.zeros((3, 100, 100), dtype="uint8")
    data[0], data[1], data[2] = 200, 100, 50
    with rasterio.open(path, "w", driver="GTiff", height=100, width=100, count=3, dtype="uint8",
                       crs="EPSG:3857", transform=from_origin(12286800, -866900, 0.1, 0.1)) as dst:
        dst.write(data)
    aoi = box(12286803, -866907, 12286807, -866903)  # 4 m di dalam raster
    img, transform = roof_raster.prepare_working_image(path, aoi, "EPSG:3857", "EPSG:32749", 0.2, pad_m=1.0)
    assert img.dtype == np.uint8 and img.shape[0] == 3
    assert 20 <= img.shape[1] <= 45 and 20 <= img.shape[2] <= 45
    assert transform.a == pytest.approx(0.2)
    h, w = img.shape[1] // 2, img.shape[2] // 2
    assert tuple(img[:, h, w]) == (200, 100, 50)
