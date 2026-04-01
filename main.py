"""
main.py — Orquestador de la capa lógica de conciliación bancaria.

Flujo:
    parsers → normalizers → validator → engine → reporter

Uso CLI:
    python main.py --bank  data/raw/bank/estado_cuenta.xlsx
                   --jde   data/raw/jde/movimientos_jde.xlsx
                   --output data/output/reconciliations/
"""

import argparse
import sys
from pathlib import Path

from src.parsers.bank_parser import BankParser
from src.parsers.jde_parser import JDEParser
from src.normalizers.bank_normalizer import BankNormalizer
from src.normalizers.jde_normalizer import JDENormalizer
from src.validacion.schema_validator import DataFrameSchemaValidator, SchemaValidationError
from src.matching.reconciliation_engine import ReconciliationEngine
from src.reporting.excel_reporter import ExcelReporter
from src.utils.logger import get_logger
from src.utils.amount_utils import clean_amount
from config.settings import (
    DATE_TOLERANCE_DAYS as _DATE_TOLERANCE_DAYS,
    PAPEL_TRABAJO_ACCOUNTS as _PAPEL_TRABAJO_ACCOUNTS,
)

logger = get_logger(__name__)


# ============================================================
# PERFIL DE CONCILIACION POR CUENTA
# ============================================================

def _normalize_account_token(value: object) -> str:
    return str(value or "").strip().replace(" ", "")


def _account_set_has_suffix(accounts: set[str], suffix: str) -> bool:
    for acct in accounts:
        a = _normalize_account_token(acct)
        if a == suffix or a.endswith(suffix):
            return True
    return False


def _configure_engine_for_accounts(engine: ReconciliationEngine, bank_accounts: set[str]) -> str:
    """
    Ajusta el perfil del motor por cuenta bancaria.
    Reglas solicitadas: los cambios de optimizacion/reglas estrictas de hoy
    aplican SOLO para la cuenta 6614.
    """
    has_6614 = _account_set_has_suffix(bank_accounts, "6614")

    if has_6614:
        # Modo rapido: reduce espacio combinatorio para respuesta mas agil.
        engine.grouped_candidate_limit = 12
        mode = "6614-rapido"
    else:
        mode = "default"

    logger.info(
        "[ENGINE-MODE] cuentas=%s | modo=%s | grouped_candidate_limit=%d | max_group_size=%d",
        sorted(bank_accounts), mode, engine.grouped_candidate_limit, engine.maximum_group_size,
    )
    return mode


# ============================================================
# HELPER: Determinar si usar Papel de Trabajo
# ============================================================

def _is_papel_trabajo_account(bank_accounts: set, jde_file_path: str) -> bool:
    """
    Determina si se debe usar la modalidad "Papel de Trabajo" (Excel + write-back).
    
    Requirements:
    1. El archivo JDE debe ser Excel (.xlsx o .xls)
    2. La cuenta bancaria debe estar en PAPEL_TRABAJO_ACCOUNTS (ej: 6614, 7133)
    
    Para otras cuentas (ej: 3478 Banorte), se aceptan archivos CSV normales
    del JDE sin write-back del Papel de Trabajo.
    """
    # Verificar si es archivo Excel
    is_excel = str(jde_file_path).lower().endswith((".xlsx", ".xls"))
    if not is_excel:
        return False
    
    # Verificar si alguna cuenta está en la lista de cuentas con Papel de Trabajo
    # Soportar cuentas con prefijo (ej: '20305077133') o sin (ej: '7133')
    for account in bank_accounts:
        account_str = str(account).strip()
        # Intentar match directo
        if account_str in _PAPEL_TRABAJO_ACCOUNTS:
            return True
        # Si no, intentar comparar últimos 4 dígitos (ej: '20305077133' termina con '7133')
        if len(account_str) > 4:
            short_account = account_str[-4:]
            if short_account in _PAPEL_TRABAJO_ACCOUNTS:
                return True
    
    return False


# ============================================================
# ENRIQUECIMIENTO BANCO ← REPORTE CAJA
# ============================================================

