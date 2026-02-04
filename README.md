
Contiene:
- ID del proyecto (ej. `1-1`)
- Nombre exacto del proyecto
- Objetivo
- Requerimientos

Regla:
- El **primer número del ID define el área temática**.

---

### 4.2 SisPT por municipio (entrada)

Carpeta:

SisPT/
├── 25486.xlsx
├── 25815.xlsx
└── ...


Cada archivo corresponde a **un municipio** y debe incluir la hoja:

Columnas críticas:
- `Código de indicador de producto (MGA)`
- `Personalización de Indicador de Producto`
- `Código DANE`
- `Entidad Territorial`

🚫 No usar códigos IP, sectores ni programas como proxy.  
✅ Usar **exclusivamente** códigos de producto MGA.

---

## 5. Proceso de Matching (Pipeline Lógico)

El sistema utiliza un proceso híbrido de dos fases para garantizar precisión y escalabilidad:

### Fase 1: Scoring Técnico (Filtrado)
Para cada municipio y cada proyecto estratégico, el sistema selecciona los **100 productos más prometedores** del SisPT:
1. **Fuzzy Matching**: Se evalúa la similitud textual ignorando el orden de las palabras (`token_set_ratio`).
2. **Coincidencia de Tokens**: Se cuentan palabras clave compartidas de más de 3 letras.
3. **Selección**: Solo los 100 con mayor puntaje pasan a la siguiente fase.

### Fase 2: Análisis Semántico por IA (LLM)
La IA recibe el proyecto y los 100 candidatos. Realiza los siguientes pasos:
1. **Pensamiento Interno**: Un análisis profundo donde contrasta el objetivo del proyecto contra el producto y evalúa si los requerimientos técnicos se ven reflejados. Clasifica la relación como directa, funcional o nula.
2. **Selección Final**: Elige un máximo de **5 productos** por proyecto.
3. **Calificación**: Asigna un valor de **0 a 3** basado estrictamente en la escala definida abajo.
4. **Justificación**: Redacta una justificación técnica de 1-2 frases.

---

## 6. Escala de calificación (OBLIGATORIA)

| Valor | Significado |
|------|------------|
| 0 | No existe ningún producto relacionado |
| 1 | Producto crea condiciones generales, pero no cumple objetivo ni requerimientos |
| 2 | Producto cumple parcialmente el objetivo o algunos requerimientos |
| 3 | Producto cumple casi totalmente el objetivo y la mayoría de requerimientos |

⚠️ Regla dura:  
Sin producto MGA → **no puede haber calificación mayor a 0**.

---

## 7. Estructura del dataset de salida

El sistema genera un archivo Excel en `salidas/resultados_matching.xlsx` con las siguientes columnas:

| Columna | Descripción |
|-------|------------|
| Municipio | Nombre del municipio (extraído de columna "Entidad territorial") |
| Codigo_DANE | Código DANE (extraído de columna "Código DANE") |
| Documento | Siempre: `SisPT – Plan indicativo - Productos` |
| ID_Proyecto | ID del proyecto estratégico (ej. 1-1, 3-3) |
| Nombre_Proyecto | Nombre exacto del proyecto |
| Codigos_MGA | Lista de códigos MGA seleccionados |
| Indicador de Producto(MGA) | Texto literal del indicador asociado al código MGA |
| Productos | Texto literal de “Personalización de Indicador de Producto” |
| Calificacion | Entero de 0 a 3 |
| Justificacion | 1–2 frases, técnicas y concisas |

🚫 No resumir ni reinterpretar nombres de productos.  
✅ Copiar literal desde SisPT.

---

## 8. Qué NO debe hacer ningún agente

- ❌ Inventar productos, códigos o nombres.
- ❌ Usar PDFs del Plan de Desarrollo.
- ❌ Usar sectores, programas o códigos IP como sustituto.
- ❌ Inflar calificaciones por lenguaje genérico.
- ❌ Escribir justificaciones largas o narrativas.

## 9. Estructura del proyecto

SCS_V2/
├── main.py
├── Proyectos.xlsx
├── SisPT/
│   ├── 25486.xlsx
│   ├── 25815.xlsx
│   └── ...
├── .env
└── salidas/
    └── resultados_matching.xlsx
└── README.md


---

## 10. Estado actual del proyecto

- Metodología validada manualmente (Áreas 1 a 6).
- Piloto exitoso con municipio Nemocón.
- Pipeline diseñado para escalar a todos los municipios.
- Dataset final reproducible y comparable.

---

## 11. Próximos pasos esperados

- Automatización completa municipio × 46 proyectos.
- Caché de resultados del modelo.
- Análisis comparativo intermunicipal.
- Visualización y reporting.

---

**Este README funciona como contrato metodológico.  
Cualquier agente que trabaje en este proyecto debe seguirlo estrictamente.**
