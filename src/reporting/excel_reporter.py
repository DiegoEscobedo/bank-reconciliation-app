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
            ("Agrupados inversos",       summary.get("reverse_grouped_matches_count", 0)),
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
                "Fuente":            bank_row.get("bank", "") or "",
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

        # Agrupados inversos: N banco → 1 JDE
        for m in results.get("reverse_grouped_matches", []):
            jde_row  = self._safe_get_row(jde_df, m["jde_row_index"])
            jde_part = _jde_rec(jde_row)
            # Una fila por cada movimiento bancario del grupo
            for bank_idx in m["bank_row_indices"]:
                bank_row = self._safe_get_row(bank_df, bank_idx)
                rec = {"Tipo Match": "Agrup. Inv.", "Diferencia": m["amount_difference"]}
                rec.update(_bank_rec(bank_row))
                rec.update(jde_part)
                records.append(rec)

        cols = [
            "Tipo Match",
            "Fecha Banco", "Cuenta Banco", "Fuente", "Tienda", "Tipo Pago", "Descripción Banco", "Monto Banco",
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
                   else ["Cuenta", "Fecha", "Fuente", "Tienda", "Tipo Pago", "Descripción", "Monto", "Origen"]
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
                out["Fuente"]     = df["bank"].fillna("") if "bank" in df.columns else ""
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
        source: "str | bytes",
        reconciled_aux_facts: list,
        match_date: "date | None" = None,
        debug_info: "dict | None" = None,
        filter_accounts: "list | None" = None,
    ) -> bytes:
        """
        Marca como conciliadas en el Papel de Trabajo las filas que
        corresponden a los Aux_Fact proporcionados.

        Estrategia: parche directo sobre el XML del ZIP original.
          1. openpyxl (data_only=True) solo LEE los valores cacheados para
             identificar qué filas marcar — nunca escribe nada.
          2. El XML del worksheet AUX CONTABLE se parchea directamente con
             regex/string: se insertan celdas AT (CONCILIADO="SÍ") y AU
             (FECHA) justo antes de </row> de cada fila a marcar.
          3. "SÍ" se agrega a sharedStrings.xml (el índice nuevo se usa en
             las celdas parcheadas). La fecha se escribe como inline string.
          4. El ZIP de salida es IDÉNTICO al original excepto por los dos
             archivos cambiados (worksheet + sharedStrings).  Así se
             preservan 100 %: filtros, colores, formatos condicionales,
             tablas, tablas dinámicas, estilos de celda, etc.

        Parámetros
        ----------
        source : str | bytes
            Ruta al Papel de Trabajo original (.xlsx) O sus bytes directos.
        reconciled_aux_facts : list
            Lista de valores Aux_Fact (str/int) a marcar.
        match_date : date, opcional
            Fecha de conciliación; por defecto hoy.
        filter_accounts : list, opcional
            Cuentas permitidas (ej: ['7133']) — solo marca filas de esas cuentas.
            Si no se proporciona, marca ALL filas.

        Retorna
        -------
        bytes — contenido del Excel modificado listo para descarga.
        """
        import re
        import zipfile
        from xml.etree import ElementTree as ET

        if match_date is None:
            match_date = date.today()

        # Normalizar source a bytes en memoria
        if isinstance(source, (bytes, bytearray)):
            src_bytes = bytes(source)
        else:
            with open(source, "rb") as f:
                src_bytes = f.read()

        src_buf = io.BytesIO(src_bytes)

        # ── 1. Parsear el ZIP sin openpyxl ────────────────────────────────────
        # Leemos los XMLs directamente: evitamos que openpyxl reescriba nada.
        with zipfile.ZipFile(src_buf, "r") as z:
            # Encontrar ruta interna de la hoja AUX CONTABLE
            wb_xml  = z.read("xl/workbook.xml")
            rel_xml = z.read("xl/_rels/workbook.xml.rels")
            wb_tree  = ET.fromstring(wb_xml)
            rel_tree = ET.fromstring(rel_xml)
            rels = {
                el.get("Id"): el.get("Target")
                for el in rel_tree
                if el.get("Target", "").startswith("worksheets/")
            }
            r_ns_key = (
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            sheet_name: str | None = None
            sheet_zip_path: str | None = None
            for candidate in ("AUX CONTABLE", "Detalle1"):
                for el in wb_tree.iter():
                    if el.get("name") == candidate:
                        r_id = el.get(r_ns_key)
                        if r_id and r_id in rels:
                            sheet_name = candidate
                            sheet_zip_path = "xl/" + rels[r_id]
                            break
                if sheet_zip_path:
                    break

            if sheet_zip_path is None:
                raise ValueError(
                    "No se encontró la hoja 'AUX CONTABLE' en el archivo."
                )

            if debug_info is not None:
                debug_info["sheet_zip_path"] = sheet_zip_path

            orig_ws_bytes = z.read(sheet_zip_path)
            orig_ss_bytes = z.read("xl/sharedStrings.xml")
            all_entries: list[tuple] = [
                (item, z.read(item.filename)) for item in z.infolist()
            ]

        orig_ws_xml = orig_ws_bytes.decode("utf-8")
        orig_ss_xml = orig_ss_bytes.decode("utf-8")

        # ── 2. Construir mapa de sharedStrings index → valor ─────────────────
        # Cada <si> puede ser texto simple (<si><t>val</t></si>) o rich text
        # (<si><r><rPr>...</rPr><t>val</t></r></si>).  Concatenamos todos los
        # <t> de cada bloque para obtener el valor visible.
        si_blocks = re.findall(r"<si>.*?</si>", orig_ss_xml, re.DOTALL)
        ss_values: list[str] = [
            "".join(re.findall(r"<t>([^<]*)</t>", blk))
            for blk in si_blocks
        ]

        # ── 3. Detectar fila de encabezado y columnas clave desde el XML ──────
        # Buscamos la primera fila donde alguna celda t="s" tiene el valor
        # "Aux_Fact" (cuyo índice en sharedStrings es típicamente 0).
        target_col_names = {"Aux_Fact", "CONCILIADO", "FECHA CONCILIACION", "Descripción", "Descripcion"}
        header_row_idx: int | None = None
        col_aux_letter: str | None = None
        col_conc_letter: str | None = None
        col_fecha_letter: str | None = None
        col_desc_letter: str | None = None  # Para filtrar por "CUENTA XXXX"

        # Iterar filas del worksheet XML buscando el encabezado
        for row_m in re.finditer(r"<row\b[^>]*>.*?</row>", orig_ws_xml, re.DOTALL):
            row_txt = row_m.group()
            r_m = re.search(r'\br="(\d+)"', row_txt)
            if not r_m:
                continue
            rn = int(r_m.group(1))

            # Mapa col_letter → valor string en esta fila
            cell_map: dict[str, str] = {}
            for c_m in re.finditer(
                r'<c\s+r="([A-Z]+)\d+"[^>]*t="s"[^>]*><v>(\d+)</v></c>',
                row_txt,
            ):
                col_letter = c_m.group(1)
                idx = int(c_m.group(2))
                if idx < len(ss_values):
                    cell_map[col_letter] = ss_values[idx]

            if "Aux_Fact" in cell_map.values():
                header_row_idx = rn
                for col_ltr, val in cell_map.items():
                    if val == "Aux_Fact":
                        col_aux_letter = col_ltr
                    elif val == "CONCILIADO":
                        col_conc_letter = col_ltr
                    elif val == "FECHA CONCILIACION":
                        col_fecha_letter = col_ltr
                    elif val in ("Descripción", "Descripcion"):
                        col_desc_letter = col_ltr
                break

        if debug_info is not None:
            debug_info["header_row_idx"] = header_row_idx
            debug_info["col_aux_letter"] = col_aux_letter
            debug_info["col_conc_letter"] = col_conc_letter
            debug_info["col_fecha_letter"] = col_fecha_letter
            debug_info["ss_count"] = len(ss_values)
            # Muestra los primeros 5 valores de sharedStrings para verificar
            debug_info["ss_head"] = ss_values[:5]

        if header_row_idx is None or col_aux_letter is None:
            raise ValueError(
                "No se pudo localizar el encabezado Aux_Fact en la hoja AUX CONTABLE."
            )

        # ── 4. Identificar filas a marcar ────────────────────────────────────
        # Aux_Fact puede ser:
        #   a) Fórmula con valor cacheado: <c r="A14"><f>...</f><v>2647414</v></c>
        #   b) Valor numérico directo:     <c r="A14"><v>2647414</v></c>
        #   c) Shared string t="s":        <c r="A14" t="s"><v>IDX</v></c>
        # Normalizar: "2647414.0" y "2647414" deben ser equivalentes
        reconciled_set: set[str] = set()
        for v in reconciled_aux_facts:
            sv = str(v).strip()
            reconciled_set.add(sv)
            try:
                reconciled_set.add(str(int(float(sv))))
            except (ValueError, OverflowError):
                pass
        rows_to_mark: list[int] = []
        _dbg_aux_vals: list = []  # primeros valores de Aux_Fact vistos en XML

        # DEBUG: Guardar estado inicial
        if debug_info is not None:
            debug_info["filter_accounts"] = filter_accounts
            debug_info["col_aux_letter"] = col_aux_letter
            debug_info["col_desc_letter"] = col_desc_letter
            debug_info["header_row_idx"] = header_row_idx
            debug_info["reconciled_set"] = list(reconciled_set)[:20]

        for row_m in re.finditer(r"<row\b[^>]*>.*?</row>", orig_ws_xml, re.DOTALL):
            row_txt = row_m.group()
            r_m = re.search(r'\br="(\d+)"', row_txt)
            if not r_m:
                continue
            rn = int(r_m.group(1))
            if rn <= header_row_idx:
                continue

            # Buscar la celda de Aux_Fact en esta fila
            aux_cell_m = re.search(
                rf'<c\s+r="{col_aux_letter}{rn}"[^>]*>(.*?)</c>',
                row_txt, re.DOTALL,
            )
            if not aux_cell_m:
                continue
            aux_inner = aux_cell_m.group(1)

            # Extraer valor
            aux_val = ""
            # Caso 1: tiene <v>
            v_m = re.search(r"<v>([^<]+)</v>", aux_inner)
            if v_m:
                raw = v_m.group(1).strip()
                # Si es shared string, resolver
                t_attr_m = re.search(r't="s"', aux_cell_m.group(0))
                if t_attr_m:
                    idx = int(raw)
                    aux_val = ss_values[idx] if idx < len(ss_values) else raw
                else:
                    # Valor numérico o texto; convertir a str de int si es posible
                    try:
                        aux_val = str(int(float(raw)))
                    except ValueError:
                        aux_val = raw

            if len(_dbg_aux_vals) < 10:
                _dbg_aux_vals.append({"row": rn, "raw_v": v_m.group(1).strip() if v_m else None, "aux_val": aux_val})

            if aux_val in reconciled_set:
                # Si hay filter_accounts, verificar que la cuenta de esta fila esté incluida
                should_mark = True
                if filter_accounts and col_desc_letter is not None:
                    # Extraer cuenta de la columna Descripción
                    desc_cell_m = re.search(
                        rf'<c\s+r="{col_desc_letter}{rn}"[^>]*>(.*?)</c>',
                        row_txt, re.DOTALL,
                    )
                    if desc_cell_m:
                        desc_inner = desc_cell_m.group(1)
                        # Extraer valor de descripción
                        desc_val = ""
                        v_m_desc = re.search(r"<v>([^<]+)</v>", desc_inner)
                        if v_m_desc:
                            raw_desc = v_m_desc.group(1).strip()
                            t_attr_m_desc = re.search(r't="s"', desc_cell_m.group(0))
                            if t_attr_m_desc:
                                idx_desc = int(raw_desc)
                                desc_val = ss_values[idx_desc] if idx_desc < len(ss_values) else raw_desc
                            else:
                                desc_val = raw_desc
                        
                        # Extraer número de cuenta del patrón "CUENTA XXXX"
                        cuenta_match = re.search(r"CUENTA\s+(\d+)", desc_val)
                        if cuenta_match:
                            row_account = cuenta_match.group(1)
                            should_mark = row_account in filter_accounts
                
                if should_mark:
                    rows_to_mark.append(rn)

        if debug_info is not None:
            debug_info["reconciled_set_sample"] = list(reconciled_set)[:10]
            debug_info["rows_to_mark"] = rows_to_mark[:20]
            debug_info["xml_aux_vals_sample"] = _dbg_aux_vals

        if not rows_to_mark:
            return src_bytes

        # ── 3. Agregar "SÍ" a sharedStrings.xml ─────────────────────────────
        si_idx: int | None = None
        for i, val in enumerate(ss_values):
            if val == "SÍ":
                si_idx = i
                break

        if si_idx is None:
            si_idx = len(ss_values)     # nuevo índice (0-based = actual count)
            new_ss_xml = orig_ss_xml.replace("</sst>", "<si><t>SÍ</t></si></sst>")
            # Actualizar contadores de atributos count / uniqueCount
            new_ss_xml = re.sub(
                r'count="(\d+)"',
                lambda m: f'count="{int(m.group(1)) + len(rows_to_mark)}"',
                new_ss_xml, count=1,
            )
            new_ss_xml = re.sub(
                r'uniqueCount="(\d+)"',
                lambda m: f'uniqueCount="{int(m.group(1)) + 1}"',
                new_ss_xml, count=1,
            )
        else:
            new_ss_xml = orig_ss_xml

        # ── 4. Parchear el worksheet XML directamente ────────────────────────
        # Para cada fila a marcar: eliminar celdas AT / AU existentes e
        # insertar las nuevas en la posición correcta (orden de columnas).
        rows_set = set(rows_to_mark)
        date_str = match_date.strftime("%d/%m/%Y")

        def _col2num(col: str) -> int:
            """Convierte letra(s) de columna Excel a número (A=1, Z=26, AA=27…)."""
            n = 0
            for ch in col.upper():
                n = n * 26 + (ord(ch) - 64)
            return n

        _fecha_col_num = _col2num(col_fecha_letter) if col_fecha_letter else 47

        def _patch_row(m: re.Match) -> str:
            row_txt = m.group(0)
            r_match = re.search(r'\br="(\d+)"', row_txt)
            if not r_match:
                return row_txt
            rn = int(r_match.group(1))
            if rn not in rows_set:
                return row_txt

            # Quitar celdas AT y AU actuales si existen (auto-close y con contenido)
            if col_conc_letter:
                row_txt = re.sub(
                    rf'<c\s+r="{col_conc_letter}{rn}"[^/]*/>', "", row_txt
                )
                row_txt = re.sub(
                    rf'<c\s+r="{col_conc_letter}{rn}"[^>]*>.*?</c>', "",
                    row_txt, flags=re.DOTALL,
                )
            if col_fecha_letter:
                row_txt = re.sub(
                    rf'<c\s+r="{col_fecha_letter}{rn}"[^/]*/>', "", row_txt
                )
                row_txt = re.sub(
                    rf'<c\s+r="{col_fecha_letter}{rn}"[^>]*>.*?</c>', "",
                    row_txt, flags=re.DOTALL,
                )

            # Construir nuevas celdas
            new_cells = ""
            if col_conc_letter:
                new_cells += (
                    f'<c r="{col_conc_letter}{rn}" t="s"><v>{si_idx}</v></c>'
                )
            if col_fecha_letter:
                new_cells += (
                    f'<c r="{col_fecha_letter}{rn}" t="inlineStr">'
                    f"<is><t>{date_str}</t></is></c>"
                )

            # Insertar en la posición correcta de columna, no al final.
            # OOXML exige que las celdas de una fila estén en orden ascendente
            # de columna; si hay celdas AV, AW… después de AU, insertar antes.
            insert_pos = None
            for cell_m in re.finditer(rf'<c\s+r="([A-Z]+){rn}"', row_txt):
                if _col2num(cell_m.group(1)) > _fecha_col_num:
                    insert_pos = cell_m.start()
                    break

            if insert_pos is not None:
                return row_txt[:insert_pos] + new_cells + row_txt[insert_pos:]
            else:
                return row_txt.replace("</row>", new_cells + "</row>")

        new_ws_xml = re.sub(
            r"<row\b[^>]*>.*?</row>", _patch_row, orig_ws_xml, flags=re.DOTALL
        )

        # ── 5. Construir ZIP de salida ────────────────────────────────────────
        # Idéntico al original, solo se reemplazan sheet5.xml y sharedStrings
        output_buf = io.BytesIO()
        with zipfile.ZipFile(output_buf, "w", zipfile.ZIP_DEFLATED) as out_zip:
            for item, data in all_entries:
                fname = item.filename
                if fname == sheet_zip_path:
                    out_zip.writestr(item, new_ws_xml.encode("utf-8"))
                elif fname == "xl/sharedStrings.xml":
                    out_zip.writestr(item, new_ss_xml.encode("utf-8"))
                else:
                    out_zip.writestr(item, data)

        output_buf.seek(0)
        return output_buf.read()

    @staticmethod
    def _safe_get_row(df: pd.DataFrame, idx) -> dict:
        try:
            return df.loc[idx].to_dict()
        except KeyError:
            return {}
