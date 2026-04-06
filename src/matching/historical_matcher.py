"""
historical_matcher.py — Cruza los pendientes históricos del archivo de
'Conciliación Bancaria' anterior contra los movimientos del periodo actual.

Lógica:
    Para cada pendiente histórico, busca si ya aparece en el periodo actual
    (ya sea en los movimientos conciliados o en los pendientes actuales).

    Regla de negocio por sección (archivo de conciliación):
        - section='mas'   -> solo lado JDE (conciliado/pending JDE)
        - section='menos' -> solo lado BANCO (conciliado/pending banco)
    No se realiza fallback al lado opuesto para evitar sugerencias cruzadas.

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


def _amount_diff(a: float, b: float) -> float:
    return abs(a - b)


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
    hist_signed: Optional[float],
    candidates: pd.DataFrame,
    date_tol: int = HIST_DATE_TOLERANCE_DAYS,
    amount_tol: float = AMOUNT_TOLERANCE,
    require_same_account: bool = False,
    enforce_same_sign: bool = True,
) -> tuple[bool, Optional[int], float, Optional[int], str, int, bool]:
    """
    Busca la mejor coincidencia en `candidates` para un monto e historial dados.

    Retorna:
      (found, row_index_in_candidates, score, date_diff_days, reason,
       candidates_count, ambiguous)
    """
    if candidates.empty:
        return False, None, 0.0, None, "sin_candidatos", 0, False

    best_idx: Optional[int] = None
    best_score: float = -1.0
    best_date_diff: Optional[int] = None
    best_reason: str = ""
    valid_matches: list[tuple[float, int]] = []

    for idx, row in candidates.iterrows():
        cand_amount = float(row.get("abs_amount", 0) or 0)
        cand_date   = row.get("movement_date")
        cand_account = row.get("account_id")
        cand_signed = row.get("amount_signed")

        account_ok = _account_match(hist_account, cand_account)

        if require_same_account and not account_ok:
            continue

        # Si hay signo en ambos lados, evitar cruzar cargo vs abono.
        if enforce_same_sign and hist_signed is not None and not pd.isnull(cand_signed):
            if float(hist_signed) * float(cand_signed) < 0:
                continue

        if not _amount_match(hist_amount, cand_amount, amount_tol):
            continue

        # Si hay fecha histórica y del candidato, verificar tolerancia
        date_diff = None
        if not pd.isnull(hist_date) and not pd.isnull(cand_date):
            date_diff = _date_diff_days(hist_date, pd.Timestamp(cand_date))
            if date_diff is not None and date_diff > date_tol:
                continue

        # Scoring para sugerencia (no altera conciliación):
        #   - base alta por pasar reglas de monto/fecha
        #   - bonus por cuenta compatible
        #   - penalización por diferencia de fecha y monto
        amt_diff = _amount_diff(hist_amount, cand_amount)
        score = 100.0
        score -= min(40.0, amt_diff * 100.0)  # 1 centavo resta ~1 punto
        if date_diff is not None:
            score -= min(30.0, float(date_diff) * 1.5)
        if account_ok:
            score += 5.0

        reason_parts = [
            f"monto_diff={amt_diff:.2f}",
            f"fecha_diff={date_diff if date_diff is not None else 'NA'}",
            f"cuenta={'SI' if account_ok else 'NO'}",
        ]

        if score > best_score:
            best_idx = idx
            best_score = score
            best_date_diff = date_diff
            best_reason = " | ".join(reason_parts)

        valid_matches.append((score, idx))

    if best_idx is None:
        return False, None, 0.0, None, "sin_match", 0, False

    valid_matches.sort(key=lambda x: x[0], reverse=True)
    candidates_count = len(valid_matches)
    ambiguous = False
    if candidates_count >= 2:
        top1 = valid_matches[0][0]
        top2 = valid_matches[1][0]
        ambiguous = abs(top1 - top2) <= 2.0

    return (
        True,
        best_idx,
        round(best_score, 1),
        best_date_diff,
        best_reason,
        candidates_count,
        ambiguous,
    )


def match_historical_pendientes(
    hist_df: pd.DataFrame,
    conciliated_bank: pd.DataFrame | None = None,
    conciliated_jde:  pd.DataFrame | None = None,
    pending_bank:     pd.DataFrame | None = None,
    pending_jde:      pd.DataFrame | None = None,
    date_tolerance_days: int = HIST_DATE_TOLERANCE_DAYS,
    amount_tolerance:    float = AMOUNT_TOLERANCE,
    require_same_account: bool = False,
    enforce_same_sign: bool = True,
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
        match_source   str  – origen del match sugerido
        match_score    float – confianza relativa (0-100)
        match_reason   str  – criterios usados en la sugerencia
        match_candidates_count int – cantidad de candidatos posibles
        match_ambiguous bool – True si hay empate cercano entre mejores candidatos
    """
    if hist_df.empty:
        return hist_df.assign(
            match_status="AUN_PENDIENTE",
            match_detail="",
            match_date=pd.NaT,
            match_amount=float("nan"),
            match_source="",
            match_score=0.0,
            match_reason="",
            match_candidates_count=0,
            match_ambiguous=False,
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
        h_signed = hist_row.get("amount_signed")
        section = str(hist_row.get("section") or "").strip().lower()
        if not isinstance(h_date, pd.Timestamp):
            h_date = pd.NaT

        status  = "AUN_PENDIENTE"
        detail  = ""
        m_date  = pd.NaT
        m_amount = float("nan")
        m_source = ""
        m_score = 0.0
        m_reason = ""
        m_candidates_count = 0
        m_ambiguous = False

        # Búsqueda por sección (estricta por lado)
        if section == "mas":
            ordered_targets = [
                (cj, "CONCILIADO", "CONCILIADO_JDE"),
                (pj, "PENDIENTE_JDE", "PENDIENTE_JDE"),
            ]
        elif section == "menos":
            ordered_targets = [
                (cb, "CONCILIADO", "CONCILIADO_BANCO"),
                (pb, "PENDIENTE_BANCO", "PENDIENTE_BANCO"),
            ]
        else:
            # Backward-compatible cuando no viene sección
            ordered_targets = [
                (cb, "CONCILIADO", "CONCILIADO_BANCO"),
                (cj, "CONCILIADO", "CONCILIADO_JDE"),
                (pb, "PENDIENTE_BANCO", "PENDIENTE_BANCO"),
                (pj, "PENDIENTE_JDE", "PENDIENTE_JDE"),
            ]

        for target_df, target_status, target_source in ordered_targets:
            if status != "AUN_PENDIENTE":
                break

            found, idx, score, date_diff, reason, cand_count, ambiguous = _find_best_match(
                h_amount,
                h_date,
                h_account,
                h_signed,
                target_df,
                date_tolerance_days,
                amount_tolerance,
                require_same_account,
                enforce_same_sign,
            )
            if found and idx is not None:
                row = target_df.loc[idx]
                status = target_status
                detail = str(row.get("description", ""))[:80]
                m_date = row.get("movement_date", pd.NaT)
                m_amount = float(row.get("abs_amount", float("nan")))
                m_source = target_source
                m_score = score
                m_reason = reason
                m_candidates_count = cand_count
                m_ambiguous = ambiguous

        results.append({
            **hist_row.to_dict(),
            "match_status":  status,
            "match_detail":  detail,
            "match_date":    m_date,
            "match_amount":  m_amount,
            "match_source":  m_source,
            "match_score":   m_score,
            "match_reason":  m_reason,
            "match_candidates_count": m_candidates_count,
            "match_ambiguous": m_ambiguous,
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
