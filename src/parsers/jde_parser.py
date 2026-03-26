"""
jde_parser.py — Parser para archivos CSV/Excel exportados del JDE.

Soporta dos formatos:
1. CSV Auxiliar de Contabilidad (R550911A1) — formato original
2. Excel "Papel de Trabajo" — libro de control continuo con columnas
   CONCILIADO y FECHA CONCILIACION; solo carga filas no conciliadas.
"""

import re
from datetime import datetime

import pandas as pd

from config.settings import TIENDA_ABBREV as _TIENDA_ABBREV
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Índices de columna para CSV R550911A1 (0-based, header en fila 2) ────────
_IDX_ACCOUNT_DESC = 9    # "CUENTA 6614"
_IDX_DOC_TYPE     = 12   # Tp doc
_IDX_DOCUMENT     = 13   # Número documento
_IDX_DATE         = 14   # Fecha LM
_IDX_AMOUNT       = 16   # Importe (ya con signo)
_IDX_DESC_MAIN    = 21   # Nombre alfa explicación
_IDX_DESC_DETAIL  = 22   # Explicación -observación-

_MIN_COLS = 23

_CUENTA_RE = re.compile(r"CUENTA\s+(\d+)", re.IGNORECASE)


# ════════════════════════════════════════════════════════════
# PARSER ORIGINAL — CSV R550911A1
# ════════════════════════════════════════════════════════════

