"""
historical_matcher.py — Cruza los pendientes históricos del archivo de
'Conciliación Bancaria' anterior contra los movimientos del periodo actual.

Lógica:
  Para cada pendiente histórico, busca si ya aparece en el periodo actual
  (ya sea en los movimientos conciliados o en los pendientes actuales).

  Secciones del archivo histórico:
    'mas'   → registro que está en banco pero aún no en JDE
    'menos' → registro que está en JDE pero aún no en banco

  Criterio de coincidencia:
    • Monto: |hist - actual| ≤ AMOUNT_TOLERANCE
    • Fecha: |hist - actual| ≤ HIST_DATE_TOLERANCE_DAYS (más amplio, puede ser cualquier mes)
    • (Opcional) Misma cuenta (account_id)

  Estados del resultado:
    'CONCILIADO'        → aparece en los movimientos conciliados del periodo
    'PENDIENTE_BANCO'   → está en pendientes de banco del periodo actual
    'PENDIENTE_JDE'     → está en pendientes de JDE del periodo actual
    'AUN_PENDIENTE'     → no se encontró en el periodo actual (sigue sin conciliar)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import numpy as np

from config.settings import AMOUNT_TOLERANCE

logger = logging.getLogger(__name__)

# Tolerancia de días para cruce histórico (más amplia porque el registro
# puede haber llegado al sistema en un mes diferente al que ocurrió)
HIST_DATE_TOLERANCE_DAYS = 90   # ± 3 meses

# Columnas requeridas en los DataFrames de entrada
_REQUIRED_COLS = {"abs_amount", "movement_date"}


def _safe_df(df: pd.DataFrame | None) -> pd.DataFrame:
    """Retorna df limpio o DataFrame vacío si es None/vacío."""
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def _amount_match(a: float, b: float, tol: float = AMOUNT_TOLERANCE) -> bool:
    return abs(a - b) <= tol


def _date_diff_days(d1: pd.Timestamp, d2: pd.Timestamp) -> Optional[int]:
    """Diferencia en días entre dos timestamps; None si alguno es NaT."""
    if pd.isnull(d1) or pd.isnull(d2):
        return None
    return abs((d1 - d2).days)


def _normalize_account(value: object) -> str:
    """Normaliza cuenta para comparación robusta (trim + sin espacios)."""
    if value is None or pd.isnull(value):
        return ""
    return str(value).strip().replace(" ", "")


def _account_match(hist_account: object, candidate_account: object) -> bool:
    """
    Compara cuentas permitiendo formato largo/corto.
    Ejemplos válidos: '7133' vs '20305077133'.
    """
    h = _normalize_account(hist_account)
    c = _normalize_account(candidate_account)
    if not h or not c:
        return False
    return h == c or h.endswith(c) or c.endswith(h)


def _find_best_match(
    hist_amount: float,
    hist_date: pd.Timestamp,
    hist_account: object,
    candidates: pd.DataFrame,
    date_tol: int = HIST_DATE_TOLERANCE_DAYS,
    amount_tol: float = AMOUNT_TOLERANCE,
    require_same_account: bool = False,
) -> tuple[bool, Optional[int]]:
    """
    Busca la mejor coincidencia en `candidates` para un monto e historial dados.

    Retorna (found, row_index_in_candidates).
    """
    if candidates.empty:
        return False, None

    for idx, row in candidates.iterrows():
        cand_amount = float(row.get("abs_amount", 0) or 0)
        cand_date   = row.get("movement_date")
        cand_account = row.get("account_id")

        if require_same_account and not _account_match(hist_account, cand_account):
            continue

        if not _amount_match(hist_amount, cand_amount, amount_tol):
            continue

        # Si hay fecha histórica y del candidato, verificar tolerancia
        if not pd.isnull(hist_date) and not pd.isnull(cand_date):
            diff = _date_diff_days(hist_date, pd.Timestamp(cand_date))
            if diff is not None and diff > date_tol:
                continue

        return True, idx

    return False, None


def match_historical_pendientes(
    hist_df: pd.DataFrame,
    conciliated_bank: pd.DataFrame | None = None,
    conciliated_jde:  pd.DataFrame | None = None,
    pending_bank:     pd.DataFrame | None = None,
    pending_jde:      pd.DataFrame | None = None,
    date_tolerance_days: int = HIST_DATE_TOLERANCE_DAYS,
    amount_tolerance:    float = AMOUNT_TOLERANCE,
    require_same_account: bool = False,
) -> pd.DataFrame:
    """
    Cruza `hist_df` (pendientes históricos) con los movimientos del período actual.

    Parameters
    ----------
    hist_df : DataFrame con columnas del conciliacion_parser
    conciliated_bank / conciliated_jde : movimientos conciliados del período
    pending_bank / pending_jde          : pendientes del período actual
    date_tolerance_days                 : rango aceptable en días
    amount_tolerance                    : diferencia máxima en pesos
    require_same_account                : si True, exige misma cuenta (con compatibilidad
                                          largo/corto por sufijo)

    Returns
    -------
    DataFrame igual a hist_df más columnas:
        match_status   str  – 'CONCILIADO' | 'PENDIENTE_BANCO' | 'PENDIENTE_JDE' | 'AUN_PENDIENTE'
        match_detail   str  – descripción del movimiento encontrado
        match_date     Timestamp | NaT
        match_amount   float | NaN
    """
    if hist_df.empty:
        return hist_df.assign(
            match_status="AUN_PENDIENTE",
            match_detail="",
            match_date=pd.NaT,
            match_amount=float("nan"),
        )

    cb  = _safe_df(conciliated_bank)
    cj  = _safe_df(conciliated_jde)
    pb  = _safe_df(pending_bank)
    pj  = _safe_df(pending_jde)

    # Normalizar columna abs_amount en todos los candidatos
    for frame in (cb, cj, pb, pj):
        if not frame.empty:
            if "abs_amount" not in frame.columns and "amount_signed" in frame.columns:
                frame["abs_amount"] = frame["amount_signed"].abs()

    results = []

    for _, hist_row in hist_df.iterrows():
        h_amount = float(hist_row.get("abs_amount", 0) or 0)
        h_date   = hist_row.get("movement_date")
        h_account = hist_row.get("account_id")
        if not isinstance(h_date, pd.Timestamp):
            h_date = pd.NaT

        status  = "AUN_PENDIENTE"
        detail  = ""
        m_date  = pd.NaT
        m_amount = float("nan")

        # 1) ¿Ya fue conciliado en el banco este período?
        found, idx = _find_best_match(
            h_amount,
            h_date,
            h_account,
            cb,
            date_tolerance_days,
            amount_tolerance,
            require_same_account,
        )
        if found and idx is not None:
            row = cb.loc[idx]
            status   = "CONCILIADO"
            detail   = str(row.get("description", ""))[:80]
            m_date   = row.get("movement_date", pd.NaT)
            m_amount = float(row.get("abs_amount", float("nan")))

        # 2) ¿Ya fue conciliado en JDE este período?
        if status == "AUN_PENDIENTE":
            found, idx = _find_best_match(
                h_amount,
                h_date,
                h_account,
                cj,
                date_tolerance_days,
                amount_tolerance,
                require_same_account,
            )
            if found and idx is not None:
                row = cj.loc[idx]
                status   = "CONCILIADO"
                detail   = str(row.get("description", ""))[:80]
                m_date   = row.get("movement_date", pd.NaT)
                m_amount = float(row.get("abs_amount", float("nan")))

        # 3) ¿Está pendiente banco este período?
        if status == "AUN_PENDIENTE":
            found, idx = _find_best_match(
                h_amount,
                h_date,
                h_account,
                pb,
                date_tolerance_days,
                amount_tolerance,
                require_same_account,
            )
            if found and idx is not None:
                row = pb.loc[idx]
                status   = "PENDIENTE_BANCO"
                detail   = str(row.get("description", ""))[:80]
                m_date   = row.get("movement_date", pd.NaT)
                m_amount = float(row.get("abs_amount", float("nan")))

        # 4) ¿Está pendiente JDE este período?
        if status == "AUN_PENDIENTE":
            found, idx = _find_best_match(
                h_amount,
                h_date,
                h_account,
                pj,
                date_tolerance_days,
                amount_tolerance,
                require_same_account,
            )
            if found and idx is not None:
                row = pj.loc[idx]
                status   = "PENDIENTE_JDE"
                detail   = str(row.get("description", ""))[:80]
                m_date   = row.get("movement_date", pd.NaT)
                m_amount = float(row.get("abs_amount", float("nan")))

        results.append({
            **hist_row.to_dict(),
            "match_status":  status,
            "match_detail":  detail,
            "match_date":    m_date,
            "match_amount":  m_amount,
        })

    return pd.DataFrame(results)


def summarize_historical_matches(matched_df: pd.DataFrame) -> dict:
    """
    Retorna estadísticas del resultado de match_historical_pendientes.
    """
    if matched_df.empty:
        return {
            "total": 0,
            "conciliado": 0,
            "pendiente_banco": 0,
            "pendiente_jde": 0,
            "aun_pendiente": 0,
            "pct_resuelto": 0.0,
            "monto_resuelto": 0.0,
            "monto_aun_pendiente": 0.0,
        }

    counts = matched_df["match_status"].value_counts().to_dict()
    resul  = matched_df[matched_df["match_status"] != "AUN_PENDIENTE"]
    pendts = matched_df[matched_df["match_status"] == "AUN_PENDIENTE"]
    total  = len(matched_df)

    return {
        "total":             total,
        "conciliado":        counts.get("CONCILIADO", 0),
        "pendiente_banco":   counts.get("PENDIENTE_BANCO", 0),
        "pendiente_jde":     counts.get("PENDIENTE_JDE", 0),
        "aun_pendiente":     counts.get("AUN_PENDIENTE", 0),
        "pct_resuelto":      round(len(resul) / total * 100, 1) if total else 0.0,
        "monto_resuelto":    float(resul["abs_amount"].sum()) if not resul.empty else 0.0,
        "monto_aun_pendiente": float(pendts["abs_amount"].sum()) if not pendts.empty else 0.0,
    }
