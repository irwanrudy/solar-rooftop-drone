import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

import roof_filters

T = from_origin(0, 20, 1, 1)  # piksel 1 m; baris r <-> y = 20 - r
CFG = {"min_area_m2": 10, "max_area_m2": 100, "min_solidity": 0.75,
       "min_brightness": 15, "max_exg": 0.05}


def gdf(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs="EPSG:32749")


def image(left, right):
    img = np.zeros((3, 20, 20), dtype="uint8")
    img[:, :, :10] = np.array(left, dtype="uint8")[:, None, None]
    img[:, :, 10:] = np.array(right, dtype="uint8")[:, None, None]
    return img


def test_zonal_mean_values_and_outside_is_nan():
    band = np.zeros((20, 20), dtype="float32")
    band[:, :10], band[:, 10:] = 1.0, 3.0
    s = roof_filters.zonal_mean(gdf(box(1, 5, 8, 15), box(11, 5, 18, 15), box(100, 100, 110, 110)), band, T)
    assert s.iloc[0] == pytest.approx(1.0) and s.iloc[1] == pytest.approx(3.0)
    assert np.isnan(s.iloc[2])


def test_exg_positive_for_green_negative_for_orange():
    exg = roof_filters.compute_exg(image((0, 200, 0), (200, 100, 50)))
    assert exg[0, 0] == pytest.approx(2.0) and exg[0, 15] < 0


def test_vegetation_is_dropped_roof_is_kept():
    img = image((0, 200, 0), (200, 100, 50))  # kiri hijau, kanan oranye
    kept, rep = roof_filters.apply_filters(gdf(box(1, 5, 8, 15), box(11, 5, 18, 15)), img, T, CFG)
    assert len(kept) == 1 and kept.geometry.iloc[0].bounds[0] == 11
    assert rep["awal"] == 2 and rep["lolos_vegetasi"] == 1


def test_black_nodata_region_is_dropped():
    img = image((200, 100, 50), (0, 0, 0))  # kanan = di luar data valid
    kept, rep = roof_filters.apply_filters(gdf(box(1, 5, 8, 15), box(11, 5, 18, 15)), img, T, CFG)
    assert len(kept) == 1 and kept.geometry.iloc[0].bounds[0] == 1
    assert rep["lolos_kecerahan"] == 1


def test_area_filter_drops_tiny_and_huge():
    img = image((200, 100, 50), (200, 100, 50))
    polys = gdf(box(1, 1, 3, 3), box(5, 5, 10, 10), box(0, 0, 12, 12))  # 4, 25, 144 m2
    kept, rep = roof_filters.apply_filters(polys, img, T, CFG)
    assert len(kept) == 1 and rep["lolos_luas"] == 1


def test_solidity_filter_drops_concave_shape():
    img = image((200, 100, 50), (200, 100, 50))
    l_shape = Polygon([(0, 0), (10, 0), (10, 3), (3, 3), (3, 10), (0, 10)])  # solidity 0,675
    kept, rep = roof_filters.apply_filters(gdf(l_shape, box(11, 5, 18, 12)), img, T, CFG)
    assert len(kept) == 1 and rep["lolos_solidity"] == 1


def test_empty_input_returns_empty_and_report():
    kept, rep = roof_filters.apply_filters(gdf(), image((200, 100, 50), (200, 100, 50)), T, CFG)
    assert kept.empty and rep["awal"] == 0
