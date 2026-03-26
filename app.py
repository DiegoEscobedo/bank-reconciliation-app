"""
app.py — Interfaz Streamlit para el motor de conciliación bancaria.

Ejecución:
    streamlit run app.py
"""

import io
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from main import run_pipeline, run_pipeline_stage1, run_pipeline_stage2
from src.reporting.excel_reporter import ExcelReporter
from src.utils.logger import get_logger
from src.parsers.conciliacion_parser import parse_conciliacion_excel, get_pending_summary
from src.matching.historical_matcher import match_historical_pendientes, summarize_historical_matches

logger = get_logger(__name__)

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

                jde_path = tmp / jde_file.name
                jde_path.write_bytes(jde_file.getvalue())

                bank_paths = []
                for bf in bank_files:
                    bp = tmp / bf.name
                    bp.write_bytes(bf.getvalue())
                    bank_paths.append(str(bp))

                # Reporte Caja: se pasa junto a los bancarios;
                # el pipeline lo separa internamente por su etiqueta REPORTE_CAJA
                for rc in (reporte_caja_files or []):
                    rp = tmp / rc.name
                    rp.write_bytes(rc.getvalue())
                    bank_paths.append(str(rp))

                stage1_data = run_pipeline_stage1(
                    bank_file_path=bank_paths,
                    jde_file_path=str(jde_path),
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
            st.session_state["error"] = str(exc)
            logger.exception("Error en stage 1: %s", exc)

    st.rerun()

# ════════════════════════════════════════════════════════════
# MOSTRAR ERROR
# ════════════════════════════════════════════════════════════

if st.session_state.get("error"):
    st.error(f"❌ Error durante la conciliación:\n\n{st.session_state['error']}")
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
                    use_container_width=True,
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
                    use_container_width=True,
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
                    use_container_width=True,
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
                    use_container_width=True,
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
                st.session_state["error"] = str(exc)
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
        if "_aux_fact" in _conciliados_jde.columns:
            _aux_facts = []
            for _v in _conciliados_jde["_aux_fact"].dropna().unique():
                _sv = str(_v).strip()
                if _sv in ("", "nan", "None"):
                    continue
                # Normalizar float a entero: "2647414.0" → "2647414"
                try:
                    _sv = str(int(float(_sv)))
                except (ValueError, OverflowError):
                    pass
                _aux_facts.append(_sv)
        else:
            _aux_facts = []

        # Obtener fecha de los movimientos banco conciliados (fecha más reciente)
        _conciliados_banco = results.get("conciliated_bank_movements", pd.DataFrame())
        _fecha_conciliacion = None
        if not _conciliados_banco.empty and "movement_date" in _conciliados_banco.columns:
            _fechas = pd.to_datetime(_conciliados_banco["movement_date"])
            # Usar la fecha más reciente (máxima)
            _fecha_conciliacion = _fechas.max().date()

        # DEBUG OPCIONAL (comentado por defecto) — muestra qué aux_facts se encontraron
        st.caption(
            f"🔍 DEBUG write-back: is_papel={results.get('_is_papel_trabajo')} | "
            f"tiene_bytes={bool(results.get('_jde_bytes'))} | "
            f"aux_facts ({len(_aux_facts)}): {_aux_facts[:5]} | "
            f"fecha_conciliacion={_fecha_conciliacion}"
        )

        # Usar bytes guardados (el TemporaryDirectory ya fue destruido)
        _pt_source = results.get("_jde_bytes") or results.get("_jde_source_path", "")
        if _pt_source and _aux_facts:
            try:
                _reporter = ExcelReporter()
                _wb_debug: dict = {}
                _pt_bytes = _reporter.write_back_conciliados(
                    _pt_source, _aux_facts, match_date=_fecha_conciliacion, debug_info=_wb_debug
                )
                # DEBUG OPCIONAL (comentado por defecto) — muestra detalles del write-back
                with st.expander("🔬 Debug interno write_back", expanded=False):
                    st.write(_wb_debug)
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
    pend_bank = results.get("pending_bank_movements", pd.DataFrame())
    if pend_bank.empty:
        st.success("✅ Sin movimientos bancarios pendientes.")
    else:
        st.warning(f"{len(pend_bank)} movimientos bancarios sin conciliar")
        disp = pend_bank[["account_id", "movement_date", "description",
                           "amount_signed", "movement_type"]].copy()
        disp.columns = ["Cuenta", "Fecha", "Descripción", "Monto", "Tipo"]
        disp["Fecha"] = pd.to_datetime(disp["Fecha"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            disp.style.format({"Monto": "{:,.2f}"}),
            width="stretch",
            height=450,
        )

# ── Tab: Pendientes JDE ──────────────────────────────────────
with tab_pend_jde:
    pend_jde = results.get("pending_jde_movements", pd.DataFrame())
    if pend_jde.empty:
        st.success("✅ Sin movimientos JDE pendientes.")
    else:
        st.warning(f"{len(pend_jde)} movimientos JDE sin conciliar")
        disp = pend_jde[["account_id", "movement_date", "description",
                          "amount_signed", "movement_type"]].copy()
        disp.columns = ["Cuenta", "Fecha", "Descripción", "Monto", "Tipo"]
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
                st.error(f"❌ Error al leer la conciliación anterior: {exc}")
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

            # Cruzar contra el período actual
            with st.spinner("Cruzando pendientes históricos con el período actual…"):
                matched_df = match_historical_pendientes(
                    hist_df=hist_df,
                    conciliated_bank=results.get("conciliated_bank_movements"),
                    conciliated_jde=results.get("conciliated_jde_movements"),
                    pending_bank=results.get("pending_bank_movements"),
                    pending_jde=results.get("pending_jde_movements"),
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

            disp_hist = matched_df[
                matched_df["match_status"].isin(estado_sel) &
                matched_df["section"].isin(seccion_sel)
            ].copy()

            if disp_hist.empty:
                st.info("No hay registros con los filtros seleccionados.")
            else:
                # Formatear para visualización
                disp_h = disp_hist[[
                    "account_id", "section", "movement_date",
                    "description", "abs_amount", "type_code",
                    "match_status", "match_detail", "match_date", "match_amount",
                ]].copy()

                disp_h.columns = [
                    "Cuenta", "Sección", "Fecha Hist.",
                    "Descripción (histórico)", "Monto Hist.", "Tipo",
                    "Estado", "Desc. Período Actual", "Fecha Actual", "Monto Actual",
                ]

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
