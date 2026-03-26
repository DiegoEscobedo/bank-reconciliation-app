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
from config.settings import PAPEL_TRABAJO_ACCOUNTS as _PAPEL_TRABAJO_ACCOUNTS

logger = get_logger(__name__)


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

    # Normalizar columnas de enriquecimiento
    rep = reporte_df[["movement_date", "abs_amount", "tienda", "tipo_banco"]].copy()
    rep = rep.dropna(subset=["abs_amount"])
    rep["_amt_key"] = rep["abs_amount"].round(2)
    rep["_date_key"] = rep["movement_date"].dt.date

    # Eliminar duplicados de clave (si el reporte repite el mismo monto+fecha+tienda)
    rep = rep.drop_duplicates(subset=["_date_key", "_amt_key"])

    bank = bank_df.copy()
    bank["_amt_key"]  = bank["abs_amount"].round(2)
    bank["_date_key"] = bank["movement_date"].dt.date

    merged = bank.merge(
        rep[["_date_key", "_amt_key", "tienda", "tipo_banco"]],
        on=["_date_key", "_amt_key"],
        how="left",
        suffixes=("", "_rep"),
    )

    # Contar matches para logging
    matches = merged[merged["tienda"].notna() | merged.get("tienda_rep", _pd.Series()).notna()].shape[0]
    logger.debug(f"[ENRICH] Matches encontrados: {matches}/{len(merged)}")

    # Si bank_df ya tenía tienda (p. ej. también es REPORTE), preferir la existente
    # Si NO tenía tienda, usar la del reporte si existe
    if "tienda" not in bank.columns and "tienda_rep" in merged.columns:
        merged["tienda"] = merged["tienda_rep"]
    elif "tienda" in merged.columns and "tienda_rep" in merged.columns:
        merged["tienda"] = merged["tienda"].fillna(merged["tienda_rep"])
        
    if "tipo_banco" not in bank.columns and "tipo_banco_rep" in merged.columns:
        merged["tipo_banco"] = merged["tipo_banco_rep"]
    elif "tipo_banco" in merged.columns and "tipo_banco_rep" in merged.columns:
        merged["tipo_banco"] = merged["tipo_banco"].fillna(merged["tipo_banco_rep"])

    # Limpiar columnas auxiliares
    drop_cols = ["_amt_key", "_date_key"] + [c for c in merged.columns if c.endswith("_rep")]
    merged = merged.drop(columns=[c for c in drop_cols if c in merged.columns])

    return merged.reset_index(drop=True)


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
            
            # CRÍTICO: Solo enriquecer los movimientos bancarios de la cuenta 6614
            # Previene cruce de comisiones de múltiples cuentas con igual monto + fecha
            bank_6614 = bank_df[bank_df["account_id"] == "6614"].copy() if not bank_df.empty else _pd.DataFrame()
            
            if not bank_6614.empty:
                # Enriquecer solo los movimientos 6614 con reporte (agregar tienda + tipo_pago)
                bank_6614_enriched = _enrich_bank_with_reporte(bank_6614, reporte_6614)
                
                # Recombinar: 6614 enriquecido + otras cuentas sin cambios
                bank_other = bank_df[bank_df["account_id"] != "6614"].copy()
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
    jde_account_ids = jde_df["account_id"].unique()
    matched_jde_ids: set = set()

    for bank_acct in bank_accounts:
        for jde_acct in jde_account_ids:
            if bank_acct == jde_acct or bank_acct.endswith(jde_acct) or jde_acct.endswith(bank_acct):
                matched_jde_ids.add(jde_acct)

    if matched_jde_ids:
        jde_filtered = jde_df[jde_df["account_id"].isin(matched_jde_ids)].copy()
        logger.info(
            "JDE filtrado por cuenta(s) bancaria(s) %s → JDE id(s) %s (%d movimientos)",
            bank_accounts, matched_jde_ids, len(jde_filtered),
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

    return bank_df, jde_df


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

    bank_df, jde_df = _prepare_dataframes(bank_file_path, jde_file_path)

    logger.info(
        "Iniciando conciliación: %d movimientos banco | %d movimientos JDE",
        len(bank_df), len(jde_df),
    )
    engine  = ReconciliationEngine()
    results = engine.reconcile(bank_df, jde_df)

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
    bank_df, jde_df = _prepare_dataframes(bank_file_path, jde_file_path)

    logger.info(
        "Stage 1 — matching exacto + propuesta de agrupaciones: "
        "%d banco | %d JDE",
        len(bank_df), len(jde_df),
    )

    engine = ReconciliationEngine()
    interactive_result = engine.reconcile_interactive(bank_df, jde_df)

    # ── Metadatos para el write-back del Papel de Trabajo ──
    # Solo usa write-back si: 1) archivo es Excel Y 2) cuenta está en whitelist (6614, 7133)
    bank_accounts = set(bank_df["account_id"].unique()) if not bank_df.empty else set()
    is_pt = _is_papel_trabajo_account(bank_accounts, jde_file_path)
    
    interactive_result["_jde_source_path"]   = str(jde_file_path)
    interactive_result["_is_papel_trabajo"]  = is_pt
    interactive_result["_bank_accounts"]     = list(bank_accounts)

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
