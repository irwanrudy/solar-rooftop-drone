import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

import compare


def gdf(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs="EPSG:32749")


def empty():
    return gpd.GeoDataFrame(geometry=[], crs="EPSG:32749")


OV = gdf(box(0, 0, 10, 10), box(100, 0, 110, 10), box(200, 0, 210, 10))


def test_iou_identical_disjoint_and_shifted():
    assert compare.iou(box(0, 0, 10, 10), box(0, 0, 10, 10)) == pytest.approx(1.0)
    assert compare.iou(box(0, 0, 10, 10), box(20, 0, 30, 10)) == 0.0
    assert compare.iou(box(0, 0, 10, 10), box(2, 0, 12, 10)) == pytest.approx(80 / 120)


def test_split_roof_is_merged_before_iou():
    segs = gdf(box(0, 0, 5, 10), box(5, 0, 10, 10), box(500, 500, 510, 510))
    res = compare.match(OV, segs)
    assert res.per_overture.loc[0, "n_segments"] == 2
    assert res.per_overture.loc[0, "iou"] == pytest.approx(1.0)
    assert bool(res.per_overture.loc[0, "matched"]) is True
    assert list(res.sam_only) == [2]
    assert res.per_overture.loc[2, "n_segments"] == 0


def test_shifted_segment_matches_with_expected_iou():
    res = compare.match(gdf(box(0, 0, 10, 10)), gdf(box(2, 0, 12, 10)))
    assert res.per_overture.loc[0, "iou"] == pytest.approx(80 / 120)
    assert bool(res.per_overture.loc[0, "matched"]) is True


def test_segment_straddling_two_buildings_goes_to_larger_overlap_only():
    ov = gdf(box(0, 0, 10, 10), box(10, 0, 20, 10))  # dinding bersama
    res = compare.match(ov, gdf(box(2, 0, 13, 10)))
    assert res.assignment.iloc[0] == 0
    assert res.per_overture.loc[1, "n_segments"] == 0
    assert compare.comparison_summary(ov, gdf(box(2, 0, 13, 10)), res)["hanya_sam"] == 0


def test_low_overlap_segment_is_sam_only():
    res = compare.match(gdf(box(0, 0, 10, 10)), gdf(box(8, 0, 18, 10)))  # 20% di dalam
    assert list(res.sam_only) == [0]


def test_low_iou_is_kurang_cocok_not_cocok():
    ov = gdf(box(0, 0, 10, 10))
    seg = gdf(box(0, 0, 10, 3))  # seluruhnya di dalam, IoU 0,3
    res = compare.match(ov, seg)
    s = compare.comparison_summary(ov, seg, res)
    assert (s["cocok"], s["kurang_cocok"], s["hanya_overture"]) == (0, 1, 0)


def test_summary_counts_and_area_difference():
    segs = gdf(box(0, 0, 5, 10), box(5, 0, 10, 10), box(500, 500, 510, 510))
    s = compare.comparison_summary(OV, segs, compare.match(OV, segs))
    assert (s["cocok"], s["kurang_cocok"], s["hanya_overture"], s["hanya_sam"]) == (1, 0, 2, 1)
    assert s["median_iou"] == pytest.approx(1.0)
    assert s["luas_overture_m2"] == 300 and s["luas_sam_m2"] == 200
    assert s["selisih_luas_pct"] == pytest.approx(-33.3)


def test_empty_inputs_do_not_crash():
    s = compare.comparison_summary(empty(), gdf(box(0, 0, 1, 1), box(5, 5, 6, 6)),
                                   compare.match(empty(), gdf(box(0, 0, 1, 1), box(5, 5, 6, 6))))
    assert (s["cocok"], s["hanya_overture"], s["hanya_sam"]) == (0, 0, 2)
    s = compare.comparison_summary(OV, empty(), compare.match(OV, empty()))
    assert (s["cocok"], s["hanya_overture"], s["hanya_sam"]) == (0, 3, 0)
    s = compare.comparison_summary(empty(), empty(), compare.match(empty(), empty()))
    assert s["cocok"] == 0 and s["selisih_luas_pct"] == 0.0


def test_invalid_overture_polygon_does_not_crash():
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not bowtie.is_valid
    res = compare.match(gdf(bowtie), gdf(box(0, 0, 10, 10)))
    assert len(res.per_overture) == 1


def test_systematic_offset_gives_bias_ratio_one():
    ov = gdf(box(0, 0, 10, 10), box(50, 0, 60, 10))
    guided = gdf(box(2, 0, 12, 10), box(52, 0, 62, 10))
    off = compare.centroid_offsets(ov, guided)
    s = compare.offset_summary(off)
    assert s["median_geser_m"] == pytest.approx(2.0)
    assert (s["rata_dx_m"], s["rata_dy_m"]) == (pytest.approx(2.0), pytest.approx(0.0))
    assert s["bias_ratio"] == pytest.approx(1.0)


def test_random_offset_gives_bias_ratio_zero():
    ov = gdf(box(0, 0, 10, 10), box(50, 0, 60, 10))
    guided = gdf(box(2, 0, 12, 10), box(48, 0, 58, 10))
    assert compare.offset_summary(compare.centroid_offsets(ov, guided))["bias_ratio"] == pytest.approx(0.0)


def test_offset_summary_empty():
    assert compare.offset_summary(compare.centroid_offsets(OV, empty()))["bias_ratio"] == 0.0


def test_sam_area_uses_union_so_nested_segments_are_not_double_counted():
    ov = gdf(box(0, 0, 10, 10))
    segs = gdf(box(0, 0, 10, 10), box(0, 0, 5, 10))  # bidang atap bersarang di dalam atap utuh
    s = compare.comparison_summary(ov, segs, compare.match(ov, segs))
    assert s["luas_sam_m2"] == 100 and s["selisih_luas_pct"] == 0.0