class JDEParser:
    """
    Parsea archivos CSV del JDE (R550911A1) y retorna un DataFrame crudo.
    Para Excel tipo Papel de Trabajo usa PapelTrabajoParser directamente.
    """

    _HEADER_ROW = 2

    def parse(self, file_path: str) -> pd.DataFrame:
        logger.info("Parseando JDE: %s", file_path)

        # Auto-detectar Papel de Trabajo Excel
        if str(file_path).lower().endswith((".xlsx", ".xls")):
            logger.info("Archivo Excel detectado — usando PapelTrabajoParser")
            return PapelTrabajoParser().parse(file_path)

        df = self._read_csv(file_path)
        df = self._filter_data_rows(df)
        df = self._build_output(df)

        logger.info(
            "JDE: %d movimientos en %d cuenta(s): %s",
            len(df),
            df["account_id"].nunique(),
            sorted(df["account_id"].unique()),
        )
        return df

    def _read_csv(self, file_path: str) -> pd.DataFrame:
        for encoding in ("utf-8-sig", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(
                    file_path,
                    skiprows=self._HEADER_ROW,
                    header=0,
                    encoding=encoding,
                    dtype=str,
                    on_bad_lines="skip",
                )
                if df.shape[1] < _MIN_COLS:
                    raise ValueError(
                        f"Se esperaban ≥{_MIN_COLS} columnas, se encontraron "
                        f"{df.shape[1]}. Verifica que sea el reporte R550911A1."
                    )
                return df
            except UnicodeDecodeError:
                continue
        raise ValueError(f"No se pudo leer el archivo JDE: {file_path}")

    @staticmethod
    def _filter_data_rows(df: pd.DataFrame) -> pd.DataFrame:
        doc_type_col = df.iloc[:, _IDX_DOC_TYPE].astype(str).str.strip()
        date_col     = df.iloc[:, _IDX_DATE].astype(str).str.strip()
        mask = (
            doc_type_col.ne("") & doc_type_col.ne("nan") &
            date_col.ne("") & date_col.ne("nan")
        )
        return df[mask].copy()

    def _build_output(self, df: pd.DataFrame) -> pd.DataFrame:
        account_names = df.iloc[:, _IDX_ACCOUNT_DESC].astype(str).str.strip()
        doc_types     = df.iloc[:, _IDX_DOC_TYPE].astype(str).str.strip()
        documents     = df.iloc[:, _IDX_DOCUMENT].astype(str).str.strip()
        dates         = df.iloc[:, _IDX_DATE].astype(str).str.strip()
        amounts       = df.iloc[:, _IDX_AMOUNT].astype(str).str.strip()
        desc_main     = df.iloc[:, _IDX_DESC_MAIN].astype(str).str.strip()
        desc_detail   = df.iloc[:, _IDX_DESC_DETAIL].astype(str).str.strip()

        account_ids  = account_names.apply(self._extract_account)
        descriptions = (desc_main + " | " + desc_detail).str.strip(" |")

        result = pd.DataFrame({
            "account_id":  account_ids,
            "description": descriptions,
            "doc_type":    doc_types,
            "document":    documents,
            "raw_date":    dates,
            "raw_amount":  amounts,
        })

        result = result[result["account_id"].ne("") & result["account_id"].notna()]
        return result.reset_index(drop=True)

    @staticmethod
    def _extract_account(account_name: str) -> str:
        m = _CUENTA_RE.search(account_name)
        return m.group(1) if m else ""


# ════════════════════════════════════════════════════════════
# PARSER PAPEL DE TRABAJO — Excel de control continuo
# ════════════════════════════════════════════════════════════

class PapelTrabajoParser:
    """
    Lee el Papel de Trabajo (.xlsx) y retorna solo las filas
    NO conciliadas (columna CONCILIADO vacía).

    Columnas del schema de salida (mismas que JDEParser +  extras):
        account_id | description | doc_type | document | raw_date | raw_amount
        tienda     | tipo_jde    | _aux_fact | _excel_row | _pt_file_path
    """

    # Nombres de hoja preferidos (en orden)
    _SHEET_PRIORITY = ["AUX CONTABLE", "Detalle1"]

    # Mapeo FORMA DE PAGO (int/str) → tipo_jde
    _FORMA_PAGO_MAP = {
        "1": "01", "01": "01",
        "3": "03", "03": "03",
        "4": "04", "04": "04",
        "28": "28",
    }

    def parse(self, file_path: str) -> pd.DataFrame:
        logger.info("[PapelTrabajo] Leyendo: %s", file_path)
        df, header_idx = self._read_sheet(file_path)
        result = self._build_output(df, file_path)
        logger.info(
            "[PapelTrabajo] %d movimientos pendientes en %d cuenta(s): %s",
            len(result),
            result["account_id"].nunique() if not result.empty else 0,
            sorted(result["account_id"].unique()) if not result.empty else [],
        )
        return result

    # ─────────────────────────────────────────────────────────
    # Lectura
    # ─────────────────────────────────────────────────────────

    def _read_sheet(self, file_path: str):
        xl = pd.ExcelFile(file_path)

        for sheet in self._SHEET_PRIORITY:
            if sheet in xl.sheet_names:
                raw = pd.read_excel(
                    xl, sheet_name=sheet, header=None, dtype=str
                ).fillna("")
                
                # Validar que el sheet no esté vacío
                if raw.empty:
                    logger.warning("[PapelTrabajo] Hoja '%s' vacía, saltando", sheet)
                    continue
                
                header_idx = self._find_header_row(raw)
                
                # Validar que se encontró la fila header y que existe en el DataFrame
                if header_idx == -1:
                    logger.warning(
                        "[PapelTrabajo] Hoja '%s' — no tiene estructura esperada (falta 'Aux_Fact' + 'Importe'), saltando",
                        sheet
                    )
                    continue
                
                if header_idx >= len(raw):
                    logger.warning(
                        "[PapelTrabajo] Hoja '%s' — header_idx=%d fuera de rango (rows=%d), saltando",
                        sheet, header_idx, len(raw)
                    )
                    continue
                
                headers = [str(v).strip() for v in raw.iloc[header_idx].values]
                df = raw.iloc[header_idx + 1:].copy().reset_index(drop=True)
                df.columns = headers
                # _excel_row: número de fila real en el Excel (1-based) para write-back
                df["_excel_row"] = range(header_idx + 2, header_idx + 2 + len(df))
                logger.info("[PapelTrabajo] Hoja '%s' — header en fila %d, %d filas de datos",
                            sheet, header_idx + 1, len(df))
                return df, header_idx

        raise ValueError(
            f"No se encontró ninguna de las hojas {self._SHEET_PRIORITY} en: {file_path}"
        )

    @staticmethod
    def _find_header_row(raw: pd.DataFrame) -> int:
        """Busca la fila que contiene 'Aux_Fact' + 'Importe'.
        Retorna el índice de la fila encontrada, o -1 si no existe."""
        for i, row in raw.iterrows():
            vals = [str(v).strip() for v in row.values]
            if "Aux_Fact" in vals and "Importe" in vals:
                return i
        logger.warning("[PapelTrabajo] No se encontró fila con 'Aux_Fact' + 'Importe'")
        return -1

    # ─────────────────────────────────────────────────────────
    # Construcción de output
    # ─────────────────────────────────────────────────────────

    def _build_output(self, df: pd.DataFrame, file_path: str) -> pd.DataFrame:

        def get_col(*candidates):
            for c in df.columns:
                if c.strip() in {x.strip() for x in candidates}:
                    return c
            return None

        col_aux     = get_col("Aux_Fact")
        col_account = get_col("Descripción", "Descripcion")
        col_doctype = get_col("Tp doc")
        col_docnum  = get_col("Número documento", "Numero documento")
        col_date    = get_col("Fecha LM")
        col_amount  = get_col("Importe")
        col_desc    = get_col("Explicación -observación-", "Explicacion -observacion-")
        col_desc2   = get_col("Nombre alfa explicación", "Nombre alfa explicacion")
        col_tipo    = get_col("FORMA DE PAGO")
        col_tienda  = get_col("TIENDA")
        col_conc    = get_col("CONCILIADO")
        col_row     = "_excel_row"

        def s(col):
            return df[col].astype(str).str.strip() if col else pd.Series("", index=df.index)

        # ── Filtrar solo pendientes ──────────────────────────
        if col_conc:
            pending_mask = s(col_conc).isin(["", "nan", "None", "NaT"])
            df = df[pending_mask].copy().reset_index(drop=True)

        if df.empty:
            return self._empty_schema()

        # ── account_id ──────────────────────────────────────
        account_ids = s(col_account).apply(self._extract_account)
        
        # Log detallado: mostrar extracción de accounts
        account_distribution = account_ids.value_counts()
        logger.info(
            "[PapelTrabajo] account_id extracción: %s",
            dict(account_distribution) if not account_distribution.empty else "SIN CUENTAS EXTRAÍDAS"
        )
        
        # Verificar si hay filas sin account_id
        if (account_ids.eq("") | account_ids.isna()).any():
            bad_rows = s(col_account)[account_ids.eq("") | account_ids.isna()]
            logger.warning(
                "[PapelTrabajo] %d filas sin account_id extraído. Ejemplos: %s",
                len(bad_rows), list(bad_rows.iloc[:3]) if len(bad_rows) > 0 else []
            )

        # ── description ─────────────────────────────────────
        desc_det = s(col_desc)
        desc_alt = s(col_desc2)
        description = desc_det.where(
            desc_det.ne("") & desc_det.ne("nan"), desc_alt
        )

        # ── tipo_jde ────────────────────────────────────────
        tipo_jde = s(col_tipo).apply(
            lambda v: self._FORMA_PAGO_MAP.get(
                str(int(float(v))) if v.replace(".", "", 1).isdigit() else v,
                None
            ) if v not in ("", "nan") else None
        )

        # ── tienda (full name → abreviatura) ─────────────────
        tienda = s(col_tienda).apply(
            lambda v: _TIENDA_ABBREV.get(v.upper().strip(), v.upper().strip() or None)
            if v.strip() not in ("", "nan", "NO ENCONTRADO") else None
        )

        # ── raw_date: puede venir como datetime string ────────
        raw_date = s(col_date)

        # ── raw_amount ───────────────────────────────────────
        raw_amount = s(col_amount)

        result = pd.DataFrame({
            "_aux_fact":    s(col_aux),
            "_excel_row":   df[col_row] if col_row in df.columns else pd.Series(None, index=df.index),
            "_pt_file":     str(file_path),
            "account_id":   account_ids,
            "description":  description,
            "doc_type":     s(col_doctype),
            "document":     s(col_docnum),
            "raw_date":     raw_date,
            "raw_amount":   raw_amount,
            "tienda":       tienda,
            "tipo_jde":     tipo_jde,
        })

        # Filtrar filas sin cuenta o sin fecha
        result = result[
            result["account_id"].ne("") &
            result["raw_date"].ne("") &
            result["raw_date"].ne("nan")
        ].copy()

        return result.reset_index(drop=True)

    # ─────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_account(account_name: str) -> str:
        m = _CUENTA_RE.search(account_name)
        return m.group(1) if m else ""

    @staticmethod
    def _empty_schema() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "_aux_fact", "_excel_row", "_pt_file",
            "account_id", "description", "doc_type", "document",
            "raw_date", "raw_amount", "tienda", "tipo_jde",
        ])
