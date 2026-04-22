"""
app.py — Interfaz Streamlit para el motor de conciliación bancaria.

Ejecución:
    streamlit run app.py
"""

import io
import re
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    TIPO_BANCO_TO_JDE_COMPAT,
)
from main import run_pipeline, run_pipeline_stage1, run_pipeline_stage2
from src.reporting.excel_reporter import ExcelReporter
from src.batch.batch_marking import extract_batch_preview, parse_batch_input
from src.utils.logger import get_logger
from src.parsers.conciliacion_parser import parse_conciliacion_excel, get_pending_summary
from src.matching.historical_matcher import match_historical_pendientes, summarize_historical_matches

logger = get_logger(__name__)


def _safe_uploaded_name(filename: object, fallback: str) -> str:
    """Normaliza nombres subidos para evitar rutas/bytes raros en disco temporal."""
    raw_name = Path(str(filename or "")).name
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name).strip("._")
    if not clean:
        clean = fallback

    if len(clean) > 120:
        dot_idx = clean.rfind(".")
        if dot_idx > 0:
            ext = clean[dot_idx:]
            stem = clean[:dot_idx]
            clean = f"{stem[:100]}{ext[:20]}"
        else:
            clean = clean[:120]
    return clean


def _normalize_account_token(value: object) -> str:
    token = str(value or "").strip().replace(" ", "")
    if token.upper() in {"", "UNKNOWN", "NOENCONTRADO", "N/A", "NA", "NONE", "NULL", "NAN", "<NA>"}:
        return ""
    return token


def _accounts_compatible(bank_account: object, jde_account: object) -> bool:
    b = _normalize_account_token(bank_account)
    j = _normalize_account_token(jde_account)
    if not b or not j:
        return True
    return b == j or b.endswith(j) or j.endswith(b)


def _normalize_tienda(value: object) -> str:
    t = str(value or "").strip().upper()
    if t in {"", "NO ENCONTRADO", "NAN", "NONE", "<NA>"}:
        return ""
    return t


