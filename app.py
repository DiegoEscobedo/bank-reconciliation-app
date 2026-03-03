"""
app.py — Interfaz Streamlit para el motor de conciliación bancaria.

Ejecución:
    streamlit run app.py
"""

import io
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from main import run_pipeline, run_pipeline_stage1, run_pipeline_stage2
from src.reporting.excel_reporter import ExcelReporter
from src.utils.logger import get_logger

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
        "Sube el reporte Auxiliar (R550911A1)",
        type=["csv", "xlsx", "xls"],
        key="jde",
        help="Reporte Auxiliar de Contabilidad exportado del JDE (CSV o Excel)"
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
    **Bancos soportados actualmente:** BBVA · Banorte
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

            st.session_state["stage1_data"] = stage1_data

            # Si no hay agrupaciones propuestas, finalizar directamente
            if not stage1_data["proposed_grouped_matches"]:
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
    stage1_data = st.session_state["stage1_data"]
    proposals   = stage1_data["proposed_grouped_matches"]
    exact_count = len(stage1_data["exact_matches"])

    st.title("Validación de Agrupaciones")
    st.info(
        f"Se encontraron **{len(proposals)}** agrupaciones propuestas "
        f"(además de **{exact_count}** matches exactos ya confirmados).\n\n"
        "Revisa cada agrupación y acepta o rechaza antes de finalizar. "
        "Pueden existir registros **atrasados de meses anteriores** — "
        "verifica las fechas y tiendas cuidadosamente."
    )

    col_all, col_none, col_spacer = st.columns([1, 1, 5])
    with col_all:
        if st.button("✅ Aceptar todas"):
            for p in proposals:
                st.session_state[f"grp_{p['group_id']}"] = True
            st.rerun()
    with col_none:
        if st.button("❌ Rechazar todas"):
            for p in proposals:
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
            checked = st.checkbox(
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

    accepted_count = sum(
        1 for p in proposals
        if st.session_state.get(f"grp_{p['group_id']}", True)
    )
    st.markdown(f"**{accepted_count} de {len(proposals)} agrupaciones seleccionadas**")

    if st.button("✅ Confirmar selección y finalizar conciliación", type="primary"):
        approved_ids = {
            p["group_id"] for p in proposals
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

_dl_cols = []
if results.get("_excel_bytes"):
    _dl_cols.append("conciliacion")
if results.get("_is_papel_trabajo"):
    _dl_cols.append("papel_trabajo")

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
            _aux_facts = [
                v for v in _conciliados_jde["_aux_fact"].dropna().unique()
                if str(v).strip() not in ("", "nan", "None")
            ]
        else:
            _aux_facts = []

        _pt_path = results.get("_jde_source_path", "")
        if _pt_path and _aux_facts:
            try:
                _reporter = ExcelReporter()
                _pt_bytes = _reporter.write_back_conciliados(
                    _pt_path, _aux_facts
                )
                with _dl_buttons[_btn_idx]:
                    st.download_button(
                        label="⬇ Descargar Papel de Trabajo actualizado",
                        data=_pt_bytes,
                        file_name="papel_de_trabajo_actualizado.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            except Exception as _pt_err:
                st.warning(f"No se pudo generar el Papel de Trabajo actualizado: {_pt_err}")
        elif results.get("_is_papel_trabajo"):
            st.info("No se encontraron Aux_Facts para marcar en el Papel de Trabajo.")

# ── Métricas ─────────────────────────────────────────────────
st.markdown("### Resumen")
c1, c2, c3, c4, c5, c6 = st.columns(6)

c1.metric("Movimientos Banco",  summary["total_bank_movements"])
c2.metric("Movimientos JDE",    summary["total_jde_movements"])
c3.metric("Matches exactos",    summary["exact_matches_count"])
c4.metric("Matches agrupados",  summary["grouped_matches_count"])
c5.metric("Pendientes Banco",   summary["pending_bank_count"],
          delta=f"-{summary['pending_bank_count']}" if summary["pending_bank_count"] else None,
          delta_color="inverse")
c6.metric("Pendientes JDE",     summary["pending_jde_count"],
          delta=f"-{summary['pending_jde_count']}" if summary["pending_jde_count"] else None,
          delta_color="inverse")

st.markdown("---")

# ════════════════════════════════════════════════════════════
# TABS DE DETALLE
# ════════════════════════════════════════════════════════════

tab_conciliados, tab_pend_bank, tab_pend_jde = st.tabs([
    f"✅ Conciliados ({summary['exact_matches_count'] + summary['grouped_matches_count']})",
    f"🔴 Pendientes Banco ({summary['pending_bank_count']})",
    f"🔴 Pendientes JDE ({summary['pending_jde_count']})",
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
