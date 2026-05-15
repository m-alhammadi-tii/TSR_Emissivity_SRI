# TSR, Emissivity and SRI Streamlit App

Run:

```bash
streamlit run app.py
```

## ASTM G173 solar file

The TSR tab does **not** ask the user to upload the ASTM file.

Place your ASTM G173 Excel file here:

```text
data/astmg173.xls
```

The app automatically reads that file every time.

## Inputs

- TSR: enter a folder path containing UV-Vis reflectance `.csv` files.
- Emissivity: enter a folder path containing FTIR `.dpt` or `.txt` files.
- SRI: enter TSR and emissivity manually.

Each tab has its own download button for results.