def _enrich_bank_with_reporte(bank_df, reporte_df):
    """
    Añade las columnas ``tienda`` y ``tipo_banco`` al DataFrame bancario
    haciendo un join por fecha + monto exacto contra el REPORTE CAJA.

    El banco puede tener movimientos que no aparecen en el reporte
    (traspasos, nóminas, etc.); esos quedan con tienda=None y siguen
    pasando al motor con la lógica normal de monto.
    """
    import pandas as _pd

    if reporte_df.empty or "tienda" not in reporte_df.columns:
        return bank_df

    bank = bank_df.copy().reset_index(drop=True)
    rep = reporte_df[["movement_date", "tienda", "tipo_banco"]].copy()

    # Usar monto con signo para evitar cruces falso-positivo (+15 vs -15).
    if "amount_signed" in reporte_df.columns:
        rep["_signed_key"] = reporte_df["amount_signed"].round(2)
    elif "abs_amount" in reporte_df.columns:
        rep["_signed_key"] = reporte_df["abs_amount"].round(2)
    else:
        return bank_df

    if "amount_signed" in bank.columns:
        bank["_signed_key"] = bank["amount_signed"].round(2)
    elif "abs_amount" in bank.columns:
        bank["_signed_key"] = bank["abs_amount"].round(2)
    else:
        return bank_df

    rep = rep.dropna(subset=["_signed_key"]).copy()
    rep["_date_key"] = reporte_df["movement_date"].dt.date
    bank["_date_key"] = bank["movement_date"].dt.date

    # Índice de candidatos por monto con signo, consumibles 1 a 1.
    available_by_amount: dict = {}
    for rep_idx, rep_row in rep.iterrows():
        amt_key = rep_row["_signed_key"]
        available_by_amount.setdefault(amt_key, []).append(rep_idx)

    matched_rep_tienda = _pd.Series([None] * len(bank), dtype="object")
    matched_rep_tipo = _pd.Series([None] * len(bank), dtype="object")
    used_rep_indices: set[int] = set()

    for bank_idx, bank_row in bank.iterrows():
        amt_key = bank_row["_signed_key"]
        date_key = bank_row["_date_key"]
        candidates = available_by_amount.get(amt_key)
        if not candidates:
            continue

        eligible = []
        for rep_idx in candidates:
            if rep_idx in used_rep_indices:
                continue
            rep_date = rep.at[rep_idx, "_date_key"]
            day_diff = abs((date_key - rep_date).days)
            if day_diff <= _DATE_TOLERANCE_DAYS:
                eligible.append((day_diff, rep_idx))

        if not eligible:
            continue

        # Elegir el más cercano en fecha para reducir cruces ambiguos.
        eligible.sort(key=lambda x: (x[0], x[1]))
        chosen_rep_idx = eligible[0][1]
        used_rep_indices.add(chosen_rep_idx)
        rep_match = rep.loc[chosen_rep_idx]
        matched_rep_tienda.iloc[bank_idx] = rep_match.get("tienda")
        matched_rep_tipo.iloc[bank_idx] = rep_match.get("tipo_banco")

    # Si bank_df ya tenía tienda/tipo, conservar salvo cuando está vacío.
    if "tienda" not in bank.columns:
        bank["tienda"] = matched_rep_tienda
    else:
        tienda_base = bank["tienda"].fillna("").astype(str).str.strip()
        bank["tienda"] = bank["tienda"].where(tienda_base != "", matched_rep_tienda)

    if "tipo_banco" not in bank.columns:
        bank["tipo_banco"] = matched_rep_tipo
    else:
        tipo_base = bank["tipo_banco"].fillna("").astype(str).str.strip()
        bank["tipo_banco"] = bank["tipo_banco"].where(tipo_base != "", matched_rep_tipo)

    matches = int(matched_rep_tienda.notna().sum() + matched_rep_tipo.notna().sum())
    logger.debug(f"[ENRICH] Matches 1:1 aplicados: {matches}/{len(bank)}")

    drop_cols = ["_signed_key", "_date_key"]
    bank = bank.drop(columns=[c for c in drop_cols if c in bank.columns])
    return bank.reset_index(drop=True)


# ============================================================
# PIPELINE PRINCIPAL (importable desde Streamlit)
# ============================================================

