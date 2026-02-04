"""
main.py — Sabana Centro Sostenible
Matching Proyectos estratégicos (46) vs SisPT (Plan indicativo - Productos) por municipio.

Estructura esperada:
.
├── Proyectos.xlsx
├── SisPT/
│   ├── 25486.xlsx
│   ├── 25815.xlsx
│   └── ...
└── main.py

Salida:
./salidas/resultados_matching.xlsx

Requisitos:
pip install pandas openpyxl openai python-dotenv rapidfuzz

Uso:
1) export OPENAI_API_KEY="tu_api_key"
2) python main.py
"""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
from rapidfuzz import fuzz
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


# -----------------------------
# Configuración
# -----------------------------
PROJECTS_XLSX = Path("Proyectos.xlsx")
SISPT_DIR = Path("SisPT")
OUTPUT_DIR = Path("salidas")
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_XLSX = OUTPUT_DIR / "resultados_matching.xlsx"

# Control de ejecución
ONLY_DANE: Optional[str] = None      # Procesa todos los municipios
MAX_CANDIDATES_PER_PROJECT = 100     # Aumentado para mayor cobertura semántica (solicitud usuario)
MODEL_NAME = "gpt-4o-mini"          # Cambia si quieres (p.ej. gpt-4.1, gpt-4o-mini). Debe soportar JSON.
TEMPERATURE = 0.2                   # Aumentado ligeramente para mayor flexibilidad en la relación

# Hojas / columnas SisPT
SISPT_SHEET_CANDIDATES = [
    "Plan indicativo - Productos",
    "Plan indicativo - Productos ",
    "Plan indicativo - Productos (1)",
]
COL_MGA_CODE = "Código de indicador de producto (MGA)"
COL_INDICADOR_MGA = "Indicador de Producto(MGA)"
COL_PERSONALIZACION = "Personalización de Indicador de Producto"
COL_DANE = "Código DANE"
COL_MUNICIPIO = "Entidad Territorial"
COL_PLAN_NAME = "Nombre del Plan de Desarrollo"  # puede variar; si no existe, se infiere


# -----------------------------
# Utilidades
# -----------------------------
def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def safe_str(x) -> str:
    if pd.isna(x):
        return ""
    return normalize_spaces(str(x))


def find_sheet_name(xls: pd.ExcelFile) -> str:
    for name in SISPT_SHEET_CANDIDATES:
        if name in xls.sheet_names:
            return name
    # fallback: buscar algo parecido
    for s in xls.sheet_names:
        if "Plan indicativo" in s and "Producto" in s:
            return s
    raise ValueError(f"No encontré la hoja 'Plan indicativo - Productos' en: {xls.sheet_names}")


def load_merged_header_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    """
    SisPT suele tener encabezados con celdas fusionadas.
    Estrategia:
    - Leer sin header
    - Encontrar la fila que contiene COL_PERSONALIZACION (o parte)
    - Usar esa fila como header
    """
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=str)
    
    # En muchos SisPT la fila 0 está vacía o tiene un título decorativo.
    if len(raw) > 0:
        raw = raw.iloc[1:].reset_index(drop=True)

    # Buscar fila header por presencia del nombre de columna clave en las siguientes filas
    header_row_idx = None
    for i in range(min(30, len(raw))):
        row = raw.iloc[i].astype(str).tolist()
        if any(COL_PERSONALIZACION in (c or "") for c in row):
            header_row_idx = i
            break
    
    if header_row_idx is None:
        header_row_idx = 0

    header = [safe_str(c) for c in raw.iloc[header_row_idx].tolist()]
    df = raw.iloc[header_row_idx + 1 :].copy()
    df.columns = header
    return df


def ensure_cols(df: pd.DataFrame, required: List[str], context: str):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en {context}: {missing}. Columnas disponibles: {list(df.columns)[:30]}...")


