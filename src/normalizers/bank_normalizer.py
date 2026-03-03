"""
bank_normalizer.py — Normaliza el DataFrame crudo bancario al schema estándar.

Schema de salida (requerido por DataFrameSchemaValidator):
    account_id      str
    movement_date   datetime64[ns]
    description     str
    amount_signed   float   (+ = depósito / ABONO, − = retiro / CARGO)
    abs_amount      float   (siempre positivo)
    movement_type   str     ("DEPOSITO" | "RETIRO")
    source          str     ("BANK")
"""

import pandas as pd

from src.utils.date_utils import parse_date_series
from src.utils.amount_utils import clean_amount, is_empty_amount
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BankNormalizer:
    """
    Convierte el DataFrame crudo producido por BankParser al schema estándar
    de conciliación.

    Es agnóstico al banco: trabaja con los nombres canónicos que todos los
    sub-parsers de BankParser producen:
        raw_date | description | description_detail | raw_deposit | raw_withdrawal
    """

    SOURCE = "BANK"

    def normalize(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Parámetros
        ----------
        raw_df : pd.DataFrame
            DataFrame crudo con columnas canónicas del BankParser.

        Retorna
        -------
        pd.DataFrame con el schema estándar.
        """
        if raw_df.empty:
            logger.warning("[BANK] DataFrame crudo vacío, no hay movimientos.")
            return self._empty_schema()

        df = raw_df.copy()

        # ── 1. Monto con signo ───────────────────────────────────
        df["amount_signed"] = df.apply(self._compute_signed_amount, axis=1)
        df["abs_amount"]    = df["amount_signed"].abs()

        # ── 2. Fecha ─────────────────────────────────────────────
        df["movement_date"] = parse_date_series(df["raw_date"])

        # ── 3. Tipo de movimiento ─────────────────────────────────
        df["movement_type"] = df.apply(self._classify_movement, axis=1)

        # ── 4. Descripción combinada ──────────────────────────────
        df["description"] = df.apply(self._build_description, axis=1)

        # ── 5. Origen ─────────────────────────────────────────────
        df["source"] = self.SOURCE

        # ── 6. account_id como string ─────────────────────────────
        df["account_id"] = df["account_id"].fillna("UNKNOWN").astype(str).str.strip()

        # ── Descartar filas con monto cero o fecha inválida ───────
        before = len(df)
        df = df[df["abs_amount"] > 0].copy()
        df = df[df["movement_date"].notna()].copy()
        after = len(df)

        if before != after:
            logger.debug("[BANK] Descartadas %d filas (monto 0 o fecha inválida).", before - after)

        base_cols = [
            "account_id",
            "movement_date",
            "description",
            "amount_signed",
            "abs_amount",
            "movement_type",
            "source",
        ]

        # Columnas opcionales del REPORTE (tienda + tipo_banco)
        for extra in ("tienda", "tipo_banco"):
            if extra in df.columns:
                df[extra] = df[extra].fillna("").astype(str).str.strip()
                base_cols.append(extra)

        result = df[base_cols].reset_index(drop=True)

        logger.info("[BANK] Movimientos normalizados: %d", len(result))
        return result

    # ────────────────────────────────────────────────────────
    # HELPERS
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _compute_signed_amount(row) -> float:
        """
        Depósito (raw_deposit)   → positivo  (dinero entra)
        Retiro   (raw_withdrawal)→ negativo  (dinero sale)
        """
        raw_deposit    = row.get("raw_deposit",    "")
        raw_withdrawal = row.get("raw_withdrawal", "")

        deposit_val    = clean_amount(raw_deposit)
        withdrawal_val = clean_amount(raw_withdrawal)

        if deposit_val != 0.0:
            return abs(deposit_val)

        if withdrawal_val != 0.0:
            return -abs(withdrawal_val)

        return 0.0

    @staticmethod
    def _classify_movement(row) -> str:
        raw_deposit    = row.get("raw_deposit",    "")
        raw_withdrawal = row.get("raw_withdrawal", "")

        amount_signed = row.get("amount_signed", 0.0)

        if amount_signed > 0:
            return "DEPOSITO"
        if amount_signed < 0:
            return "RETIRO"

        # Por si clean_amount ya corrió antes
        if not is_empty_amount(raw_deposit) and clean_amount(raw_deposit) != 0:
            return "DEPOSITO"
        if not is_empty_amount(raw_withdrawal) and clean_amount(raw_withdrawal) != 0:
            return "RETIRO"

        return "DESCONOCIDO"

    @staticmethod
    def _build_description(row) -> str:
        """
        Combina descripción principal + detallada para tener más contexto
        al momento de la conciliación manual.
        """
        desc   = str(row.get("description",        "")).strip()
        detail = str(row.get("description_detail", "")).strip()

        if detail and detail.lower() not in ("nan", "none", "-", ""):
            return f"{desc} | {detail}" if desc else detail

        return desc

    @staticmethod
    def _empty_schema() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "account_id", "movement_date", "description",
            "amount_signed", "abs_amount", "movement_type", "source",
        ])