# ============================================================
# PREPARACIÓN DE DATAFRAMES (compartido por todas las variantes del pipeline)
# ============================================================

def _prepare_dataframes(bank_file_path, jde_file_path):
    """
    Parsea, normaliza, enriquece y valida los archivos de entrada.
    Devuelve (bank_df, jde_df) listos para el motor de conciliación.
    """
    import pandas as _pd

    mp_color_filter_debug = {
        "enabled": False,
        "scotiabank_amounts_count": 0,
        "scotiabank_amounts_sample": [],
        "total_mp_rows_before": 0,
        "total_mp_rows_after": 0,
        "eligible_colors": [],
        "colors": [],
    }

    if isinstance(bank_file_path, (str, Path)):
        bank_file_paths = [bank_file_path]
    else:
        bank_file_paths = list(bank_file_path)

    bank_dfs_raw       = []
    reporte_caja_dfs   = []

    for bp in bank_file_paths:
        logger.info("Parseando archivo bancario: %s", bp)
        raw = BankParser().parse(str(bp))
        bank_name = raw["bank"].iloc[0] if ("bank" in raw.columns and not raw.empty) else ""
        if bank_name == "REPORTE_CAJA":
            reporte_caja_dfs.append(raw)
        else:
            bank_dfs_raw.append(raw)

    # ── Filtro MercadoPago por grupos de color presentes en Scotiabank ─────
    # Mantiene el matching igual, pero reduce qué registros MP entran al motor:
    # solo los colores cuyo total (suma por color) exista en montos del banco.
    mp_raw_dfs = []
    scotia_amounts = set()
    for raw_df in bank_dfs_raw:
        if raw_df.empty or "bank" not in raw_df.columns:
            continue
        bname = str(raw_df["bank"].iloc[0]).strip().upper()
        if bname == "MERCADOPAGO":
            mp_raw_dfs.append(raw_df)
        elif bname == "SCOTIABANK":
            if "raw_deposit" in raw_df.columns:
                for v in raw_df["raw_deposit"].fillna(""):
                    amt = round(clean_amount(v), 2)
                    if amt > 0:
                        scotia_amounts.add(amt)

    if mp_raw_dfs and scotia_amounts:
        mp_color_filter_debug["enabled"] = True
        mp_color_filter_debug["scotiabank_amounts_count"] = len(scotia_amounts)
        mp_color_filter_debug["scotiabank_amounts_sample"] = sorted(scotia_amounts)[:25]
        filtered_bank_dfs_raw = []
        total_mp_before = 0
        total_mp_after = 0
        logger.info(
            "[MP-COLOR-FILTER] Montos Scotiabank detectados (muestra hasta 25): %s",
            sorted(scotia_amounts)[:25],
        )

        for raw_df in bank_dfs_raw:
            if raw_df.empty or "bank" not in raw_df.columns:
                filtered_bank_dfs_raw.append(raw_df)
                continue

            bname = str(raw_df["bank"].iloc[0]).strip().upper()
            if bname != "MERCADOPAGO" or "cell_color" not in raw_df.columns:
                filtered_bank_dfs_raw.append(raw_df)
                continue

            mp = raw_df.copy()
            total_mp_before += len(mp)

            mp["_color_key"] = mp["cell_color"].fillna("").astype(str).str.strip().str.upper()
            # Para filtro de grupos por banco usamos TOTAL A RECIBIR (depósito neto).
            # El match con JDE sigue usando COBRO (raw_deposit) dentro del pipeline.
            if "raw_total_recibir" in mp.columns:
                mp["_amount_num"] = mp["raw_total_recibir"].fillna("").apply(clean_amount)
            else:
                mp["_amount_num"] = mp["raw_deposit"].fillna("").apply(clean_amount)
            mp = mp[mp["_amount_num"] > 0].copy()

            color_sums = (
                mp.groupby("_color_key", dropna=False)["_amount_num"]
                .sum()
                .round(2)
            )

            # Logging detallado por color: suma y si hace match contra Scotiabank
            for color, total in color_sums.items():
                if not color:
                    continue
                row_count = int((mp["_color_key"] == color).sum())
                has_match = total in scotia_amounts
                mp_color_filter_debug["colors"].append({
                    "color": color,
                    "rows": row_count,
                    "total": float(total),
                    "match_scotiabank": bool(has_match),
                })
                logger.info(
                    "[MP-COLOR-FILTER] color=%s | filas=%d | total=%.2f | match_scotiabank=%s",
                    color,
                    row_count,
                    total,
                    "SI" if has_match else "NO",
                )

            eligible_colors = {
                color for color, total in color_sums.items()
                if color and total in scotia_amounts
            }

            mp_filtered = mp[mp["_color_key"].isin(eligible_colors)].copy()
            total_mp_after += len(mp_filtered)

            logger.info(
                "[MP-COLOR-FILTER] filas MP %d -> %d | colores elegibles=%d | montos Scotiabank=%d",
                len(raw_df), len(mp_filtered), len(eligible_colors), len(scotia_amounts),
            )
            logger.info(
                "[MP-COLOR-FILTER] colores elegibles: %s",
                sorted(eligible_colors),
            )
            mp_color_filter_debug["eligible_colors"] = sorted(
                set(mp_color_filter_debug["eligible_colors"]) | set(eligible_colors)
            )

            mp_filtered = mp_filtered.drop(columns=["_color_key", "_amount_num"], errors="ignore")
            filtered_bank_dfs_raw.append(mp_filtered)

        bank_dfs_raw = filtered_bank_dfs_raw
        logger.info(
            "[MP-COLOR-FILTER] total filas MercadoPago consideradas: %d -> %d",
            total_mp_before, total_mp_after,
        )
        mp_color_filter_debug["total_mp_rows_before"] = int(total_mp_before)
        mp_color_filter_debug["total_mp_rows_after"] = int(total_mp_after)
    elif mp_raw_dfs:
        logger.info(
            "[MP-COLOR-FILTER] Se detectó MercadoPago pero no Scotiabank; no se aplicó filtro por total de color."
        )

    logger.info("Parseando archivo JDE: %s", jde_file_path)
    jde_raw_df = JDEParser().parse(jde_file_path)

    logger.info("Normalizando movimientos bancarios...")
    bank_normalized = [BankNormalizer().normalize(r) for r in bank_dfs_raw]
    bank_df = (
        _pd.concat(bank_normalized, ignore_index=True)
        if len(bank_normalized) > 1
        else (bank_normalized[0] if bank_normalized else _pd.DataFrame())
    )

    # ── Enriquecimiento de REPORTE_CAJA para la cuenta 6614 WB──────────────────────────────
    # Solo enriquece: agrega tienda + tipo_pago al banco PERO SOLO PARA LA CUENTA 6614
    # No agrega registros sin match
    # CRÍTICO: Prevenir cruce con otras cuentas (ej: comisión 7133 -10.50 vs comisión 6614 -10.50)
    if reporte_caja_dfs:
        logger.info("[ENRIQUECIMIENTO] %d archivo(s) REPORTE_CAJA disponible(s)", len(reporte_caja_dfs))
        
        # Concatenar todos los REPORTE_CAJA y normalizar
        reporte_raw = _pd.concat(reporte_caja_dfs, ignore_index=True)
        reporte_norm = BankNormalizer().normalize(reporte_raw)
        
        # Filtrar solo movimientos de la 6614
        reporte_6614 = reporte_norm[reporte_norm["account_id"] == "6614"].copy() if not reporte_norm.empty else _pd.DataFrame()
        
        if not reporte_6614.empty:
            logger.info("[ENRIQUECIMIENTO] Movimientos 6614 en REPORTE_CAJA: %d", len(reporte_6614))

            bank_account_str = bank_df["account_id"].fillna("").astype(str).str.strip() if not bank_df.empty else _pd.Series(dtype=str)
            bank_6614_mask = bank_account_str.eq("6614") | bank_account_str.str.endswith("6614")
            
            # CRÍTICO: Solo enriquecer los movimientos bancarios de la cuenta 6614
            # Previene cruce de comisiones de múltiples cuentas con igual monto + fecha
            bank_6614 = bank_df[bank_6614_mask].copy() if not bank_df.empty else _pd.DataFrame()
            
            if not bank_6614.empty:
                # Enriquecer solo los movimientos 6614 con reporte (agregar tienda + tipo_pago)
                bank_6614_enriched = _enrich_bank_with_reporte(bank_6614, reporte_6614)
                
                # Recombinar: 6614 enriquecido + otras cuentas sin cambios
                bank_other = bank_df[~bank_6614_mask].copy()
                bank_df = _pd.concat([bank_6614_enriched, bank_other], ignore_index=True) if not bank_other.empty else bank_6614_enriched
                
                logger.info(
                    "[ENRIQUECIMIENTO] Banco 6614 enriquecido: %d movimientos con tienda",
                    bank_6614_enriched["tienda"].notna().sum() if "tienda" in bank_6614_enriched.columns else 0,
                )
            else:
                logger.info("[ENRIQUECIMIENTO] No hay movimientos 6614 en banco para enriquecer")
        else:
            logger.info("[ENRIQUECIMIENTO] No hay movimientos 6614 en REPORTE_CAJA para enriquecer")

    logger.info("Normalizando movimientos JDE...")
    jde_df = JDENormalizer().normalize(jde_raw_df)

    # Filtrar JDE por cuenta bancaria
    # Siempre intentar match exacto + sufijo para todas las cuentas bancarias,
    # ya que algunos bancos (ej. NetPay) reportan cuenta larga "0884166614"
    # mientras JDE usa solo los últimos 4 dígitos "6614".
    bank_accounts   = set(bank_df["account_id"].unique())
    jde_account_ids = set(jde_df["account_id"].unique())
    
    logger.info("────────────────────────────────────────────────────")
    logger.info("[FILTRADO CUENTA] Cuentas en BANCO: %s", sorted(bank_accounts))
    logger.info("[FILTRADO CUENTA] Cuentas en JDE: %s", sorted(jde_account_ids))
    
    matched_jde_ids: set = set()

    for bank_acct in bank_accounts:
        for jde_acct in jde_account_ids:
            if bank_acct == jde_acct or bank_acct.endswith(jde_acct) or jde_acct.endswith(bank_acct):
                matched_jde_ids.add(jde_acct)
                logger.info("[FILTRADO CUENTA] MATCH: banco '%s' ↔ JDE '%s'", bank_acct, jde_acct)

    logger.info("[FILTRADO CUENTA] JDE ids a usar: %s", sorted(matched_jde_ids) if matched_jde_ids else "NINGUNO")
    logger.info("────────────────────────────────────────────────────")

    if matched_jde_ids:
        jde_filtered = jde_df[jde_df["account_id"].isin(matched_jde_ids)].copy()
        logger.info(
            "JDE filtrado por cuenta(s) bancaria(s) %s → JDE id(s) %s (%d movimientos)",
            bank_accounts, matched_jde_ids, len(jde_filtered),
        )
        
        # VALIDACIÓN: Si banco tiene SOLO 1 cuenta, filtrar JDE a esa única cuenta
        # Previene cruce de comisiones cuando banco tiene menos cuentas que JDE
        if len(bank_accounts) == 1 and len(matched_jde_ids) > 1:
            single_bank_account = list(bank_accounts)[0]
            before_count = len(jde_filtered)
            
            # Buscar la cuenta JDE que coincida con la única cuenta del banco
            jde_accts_to_use = {single_bank_account}
            for jde_acct in matched_jde_ids:
                if (single_bank_account == jde_acct or 
                    single_bank_account.endswith(jde_acct) or 
                    jde_acct.endswith(single_bank_account)):
                    jde_accts_to_use = {jde_acct}
                    break
            
            jde_filtered = jde_filtered[jde_filtered["account_id"].isin(jde_accts_to_use)].copy()
            logger.warning(
                "[SEGURIDAD-CUENTA] Banco solo tiene cuenta '%s' pero JDE tenía %s. "
                "Filtrando JDE a solo cuenta '%s' (%d -> %d movimientos)",
                single_bank_account, sorted(matched_jde_ids), list(jde_accts_to_use)[0] if jde_accts_to_use else "NINGUNA",
                before_count, len(jde_filtered)
            )
    else:
        jde_filtered = _pd.DataFrame(columns=jde_df.columns)

    if jde_filtered.empty:
        logger.warning(
            "No se encontraron movimientos JDE para la(s) cuenta(s) bancaria(s): %s. "
            "Se usarán todos los movimientos JDE.",
            bank_accounts,
        )
        jde_filtered = jde_df
    else:
        logger.info(
            "JDE filtrado a cuenta(s) %s: %d -> %d movimientos",
            bank_accounts, len(jde_df), len(jde_filtered),
        )

    jde_df = jde_filtered

    logger.info("Validando schema del DataFrame bancario...")
    DataFrameSchemaValidator.validate_bank_dataframe(bank_df)
    logger.info("Validando schema del DataFrame JDE...")
    DataFrameSchemaValidator.validate_jde_dataframe(jde_df)

    return bank_df, jde_df, mp_color_filter_debug


