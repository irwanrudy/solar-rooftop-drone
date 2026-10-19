"""Estimasi kapasitas dan energi PV atap dari luas denah bangunan (v0.2).

Rumus (mengikuti Triana dkk. 2024, pers. 13, dengan iradiasi horizontal):

    A_eff   = A_denah x UF                 luas efektif (m2)
    kWp     = A_eff x eta x 1 kW/m2        kapasitas terpasang (kondisi STC)
    kWh/thn = A_eff x eta x GHI x PR       energi tahunan

dengan
    UF   faktor pemanfaatan atap (fraksi denah yang bisa dipasangi modul)
    eta  efisiensi modul pada STC (pecahan, mis. 0.20)
    GHI  iradiasi global horizontal tahunan (kWh/m2/tahun)
    PR   performance ratio (rugi suhu, kotoran, mismatch, inverter, kabel)

Hasil adalah screening berbasis luas: kemiringan, arah, dan bayangan atap
TIDAK dimodelkan (lihat README). Fungsi di sini murni (tanpa I/O) agar mudah diuji.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

STC_IRRADIANCE_KW_M2 = 1.0  # 1000 W/m2 pada Standard Test Conditions


@dataclass(frozen=True)
class Scenario:
    """Satu set asumsi: skenario rendah / dasar / tinggi."""

    name: str
    utilization_factor: float
    module_efficiency: float
    performance_ratio: float

    def __post_init__(self) -> None:
        for field, value in (
            ("utilization_factor", self.utilization_factor),
            ("module_efficiency", self.module_efficiency),
            ("performance_ratio", self.performance_ratio),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{self.name}.{field} harus di (0, 1], dapat {value}")


def scenarios_from_config(solar_cfg: dict) -> list[Scenario]:
    """Bangun daftar Scenario dari bagian `solar.scenarios` pada config.yaml."""
    return [Scenario(name=name, **params) for name, params in solar_cfg["scenarios"].items()]


def effective_area(area_m2: pd.Series, scenario: Scenario) -> pd.Series:
    """Luas efektif (m2) = luas denah x faktor pemanfaatan."""
    return area_m2 * scenario.utilization_factor


def capacity_kwp(area_m2: pd.Series, scenario: Scenario) -> pd.Series:
    """Kapasitas terpasang (kWp) dari luas denah."""
    return effective_area(area_m2, scenario) * scenario.module_efficiency * STC_IRRADIANCE_KW_M2


def annual_energy_kwh(area_m2: pd.Series, scenario: Scenario, ghi_kwh_m2_year: float) -> pd.Series:
    """Energi tahunan (kWh/tahun) = A_eff x eta x GHI x PR."""
    return (
        effective_area(area_m2, scenario)
        * scenario.module_efficiency
        * ghi_kwh_m2_year
        * scenario.performance_ratio
    )


def add_estimates(gdf, scenario: Scenario, ghi_kwh_m2_year: float):
    """Tambah kolom `eff_area_m2`, `kwp`, `kwh_year` (skenario dasar) ke GeoDataFrame."""
    out = gdf.copy()
    out["eff_area_m2"] = effective_area(out["area_m2"], scenario).round(2)
    out["kwp"] = capacity_kwp(out["area_m2"], scenario).round(2)
    out["kwh_year"] = annual_energy_kwh(out["area_m2"], scenario, ghi_kwh_m2_year).round(0)
    return out


def scenario_table(area_m2: pd.Series, scenarios: list[Scenario], ghi_kwh_m2_year: float) -> pd.DataFrame:
    """Total per skenario: luas efektif, kWp, MWh/tahun, dan yield spesifik."""
    rows = []
    for sc in scenarios:
        kwp = float(capacity_kwp(area_m2, sc).sum())
        kwh = float(annual_energy_kwh(area_m2, sc, ghi_kwh_m2_year).sum())
        rows.append(
            {
                "skenario": sc.name,
                "faktor_pemanfaatan": sc.utilization_factor,
                "efisiensi_modul": sc.module_efficiency,
                "performance_ratio": sc.performance_ratio,
                "luas_efektif_m2": round(float(effective_area(area_m2, sc).sum()), 1),
                "kapasitas_kwp": round(kwp, 1),
                "energi_mwh_tahun": round(kwh / 1000, 1),
                "yield_kwh_per_kwp": round(kwh / kwp, 0) if kwp else 0.0,
            }
        )
    return pd.DataFrame(rows)
