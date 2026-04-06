"""
app_dashboard.py — Sabana Centro Sostenible · Dashboard Web
Sirve la interfaz de visualización de resultados usando Flask.

Uso:
    python app_dashboard.py
    Abrir http://localhost:5001
"""

from __future__ import annotations
import json
import os
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template_string, send_from_directory, request
from pyproj import Transformer

BASE_DIR      = Path(__file__).parent
OUTPUT_XLSX   = BASE_DIR / "salidas/resultados_matching.xlsx"
GEOJSON_FILE  = BASE_DIR / "sabanacentro.geojson"
SISPT_DIR     = BASE_DIR / "SisPT"
ALERTAS_DIR   = BASE_DIR / "Alertas"

# Dimensiones (primer número del ID)
DIMENSION_NAMES = {
    "1": "Medio Ambiente",
    "2": "Competitividad",
    "3": "Infraestructura",
    "4": "Salud",
    "5": "Educación",
    "6": "Gobernanza",
    "7": "Cultura y Deporte",
    "8": "Social",
    "9": "TIC",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static")


_alertas_cache: dict | None = None

def load_alertas() -> dict:
    """
    Lee todos los Alertas-{DANE}.xlsx y devuelve:
      { dane: { mga_code: {
          'oblig_2024': float, 'pagos_2024': float, 'pct_fin_2024': str,
          'oblig_2025': float, 'pagos_2025': float, 'pct_fin_2025': str,
          'ejec_fis_2024': float, 'pct_fis_2024': str,
          'ejec_fis_2025': float, 'pct_fis_2025': str,
          'meta_cuatrenio': str, 'unidad': str
      }}}
    """
    global _alertas_cache
    if _alertas_cache is not None:
        return _alertas_cache

    result: dict = {}
    if not ALERTAS_DIR.exists():
        _alertas_cache = result
        return result

    for f in sorted(ALERTAS_DIR.glob("Alertas-[0-9]*.xlsx")):
        dane = f.stem.replace("Alertas-", "").strip()
        dane_data: dict = {}
        try:
            xls = pd.ExcelFile(f, engine="openpyxl")
            # --- Hoja financiera ---
            fin_sheet = next((s for s in xls.sheet_names if "financier" in s.lower()), None)
            if fin_sheet:
                df_fin = pd.read_excel(xls, fin_sheet, header=None, dtype=str,
                                       engine="openpyxl").fillna("")
                # Header row is row 6 (0-indexed)
                MGA_C, OBL24, PAG24, PCT24, OBL25, PAG25, PCT25 = 5, 15, 16, 17, 20, 21, 22
                for i in range(7, len(df_fin)):
                    row = df_fin.iloc[i]
                    mga = str(row.iloc[MGA_C] if MGA_C < len(row) else "").strip()
                    if not mga or mga == "nan":
                        continue
                    def _safe_float(val):
                        try: return float(str(val).strip().replace(",", "."))
                        except: return 0.0
                    def _pct(val):
                        v = str(val).strip()
                        if not v or v in ("nan", ""):
                            return "0.00%"
                        try:
                            num = float(v.replace(",", ".").replace("%", ""))
                            if abs(num) < 2: num = num * 100
                            return f"{num:.2f}%"
                        except: return v

                    entry = dane_data.setdefault(mga, {})
                    entry["oblig_2024"]   = entry.get("oblig_2024", 0.0) + _safe_float(row.iloc[OBL24] if OBL24 < len(row) else 0)
                    entry["pagos_2024"]   = entry.get("pagos_2024", 0.0) + _safe_float(row.iloc[PAG24] if PAG24 < len(row) else 0)
                    entry["pct_fin_2024"] = _pct(row.iloc[PCT24] if PCT24 < len(row) else "")
                    entry["oblig_2025"]   = entry.get("oblig_2025", 0.0) + _safe_float(row.iloc[OBL25] if OBL25 < len(row) else 0)
                    entry["pagos_2025"]   = entry.get("pagos_2025", 0.0) + _safe_float(row.iloc[PAG25] if PAG25 < len(row) else 0)
                    entry["pct_fin_2025"] = _pct(row.iloc[PCT25] if PCT25 < len(row) else "")

            # --- Hoja física ---
            fis_sheet = next((s for s in xls.sheet_names if "físic" in s.lower() or "fisic" in s.lower()), None)
            if fis_sheet:
                df_fis = pd.read_excel(xls, fis_sheet, header=None, dtype=str,
                                       engine="openpyxl").fillna("")
                MGA_C, UNI_C, META_C, EF24, PCT_F24, EF25, PCT_F25 = 5, 11, 12, 17, 18, 20, 21
                for i in range(7, len(df_fis)):
                    row = df_fis.iloc[i]
                    mga = str(row.iloc[MGA_C] if MGA_C < len(row) else "").strip()
                    if not mga or mga == "nan":
                        continue
                    def _sf(val):
                        try: return float(str(val).strip().replace(",", "."))
                        except: return 0.0
                    def _ss(val):
                        v = str(val).strip()
                        return "" if v in ("", "nan") else v
                    def _pct_fis(val):
                        v = str(val).strip()
                        if not v or v in ("nan", ""): return "0.00%"
                        try:
                            num = float(v.replace(",", ".").replace("%", ""))
                            if abs(num) < 2: num = num * 100
                            return f"{num:.2f}%"
                        except: return v

                    entry = dane_data.setdefault(mga, {})
                    if "unidad" not in entry:
                        entry["unidad"]         = _ss(row.iloc[UNI_C] if UNI_C < len(row) else "")
                        entry["meta_cuatrenio"]  = _ss(row.iloc[META_C] if META_C < len(row) else "")
                    entry["ejec_fis_2024"] = entry.get("ejec_fis_2024", 0.0) + _sf(row.iloc[EF24] if EF24 < len(row) else 0)
                    entry["pct_fis_2024"]  = _pct_fis(row.iloc[PCT_F24] if PCT_F24 < len(row) else "")
                    entry["ejec_fis_2025"] = entry.get("ejec_fis_2025", 0.0) + _sf(row.iloc[EF25] if EF25 < len(row) else 0)
                    entry["pct_fis_2025"]  = _pct_fis(row.iloc[PCT_F25] if PCT_F25 < len(row) else "")

        except Exception as e:
            print(f"Error {dane}: {e}")

        if dane_data:
            result[str(dane).strip()] = dane_data

    print(f"Alertas Discoveries: {list(result.keys())}")
    _alertas_cache = result
    return result


def load_data() -> pd.DataFrame:
    """Carga y normaliza el Excel de resultados y enriquece con finanzas de SisPT."""
    if not OUTPUT_XLSX.exists():
        return pd.DataFrame()
    df = pd.read_excel(OUTPUT_XLSX, dtype=str)
    # Convertir columnas numéricas
    for col in ["Especificidad", "Vision_Regional", "Impacto", "Calificacion_Promedio"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Extraer dimensión del ID
    if "ID_Proyecto" in df.columns:
        df["Dimension_ID"] = df["ID_Proyecto"].str.split("-").str[0].str.strip()
        df["Dimension"] = df["Dimension_ID"].map(DIMENSION_NAMES).fillna(
            df["Dimension_ID"].apply(lambda x: f"Dimensión {x}")
        )
    # Normalizar DANE
    if "Codigo_DANE" in df.columns:
        df["Codigo_DANE"] = df["Codigo_DANE"].str.strip().str.split(".").str[0]

    # Cargar totales financieros desde SisPT
    sispt_finances = {} # dane -> mga -> {2024: val, 2025: val...}
    for dane in df["Codigo_DANE"].dropna().unique():
        p = SISPT_DIR / f"{dane}.xlsx"
        if not p.exists(): continue
        
        try:
            xls = pd.ExcelFile(p)
            ts = next((s for s in xls.sheet_names if "producto" in s.lower()), xls.sheet_names[0])
            sdf = pd.read_excel(xls, ts, header=None, dtype=str).fillna("")
            
            mga_c = None
            for r in range(min(5, len(sdf))):
                for c in range(len(sdf.columns)):
                    val = str(sdf.iloc[r, c]).lower()
                    if "mga" in val and "digo" in val and "indicador" in val:
                        mga_c = c; break
                if mga_c is not None: break
                
            if mga_c is None: continue
            
            t_cols = {}
            for c in range(len(sdf.columns)):
                hdr = str(sdf.iloc[1, c]).lower()
                if "total" in hdr:
                    for y in ["2024", "2025", "2026", "2027"]:
                        if y in hdr: t_cols[y] = c
            
            dane_dict = {}
            for r in range(2, len(sdf)):
                cell_mga = str(sdf.iloc[r, mga_c]).strip()
                if cell_mga:
                    dane_dict[cell_mga] = {}
                    for y, c in t_cols.items():
                        val = str(sdf.iloc[r, c]).strip()
                        if val and val != "nan":
                            try:
                                num = float(val)
                                dane_dict[cell_mga][y] = f"${num:,.0f}".replace(",", ".") if num > 0 else "$0"
                            except:
                                dane_dict[cell_mga][y] = val
                        else:
                            dane_dict[cell_mga][y] = "$0"
            sispt_finances[dane] = dane_dict
        except Exception as e:
            print(f"Error procesando finanzas para {dane}: {e}")

    # Inject to df row by row
    def get_finances(row):
        dane = str(row.get("Codigo_DANE", "")).strip()
        codes = str(row.get("Codigos_MGA", "")).split(",")
        f_dict = {}
        for c in codes:
            c = c.strip()
            if c and dane in sispt_finances and c in sispt_finances[dane]:
                f_dict[c] = sispt_finances[dane][c]
            else:
                f_dict[c] = {"2024": "—", "2025": "—", "2026": "—", "2027": "—"}
        return f_dict

    df["Finanzas"] = df.apply(get_finances, axis=1)

    return df


def reproject_geojson(geojson: dict) -> dict:
    """Reproyecta de EPSG:9377 (Colombia) a WGS84 para Leaflet."""
    transformer = Transformer.from_crs("EPSG:9377", "EPSG:4326", always_xy=True)

    def reproject_coords(coords):
        if isinstance(coords[0], (int, float)):
            lon, lat = transformer.transform(coords[0], coords[1])
            return [lon, lat]
        return [reproject_coords(c) for c in coords]

    features_out = []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        if geom:
            geom = dict(geom)
            geom["coordinates"] = reproject_coords(geom["coordinates"])
        features_out.append({**feat, "geometry": geom})

    return {**geojson, "features": features_out, "crs": None}


@app.route("/")
def index():
    return render_template_string(open("templates/index.html", encoding="utf-8").read())


@app.route("/api/geojson")
def api_geojson():
    if not GEOJSON_FILE.exists():
        return jsonify({"error": "GeoJSON no encontrado"}), 404
    with open(GEOJSON_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    reprojected = reproject_geojson(raw)
    return jsonify(reprojected)


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/data")
def api_data():
    df = load_data()
    if df.empty:
        return jsonify({"rows": [], "municipalities": [], "dimensions": []})

    # Extract rows to dicts
    raw_rows = df.to_dict(orient="records")
    
    # Scrub NaN values safely (since pandas to_dict sometimes leaves float('nan') which breaks JS JSON)
    rows = []
    for r in raw_rows:
        cleaned = {}
        for k, v in r.items():
            if isinstance(v, float) and v != v: # NaN check
                cleaned[k] = None
            elif v is pd.NA:
                cleaned[k] = None
            else:
                cleaned[k] = v
        rows.append(cleaned)

    municipalities = sorted(df["Municipio"].dropna().unique().tolist()) if "Municipio" in df.columns else []
    dimensions = sorted(df["Dimension"].dropna().unique().tolist()) if "Dimension" in df.columns else []

    # Build sorted list of unique projects: [{id, nombre}]
    projects = []
    if "ID_Proyecto" in df.columns and "Nombre_Proyecto" in df.columns:
        proj_df = df[["ID_Proyecto", "Nombre_Proyecto"]].drop_duplicates().dropna(subset=["ID_Proyecto"])
        proj_df = proj_df.sort_values("ID_Proyecto", key=lambda s: s.str.extract(r'(\d+)', expand=False).astype(float, errors='ignore'))
        projects = proj_df.apply(lambda r: {"id": r["ID_Proyecto"], "nombre": r["Nombre_Proyecto"]}, axis=1).tolist()

    # Inject Alertas execution per row
    # Codigos_MGA usa 9 dígitos (indicador); Alertas usa 7 dígitos (producto) → primeros 7 dígitos
    alertas = load_alertas()
    for row in rows:
        dane = str(row.get("Codigo_DANE") or "").strip()
        codes = str(row.get("Codigos_MGA") or "").split(",")
        alertas_per_code = {}
        for c9 in codes:
            c9 = c9.strip()
            if not c9:
                continue
            # Intentar primero con los 7 primeros dígitos (código producto)
            c7 = c9[:7]
            if dane in alertas:
                if c7 in alertas[dane]:
                    alertas_per_code[c9] = alertas[dane][c7]  # guardar con la clave original de 9 díg
                elif c9 in alertas[dane]:
                    alertas_per_code[c9] = alertas[dane][c9]
        row["Alertas"] = alertas_per_code

    return jsonify({"rows": rows, "municipalities": municipalities, "dimensions": dimensions, "projects": projects})


@app.route("/api/alertas/<dane_code>")
def api_alertas(dane_code):
    """Devuelve datos de ejecución del municipio (todos los códigos MGA)."""
    alertas = load_alertas()
    dane_data = alertas.get(str(dane_code).strip(), {})
    return jsonify(dane_data)


@app.route("/sispt/<dane_code>")
def sispt_viewer(dane_code):
    """Renderiza la hoja 'Plan indicativo - Productos' del SisPT como tabla HTML."""
    highlight = request.args.get("highlight", "").strip()

    xlsx_path = SISPT_DIR / f"{dane_code}.xlsx"
    if not xlsx_path.exists():
        return f"<h1>Archivo SisPT no encontrado para código {dane_code}</h1>", 404

    xls = pd.ExcelFile(xlsx_path)

    # Buscar la hoja de Productos
    target_sheet = None
    for s in xls.sheet_names:
        if "producto" in s.lower():
            target_sheet = s
            break
    if not target_sheet:
        target_sheet = xls.sheet_names[0]

    df = pd.read_excel(xls, target_sheet, header=None, dtype=str)
    df = df.fillna("")

    # Encontrar la columna con códigos MGA (buscar "mga" en headers)
    # Hay dos columnas con MGA: C9 "Código del producto (MGA)" y C11 "Código de indicador de producto (MGA)"
    # Los códigos de 9 dígitos que usamos (ej: 400203400) están en la de indicador (C11)
    mga_col_idx = None
    mga_candidates = []
    for r in range(min(5, len(df))):
        for c in range(len(df.columns)):
            val = str(df.iloc[r, c]).lower()
            if "mga" in val and "digo" in val:
                mga_candidates.append(c)
    # Preferir la columna de "indicador" si existe, si no usar la primera
    for c in mga_candidates:
        hdr = str(df.iloc[1, c]).lower() if len(df) > 1 else ""
        if "indicador" in hdr:
            mga_col_idx = c
            break
    if mga_col_idx is None and mga_candidates:
        mga_col_idx = mga_candidates[0]

    # Detectar columna de código de PRODUCTO (7 dígitos) para merge con Alertas
    # Es la columna MGA que NO tiene "indicador" en el encabezado
    product_col_idx = None
    for c in mga_candidates:
        hdr = str(df.iloc[1, c]).lower() if len(df) > 1 else ""
        if "indicador" not in hdr and "programa" not in hdr:
            product_col_idx = c
            break
    if product_col_idx is None:
        product_col_idx = mga_candidates[0] if mga_candidates else None

    # Detectar nombre del municipio
    muni_name = dane_code
    for r in range(min(5, len(df))):
        for c in range(len(df.columns)):
            val = str(df.iloc[r, c]).strip()
            if val and len(val) > 3 and not any(kw in val.upper() for kw in ["PARTE", "CÓDIGO", "INDICADOR", "PRODUCTO", "META", "LÍNEA", "NAN"]):
                if not val.isdigit() and not val.startswith("20"):
                    muni_name = val
                    break
        if muni_name != dane_code:
            break

    # Precomputar filas resaltadas
    highlighted_rows = set()
    if highlight and mga_col_idx is not None:
        for r in range(len(df)):
            cell = str(df.iloc[r, mga_col_idx]).strip()
            if cell and highlight in cell:
                highlighted_rows.add(r)

    # Identificar columna donde empiezan los precios (ej: "Recursos propios 2024")
    price_start_idx = None
    if len(df) > 1:
        for c in range(len(df.columns)):
            hdr = str(df.iloc[1, c]).lower()
            if "recursos propios 2024" in hdr or "recursos propios" in hdr:
                price_start_idx = c
                break

    def format_currency(val):
        try:
            val = str(val).strip()
            if not val or val == "nan":
                return "·"
            num = float(val)
            if num == 0:
                return "$ 0"
            return f"$ {num:,.0f}".replace(",", ".")
        except ValueError:
            return val

    # Cargar datos de ejecución Alertas para este municipio
    alertas_all = load_alertas()
    alertas_data = alertas_all.get(str(dane_code).strip(), {})

    html = open("templates/sispt_viewer.html", encoding="utf-8").read()
    return render_template_string(
        html,
        dane_code=dane_code,
        muni_name=muni_name,
        highlight=highlight,
        df=df,
        mga_col_idx=mga_col_idx,
        product_col_idx=product_col_idx,
        highlighted_rows=highlighted_rows,
        price_start_idx=price_start_idx,
        format_currency=format_currency,
        alertas_data=alertas_data,
    )


if __name__ == "__main__":
    # Crear carpeta templates si no existe
    Path("templates").mkdir(exist_ok=True)
    app.run(debug=True, port=8001)