# ============================================================
# PIPELINE PRINCIPAL (importable desde Streamlit / CLI)
# ============================================================

def run_pipeline(
    bank_file_path,          # str  o  list[str]
    jde_file_path: str,
    output_dir: str,
) -> dict:

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    bank_df, jde_df, mp_color_filter_debug = _prepare_dataframes(bank_file_path, jde_file_path)

    logger.info(
        "Iniciando conciliación: %d movimientos banco | %d movimientos JDE",
        len(bank_df), len(jde_df),
    )
    engine  = ReconciliationEngine()
    bank_accounts = set(bank_df["account_id"].unique()) if not bank_df.empty else set()
    _configure_engine_for_accounts(engine, bank_accounts)
    results = engine.reconcile(bank_df, jde_df)
    results["_mp_color_filter_debug"] = mp_color_filter_debug

    logger.info("Generando reporte Excel en: %s", output_dir)
    reporter   = ExcelReporter()
    report_path = reporter.generate(results, output_path)

    _print_summary(results["summary"], report_path)
    return results


# ============================================================
# PIPELINE INTERACTIVO — FASE 1 (Streamlit: proponer agrupaciones)
# ============================================================

def run_pipeline_stage1(
    bank_file_path,   # str o list[str]
    jde_file_path: str,
) -> dict:
    """
    Parsea, normaliza, valida y ejecuta el matching exacto.
    Devuelve las agrupaciones como *propuestas* (sin confirmar) para
    que el usuario las revise en la UI antes de finalizar.

    El dict devuelto se guarda en session_state y se pasa a
    ``run_pipeline_stage2`` junto con los group_ids aprobados.
    """
    bank_df, jde_df, mp_color_filter_debug = _prepare_dataframes(bank_file_path, jde_file_path)

    logger.info(
        "Stage 1 — matching exacto + propuesta de agrupaciones: "
        "%d banco | %d JDE",
        len(bank_df), len(jde_df),
    )

    engine = ReconciliationEngine()
    bank_accounts = set(bank_df["account_id"].unique()) if not bank_df.empty else set()
    selected_mode = _configure_engine_for_accounts(engine, bank_accounts)
    interactive_result = engine.reconcile_interactive(bank_df, jde_df)

    # ── Metadatos para el write-back del Papel de Trabajo ──
    # Solo usa write-back si: 1) archivo es Excel Y 2) cuenta está en whitelist (6614, 7133)
    bank_accounts = set(bank_df["account_id"].unique()) if not bank_df.empty else set()
    is_pt = _is_papel_trabajo_account(bank_accounts, jde_file_path)
    
    interactive_result["_jde_source_path"]   = str(jde_file_path)
    interactive_result["_is_papel_trabajo"]  = is_pt
    interactive_result["_bank_accounts"]     = list(bank_accounts)
    interactive_result["_engine_mode"]       = selected_mode
    interactive_result["_mp_color_filter_debug"] = mp_color_filter_debug

    if is_pt:
        logger.info("✓ Papel de Trabajo detectado para cuenta(s): %s", bank_accounts)
    else:
        logger.info("ℹ Conciliación normal (sin write-back) para cuenta(s): %s", bank_accounts)

    logger.info(
        "Stage 1 completado — %d exactos | %d agrupaciones propuestas",
        len(interactive_result["exact_matches"]),
        len(interactive_result["proposed_grouped_matches"]),
    )

    return interactive_result


