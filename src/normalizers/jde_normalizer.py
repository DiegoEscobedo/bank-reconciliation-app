"""
jde_normalizer.py — Normaliza el DataFrame crudo del JDE al schema estándar.

Schema de salida (requerido por DataFrameSchemaValidator):
    account_id      str
    movement_date   datetime64[ns]
    description     str
    amount_signed   float   (+ = dinero entra a la cuenta, − = dinero sale)
    abs_amount      float   (siempre positivo)
    movement_type   str     (DEPOSITO | RETIRO)
    source          str     ("JDE")

Columnas adicionales incluidas en el output:
    doc_type        str     (JL, RC, P3, JO, RO…)
    document        str     (número de documento JDE)
"""

import re
import pandas as pd

from src.utils.date_utils import parse_date_series
from src.utils.amount_utils import clean_amount_series
from src.utils.logger import get_logger

# Patrón: "PI 2238 OUG 355382 7133 28"  → tienda=OUG, tipo_jde=28
# El lote puede tener espacios ("FAB 357 362"), por eso .*
_PI_RE = re.compile(
    r'PI\s+\d+\s+(\w+)\s+.*\s\d{3,}\s+(\d{1,2})\s*$',
    re.IGNORECASE,
)

logger = get_logger(__name__)


class JDENormalizer:
    """
    Convierte el DataFrame crudo producido por JDEParser al schema estándar
    de conciliación.

    Cambio respecto al formato anterior:
        Antes : raw_debit (débito) y raw_credit (crédito) separados.
        Ahora : raw_amount con signo (+ entra / − sale) — columna "Importe" del JDE.
    """

    SOURCE = "JDE"

    def normalize(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Parámetros
        ----------
        raw_df : pd.DataFrame
            DataFrame crudo con columnas:
            account_id | description | doc_type | document | raw_date | raw_amount

        Retorna
        -------
        pd.DataFrame con el schema estándar.
        """
        if raw_df.empty:
            logger.warning("[JDE] DataFrame crudo vacío, no hay movimientos.")
            return self._empty_schema()

        df = raw_df.copy()

        # ── 1. Monto con signo ───────────────────────────────────
        # raw_amount puede ser float (Papel de Trabajo) o string (CSV)
        if pd.api.types.is_numeric_dtype(df["raw_amount"]):
            df["amount_signed"] = df["raw_amount"].astype(float)
        else:
            df["amount_signed"] = clean_amount_series(df["raw_amount"].astype(str))
        df["abs_amount"] = df["amount_signed"].abs()

        # ── 2. Fecha ─────────────────────────────────────────────
        # raw_date puede ser datetime (Papel de Trabajo) o string (CSV)
        if pd.api.types.is_datetime64_any_dtype(df["raw_date"]):
            df["movement_date"] = df["raw_date"]
        else:
            # Convertir strings que pueden venir como repr de datetime
            raw_dates = df["raw_date"].astype(str).str.extract(
                r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})'
            )[0].fillna(df["raw_date"].astype(str))
            df["movement_date"] = parse_date_series(raw_dates)

        # ── 3. Tipo de movimiento (por signo del monto) ───────────
        df["movement_type"] = df["amount_signed"].apply(
            lambda x: "DEPOSITO" if x >= 0 else "RETIRO"
        )

        # ── 4. Campos de texto ────────────────────────────────────
        df["description"] = df["description"].fillna("").str.strip()
        df["doc_type"]    = df["doc_type"].fillna("").str.strip()
        df["document"]    = df["document"].fillna("").str.strip()

        # ── 5. Tienda + tipo_jde ─────────────────────────────────
        # Si el parser ya suministró estos valores (Papel de Trabajo),
        # solo completar los que falten con extracción de descripción.
        if "tienda" not in df.columns:
            df["tienda"] = None
        if "tipo_jde" not in df.columns:
            df["tipo_jde"] = None

        missing_mask = (
            df["tienda"].isna() | (df["tienda"].astype(str).str.strip().isin(["", "nan", "None"]))
        )
        if missing_mask.any():
            parsed = df.loc[missing_mask, "description"].apply(self._extract_tienda_tipo)
            df.loc[missing_mask, "tienda"]   = parsed.apply(lambda x: x[0]).values
            df.loc[missing_mask, "tipo_jde"] = parsed.apply(lambda x: x[1]).values

        # ── 6. Origen ─────────────────────────────────────────────────
        df["source"] = self.SOURCE

        # ── 7. Preservar columnas de write-back (Papel de Trabajo) ─
        for wb_col in ("_aux_fact", "_excel_row", "_pt_file"):
            if wb_col not in df.columns:
                df[wb_col] = None

        # ── 6. account_id como string ─────────────────────────────
        df["account_id"] = df["account_id"].fillna("UNKNOWN").astype(str).str.strip()

        # ── Descartar filas con monto cero o fecha inválida ───────
        before = len(df)
        df = df[df["abs_amount"] > 0].copy()
        df = df[df["movement_date"].notna()].copy()
        after = len(df)

        if before != after:
            logger.debug("[JDE] Descartadas %d filas (monto 0 o fecha inválida).", before - after)

        result = df[[
            "account_id",
            "movement_date",
            "description",
            "doc_type",
            "document",
            "amount_signed",
            "abs_amount",
            "movement_type",
            "source",
            "tienda",
            "tipo_jde",
            "_aux_fact",
            "_excel_row",
            "_pt_file",
        ]].reset_index(drop=True)

        logger.info("[JDE] Movimientos normalizados: %d", len(result))
        return result

    # ────────────────────────────────────────────────────────
    # HELPERS
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_tienda_tipo(description: str):
        """Extrae tienda y tipo_jde de la descripción JDE.

        Ejemplo:
            'Depósito banc | PI 238 OUG 353283 7133 04'  → ('OUG', '04')
            'PI 2268 FAB 357 362 7133 28'               → ('FAB', '28')
            'NOMINA CORR ...'                            → (None, None)
        """
        if not description:
            return (None, None)
        m = _PI_RE.search(description)
        if not m:
            return (None, None)
        tienda   = m.group(1).strip().upper()
        tipo_raw = m.group(2).strip()
        # Sólo aceptar tipos conocidos
        tipo_jde = tipo_raw.zfill(2) if tipo_raw.zfill(2) in ("01", "03", "04", "28") else None
        return (tienda, tipo_jde)

    @staticmethod
    def _empty_schema() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "account_id", "movement_date", "description",
            "doc_type", "document",
            "amount_signed", "abs_amount", "movement_type", "source",
            "tienda", "tipo_jde",
            "_aux_fact", "_excel_row", "_pt_file",
        ])