def extract_dane_and_municipio(df: pd.DataFrame, file_stem: str) -> Tuple[str, str]:
    """
    Intenta extraer DANE y municipio desde columnas si existen (case-insensitive).
    Si no, usa el nombre del archivo como respaldo para DANE.
    """
    dane = ""
    muni = ""

    # Normalizar nombres de columnas para búsqueda insensible a mayúsculas
    cols_map = {c.lower().strip(): c for c in df.columns}
    
    col_dane_real = cols_map.get(COL_DANE.lower())
    col_muni_real = cols_map.get(COL_MUNICIPIO.lower())

    if col_dane_real:
        valid_dane = df[col_dane_real].replace("", pd.NA).dropna()
        if not valid_dane.empty:
            dane = safe_str(valid_dane.iloc[0])
    
    if col_muni_real:
        valid_muni = df[col_muni_real].replace("", pd.NA).dropna()
        if not valid_muni.empty:
            muni = safe_str(valid_muni.iloc[0])

    # Fallbacks: Si no se encontró en las celdas, usar el nombre del archivo
    if not dane or dane == "NA":
        dane = file_stem
    if not muni or muni == "NA":
        muni = file_stem # Usar el DANE como nombre si no hay otro
    
    return dane, muni


def basic_keyword_score(project_text: str, product_text: str) -> int:
    """
    Scoring rápido para filtrar candidatos antes del LLM.
    Combina fuzzy match y coincidencias de tokens.
    """
    p = project_text.lower()
    t = product_text.lower()

    # 1. Fuzzy general (partial ratio)
    f_partial = fuzz.partial_ratio(p, t)
    
    # 2. Token Set Ratio (mejor para palabras en desorden)
    f_set = fuzz.token_set_ratio(p, t)

    # 3. Token overlap (palabras clave exactas)
    tokens_p = set(re.findall(r"[a-záéíóúñ]{3,}", p)) # Solo palabras de >2 letras
    tokens_t = set(re.findall(r"[a-záéíóúñ]{3,}", t))
    overlap = len(tokens_p & tokens_t)

    # Score ponderado: priorizamos el set_ratio y el overlap
    return int(0.3 * f_partial + 0.7 * f_set + 10 * overlap)


# -----------------------------
# Carga de Proyectos
# -----------------------------
@dataclass
class Proyecto:
    id: str
    nombre: str
    objetivo: str
    requerimientos: str
    area: str


def load_projects(path: Path) -> List[Proyecto]:
    df = pd.read_excel(path, dtype=str)
    # Ajusta estos nombres si tu Excel usa otros headers
    # (por lo que has dicho, suelen ser: ID, Proyecto, Objetivo, Requerimiento/s)
    possible_cols = {c.lower(): c for c in df.columns}
    id_col = possible_cols.get("id", None) or possible_cols.get("ID".lower(), None)
    proj_col = possible_cols.get("proyecto", None)
    obj_col = possible_cols.get("objetivo", None)
    req_col = possible_cols.get("requerimiento", None) or possible_cols.get("requerimientos", None)

    if not all([id_col, proj_col, obj_col, req_col]):
        raise ValueError(f"Columnas esperadas no encontradas en Proyectos.xlsx. Columnas: {list(df.columns)}")

    proyectos: List[Proyecto] = []
    for _, r in df.iterrows():
        pid = safe_str(r[id_col])
        if not pid:
            continue
        area = pid.split("-")[0].strip()
        proyectos.append(
            Proyecto(
                id=pid,
                nombre=safe_str(r[proj_col]),
                objetivo=safe_str(r[obj_col]),
                requerimientos=safe_str(r[req_col]),
                area=area,
            )
        )
    return proyectos


