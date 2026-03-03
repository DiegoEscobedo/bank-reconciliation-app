"""
excel_reporter.py — Genera el reporte Excel de conciliación.

Pestañas generadas:
    1. Resumen          — métricas clave
    2. Conciliados      — matches exactos y agrupados con detalle
    3. Pendientes Banco — movimientos bancarios sin match
    4. Pendientes JDE   — movimientos JDE sin match
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd


class ExcelReporter:
    """
    Genera un archivo Excel formateado con los resultados de la conciliación.
    """

    def generate(self, results: dict, output_dir: Path) -> Path:
        """
        Parámetros
        ----------
        results : dict
            Diccionario retornado por ReconciliationEngine.reconcile()
        output_dir : Path
            Directorio donde se guarda el archivo.

        Retorna
        -------
        Path al archivo generado.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = output_dir / f"conciliacion_{timestamp}.xlsx"

        with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
            wb = writer.book

            # ── Formatos ────────────────────────────────────────
            fmt_title   = wb.add_format({"bold": True, "font_size": 14, "font_color": "#FFFFFF", "bg_color": "#1F4E79", "align": "center", "valign": "vcenter"})
            fmt_header  = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#2E75B6", "align": "center", "valign": "vcenter", "border": 1})
            fmt_label   = wb.add_format({"bold": True, "bg_color": "#D6E4F0", "border": 1})
            fmt_value   = wb.add_format({"border": 1, "num_format": "#,##0.00"})
            fmt_value_s = wb.add_format({"border": 1})
            fmt_pos     = wb.add_format({"border": 1, "num_format": "#,##0.00", "font_color": "#1F6B28"})
            fmt_neg     = wb.add_format({"border": 1, "num_format": "#,##0.00", "font_color": "#C00000"})
            fmt_date    = wb.add_format({"border": 1, "num_format": "dd/mm/yyyy"})
            fmt_alt     = wb.add_format({"border": 1, "bg_color": "#EBF3FB"})
            fmt_alt_num = wb.add_format({"border": 1, "bg_color": "#EBF3FB", "num_format": "#,##0.00"})
            fmt_alt_dt  = wb.add_format({"border": 1, "bg_color": "#EBF3FB", "num_format": "dd/mm/yyyy"})

            self._write_summary(writer, wb, results["summary"], fmt_title, fmt_label, fmt_value, fmt_value_s)
            self._write_matches(writer, results, fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt)
            self._write_pending(writer, "Pendientes Banco", results["pending_bank_movements"], fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt)
            self._write_pending(writer, "Pendientes JDE",  results["pending_jde_movements"],  fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt)

        return file_path

    # ════════════════════════════════════════════════════════
    # HOJA 1 — RESUMEN
    # ════════════════════════════════════════════════════════

    def _write_summary(self, writer, wb, summary: dict, fmt_title, fmt_label, fmt_value, fmt_value_s):
        ws = writer.book.add_worksheet("Resumen")
        writer.sheets["Resumen"] = ws

        ws.set_column("A:A", 35)
        ws.set_column("B:B", 20)
        ws.merge_range("A1:B1", "RESUMEN DE CONCILIACIÓN", fmt_title)
        ws.set_row(0, 28)

        rows = [
            ("Movimientos bancarios",    summary["total_bank_movements"]),
            ("Movimientos JDE",          summary["total_jde_movements"]),
            ("Matches exactos",          summary["exact_matches_count"]),
            ("Matches agrupados",        summary["grouped_matches_count"]),
            ("Pendientes banco",         summary["pending_bank_count"]),
            ("Pendientes JDE",           summary["pending_jde_count"]),
        ]

        for i, (label, value) in enumerate(rows, start=1):
            ws.write(i, 0, label, fmt_label)
            ws.write(i, 1, value, fmt_value)

    # ════════════════════════════════════════════════════════
    # HOJA 2 — CONCILIADOS
    # ════════════════════════════════════════════════════════

    def _write_matches(self, writer, results: dict, fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt):
        exact   = results["exact_matches"]
        grouped = results["grouped_matches"]
        bank_df = results.get("_bank_df_full", results["conciliated_bank_movements"])
        jde_df  = results.get("_jde_df_full",  results["pending_jde_movements"])

        records = []

        def _bank_rec(bank_row):
            return {
                "Fecha Banco":       bank_row.get("movement_date"),
                "Cuenta Banco":      bank_row.get("account_id", ""),
                "Tienda":            bank_row.get("tienda", "") or "",
                "Tipo Pago":         bank_row.get("tipo_banco", "") or "",
                "Descripción Banco": bank_row.get("description", ""),
                "Monto Banco":       bank_row.get("amount_signed", 0),
            }

        def _jde_rec(jde_row):
            return {
                "Fecha JDE":         jde_row.get("movement_date"),
                "Cuenta JDE":        jde_row.get("account_id", ""),
                "Doc Tipo":          jde_row.get("doc_type", "") or "",
                "Documento JDE":     jde_row.get("document", "") or "",
                "Tienda JDE":        jde_row.get("tienda", "") or "",
                "Tipo JDE":          jde_row.get("tipo_jde", "") or "",
                "Descripción JDE":   jde_row.get("description", ""),
                "Monto JDE":         jde_row.get("amount_signed", 0),
            }

        for m in exact:
            bank_row = self._safe_get_row(bank_df, m["bank_row_index"])
            jde_row  = self._safe_get_row(jde_df,  m["jde_row_index"])
            rec = {"Tipo Match": "Exacto", "Diferencia": m["amount_difference"]}
            rec.update(_bank_rec(bank_row))
            rec.update(_jde_rec(jde_row))
            records.append(rec)

        for m in grouped:
            bank_row = self._safe_get_row(bank_df, m["bank_row_index"])
            bank_part = _bank_rec(bank_row)
            # Una fila por cada movimiento JDE del grupo
            for jde_idx in m["jde_row_indices"]:
                jde_row = self._safe_get_row(jde_df, jde_idx)
                rec = {"Tipo Match": "Agrupado", "Diferencia": m["amount_difference"]}
                rec.update(bank_part)
                rec.update(_jde_rec(jde_row))
                records.append(rec)

        cols = [
            "Tipo Match",
            "Fecha Banco", "Cuenta Banco", "Tienda", "Tipo Pago", "Descripción Banco", "Monto Banco",
            "Fecha JDE",   "Cuenta JDE",   "Doc Tipo", "Documento JDE", "Tienda JDE", "Tipo JDE", "Descripción JDE", "Monto JDE",
            "Diferencia",
        ]
        df = pd.DataFrame(records, columns=cols) if records else pd.DataFrame(columns=cols)

        self._df_to_sheet(writer, "Conciliados", df, fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt,
                          date_cols=["Fecha Banco", "Fecha JDE"],
                          amount_cols=["Monto Banco", "Monto JDE", "Diferencia"])

    # ════════════════════════════════════════════════════════
    # HOJAS 3 y 4 — PENDIENTES
    # ════════════════════════════════════════════════════════

    def _write_pending(self, writer, sheet_name: str, df: pd.DataFrame, fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt):
        is_jde = "JDE" in sheet_name

        if df.empty:
            base_cols = ["Cuenta", "Fecha", "Tienda", "Tipo", "Doc Tipo", "Documento", "Descripción", "Monto", "Origen"] if is_jde \
                   else ["Cuenta", "Fecha", "Tienda", "Tipo Pago", "Descripción", "Monto", "Origen"]
            out = pd.DataFrame(columns=base_cols)
        else:
            out = pd.DataFrame()
            out["Cuenta"]      = df["account_id"]
            out["Fecha"]       = df["movement_date"]
            # Tienda (banco o JDE)
            if "tienda" in df.columns:
                out["Tienda"] = df["tienda"].fillna("")
            else:
                out["Tienda"] = ""

            if is_jde:
                out["Tipo JDE"]   = df.get("tipo_jde",  pd.Series("", index=df.index)).fillna("")
                out["Doc Tipo"]   = df.get("doc_type",  pd.Series("", index=df.index)).fillna("")
                out["Documento"]  = df.get("document",  pd.Series("", index=df.index)).fillna("")
            else:
                out["Tipo Pago"]  = df.get("tipo_banco", pd.Series("", index=df.index)).fillna("")

            out["Descripción"] = df["description"]
            out["Monto"]       = df["amount_signed"]
            out["Origen"]      = df["source"]

        self._df_to_sheet(writer, sheet_name, out, fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date, fmt_alt, fmt_alt_num, fmt_alt_dt,
                          date_cols=["Fecha"], amount_cols=["Monto"])

    # ════════════════════════════════════════════════════════
    # HELPER: DataFrame → Hoja formateada
    # ════════════════════════════════════════════════════════

    def _df_to_sheet(self, writer, sheet_name: str, df: pd.DataFrame,
                     fmt_header, fmt_value, fmt_neg, fmt_pos, fmt_date,
                     fmt_alt, fmt_alt_num, fmt_alt_dt,
                     date_cols: list[str] = None,
                     amount_cols: list[str] = None):
        date_cols   = date_cols   or []
        amount_cols = amount_cols or []

        ws = writer.book.add_worksheet(sheet_name)
        writer.sheets[sheet_name] = ws

        # Header
        for col_idx, col_name in enumerate(df.columns):
            ws.write(0, col_idx, col_name, fmt_header)
            # Ancho de columna automático
            width = max(len(str(col_name)) + 4, 14)
            ws.set_column(col_idx, col_idx, width)

        # Datos
        for row_idx, (_, row) in enumerate(df.iterrows(), start=1):
            is_alt = row_idx % 2 == 0
            for col_idx, col_name in enumerate(df.columns):
                val = row[col_name]

                if col_name in date_cols:
                    fmt = fmt_alt_dt if is_alt else fmt_date
                    ws.write(row_idx, col_idx, val, fmt)

                elif col_name in amount_cols:
                    try:
                        num = float(val)
                    except (ValueError, TypeError):
                        num = 0.0
                    if is_alt:
                        ws.write(row_idx, col_idx, num, fmt_alt_num)
                    elif num < 0:
                        ws.write(row_idx, col_idx, num, fmt_neg)
                    else:
                        ws.write(row_idx, col_idx, num, fmt_pos)

                else:
                    fmt = fmt_alt if is_alt else fmt_value
                    ws.write(row_idx, col_idx, str(val) if val is not None else "", fmt)

        # Autofilter
        if len(df) > 0:
            ws.autofilter(0, 0, len(df), len(df.columns) - 1)

    # ════════════════════════════════════════════════════════
    # HELPER: acceso seguro a fila por índice
    # ════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────
    # WRITE-BACK — Papel de Trabajo
    # ──────────────────────────────────────────────────────────────

    def write_back_conciliados(
        self,
        source_path: str,
        reconciled_aux_facts: list,
        match_date: "date | None" = None,
    ) -> bytes:
        """
        Marca como conciliadas en el Papel de Trabajo las filas que
        corresponden a los Aux_Fact proporcionados.

        Parámetros
        ----------
        source_path : str
            Ruta al Papel de Trabajo original (.xlsx).
        reconciled_aux_facts : list
            Lista de valores Aux_Fact (str/int) a marcar.
        match_date : date, opcional
            Fecha de conciliación; por defecto hoy.

        Retorna
        -------
        bytes — contenido del Excel modificado listo para descarga.
        """
        if match_date is None:
            match_date = date.today()

        wb = openpyxl.load_workbook(source_path)

        sheet_name = next(
            (s for s in ("AUX CONTABLE", "Detalle1") if s in wb.sheetnames),
            None,
        )
        if sheet_name is None:
            raise ValueError("No se encontró la hoja 'AUX CONTABLE' en el archivo.")

        ws = wb[sheet_name]

        # ── Localizar columnas por encabezado ────────────────
        header_row_idx = None
        col_aux  = None
        col_conc = None
        col_fecha = None

        for row in ws.iter_rows():
            vals = [str(c.value).strip() if c.value is not None else "" for c in row]
            if "Aux_Fact" in vals and "Importe" in vals:
                header_row_idx = row[0].row
                for cell in row:
                    v = str(cell.value).strip() if cell.value else ""
                    if v == "Aux_Fact":
                        col_aux = cell.column
                    elif v == "CONCILIADO":
                        col_conc = cell.column
                    elif v == "FECHA CONCILIACION":
                        col_fecha = cell.column
                break

        if header_row_idx is None or col_aux is None:
            raise ValueError("No se pudo localizar el encabezado en la hoja AUX CONTABLE.")

        reconciled_set = {str(v).strip() for v in reconciled_aux_facts}
        updated = 0

        for row in ws.iter_rows(min_row=header_row_idx + 1):
            aux_cell = row[col_aux - 1]
            aux_val = str(aux_cell.value).strip() if aux_cell.value is not None else ""
            if aux_val in reconciled_set:
                if col_conc:
                    ws.cell(row=row[0].row, column=col_conc, value="Sí")
                if col_fecha:
                    ws.cell(row=row[0].row, column=col_fecha, value=match_date)
                updated += 1

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.read()

    @staticmethod
    def _safe_get_row(df: pd.DataFrame, idx) -> dict:
        try:
            return df.loc[idx].to_dict()
        except KeyError:
            return {}
