from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st
import pandas as pd
import numpy as np

from calculations import (
    curves_to_zip_bytes,
    dataframe_to_excel_bytes,
    process_emissivity_folder,
    process_tsr_folder,
    sri_all_wind_speeds,
)

APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOLAR_PATH = APP_DIR / "data" / "astmg173.xls"

st.set_page_config(page_title="TSR, Emissivity and SRI Calculator", layout="wide")
st.title("TSR, Emissivity and SRI Calculator")
st.caption("Calculations of ASTM E903 TSR, FTIR-derived emissivity from 8-13um, and ASTM E1980 SRI.")

def show_downloads(prefix: str, df):
    st.download_button(
        f"Download {prefix} results as Excel",
        data=dataframe_to_excel_bytes(prefix, df),
        file_name=f"{prefix.lower().replace(' ', '_')}_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        f"Download {prefix} results as CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"{prefix.lower().replace(' ', '_')}_results.csv",
        mime="text/csv",
    )


def get_solar_path() -> Path | None:
    st.info("The TSR calculation uses the ASTM G173 file, please download in data folder if not present.")

    if DEFAULT_SOLAR_PATH.exists():
        st.success("ASTM solar file found.")
        return DEFAULT_SOLAR_PATH

    st.error("ASTM solar file was not found in the project data folder.")
    st.write("Create a folder named `data` next to `app.py`, then place `astmg173.xls` inside it.")
    return None


def process_tsr_files(files, solar_path):
    results = []

    solar = pd.read_excel(solar_path)
    solar = solar.rename(columns={'Wvlgth nm': 'wavelength'})
    solar = solar[(solar['wavelength'] % 5 == 0) &
                  (solar['wavelength'] >= 300) &
                  (solar['wavelength'] <= 2500)]

    for file in files:
        reflectance = pd.read_csv(file)
        reflectance = reflectance.rename(columns={'nm': 'wavelength'})

        reflectance = reflectance[(reflectance['wavelength'] % 5 == 0) &
                                 (reflectance['wavelength'] >= 300) &
                                 (reflectance['wavelength'] <= 2500)]

        merged = pd.merge(
            reflectance[['wavelength', ' %R']],
            solar[['wavelength', 'Global tilt  W*m-2*nm-1']],
            on='wavelength'
        )

        merged['reflectance_frac'] = merged[' %R'] / 100

        TSR = (
            (merged['reflectance_frac'] * merged['Global tilt  W*m-2*nm-1']).sum()
            / merged['Global tilt  W*m-2*nm-1'].sum()
        )

        results.append({"Filename": file.name, "TSR": round(TSR, 4)})

    return pd.DataFrame(results)

def process_emissivity_files(files):
    results = []
    curves = []

    for file in files:
        data = np.loadtxt(file)

        x = data[:, 0]
        y = data[:, 1]

        wavelength_um = (1 / x) * 10000
        emissivity = 1 - y

        mask = (wavelength_um >= 8) & (wavelength_um <= 13)
        mean_E = np.mean(emissivity[mask])

        df_curve = pd.DataFrame({
            "Wavelength_um": wavelength_um,
            "Emissivity": emissivity
        })

        curves.append(type("Curve", (), {
            "filename": file.name,
            "dataframe": df_curve
        }))

        results.append({
            "Filename": file.name,
            "Emissivity (8–13 µm)": round(mean_E, 4)
        })

    return pd.DataFrame(results), curves

tab_tsr, tab_emissivity, tab_sri = st.tabs(["TSR", "Emissivity", "SRI"])

with tab_tsr:
    st.subheader("Total Solar Reflectance")
    st.write("The app calculates TSR by taking the weighted average of the reflectance values with reference to the Global Tilt irradiance.")
    solar_path = get_solar_path()

    uv_files = st.file_uploader(
        "Upload UV-Vis reflectance CSV files",
        type=["csv"],
        accept_multiple_files=True
    )

    if st.button("Calculate TSR"):
        if solar_path is None:
            st.stop()
        if not uv_files:
            st.error("Please upload at least one CSV file.")
        else:
            try:
                tsr_results = process_tsr_files(uv_files, solar_path)

                if tsr_results.empty:
                    st.warning("No valid files were processed.")
                else:
                    st.success("TSR calculation complete.")
                    st.dataframe(tsr_results, use_container_width=True)
                    show_downloads("TSR", tsr_results)

            except Exception as exc:
                st.error(f"TSR calculation failed: {exc}")

with tab_emissivity:
    st.subheader("FTIR-derived Emissivity")
    st.write("The app calculates mean emissivity from 8–13 µm.")

    ftir_files = st.file_uploader(
        "Upload FTIR DPT files",
        type=["dpt"],
        accept_multiple_files=True
    )

    if st.button("Calculate emissivity"):
        if not ftir_files:
            st.error("Please upload at least one FTIR file.")
        else:
            try:
                emissivity_results, emissivity_curves = process_emissivity_files(ftir_files)

                if emissivity_results.empty:
                    st.warning("No valid FTIR files were processed.")
                else:
                    st.success("Emissivity calculation complete.")
                    st.dataframe(emissivity_results, use_container_width=True)

                    fig, ax = plt.subplots(figsize=(8, 5))
                    for curve in emissivity_curves:
                        ax.plot(
                            curve.dataframe["Wavelength_um"],
                            curve.dataframe["Emissivity"],
                            label=curve.filename
                        )

                    ax.set_xlim(2, 20)
                    ax.set_ylim(0, 1.1)
                    ax.set_xlabel("Wavelength (µm)")
                    ax.set_ylabel("Emissivity")
                    ax.set_title("FTIR-derived Emissivity Curves")
                    ax.grid(True)
                    ax.legend(fontsize=8)

                    st.pyplot(fig)

                    show_downloads("Emissivity", emissivity_results)

                    st.download_button(
                        "Download converted FTIR emissivity TXT files",
                        data=curves_to_zip_bytes(emissivity_curves),
                        file_name="converted_emissivity_curves.zip",
                        mime="application/zip",
                    )

            except Exception as exc:
                st.error(f"Emissivity calculation failed: {exc}")

with tab_sri:
    st.subheader("Solar Reflectance Index")
    st.write("Enter TSR and emissivity manually. The app calculates SRI for low, medium, and high wind conditions using ASTM E1980.")

    col1, col2 = st.columns(2)
    with col1:
        tsr = st.number_input("TSR", min_value=0.0, max_value=1.5, value=0.9000, step=0.0001, format="%.4f")
    with col2:
        emissivity = st.number_input("Emissivity", min_value=0.0, max_value=1.5, value=0.9000, step=0.0001, format="%.4f")

    if st.button("Calculate SRI"):
        sri_results = sri_all_wind_speeds(tsr, emissivity)
        st.success("SRI calculation complete.")
        st.dataframe(sri_results, use_container_width=True)
        show_downloads("SRI", sri_results)