# -----------------------------
# Matching con OpenAI
# -----------------------------
def llm_match_project(
    client: OpenAI,
    proyecto: Proyecto,
    municipio: str,
    dane: str,
    candidates: List[Tuple[str, str]],
) -> Dict:
    """
    candidates: list of (codigo_mga, personalizacion_text) ya copiados del SisPT.
    El modelo elige subset (0..n), calificación 0..3, y justificación.
    """
    # Compactar candidatos en formato estricto
    cand_lines = []
    for code, text in candidates:
        cand_lines.append({"codigo_mga": code, "producto": text})

    prompt = {
        "tarea": "Seleccionar productos del plan indicativo SisPT que correspondan al proyecto estratégico.",
        "escala_calificacion": {
            "0": "No existe ningún producto relacionado. El proyecto no cumple ni objetivos ni requerimientos, ni el nombre es similar.",
            "1": "El producto crea condiciones o facilita que se cumpla el objetivo, pero NO tiene el mismo objetivo y NO cumple con los requerimientos.",
            "2": "El producto cumple PARCIALMENTE con el objetivo O cumple PARCIALMENTE con los requerimientos.",
            "3": "El producto cumple con el objetivo Y con casi todos o todos los requerimientos."
        },
        "reglas": [
            "Usa SOLO los candidatos provistos (no inventes códigos).",
            "Si no hay correspondencia que amerite al menos calificación 1, devuelve lista vacía y calificacion 0.",
            "La columna Productos debe ser copia literal de 'Personalización de Indicador de Producto'.",
            "MÁXIMO 5 productos por proyecto. Selecciona solo los más relevantes.",
            "Justificación: 1–2 frases, directa y técnica."
        ],
        "contexto": {
            "municipio": municipio,
            "codigo_dane": dane,
            "documento": "SisPT – Plan indicativo - Productos",
            "proyecto": {
                "id": proyecto.id,
                "nombre": proyecto.nombre,
                "objetivo": proyecto.objetivo,
                "requerimientos": proyecto.requerimientos
            },
            "candidatos": cand_lines,
            "flexible_matching": True
        }
    }

    # Pedimos salida JSON estricta para que sea parseable
    schema = {
        "type": "object",
        "properties": {
            "pensamiento_interno": {
                "type": "string", 
                "description": (
                    "Análisis exhaustivo y razonado. Empieza comparando el 'Objetivo' del proyecto contra el 'Producto'. "
                    "Luego, evalúa si los 'Requerimientos' técnicos se ven reflejados o habilitados por el producto. "
                    "Determina si la relación es directa (misma meta), funcional (el producto es necesario para el proyecto) "
                    "o nula. Explica por qué asignas la calificación específica basada estrictamente en la escala."
                )
            },
            "codigos_mga": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "productos": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "calificacion": {"type": "integer", "enum": [0, 1, 2, 3], "description": "Sigue estrictamente la escala proporcionada."},
            "justificacion": {"type": "string"}
        },
        "required": ["pensamiento_interno", "codigos_mga", "productos", "calificacion", "justificacion"],
        "additionalProperties": False
    }

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": "Devuelve SOLO JSON válido según el esquema.\n" + json.dumps(prompt, ensure_ascii=False)
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "matching_sispt",
                "schema": schema,
                "strict": True
            }
        },
        temperature=TEMPERATURE,
    )

    out_text = resp.choices[0].message.content
    return json.loads(out_text)


