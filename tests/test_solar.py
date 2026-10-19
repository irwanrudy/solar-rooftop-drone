"""Tes untuk src/solar.py. Jalankan: pytest"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import solar  # noqa: E402

BASE = solar.Scenario("base", utilization_factor=0.5, module_efficiency=0.20, performance_ratio=0.75)


def test_capacity_and_energy_formula():
    area = pd.Series([100.0])
    # 100 m2 x 0.5 = 50 m2 efektif; x 0.20 = 10 kWp
    assert solar.capacity_kwp(area, BASE).iloc[0] == pytest.approx(10.0)
    # 10 kWp x GHI 1800 x PR 0.75 = 13_500 kWh
    assert solar.annual_energy_kwh(area, BASE, 1800).iloc[0] == pytest.approx(13_500)


def test_specific_yield_equals_ghi_times_pr():
    area = pd.Series([40.0, 250.0, 4000.0])
    table = solar.scenario_table(area, [BASE], ghi_kwh_m2_year=1900)
    assert table.loc[0, "yield_kwh_per_kwp"] == pytest.approx(1900 * 0.75)


def test_scenarios_are_ordered():
    low = solar.Scenario("low", 0.1, 0.17, 0.70)
    high = solar.Scenario("high", 0.6, 0.23, 0.80)
    table = solar.scenario_table(pd.Series([500.0]), [low, BASE, high], 1900)
    assert table["energi_mwh_tahun"].is_monotonic_increasing


def test_empty_input_gives_zero():
    table = solar.scenario_table(pd.Series([], dtype=float), [BASE], 1900)
    assert table.loc[0, "kapasitas_kwp"] == 0
    assert table.loc[0, "yield_kwh_per_kwp"] == 0


@pytest.mark.parametrize("bad", [0, -0.1, 1.5])
def test_invalid_parameters_rejected(bad):
    with pytest.raises(ValueError):
        solar.Scenario("x", utilization_factor=bad, module_efficiency=0.2, performance_ratio=0.75)


def test_scenarios_from_config():
    cfg = {"scenarios": {"a": {"utilization_factor": 0.3, "module_efficiency": 0.2, "performance_ratio": 0.7}}}
    (sc,) = solar.scenarios_from_config(cfg)
    assert sc.name == "a" and sc.utilization_factor == 0.3