def _is_amount_close(a: object, b: object, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= float(tol)
    except Exception:
        return False


def _diagnose_unmatched_row(
    row: pd.Series,
    opposite_df: pd.DataFrame,
    amount_tolerance: float,
    date_tolerance_days: int,
    side: str,
) -> str:
    if opposite_df.empty:
        return "Sin movimientos en el lado opuesto"

    amount = row.get("abs_amount")
    date = pd.to_datetime(row.get("movement_date"), errors="coerce")
    move_type = str(row.get("movement_type") or "").strip().upper()
    account = row.get("account_id")
    tienda = _normalize_tienda(row.get("tienda"))

    c_amount = opposite_df[
        opposite_df["abs_amount"].apply(lambda x: _is_amount_close(x, amount, amount_tolerance))
    ] if "abs_amount" in opposite_df.columns else pd.DataFrame()
    if c_amount.empty:
        return "Sin monto en tolerancia"

    if pd.notnull(date) and "movement_date" in c_amount.columns:
        opp_dates = pd.to_datetime(c_amount["movement_date"], errors="coerce")
        c_date = c_amount[(opp_dates - date).abs().dt.days <= int(date_tolerance_days)]
        if c_date.empty:
            return "Monto encontrado, pero fecha fuera de tolerancia"
    else:
        c_date = c_amount

    if move_type and "movement_type" in c_date.columns:
        c_type = c_date[
            c_date["movement_type"].fillna("").astype(str).str.strip().str.upper() == move_type
        ]
        if c_type.empty:
            return "Monto+fecha OK, pero tipo de movimiento distinto"
    else:
        c_type = c_date

    if "account_id" in c_type.columns:
        c_account = c_type[
            c_type["account_id"].apply(lambda x: _accounts_compatible(account, x))
        ]
        if c_account.empty:
            return "Monto+fecha+tipo OK, pero cuenta no compatible"
    else:
        c_account = c_type

    if tienda and "tienda" in c_account.columns:
        c_store = c_account[
            c_account["tienda"].apply(lambda x: _normalize_tienda(x) == tienda)
        ]
        if c_store.empty:
            return "Monto+fecha+tipo+cuenta OK, pero tienda no coincide"
    else:
        c_store = c_account

    if side == "BANK" and "tipo_banco" in row.index and "tipo_jde" in c_store.columns:
        tipo_banco = str(row.get("tipo_banco") or "").strip().upper()
        compat = TIPO_BANCO_TO_JDE_COMPAT.get(tipo_banco, set())
        if compat:
            c_pay = c_store[
                c_store["tipo_jde"].fillna("").astype(str).str.strip().str.upper().isin(compat)
            ]
            if c_pay.empty:
                return "Monto+fecha+tipo+cuenta+tienda OK, pero tipo de pago no compatible"

    return "Coincidencia potencial; revisar reglas de unicidad/agrupación"


def _add_unmatched_reason_column(
    pending_df: pd.DataFrame,
    opposite_full_df: pd.DataFrame,
    amount_tolerance: float,
    date_tolerance_days: int,
    side: str,
) -> pd.DataFrame:
    if pending_df.empty:
        return pending_df
    out = pending_df.copy()
    out["no_match_reason"] = out.apply(
        lambda r: _diagnose_unmatched_row(
            r,
            opposite_full_df,
            amount_tolerance=amount_tolerance,
            date_tolerance_days=date_tolerance_days,
            side=side,
        ),
        axis=1,
    )
    return out


def _refresh_excel_with_pending_bank_reason(results: dict, pending_bank_diag: pd.DataFrame) -> dict:
    """
    Regenera el Excel descargable incluyendo la columna de diagnóstico
    en la hoja de Pendientes Banco.
    """
    if not results.get("_excel_bytes"):
        return results

    payload = dict(results)
    payload["pending_bank_movements"] = pending_bank_diag

    try:
        reporter = ExcelReporter()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            out_dir = Path(tmp_dir)
            file_path = reporter.generate(payload, out_dir)
            payload["_excel_bytes"] = file_path.read_bytes()
    except Exception as exc:
        logger.warning("No se pudo regenerar Excel con diagnóstico de pendientes banco: %s", exc)

    return payload


def _data_quality_metrics(df: pd.DataFrame, side: str) -> dict:
    if df is None or df.empty:
        return {
            "lado": side,
            "total": 0,
            "cuenta_faltante": 0,
            "desc_vacia": 0,
            "fecha_invalida": 0,
            "tipo_vacio": 0,
            "tienda_vacia": 0,
            "duplicados_clave": 0,
        }

    w = df.copy()
    total = len(w)

    cuenta_faltante = w["account_id"].apply(lambda x: _normalize_account_token(x) == "").sum() if "account_id" in w.columns else 0
    desc_vacia = w["description"].fillna("").astype(str).str.strip().eq("").sum() if "description" in w.columns else 0
    fecha_invalida = pd.to_datetime(w.get("movement_date"), errors="coerce").isna().sum() if "movement_date" in w.columns else 0

    tipo_col = "tipo_banco" if side == "Banco" else "tipo_jde"
    tipo_vacio = w[tipo_col].fillna("").astype(str).str.strip().eq("").sum() if tipo_col in w.columns else 0
    tienda_vacia = w["tienda"].fillna("").astype(str).str.strip().eq("").sum() if "tienda" in w.columns else 0

    key_cols = [c for c in ["account_id", "movement_date", "abs_amount", "movement_type"] if c in w.columns]
    duplicados = w.duplicated(subset=key_cols, keep=False).sum() if key_cols else 0

    return {
        "lado": side,
        "total": int(total),
        "cuenta_faltante": int(cuenta_faltante),
        "desc_vacia": int(desc_vacia),
        "fecha_invalida": int(fecha_invalida),
        "tipo_vacio": int(tipo_vacio),
        "tienda_vacia": int(tienda_vacia),
        "duplicados_clave": int(duplicados),
    }


# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PÁGINA
# ════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Conciliación Bancaria",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════
# ESTILOS
# ════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .metric-card {
        background: #f0f6ff;
        border-left: 4px solid #2E75B6;
        padding: 12px 16px;
        border-radius: 6px;
        margin-bottom: 8px;
    }
    .metric-card h3 { margin: 0; font-size: 1.6rem; color: #1F4E79; }
    .metric-card p  { margin: 0; font-size: 0.85rem; color: #555; }
    .pending-warning { color: #C00000; font-weight: bold; }
    .match-ok        { color: #1F6B28; font-weight: bold; }

</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("### Modo")
app_mode = st.sidebar.radio(
    "Selecciona operación",
    ["Conciliación", "Marcar por batch"],
    label_visibility="collapsed",
)

if app_mode == "Marcar por batch":
    st.title("Marcado por Batch — Papel de Trabajo")
    st.caption(
        "Módulo independiente de conciliación principal: puedes confirmar varios grupos de batch y generar un solo descargable final cuando tú decidas."
    )

    if "batch_mark_preview" not in st.session_state:
        st.session_state["batch_mark_preview"] = None
    if "batch_mark_output" not in st.session_state:
        st.session_state["batch_mark_output"] = None
    if "batch_mark_groups" not in st.session_state:
        st.session_state["batch_mark_groups"] = []
    if "batch_mark_source_name" not in st.session_state:
        st.session_state["batch_mark_source_name"] = None
    if "batch_mark_source_bytes" not in st.session_state:
        st.session_state["batch_mark_source_bytes"] = None

    c1, c2 = st.columns([2, 1])
    with c1:
        pt_batch_file = st.file_uploader(
            "Papel de Trabajo (.xlsx)",
            type=["xlsx", "xls"],
            key="pt_batch_file",
        )
    with c2:
        batch_date = st.date_input(
            "Fecha de conciliación",
            value=datetime.now().date(),
            key="pt_batch_date",
        )

    batch_text = st.text_area(
        "Lista de batch",
        placeholder="Ejemplo: 70241, 70242, 70243 (también acepta saltos de línea)",
        height=140,
        key="pt_batch_text",
    )
    only_pending_batch = st.checkbox(
        "Marcar solo filas pendientes (CONCILIADO vacío/0)",
        value=True,
        key="pt_batch_only_pending",
    )

    if pt_batch_file is not None:
        current_source_name = f"{pt_batch_file.name}|{getattr(pt_batch_file, 'size', '')}"
        previous_source_name = st.session_state.get("batch_mark_source_name")
        if previous_source_name and previous_source_name != current_source_name:
            st.session_state["batch_mark_preview"] = None
            st.session_state["batch_mark_output"] = None
            st.session_state["batch_mark_groups"] = []
            st.session_state["batch_mark_source_bytes"] = None
            st.info("Se detectó un archivo distinto. Se reinició la lista de grupos confirmados para evitar mezclar fuentes.")
        st.session_state["batch_mark_source_name"] = current_source_name

    reset_btn = st.button("🗑 Reiniciar grupos confirmados", key="pt_batch_reset_groups")
    if reset_btn:
        st.session_state["batch_mark_preview"] = None
        st.session_state["batch_mark_output"] = None
        st.session_state["batch_mark_groups"] = []
        st.session_state["batch_mark_source_bytes"] = None
        st.rerun()

    run_batch_btn = st.button(
        "🔍 Previsualizar conciliación por batch",
        type="primary",
        disabled=(pt_batch_file is None or not str(batch_text or "").strip()),
        key="pt_batch_run",
    )

    if run_batch_btn:
        try:
            batch_tokens = parse_batch_input(batch_text)
            if not batch_tokens:
                raise ValueError("No se detectaron números batch válidos")

            source_bytes = pt_batch_file.getvalue()
            preview = extract_batch_preview(
                source_bytes,
                batch_tokens=batch_tokens,
                only_pending=only_pending_batch,
            )
            st.session_state["batch_mark_output"] = None
            st.session_state["batch_mark_preview"] = {
                "source_bytes": source_bytes,
                "batch_tokens": sorted(batch_tokens),
                "preview": preview,
                "date": batch_date,
            }
            st.session_state["batch_mark_source_bytes"] = source_bytes
        except Exception as exc:
            st.session_state["batch_mark_preview"] = None
            st.session_state["batch_mark_output"] = None
            logger.exception("Error al previsualizar por batch: %s", exc)
            st.error("Error al previsualizar por batch. Revisa los logs del servidor.")

    batch_preview = st.session_state.get("batch_mark_preview")
    if batch_preview:
        preview = batch_preview["preview"]
        stats = preview["stats"]
        selected_df = preview["selected_rows"]
        aux_facts = preview["aux_facts"]

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Batch capturados", len(batch_preview["batch_tokens"]))
        m2.metric("Filas con batch", stats.get("rows_batch", 0))
        m3.metric("Filas a marcar", stats.get("rows_pending", 0))
        m4.metric("Aux_Fact marcados", len(aux_facts))
        m5.metric("Total importes", f"${preview.get('total_amount', 0.0):,.2f}")

        st.caption(
            f"Hoja: {stats.get('sheet', '')} | Columna batch: {stats.get('batch_column', '')} | Columna importe: {stats.get('amount_column', '')}"
        )

        if selected_df.empty:
            st.warning(
                "No se encontraron filas para marcar con los batch indicados. "
                "Revisa formato de batch o desactiva el filtro de pendientes."
            )
        else:
            with st.expander("Ver detalle de movimientos a conciliar", expanded=False):
                st.dataframe(
                    selected_df.style.format({"importe_num": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )

        confirm_btn = st.button(
            "✅ Confirmar conciliación por batch",
            type="secondary",
            disabled=(len(aux_facts) == 0),
            key="pt_batch_confirm",
        )

        if confirm_btn:
            groups = st.session_state.get("batch_mark_groups", [])
            batch_signature = tuple(sorted(batch_preview["batch_tokens"]))
            already_exists = any(tuple(sorted(g.get("batch_tokens", []))) == batch_signature for g in groups)
            if already_exists:
                st.warning("Este grupo de batch ya fue confirmado anteriormente.")
            else:
                existing_aux = set()
                for g in groups:
                    existing_aux.update(g.get("aux_facts", []))
                new_unique_aux = len(set(aux_facts) - existing_aux)

                group_id = max([g.get("group_id", 0) for g in groups], default=0) + 1
                groups.append({
                    "group_id": group_id,
                    "batch_tokens": list(batch_preview["batch_tokens"]),
                    "aux_facts": list(aux_facts),
                    "aux_count": len(aux_facts),
                    "new_unique_aux": new_unique_aux,
                    "rows_pending": int(stats.get("rows_pending", 0)),
                    "total_amount": float(preview.get("total_amount", 0.0) or 0.0),
                })
                st.session_state["batch_mark_groups"] = groups
                st.session_state["batch_mark_output"] = None
                st.success(f"Grupo confirmado. Aux_Fact nuevos aportados: {new_unique_aux}")
                st.rerun()

    groups = st.session_state.get("batch_mark_groups", [])
    if groups:
        st.markdown("---")
        st.subheader("Grupos confirmados")

        all_aux = set()
        for g in groups:
            all_aux.update(g.get("aux_facts", []))

        total_rows = sum(int(g.get("rows_pending", 0)) for g in groups)
        total_amount = sum(float(g.get("total_amount", 0.0) or 0.0) for g in groups)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Grupos confirmados", len(groups))
        c2.metric("Filas acumuladas", total_rows)
        c3.metric("Aux_Fact únicos", len(all_aux))
        c4.metric("Total importes acumulado", f"${total_amount:,.2f}")

        remove_idx = None
        for i, g in enumerate(groups):
            left, right = st.columns([8, 1])
            batches = ", ".join(g.get("batch_tokens", []))
            with left:
                st.caption(
                    f"Grupo {g.get('group_id')} | batch: {batches} | filas: {g.get('rows_pending', 0)} | "
                    f"aux: {g.get('aux_count', 0)} (nuevos: {g.get('new_unique_aux', 0)}) | "
                    f"total: ${float(g.get('total_amount', 0.0) or 0.0):,.2f}"
                )
            with right:
                if st.button("Quitar", key=f"pt_batch_remove_{g.get('group_id')}"):
                    remove_idx = i

        if remove_idx is not None:
            groups.pop(remove_idx)
            st.session_state["batch_mark_groups"] = groups
            st.session_state["batch_mark_output"] = None
            st.rerun()

        generate_btn = st.button(
            "⬇ Generar descargable final",
            type="primary",
            key="pt_batch_generate_final",
            disabled=(len(groups) == 0 or st.session_state.get("batch_mark_source_bytes") is None),
        )
        if generate_btn:
            try:
                reporter = ExcelReporter()
                updated_bytes = reporter.write_back_conciliados(
                    source=st.session_state["batch_mark_source_bytes"],
                    reconciled_aux_facts=sorted(all_aux),
                    match_date=batch_date,
                )
                st.session_state["batch_mark_output"] = {
                    "bytes": updated_bytes,
                    "group_count": len(groups),
                    "rows_total": total_rows,
                    "aux_count": len(all_aux),
                    "date": batch_date,
                    "total_amount": total_amount,
                }
            except Exception as exc:
                st.session_state["batch_mark_output"] = None
                logger.exception("Error al generar descargable final por batch: %s", exc)
                st.error("Error al generar descargable final. Revisa los logs del servidor.")

    batch_output = st.session_state.get("batch_mark_output")
    if batch_output:
        st.success("Descargable final generado con los grupos confirmados.")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Grupos incluidos", batch_output.get("group_count", 0))
        m2.metric("Filas acumuladas", batch_output.get("rows_total", 0))
        m4.metric("Aux_Fact marcados", batch_output["aux_count"])
        m3.metric("Total importes", f"${batch_output.get('total_amount', 0.0):,.2f}")
        fecha_archivo = batch_output["date"].strftime("%d-%m-%Y")
        st.download_button(
            label="⬇ Descargar Papel de Trabajo actualizado",
            data=batch_output["bytes"],
            file_name=f"PAPEL DE TRABAJO BATCH {fecha_archivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="pt_batch_download",
        )

    st.stop()

# ════════════════════════════════════════════════════════════
# SIDEBAR — CARGA DE ARCHIVOS
# ════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("🏦 Conciliación Bancaria")
    st.markdown("---")

    st.subheader("1. Archivo JDE")
    jde_file = st.file_uploader(
        "Sube el reporte transaccional",
        type=["csv", "xlsx", "xls"],
        key="jde",
        help=(
            "**Cuentas 6614 y 7133 (BBVA):** Sube el Papel de Trabajo (.xlsx)\n\n"
            "**Otras cuentas (3478 Banorte, etc.):** Sube el Reporte Auxiliar de Contabilidad (.csv) del JDE"
        )
    )

    st.markdown("---")
    st.subheader("2. Archivos bancarios")
    st.caption("Puedes subir uno o varios estados de cuenta (BBVA, Banorte, HSBC…)")
    bank_files = st.file_uploader(
        "Sube los estados de cuenta",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="bank",
        help="Estados de cuenta bancarios en CSV o Excel. Soporta BBVA, Banorte, Scotiabank…"
    )

    st.markdown("---")
    st.subheader("3. Reporte Caja (opcional)")
    st.caption("Contiene la tienda y forma de pago por movimiento (enriquecimiento).")
    reporte_caja_files = st.file_uploader(
        "Sube el Reporte Caja",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="reporte_caja",
        help="Reporte de caja con abreviaturas de tienda y tipo de pago. "
             "Se usa para identificar a qué tienda pertenece cada movimiento."
    )

    st.markdown("---")
    st.subheader("4. Conciliación anterior (opcional)")
    st.caption(
        "Sube el archivo de Conciliación Bancaria del mes anterior para "
        "identificar qué pendientes históricos ya se resolvieron en el período actual."
    )
    concil_ant_file = st.file_uploader(
        "Conciliación Bancaria anterior (.xlsx)",
        type=["xlsx", "xls"],
        key="concil_ant",
        help="Archivo 'Conciliación Bancaria al DD-MM-AAAA.xlsx' con las hojas por cuenta."
    )

    st.markdown("---")
    st.subheader("5. Tolerancias")
    amount_tolerance_ui = st.number_input(
        "Tolerancia de monto (+/-):",
        min_value=0.0,
        max_value=1000.0,
        value=float(AMOUNT_TOLERANCE),
        step=0.01,
        format="%.2f",
        help="Diferencia máxima permitida entre montos para considerar match.",
    )
    date_tolerance_ui = st.slider(
        "Tolerancia de fecha (días):",
        min_value=0,
        max_value=30,
        value=int(DATE_TOLERANCE_DAYS),
        step=1,
        help="Días máximos de diferencia permitidos entre fechas.",
    )

    st.markdown("---")
    run_btn = st.button(
        "▶ Conciliar",
        type="primary",
        disabled=(jde_file is None or len(bank_files) == 0),
    )

    if jde_file is None or len(bank_files) == 0:
        st.caption("⚠ Sube los archivos de banco y JDE para habilitar la conciliación.")

# ════════════════════════════════════════════════════════════
# PANTALLA INICIAL (sin archivos)
# ════════════════════════════════════════════════════════════

if jde_file is None and len(bank_files) == 0:
    st.title("Motor de Conciliación Bancaria")
    st.markdown("""
    ### ¿Cómo usar?

    1. En el panel izquierdo, sube el **reporte JDE** (R09421 — LM por cuenta objeto).
    2. Sube uno o más **estados de cuenta bancarios** (BBVA, Banorte).
    3. Presiona **▶ Conciliar**.
    4. Revisa los resultados y descarga el reporte Excel.

    ---
    **Bancos soportados actualmente:** BBVA · Banorte · HSBC · Scotiabank · NetPay · Mercado Pago
    """)
    st.stop()

# ════════════════════════════════════════════════════════════
# EJECUCIÓN DEL PIPELINE
# ════════════════════════════════════════════════════════════

if run_btn:
    # Reiniciar estado para una nueva conciliación
    st.session_state["phase"]       = "idle"
    st.session_state["stage1_data"] = None
    st.session_state["results"]     = None
    st.session_state["error"]       = None

    with st.spinner("Procesando archivos y matching exacto…"):
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
                tmp = Path(tmp_dir)

                jde_path = tmp / _safe_uploaded_name(jde_file.name, "jde_input.xlsx")
                jde_path.write_bytes(jde_file.getvalue())

                bank_paths = []
                for idx, bf in enumerate(bank_files):
                    bp = tmp / _safe_uploaded_name(bf.name, f"bank_{idx + 1}.xlsx")
                    bp.write_bytes(bf.getvalue())
                    bank_paths.append(str(bp))

                # Reporte Caja: se pasa junto a los bancarios;
                # el pipeline lo separa internamente por su etiqueta REPORTE_CAJA
                for idx, rc in enumerate((reporte_caja_files or [])):
                    rp = tmp / _safe_uploaded_name(rc.name, f"reporte_caja_{idx + 1}.xlsx")
                    rp.write_bytes(rc.getvalue())
                    bank_paths.append(str(rp))

                stage1_data = run_pipeline_stage1(
                    bank_file_path=bank_paths,
                    jde_file_path=str(jde_path),
                    amount_tolerance=float(amount_tolerance_ui),
                    date_tolerance_days=int(date_tolerance_ui),
                )
                # Guardar los bytes del Papel de Trabajo DENTRO del with,
                # antes de que el TemporaryDirectory sea destruido.
                if stage1_data.get("_is_papel_trabajo"):
                    stage1_data["_jde_bytes"] = jde_file.getvalue()

            st.session_state["stage1_data"] = stage1_data

            # Si no hay agrupaciones propuestas (forward ni reverse), finalizar directamente
            if not stage1_data["proposed_grouped_matches"] and not stage1_data.get("proposed_reverse_grouped_matches"):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp2:
                    out2 = Path(tmp2) / "output"
                    out2.mkdir()
                    results = run_pipeline_stage2(
                        interactive_result=stage1_data,
                        approved_group_ids=set(),
                        output_dir=str(out2),
                    )
                    excel_files = list(out2.glob("conciliacion_*.xlsx"))
                    if excel_files:
                        results["_excel_bytes"] = excel_files[0].read_bytes()
                st.session_state["results"] = results
                st.session_state["phase"]   = "results"
            else:
                st.session_state["phase"] = "validating"

        except Exception as exc:
            st.session_state["error"] = "Ocurrio un error interno en la conciliacion."
            logger.exception("Error en stage 1: %s", exc)

    st.rerun()

# ════════════════════════════════════════════════════════════
# MOSTRAR ERROR
# ════════════════════════════════════════════════════════════

if st.session_state.get("error"):
    st.error(f"❌ {st.session_state['error']} Revisa los logs del servidor.")
    st.stop()

# ════════════════════════════════════════════════════════════
# FASE 2 — VALIDACIÓN DE AGRUPACIONES
# ════════════════════════════════════════════════════════════

if st.session_state.get("phase") == "validating":
    stage1_data      = st.session_state["stage1_data"]
    proposals        = stage1_data["proposed_grouped_matches"]
    rev_proposals    = stage1_data.get("proposed_reverse_grouped_matches", [])
    all_proposals    = proposals + rev_proposals
    exact_count      = len(stage1_data["exact_matches"])

    st.title("Validación de Agrupaciones")
    st.info(
        f"Se encontraron **{len(proposals)}** agrupaciones (1 banco → N JDE) "
        f"y **{len(rev_proposals)}** agrupaciones inversas (N banco → 1 JDE) "
        f"(además de **{exact_count}** matches exactos ya confirmados).\n\n"
        "Revisa cada agrupación y acepta o rechaza antes de finalizar. "
        "Pueden existir registros **atrasados de meses anteriores** — "
        "verifica las fechas y tiendas cuidadosamente."
    )

    col_all, col_none, col_spacer = st.columns([1, 1, 5])
    with col_all:
        if st.button("✅ Aceptar todas"):
            for p in all_proposals:
                st.session_state[f"grp_{p['group_id']}"] = True
            st.rerun()
    with col_none:
        if st.button("❌ Rechazar todas"):
            for p in all_proposals:
                st.session_state[f"grp_{p['group_id']}"] = False
            st.rerun()

    st.markdown("---")

    def _fmt_date(val):
        try:
            return str(val)[:10]
        except Exception:
            return str(val)

    def _safe(snap, key, default="—"):
        v = snap.get(key, default)
        return default if (v is None or str(v).strip() in ("", "nan", "None")) else v

    # ── Agrupaciones normales: 1 banco → N JDE ──────────────────────
    if proposals:
        st.subheader("📦 1 banco → N JDE")
    for proposal in proposals:
        gid        = proposal["group_id"]
        bank_snap  = proposal["bank_snapshot"]
        jde_snaps  = proposal["jde_snapshots"]
        diff       = proposal["amount_difference"]
        tienda     = _safe(bank_snap, "tienda")
        banco_monto = bank_snap.get("abs_amount", 0) or 0
        banco_fecha = _fmt_date(bank_snap.get("movement_date", ""))

        header = (
            f"Grupo {gid + 1} │ "
            f"${banco_monto:,.2f} │ "
            f"{banco_fecha} │ "
            f"Tienda: {tienda} │ "
            f"{len(jde_snaps)} reg. JDE"
        )

        with st.expander(header, expanded=True):
            st.checkbox(
                "✔ Aceptar esta agrupación",
                key=f"grp_{gid}",
                value=st.session_state.get(f"grp_{gid}", True),
            )

            col_b, col_j = st.columns(2)

            with col_b:
                st.markdown("**Movimiento bancario**")
                st.dataframe(
                    pd.DataFrame([{
                        "Cuenta":      _safe(bank_snap, "account_id"),
                        "Fecha":       banco_fecha,
                        "Descripción": _safe(bank_snap, "description"),
                        "Monto":       banco_monto,
                        "Tienda":      tienda,
                        "Tipo":        _safe(bank_snap, "tipo_banco",
                                             _safe(bank_snap, "movement_type")),
                    }]).style.format({"Monto": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )

            with col_j:
                st.markdown(f"**Registros JDE agrupados ({len(jde_snaps)})**")
                jde_rows = []
                for snap in jde_snaps:
                    jde_rows.append({
                        "Cuenta":      _safe(snap, "account_id"),
                        "Fecha":       _fmt_date(snap.get("movement_date", "")),
                        "Descripción": _safe(snap, "description"),
                        "Monto":       snap.get("abs_amount", 0) or 0,
                        "Tienda":      _safe(snap, "tienda"),
                        "Tipo":        _safe(snap, "tipo_jde",
                                             _safe(snap, "movement_type")),
                    })
                st.dataframe(
                    pd.DataFrame(jde_rows).style.format({"Monto": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )

            if abs(diff) >= 0.01:
                st.caption(f"⚠ Diferencia de centavos: ${diff:,.2f}")

        st.markdown("---")

    # ── Agrupaciones inversas: N banco → 1 JDE ──────────────────────
    if rev_proposals:
        st.subheader("🔄 N banco → 1 JDE (comisiones y otros)")

    for proposal in rev_proposals:
        gid       = proposal["group_id"]
        jde_snap  = proposal["jde_snapshot"]
        bank_snaps = proposal["bank_snapshots"]
        diff      = proposal["amount_difference"]
        jde_monto = jde_snap.get("abs_amount", 0) or 0
        jde_fecha = _fmt_date(jde_snap.get("movement_date", ""))
        tienda    = _safe(jde_snap, "tienda")

        header = (
            f"Inv. Grupo {gid + 1} │ "
            f"${jde_monto:,.2f} JDE │ "
            f"{jde_fecha} │ "
            f"Tienda: {tienda} │ "
            f"{len(bank_snaps)} reg. banco"
        )

        with st.expander(header, expanded=True):
            st.checkbox(
                "✔ Aceptar esta agrupación",
                key=f"grp_{gid}",
                value=st.session_state.get(f"grp_{gid}", True),
            )

            col_b, col_j = st.columns(2)

            with col_b:
                st.markdown(f"**Movimientos bancarios ({len(bank_snaps)})**")
                bank_rows = []
                for snap in bank_snaps:
                    bank_rows.append({
                        "Cuenta":      _safe(snap, "account_id"),
                        "Fecha":       _fmt_date(snap.get("movement_date", "")),
                        "Descripción": _safe(snap, "description"),
                        "Monto":       snap.get("abs_amount", 0) or 0,
                        "Fuente":      _safe(snap, "bank"),
                    })
                st.dataframe(
                    pd.DataFrame(bank_rows).style.format({"Monto": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )

            with col_j:
                st.markdown("**Registro JDE**")
                st.dataframe(
                    pd.DataFrame([{
                        "Cuenta":      _safe(jde_snap, "account_id"),
                        "Fecha":       jde_fecha,
                        "Descripción": _safe(jde_snap, "description"),
                        "Monto":       jde_monto,
                        "Tienda":      tienda,
                        "Tipo":        _safe(jde_snap, "tipo_jde",
                                             _safe(jde_snap, "movement_type")),
                    }]).style.format({"Monto": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )

            if abs(diff) >= 0.01:
                st.caption(f"⚠ Diferencia de centavos: ${diff:,.2f}")

        st.markdown("---")

    accepted_count = sum(
        1 for p in all_proposals
        if st.session_state.get(f"grp_{p['group_id']}", True)
    )
    st.markdown(f"**{accepted_count} de {len(all_proposals)} agrupaciones seleccionadas**")

    if st.button("✅ Confirmar selección y finalizar conciliación", type="primary"):
        approved_ids = {
            p["group_id"] for p in all_proposals
            if st.session_state.get(f"grp_{p['group_id']}", True)
        }
        with st.spinner("Finalizando conciliación y generando reporte…"):
            try:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
                    out = Path(tmp_dir) / "output"
                    out.mkdir()
                    results = run_pipeline_stage2(
                        interactive_result=st.session_state["stage1_data"],
                        approved_group_ids=approved_ids,
                        output_dir=str(out),
                    )
                    excel_files = list(out.glob("conciliacion_*.xlsx"))
                    if excel_files:
                        results["_excel_bytes"] = excel_files[0].read_bytes()

                st.session_state["results"] = results
                st.session_state["phase"]   = "results"
                st.session_state["error"]   = None
                st.rerun()
            except Exception as exc:
                st.session_state["error"] = "Ocurrio un error interno en la conciliacion."
                logger.exception("Error en stage 2: %s", exc)
                st.rerun()

    st.stop()

# ════════════════════════════════════════════════════════════
# MOSTRAR RESULTADOS
# ════════════════════════════════════════════════════════════

results = st.session_state.get("results")

if results is None:
    st.info("Sube los archivos y presiona **▶ Conciliar** para ver resultados.")
    st.stop()

summary = results["summary"]

# ── Título y descargas ──────────────────────────────────────────
st.title("Resultados de Conciliación")

# Capturar fecha para el nombre del Papel de Trabajo
_fecha_descarga = None
if results.get("_is_papel_trabajo"):
    st.markdown("#### Fecha para el nombre del archivo")
    _fecha_descarga = st.date_input(
        "Selecciona la fecha que deseas incluir en el archivo descargable:",
        value=datetime.now().date(),
        label_visibility="collapsed"
    )

st.markdown("---")

# ── Panel de calidad de datos ─────────────────────────────────────
bank_full_df = results.get("_bank_df_full", pd.DataFrame())
jde_full_df = results.get("_jde_df_full", pd.DataFrame())

if bank_full_df.empty:
    bank_full_df = pd.concat([
        results.get("conciliated_bank_movements", pd.DataFrame()),
        results.get("pending_bank_movements", pd.DataFrame()),
    ], ignore_index=True)
if jde_full_df.empty:
    jde_full_df = pd.concat([
        results.get("conciliated_jde_movements", pd.DataFrame()),
        results.get("pending_jde_movements", pd.DataFrame()),
    ], ignore_index=True)

with st.expander("🔎 Panel de calidad de datos", expanded=False):
    qm_bank = _data_quality_metrics(bank_full_df, "Banco")
    qm_jde = _data_quality_metrics(jde_full_df, "JDE")
    qdf = pd.DataFrame([qm_bank, qm_jde])
    qdf.columns = [
        "Lado", "Total", "Cuenta faltante", "Descripción vacía", "Fecha inválida",
        "Tipo vacío", "Tienda vacía", "Duplicados clave",
    ]
    st.dataframe(qdf, use_container_width=True, hide_index=True)
    st.caption(
        "Duplicados clave = mismos valores en cuenta + fecha + monto abs + tipo de movimiento."
    )

# ── Diagnóstico: por qué no concilió ─────────────────────────────
diag_amount_tol = float(results.get("_amount_tolerance", amount_tolerance_ui))
diag_date_tol = int(results.get("_date_tolerance_days", date_tolerance_ui))

pending_bank_diag = _add_unmatched_reason_column(
    results.get("pending_bank_movements", pd.DataFrame()),
    opposite_full_df=jde_full_df,
    amount_tolerance=diag_amount_tol,
    date_tolerance_days=diag_date_tol,
    side="BANK",
)
pending_jde_diag = _add_unmatched_reason_column(
    results.get("pending_jde_movements", pd.DataFrame()),
    opposite_full_df=bank_full_df,
    amount_tolerance=diag_amount_tol,
    date_tolerance_days=diag_date_tol,
    side="JDE",
)

# Mantener el Excel descargable alineado con la vista de diagnóstico
# (solo se agrega columna extra para Pendientes Banco).
results = _refresh_excel_with_pending_bank_reason(results, pending_bank_diag)
st.session_state["results"] = results

with st.expander("🧭 Explicación de por qué no concilió", expanded=False):
    col_rb, col_rj = st.columns(2)
    with col_rb:
        st.markdown("**Pendientes Banco — causas**")
        if pending_bank_diag.empty or "no_match_reason" not in pending_bank_diag.columns:
            st.caption("Sin pendientes banco.")
        else:
            c = pending_bank_diag["no_match_reason"].value_counts().reset_index()
            c.columns = ["Motivo", "Casos"]
            st.dataframe(c, use_container_width=True, hide_index=True)
    with col_rj:
        st.markdown("**Pendientes JDE — causas**")
        if pending_jde_diag.empty or "no_match_reason" not in pending_jde_diag.columns:
            st.caption("Sin pendientes JDE.")
        else:
            c = pending_jde_diag["no_match_reason"].value_counts().reset_index()
            c.columns = ["Motivo", "Casos"]
            st.dataframe(c, use_container_width=True, hide_index=True)

st.caption(
    f"Diagnóstico con tolerancias activas: monto +/- ${diag_amount_tol:,.2f} | fecha +/- {diag_date_tol} día(s)."
)
st.markdown("---")

_dl_cols = []
if results.get("_excel_bytes"):
    _dl_cols.append("conciliacion")
if results.get("_is_papel_trabajo"):
    _dl_cols.append("papel_trabajo")

# Mostrar tipo de conciliación realizada
if results.get("_is_papel_trabajo"):
    st.success(
        f"✅ **Conciliación Papel de Trabajo** — Cuenta(s): {', '.join(results.get('_bank_accounts', []))}\n\n"
        "Se generó el resumen de conciliación y puede actualizar el Papel de Trabajo."
    )
else:
    _accounts_str = ', '.join(results.get('_bank_accounts', ['Desconocida']))
    st.info(
        f"✓ **Conciliación completada** — Cuenta(s): {_accounts_str}\n\n"
        "Se generó el resumen de conciliación. Los registros JDE cargados no se modifican."
    )

st.markdown("---")

if _dl_cols:
    _n = len(_dl_cols)
    _dl_buttons = st.columns(_n)
    _btn_idx = 0

    if results.get("_excel_bytes"):
        with _dl_buttons[_btn_idx]:
            st.download_button(
                label="⬇ Descargar Excel conciliación",
                data=results["_excel_bytes"],
                file_name="conciliacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        _btn_idx += 1

    if results.get("_is_papel_trabajo"):
        # Recopilar Aux_Facts de los movimientos JDE conciliados
        _conciliados_jde = results.get("conciliated_jde_movements", pd.DataFrame())
        _strict_entries = []
        if "_aux_fact" in _conciliados_jde.columns:
            _aux_facts = []
            for _, _row in _conciliados_jde.iterrows():
                _v = _row.get("_aux_fact")
                _sv = str(_v).strip()
                if _sv in ("", "nan", "None", "NaT"):
                    continue
                # Normalizar float a entero: "2647414.0" → "2647414"
                try:
                    _sv = str(int(float(_sv)))
                except (ValueError, OverflowError):
                    pass
                _aux_facts.append(_sv)

                _acc = str(_row.get("account_id", "") or "").strip()
                _amt = _row.get("amount_signed", None)
                if _acc and pd.notna(_amt):
                    _strict_entries.append({
                        "aux_fact": _sv,
                        "account_id": _acc,
                        "amount_signed": float(_amt),
                    })

            _aux_facts = sorted(set(_aux_facts))
        else:
            _aux_facts = []

        # Obtener fecha de los movimientos banco conciliados (fecha más reciente)
        _conciliados_banco = results.get("conciliated_bank_movements", pd.DataFrame())
        _fecha_conciliacion = None
        if not _conciliados_banco.empty and "movement_date" in _conciliados_banco.columns:
            _fechas = pd.to_datetime(_conciliados_banco["movement_date"])
            # Usar la fecha más reciente (máxima)
            _fecha_conciliacion = _fechas.max().date()

        # Usar bytes guardados (el TemporaryDirectory ya fue destruido)
        _pt_source = results.get("_jde_bytes") or results.get("_jde_source_path", "")
        if _pt_source and _aux_facts:
            try:
                _reporter = ExcelReporter()
                _bank_accounts = results.get("_bank_accounts", [])
                # Extraer últimos 4 dígitos de cada cuenta (bancaria tiene 11, Papel tiene 4)
                _bank_accounts_last4 = [acct[-4:] for acct in _bank_accounts]
                _pt_bytes = _reporter.write_back_conciliados(
                    _pt_source, _aux_facts, match_date=_fecha_conciliacion, 
                    filter_accounts=_bank_accounts_last4,
                    strict_match_entries=_strict_entries,
                    amount_tolerance=float(results.get("_amount_tolerance", amount_tolerance_ui)),
                    require_full_strict_match=True,
                )
                with _dl_buttons[_btn_idx]:
                    # Usar la fecha elegida por el usuario o la de hoy
                    fecha_archivo = _fecha_descarga.strftime("%d-%m-%Y") if _fecha_descarga else datetime.now().strftime("%d-%m-%Y")
                    st.download_button(
                        label="⬇ Descargar Papel de Trabajo actualizado",
                        data=_pt_bytes,
                        file_name=f"PAPEL DE TRABAJO TRAJETAS {fecha_archivo}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            except Exception as _pt_err:
                import traceback
                st.warning(f"No se pudo generar el Papel de Trabajo actualizado: {_pt_err}")
                # DEBUG OPCIONAL (comentado por defecto) — muestra traceback en caso de error
                st.code(traceback.format_exc())
        elif results.get("_is_papel_trabajo"):
            st.info("No se encontraron Aux_Facts para marcar en el Papel de Trabajo.")

# ── Métricas ─────────────────────────────────────────────────
st.markdown("### Resumen")
c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

c1.metric("Movimientos Banco",  summary["total_bank_movements"])
c2.metric("Movimientos JDE",    summary["total_jde_movements"])
c3.metric("Matches exactos",    summary["exact_matches_count"])
c4.metric("Matches agrupados",  summary["grouped_matches_count"])
c5.metric("Agrupados inv.",     summary.get("reverse_grouped_matches_count", 0))
c6.metric("Pendientes Banco",   summary["pending_bank_count"],
          delta=f"-{summary['pending_bank_count']}" if summary["pending_bank_count"] else None,
          delta_color="inverse")
c7.metric("Pendientes JDE",     summary["pending_jde_count"],
          delta=f"-{summary['pending_jde_count']}" if summary["pending_jde_count"] else None,
          delta_color="inverse")

# ── Suma total de diferencias en centavos ──────────────────────
_all_diffs = (
    [m["amount_difference"] for m in results.get("exact_matches", [])]
    + [m["amount_difference"] for m in results.get("grouped_matches", [])]
    + [m["amount_difference"] for m in results.get("reverse_grouped_matches", [])]
)
if _all_diffs:
    _total_diff = round(sum(_all_diffs), 2)
    _n_with_diff = sum(1 for d in _all_diffs if abs(d) >= 0.01)
    _color = "normal" if abs(_total_diff) < 1.0 else "inverse"
    st.metric(
        label="Diferencia total en centavos (conciliados)",
        value=f"${_total_diff:,.2f}",
        delta=f"{_n_with_diff} match(es) con diferencia" if _n_with_diff else "Todos exactos al centavo",
        delta_color=_color,
    )

# ── Debug pequeño: filtro MercadoPago por color ─────────────────
_mp_dbg = results.get("_mp_color_filter_debug") or {}
if _mp_dbg.get("enabled"):
    st.caption(
        "🔎 MP color-filter: "
        f"filas {int(_mp_dbg.get('total_mp_rows_before', 0))} → {int(_mp_dbg.get('total_mp_rows_after', 0))} | "
        f"colores elegibles={len(_mp_dbg.get('eligible_colors', []))} | "
        f"montos Scotiabank={int(_mp_dbg.get('scotiabank_amounts_count', 0))}"
    )
    with st.expander("Ver detalle filtro MercadoPago", expanded=False):
        _colors = _mp_dbg.get("colors", [])
        if _colors:
            _df_colors = pd.DataFrame(_colors)
            _df_colors["Grupo #"] = range(1, len(_df_colors) + 1)
            _df_colors["Filas"] = _df_colors["rows"].fillna(0).astype(int)
            _df_colors["Total"] = pd.to_numeric(_df_colors["total"], errors="coerce").fillna(0.0)
            _df_colors["Match en Scotiabank"] = _df_colors["match_scotiabank"].apply(
                lambda v: "✅" if bool(v) else "❌"
            )

            _df_colors = _df_colors[["Grupo #", "Filas", "Total", "Match en Scotiabank"]]
            st.dataframe(
                _df_colors.style.format({"Total": "{:,.2f}"}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No hubo grupos de color para analizar.")
        st.caption(
            "Montos Scotiabank (muestra): "
            + ", ".join(str(v) for v in _mp_dbg.get("scotiabank_amounts_sample", []))
        )

st.markdown("---")

# ════════════════════════════════════════════════════════════
# TABS DE DETALLE
# ════════════════════════════════════════════════════════════

tab_conciliados, tab_pend_bank, tab_pend_jde, tab_historicos = st.tabs([
    f"✅ Conciliados ({summary['exact_matches_count'] + summary['grouped_matches_count'] + summary.get('reverse_grouped_matches_count', 0)})",
    f"🔴 Pendientes Banco ({summary['pending_bank_count']})",
    f"🔴 Pendientes JDE ({summary['pending_jde_count']})",
    "📋 Análisis Históricos",
])

# ── Tab: Conciliados ─────────────────────────────────────────
with tab_conciliados:
    conciliated = results.get("conciliated_bank_movements", pd.DataFrame())
    if conciliated.empty:
        st.warning("No se encontraron movimientos conciliados.")
    else:
        st.caption(f"{len(conciliated)} movimientos bancarios conciliados")
        disp = conciliated[["account_id", "movement_date", "description",
                             "amount_signed", "movement_type"]].copy()
        disp.columns = ["Cuenta", "Fecha", "Descripción", "Monto", "Tipo"]
        disp["Fecha"] = pd.to_datetime(disp["Fecha"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            disp.style.format({"Monto": "{:,.2f}"}),
            width="stretch",
            height=450,
        )

# ── Tab: Pendientes Banco ────────────────────────────────────
with tab_pend_bank:
    pend_bank = pending_bank_diag
    if pend_bank.empty:
        st.success("✅ Sin movimientos bancarios pendientes.")
    else:
        st.warning(f"{len(pend_bank)} movimientos bancarios sin conciliar")
        disp = pend_bank[["account_id", "movement_date", "description",
                           "amount_signed", "movement_type", "no_match_reason"]].copy()
        disp.columns = ["Cuenta", "Fecha", "Descripción", "Monto", "Tipo", "Por qué no concilió"]
        disp["Fecha"] = pd.to_datetime(disp["Fecha"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            disp.style.format({"Monto": "{:,.2f}"}),
            width="stretch",
            height=450,
        )

# ── Tab: Pendientes JDE ──────────────────────────────────────
with tab_pend_jde:
    pend_jde = pending_jde_diag
    if pend_jde.empty:
        st.success("✅ Sin movimientos JDE pendientes.")
    else:
        st.warning(f"{len(pend_jde)} movimientos JDE sin conciliar")
        disp = pend_jde[["account_id", "movement_date", "description",
                          "amount_signed", "movement_type", "no_match_reason"]].copy()
        disp.columns = ["Cuenta", "Fecha", "Descripción", "Monto", "Tipo", "Por qué no concilió"]
        disp["Fecha"] = pd.to_datetime(disp["Fecha"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            disp.style.format({"Monto": "{:,.2f}"}),
            width="stretch",
            height=450,
        )

# ── Tab: Análisis Históricos ──────────────────────────────────
with tab_historicos:
    if concil_ant_file is None:
        st.info(
            "Para analizar pendientes históricos, sube el archivo de "
            "**Conciliación Bancaria anterior** en el panel lateral (sección 4)."
        )
    else:
        # Parsear el Excel histórico
        with st.spinner("Leyendo pendientes históricos…"):
            try:
                hist_df = parse_conciliacion_excel(concil_ant_file.getvalue())
            except Exception as exc:
                logger.exception("Error al leer la conciliacion anterior: %s", exc)
                st.error("❌ No se pudo leer la conciliacion anterior. Verifica el archivo y revisa logs.")
                st.stop()

        if hist_df.empty:
            st.warning("No se encontraron pendientes en el archivo seleccionado.")
        else:
            hist_summary = get_pending_summary(hist_df)
            st.markdown(f"### Pendientes en `{concil_ant_file.name}`")

            # Métricas del archivo histórico
            hc1, hc2, hc3, hc4, hc5 = st.columns(5)
            hc1.metric("Total pendientes", hist_summary["total"])
            hc2.metric("Sección Más (Banco)",  hist_summary["mas_count"],
                       help="Registros en banco que aún no están en JDE")
            hc3.metric("Sección Menos (JDE)", hist_summary["menos_count"],
                       help="Registros en JDE que el banco aún no ha reflejado")
            hc4.metric("Monto Más (Banco)",
                       f"${hist_summary['mas_total']:,.2f}")
            hc5.metric("Monto Menos (JDE)",
                       f"${hist_summary['menos_total']:,.2f}")

            col_df, col_dt = st.columns(2)
            with col_df:
                if hist_summary["date_min"] and not pd.isnull(hist_summary["date_min"]):
                    st.caption(f"Fecha más antigua: **{hist_summary['date_min'].strftime('%d/%m/%Y')}**")
            with col_dt:
                if hist_summary["date_max"] and not pd.isnull(hist_summary["date_max"]):
                    st.caption(f"Fecha más reciente: **{hist_summary['date_max'].strftime('%d/%m/%Y')}**")

            st.markdown("---")

            # Modo estricto fijo: el cruce histórico siempre exige misma cuenta
            # (con compatibilidad cuenta corta/larga por sufijo).
            _hist_strict_account = True

            # Cruzar contra el período actual
            with st.spinner("Cruzando pendientes históricos con el período actual…"):
                matched_df = match_historical_pendientes(
                    hist_df=hist_df,
                    conciliated_bank=results.get("conciliated_bank_movements"),
                    conciliated_jde=results.get("conciliated_jde_movements"),
                    pending_bank=results.get("pending_bank_movements"),
                    pending_jde=results.get("pending_jde_movements"),
                    require_same_account=_hist_strict_account,
                )

            stats = summarize_historical_matches(matched_df)
            st.markdown("### Resultado del cruce con el período actual")

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("✅ Conciliados (este período)",
                       stats["conciliado"],
                       help="Ya se pudo conciliar: aparece tanto en banco como en JDE")
            sc2.metric("🟡 Pendiente Banco",
                       stats["pendiente_banco"],
                       help="Sigue en pendientes de banco: el banco lo tiene, falta en JDE")
            sc3.metric("🟠 Pendiente JDE",
                       stats["pendiente_jde"],
                       help="Sigue en pendientes de JDE: los libros lo tienen, el banco aún no lo refleja")
            sc4.metric("🔴 Sigue Pendiente",
                       stats["aun_pendiente"],
                       help="No se encontró en ninguna categoría del período actual")

            st.caption(
                f"**{stats['pct_resuelto']}%** de los pendientes históricos "
                f"se encontraron en el período actual  |  "
                f"Monto resuelto: **${stats['monto_resuelto']:,.2f}**  |  "
                f"Monto aún pendiente: **${stats['monto_aun_pendiente']:,.2f}**"
            )

            st.markdown("---")

            # Filtro de estado
            estados_disp = sorted(matched_df["match_status"].unique().tolist())
            estado_sel = st.multiselect(
                "Filtrar por estado:",
                options=estados_disp,
                default=estados_disp,
                key="hist_estado_filter",
            )
            seccion_sel = st.multiselect(
                "Filtrar por sección:",
                options=["mas", "menos"],
                default=["mas", "menos"],
                key="hist_seccion_filter",
            )
            score_min = st.slider(
                "Score mínimo de sugerencia:",
                min_value=0,
                max_value=100,
                value=0,
                step=5,
                key="hist_score_min",
                help="Muestra solo sugerencias con score igual o superior al valor elegido.",
            )

            show_only_ambiguous = st.checkbox(
                "Mostrar solo sugerencias ambiguas",
                value=False,
                key="hist_only_ambiguous",
                help="Útil para revisar primero casos con más de un candidato similar.",
            )

            disp_hist = matched_df[
                matched_df["match_status"].isin(estado_sel) &
                matched_df["section"].isin(seccion_sel)
            ].copy()

            if "match_score" in disp_hist.columns:
                disp_hist["match_score"] = pd.to_numeric(disp_hist["match_score"], errors="coerce").fillna(0)
                disp_hist = disp_hist[disp_hist["match_score"] >= score_min]

            if show_only_ambiguous and "match_ambiguous" in disp_hist.columns:
                disp_hist = disp_hist[disp_hist["match_ambiguous"] == True]

            # Orden inteligente: Estado -> Score desc -> Fecha histórica asc.
            status_rank = {
                "AUN_PENDIENTE": 0,
                "PENDIENTE_BANCO": 1,
                "PENDIENTE_JDE": 2,
                "CONCILIADO": 3,
            }
            disp_hist["_status_rank"] = disp_hist["match_status"].map(status_rank).fillna(99)
            disp_hist["_score_sort"] = pd.to_numeric(disp_hist.get("match_score", 0), errors="coerce").fillna(0)
            disp_hist = disp_hist.sort_values(
                by=["_status_rank", "_score_sort", "movement_date"],
                ascending=[True, False, True],
            ).drop(columns=["_status_rank", "_score_sort"], errors="ignore")

            if disp_hist.empty:
                st.info("No hay registros con los filtros seleccionados.")
            else:
                # Formatear para visualización
                display_cols = [
                    "account_id", "section", "movement_date",
                    "description", "abs_amount", "type_code",
                    "match_status", "match_detail", "match_date", "match_amount",
                    "match_source", "match_score", "match_candidates_count", "match_ambiguous", "match_reason",
                ]
                disp_h = disp_hist.reindex(columns=display_cols).copy()

                disp_h.columns = [
                    "Cuenta", "Sección", "Fecha Hist.",
                    "Descripción (histórico)", "Monto Hist.", "Tipo",
                    "Estado", "Desc. Período Actual", "Fecha Actual", "Monto Actual",
                    "Fuente Match", "Score", "# Candidatos", "Ambiguo", "Razón Match",
                ]

                if "Ambiguo" in disp_h.columns:
                    disp_h["Ambiguo"] = disp_h["Ambiguo"].apply(
                        lambda v: "SI" if bool(v) else "NO"
                    )

                # Formateo fechas
                for col_f in ("Fecha Hist.", "Fecha Actual"):
                    disp_h[col_f] = pd.to_datetime(disp_h[col_f], errors="coerce").apply(
                        lambda x: x.strftime("%d/%m/%Y") if not pd.isnull(x) else ""
                    )

                # Color por estado
                _STATUS_COLORS = {
                    "CONCILIADO":      "background-color: #D6F4D0",
                    "PENDIENTE_BANCO": "background-color: #FFF3CC",
                    "PENDIENTE_JDE":   "background-color: #FFE5CC",
                    "AUN_PENDIENTE":   "background-color: #FFD6D6",
                }

                def _color_row(row):
                    color = _STATUS_COLORS.get(row["Estado"], "")
                    return [color] * len(row)

                styled = (
                    disp_h.style
                    .apply(_color_row, axis=1)
                    .format({
                        "Monto Hist.":   "{:,.2f}",
                        "Monto Actual":  lambda x: f"{x:,.2f}" if pd.notnull(x) and x == x else "",
                        "Score":        lambda x: f"{float(x):.1f}" if pd.notnull(x) and str(x).strip() != "" else "",
                    })
                )

                st.dataframe(styled, width="stretch", height=500, hide_index=True)

                # Descargar como Excel
                @st.cache_data(show_spinner=False)
                def _to_excel_bytes(df: pd.DataFrame) -> bytes:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                        df.to_excel(writer, index=False, sheet_name="Históricos")
                    return buf.getvalue()

                excel_hist_bytes = _to_excel_bytes(disp_h)
                st.download_button(
                    label="⬇ Descargar análisis histórico (Excel)",
                    data=excel_hist_bytes,
                    file_name="historicos_conciliacion.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