# -----------------------------
# Pipeline por municipio
# -----------------------------
def process_municipio_file(
    client: OpenAI,
    proyectos: List[Proyecto],
    path: Path
) -> pd.DataFrame:
    xls = pd.ExcelFile(path)
    sheet = find_sheet_name(xls)
    # ⚠️ Usar la lógica de saltar fila 0 y buscar header
    df = load_merged_header_sheet(path, sheet)

    # Intentar corregir nombres de columnas si vienen con espacios o mayúsculas distintas
    cols_map = {c.lower().strip(): c for c in df.columns}
    col_mga_actual = cols_map.get(COL_MGA_CODE.lower()) or COL_MGA_CODE
    col_ind_actual = cols_map.get(COL_INDICADOR_MGA.lower()) or COL_INDICADOR_MGA
    col_pers_actual = cols_map.get(COL_PERSONALIZACION.lower()) or COL_PERSONALIZACION

    ensure_cols(df, [col_mga_actual, col_ind_actual, col_pers_actual], context=f"{path.name}:{sheet}")

    dane, municipio = extract_dane_and_municipio(df, file_stem=path.stem)
    
    # Construir tabla base de productos SisPT (solo columnas necesarias, copiado literal)
    products_df = df[[col_mga_actual, col_ind_actual, col_pers_actual]].copy()
    products_df[col_mga_actual] = products_df[col_mga_actual].apply(safe_str)
    products_df[col_ind_actual] = products_df[col_ind_actual].apply(safe_str)
    products_df[col_pers_actual] = products_df[col_pers_actual].apply(safe_str)
    products_df = products_df[(products_df[col_mga_actual] != "") & (products_df[col_pers_actual] != "")]

    # Lista de todos los productos disponibles (ahora con 3 campos)
    all_products_list = []
    for _, r in products_df.iterrows():
        all_products_list.append((r[col_mga_actual], r[col_ind_actual], r[col_pers_actual]))

    rows = []
    print(f"--- Procesando municipio: {municipio} ({dane}) ---")
    for i, proj in enumerate(proyectos):
        print(f"[{i+1}/{len(proyectos)}] Analizando proyecto: {proj.nombre}...", end="\r")
        # 1) Filtrado previo: top candidatos por score
        proj_text = normalize_spaces(f"{proj.nombre}. {proj.objetivo}. {proj.requerimientos}")
        scored = []
        for code, ind, text in all_products_list:
            # Comparamos contra el texto de personalización que es el más descriptivo
            s = basic_keyword_score(proj_text, text)
            scored.append((s, code, ind, text))
        
        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:MAX_CANDIDATES_PER_PROJECT]
        
        # Preparamos candidatos para la IA (incluimos el indicador para contexto)
        candidates_for_llm = []
        for _, code, ind, text in top:
            candidates_for_llm.append((code, f"{ind} | {text}")) # Combinamos para que la IA vea ambos

        # 2) Matching LLM (elige subset real + calificación)
        result = llm_match_project(client, proj, municipio, dane, candidates_for_llm)

        # 3) Ensamble
        codigos = [normalize_spaces(c) for c in result["codigos_mga"] if normalize_spaces(c)]
        # Buscamos los textos originales para el reporte final
        prods_final = []
        inds_final = []
        for c_mga in codigos:
            # Buscar en el df original de este municipio
            match_row = products_df[products_df[col_mga_actual] == c_mga]
            if not match_row.empty:
                inds_final.append(safe_str(match_row.iloc[0][col_ind_actual]))
                prods_final.append(safe_str(match_row.iloc[0][col_pers_actual]))

        rows.append({
            "Municipio": municipio,
            "Codigo_DANE": dane,
            "Documento": "SisPT – Plan indicativo - Productos",
            "ID_Proyecto": proj.id,
            "Nombre_Proyecto": proj.nombre,
            "Codigos_MGA": ", ".join(codigos) if codigos else "NA",
            "Indicador de Producto(MGA)": "; ".join(inds_final) if inds_final else "NA",
            "Productos": "; ".join(prods_final) if prods_final else "NA",
            "Calificacion": int(result["calificacion"]),
            "Justificacion": normalize_spaces(result["justificacion"])
        })

    return pd.DataFrame(rows)


def main():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en el entorno.")

    client = OpenAI(api_key=api_key)

    proyectos = load_projects(PROJECTS_XLSX)

    all_results = []
    for f in sorted(SISPT_DIR.glob("*.xlsx")):
        df_muni = process_municipio_file(client, proyectos, f)
        if not df_muni.empty:
            all_results.append(df_muni)

    if not all_results:
        raise RuntimeError("No se generaron resultados. Revisa ONLY_DANE o la carpeta SisPT.")

    out = pd.concat(all_results, ignore_index=True)

    # Guardar Excel con manejo de errores (por si está abierto)
    try:
        with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="matching")
        print(f"Listo. Guardado en: {OUTPUT_XLSX.resolve()}")
    except PermissionError:
        alt_output = OUTPUT_DIR / f"resultados_matching_{int(pd.Timestamp.now().timestamp())}.xlsx"
        with pd.ExcelWriter(alt_output, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="matching")
        print(f"⚠️ No se pudo sobreescribir el archivo original (¿está abierto?).")
        print(f"Guardado alternativo en: {alt_output.resolve()}")


if __name__ == "__main__":
    main()
