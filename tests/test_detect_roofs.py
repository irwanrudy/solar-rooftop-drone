import json

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

import detect_roofs


class FakeBackend:
    """Mask palsu yang posisinya diketahui, untuk menguji pemetaan koordinat."""

    def generate(self, image):
        m = np.zeros(image.shape[:2], dtype=bool)
        m[10:30, 20:60] = True  # baris 10-29, kolom 20-59 (koordinat tile)
        return [m]

    def predict_box(self, image, box_xyxy):
        x0, y0, x1, y1 = (int(round(v)) for v in box_xyxy)
        m = np.zeros(image.shape[:2], dtype=bool)
        m[y0:y1, x0:x1] = True
        return np.stack([m, m, m]), np.array([0.9, 0.8, 0.7])


SAM_CFG = {"tile_px": 200, "overlap_px": 50, "working_gsd_m": 1.0,
           "auto": {"dedupe_iou": 0.7}, "guided": {"box_pad_m": 2.0}}


def test_run_auto_maps_tile_masks_to_world_coordinates():
    image = np.zeros((3, 300, 300), dtype="uint8")
    out = detect_roofs.run_auto(FakeBackend(), image, from_origin(0, 300, 1, 1), "EPSG:32749", SAM_CFG)
    assert len(out) == 4  # 4 tile, mask di posisi lokal sama -> 4 poligon berbeda
    bounds = {tuple(round(v, 6) for v in g.bounds) for g in out.geometry}
    assert (20.0, 270.0, 60.0, 290.0) in bounds  # tile (0,0): kolom 20-60, baris 10-30 -> y 270-290
    assert (120.0, 270.0, 160.0, 290.0) in bounds  # tile bergeser 100 piksel ke kanan
    assert out.crs.to_string() == "EPSG:32749"


def test_write_geojson_empty_and_nonempty(tmp_path):
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:32749")
    p = tmp_path / "e.geojson"
    detect_roofs.write_geojson(empty, p)
    assert json.loads(p.read_text())["features"] == []
    full = gpd.GeoDataFrame({"a": [1]}, geometry=[box(430600, 9141500, 430610, 9141510)], crs="EPSG:32749")
    q = tmp_path / "f.geojson"
    detect_roofs.write_geojson(full, q)
    assert len(json.loads(q.read_text())["features"]) == 1