# ============================================================
# PIPELINE INTERACTIVO — FASE 2 (Streamlit: confirmar y reportar)
# ============================================================

def run_pipeline_stage2(
    interactive_result: dict,
    approved_group_ids: set,
    output_dir: str,
) -> dict:
    """
    Aplica los grupos aprobados por el usuario, construye el resultado
    final y genera el reporte Excel.

    Parámetros
    ----------
    interactive_result : dict
        Resultado devuelto por ``run_pipeline_stage1`` (o
        ``engine.reconcile_interactive``).
    approved_group_ids : set[int]
        ``group_id`` de las agrupaciones que el usuario aprobó.
    output_dir : str
        Directorio donde se guardará el reporte Excel.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    engine  = ReconciliationEngine()
    results = engine.confirm_grouped_matches(interactive_result, approved_group_ids)

    logger.info(
        "Stage 2 — %d agrupaciones confirmadas | %d pendientes banco | %d pendientes JDE",
        results["summary"]["grouped_matches_count"],
        results["summary"]["pending_bank_count"],
        results["summary"]["pending_jde_count"],
    )

    logger.info("Generando reporte Excel en: %s", output_dir)
    reporter    = ExcelReporter()
    report_path = reporter.generate(results, output_path)

    _print_summary(results["summary"], report_path)
    
    # Preservar metadatos del interactive_result en el resultado final
    if "_is_papel_trabajo" in interactive_result:
        results["_is_papel_trabajo"] = interactive_result["_is_papel_trabajo"]
    if "_jde_bytes" in interactive_result:
        results["_jde_bytes"] = interactive_result["_jde_bytes"]
    if "_jde_source_path" in interactive_result:
        results["_jde_source_path"] = interactive_result["_jde_source_path"]
    if "_bank_accounts" in interactive_result:
        results["_bank_accounts"] = interactive_result["_bank_accounts"]
    if "_mp_color_filter_debug" in interactive_result:
        results["_mp_color_filter_debug"] = interactive_result["_mp_color_filter_debug"]
    if "_engine_mode" in interactive_result:
        results["_engine_mode"] = interactive_result["_engine_mode"]
    
    return results


# ============================================================
# RESUMEN EN CONSOLA
# ============================================================

def _print_summary(summary: dict, report_path) -> None:
    print("\n" + "=" * 50)
    print("  RESUMEN DE CONCILIACIÓN")
    print("=" * 50)
    print(f"  Movimientos banco         : {summary['total_bank_movements']}")
    print(f"  Movimientos JDE           : {summary['total_jde_movements']}")
    print(f"  Matches exactos           : {summary['exact_matches_count']}")
    print(f"  Matches agrupados         : {summary['grouped_matches_count']}")
    print(f"  Agrupados inversos        : {summary.get('reverse_grouped_matches_count', 0)}")
    print(f"  Pendientes banco          : {summary['pending_bank_count']}")
    print(f"  Pendientes JDE            : {summary['pending_jde_count']}")
    print(f"  Reporte guardado en       : {report_path}")
    print("=" * 50 + "\n")


# ============================================================
# ENTRADA CLI
# ============================================================

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Motor de conciliación bancaria (CLI)"
    )
    parser.add_argument(
        "--bank",
        required=True,
        nargs="+",
        metavar="ARCHIVO",
        help="Ruta(s) al archivo(s) de movimientos bancarios (se pueden pasar varios)",
    )
    parser.add_argument(
        "--jde",
        required=True,
        metavar="ARCHIVO",
        help="Ruta al archivo de movimientos JDE",
    )
    parser.add_argument(
        "--output",
        required=False,
        default="data/output/reconciliations/",
        metavar="DIRECTORIO",
        help="Directorio de salida para el reporte (default: data/output/reconciliations/)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    try:
        run_pipeline(
            bank_file_path=args.bank,   # ya es lista por nargs="+"
            jde_file_path=args.jde,
            output_dir=args.output,
        )
    except SchemaValidationError as exc:
        logger.error("Error de validación: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        logger.error("Archivo no encontrado: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Error inesperado: %s", exc)
        sys.exit(1)
