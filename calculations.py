from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BANDS = {
    "UV": (300, 380),
    "VIS": (380, 780),
    "NIR": (780, 2500),
}


@dataclass
class EmissivityCurve:
    filename: str
    dataframe: pd.DataFrame
    mean_emissivity: float


def _find_column(columns: Iterable[str], candidates: list[str]) -> str:
    normalized = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    raise KeyError(f"Could not find any of these columns: {candidates}. Available columns: {list(columns)}")


def read_solar_file(file_or_path) -> pd.DataFrame:
    solar = pd.read_excel(file_or_path)
    wavelength_col = _find_column(solar.columns, ["Wvlgth nm", "wavelength", "nm"])
    irradiance_col = _find_column(
        solar.columns,
        ["Global tilt  W*m-2*nm-1", "Global tilt W*m-2*nm-1", "global tilt", "irradiance"],
    )
    solar = solar.rename(columns={wavelength_col: "wavelength", irradiance_col: "solar_irradiance"})
    solar["wavelength"] = pd.to_numeric(solar["wavelength"], errors="coerce")
    solar["solar_irradiance"] = pd.to_numeric(solar["solar_irradiance"], errors="coerce")
    solar = solar.dropna(subset=["wavelength", "solar_irradiance"])
    solar = solar[(solar["wavelength"] >= 300) & (solar["wavelength"] <= 2500)].copy()
    return solar


def read_reflectance_csv(file_or_path, filename: str | None = None) -> pd.DataFrame:
    reflectance = pd.read_csv(file_or_path)
    wavelength_col = _find_column(reflectance.columns, ["nm", "wavelength", "Wavelength"])
    reflectance_col = _find_column(reflectance.columns, [" %R", "%R", "R", "Reflectance", "reflectance"])
    reflectance = reflectance.rename(columns={wavelength_col: "wavelength", reflectance_col: "reflectance_percent"})
    reflectance["wavelength"] = pd.to_numeric(reflectance["wavelength"], errors="coerce")
    reflectance["reflectance_percent"] = pd.to_numeric(reflectance["reflectance_percent"], errors="coerce")
    reflectance = reflectance.dropna(subset=["wavelength", "reflectance_percent"])
    reflectance = reflectance[(reflectance["wavelength"] >= 300) & (reflectance["wavelength"] <= 2500)].copy()
    reflectance["filename"] = filename or "reflectance.csv"
    return reflectance


def calculate_tsr_for_reflectance(reflectance: pd.DataFrame, solar: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    merged = pd.merge(
        reflectance[["wavelength", "reflectance_percent"]],
        solar[["wavelength", "solar_irradiance"]],
        on="wavelength",
        how="inner",
    )
    if merged.empty:
        raise ValueError("No overlapping wavelengths between reflectance data and solar spectrum.")

    merged["reflectance_fraction"] = merged["reflectance_percent"] / 100.0
    weighted_reflectance = (merged["reflectance_fraction"] * merged["solar_irradiance"]).sum()
    total_irradiance = merged["solar_irradiance"].sum()
    tsr = weighted_reflectance / total_irradiance

    row = {"Filename": reflectance["filename"].iloc[0], "TSR": tsr}
    for band, (low, high) in BANDS.items():
        subset = reflectance.loc[
            (reflectance["wavelength"] >= low) & (reflectance["wavelength"] <= high),
            "reflectance_percent",
        ]
        row[f"{band}_mean"] = subset.mean()
        row[f"{band}_std"] = subset.std()

    return row, merged


def list_files_from_folder(folder: str, suffixes: tuple[str, ...]) -> list[Path]:
    if not folder:
        return []
    path = Path(folder).expanduser()
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    return sorted([p for p in path.iterdir() if p.suffix.lower() in suffixes])


def process_tsr_folder(folder: str, solar_file_or_path) -> pd.DataFrame:
    solar = read_solar_file(solar_file_or_path)
    rows = []
    for path in list_files_from_folder(folder, (".csv",)):
        reflectance = read_reflectance_csv(path, filename=path.name)
        row, _ = calculate_tsr_for_reflectance(reflectance, solar)
        rows.append(row)
    return pd.DataFrame(rows)


def read_ftir_file(file_or_path, filename: str | None = None) -> EmissivityCurve:
    data = np.loadtxt(file_or_path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("FTIR file must have at least two numeric columns: wavenumber and transmittance/reflectance value.")

    wavenumber = data[:, 0]
    y = data[:, 1]
    wavelength_um = (1 / wavenumber) * 10000
    emissivity = 1 - y

    df = pd.DataFrame({"Wavelength_um": wavelength_um, "Emissivity": emissivity})
    df = df.sort_values("Wavelength_um")
    mask = (df["Wavelength_um"] >= 8) & (df["Wavelength_um"] <= 13)
    mean_emissivity = df.loc[mask, "Emissivity"].mean()
    return EmissivityCurve(filename=filename or "ftir_file", dataframe=df, mean_emissivity=mean_emissivity)


def process_emissivity_folder(folder: str) -> tuple[pd.DataFrame, list[EmissivityCurve]]:
    curves = []
    for path in list_files_from_folder(folder, (".dpt", ".txt")):
        curves.append(read_ftir_file(path, filename=path.name))
    results = pd.DataFrame([{"Filename": c.filename, "Emissivity_8_13_um": c.mean_emissivity} for c in curves])
    return results, curves


def sri_astm_e1980(tsr: float, emissivity: float, hc: float) -> float:
    e = emissivity
    a = 1.0 - tsr
    numerator = (a - 0.029 * e) * (8.797 + hc)
    denominator = 9.5205 * e + hc
    x = numerator / denominator
    return 123.97 - 141.35 * x + 9.655 * x**2


def sri_all_wind_speeds(tsr: float, emissivity: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"Condition": "Low wind", "hc": 5.0, "SRI": sri_astm_e1980(tsr, emissivity, 5.0)},
        {"Condition": "Medium wind", "hc": 12.0, "SRI": sri_astm_e1980(tsr, emissivity, 12.0)},
        {"Condition": "High wind", "hc": 30.0, "SRI": sri_astm_e1980(tsr, emissivity, 30.0)},
    ])


def dataframe_to_excel_bytes(sheet_name: str, df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return buffer.getvalue()


def curves_to_zip_bytes(curves: list[EmissivityCurve]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for curve in curves:
            name = Path(curve.filename).stem
            txt = curve.dataframe.to_csv(index=False, sep="\t", float_format="%.6f")
            zf.writestr(f"FTIR-{name}.txt", txt)
    return buffer.getvalue()
