import io
import re
import unicodedata

import pandas as pd


def normalize_header_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.strip().upper().split())


def canonical_batch_token(value: object) -> str:
    token = str(value or "").strip()
    if token.upper() in {"", "NAN", "NONE", "NAT", "<NA>"}:
        return ""

    compact = token.replace(" ", "")
    try:
        if re.fullmatch(r"[-+]?\d+(\.0+)?", compact):
            compact = str(int(float(compact)))
    except (ValueError, OverflowError):
        pass
    return compact.upper()


def parse_batch_input(raw_text: str) -> set[str]:
    parts = re.split(r"[\s,;]+", str(raw_text or ""))
    tokens = {canonical_batch_token(p) for p in parts}
    return {t for t in tokens if t}


def parse_amount(value: object) -> float:
    text = str(value or "").strip()
    if text.upper() in {"", "NAN", "NONE", "NAT", "<NA>"}:
        return 0.0

    text = text.replace("$", "").replace(" ", "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.endswith("-"):
        negative = True
        text = text[:-1]

    text = text.replace(",", "")
    try:
        value_num = float(text)
    except ValueError:
        return 0.0

    return -abs(value_num) if negative else value_num


def extract_batch_preview(
    excel_bytes: bytes,
    batch_tokens: set[str],
    only_pending: bool = True,
) -> dict:
    if not batch_tokens:
        return {
            "aux_facts": [],
            "selected_rows": pd.DataFrame(),
            "stats": {"rows_total": 0, "rows_batch": 0, "rows_pending": 0},
            "total_amount": 0.0,
        }

    sheet_names_priority = ["AUX CONTABLE", "Detalle1"]
    batch_candidates = {
        "BATCH", "NO BATCH", "N BATCH", "NUMERO BATCH", "# BATCH",
        "LOTE", "NO LOTE", "NUMERO LOTE",
    }

    with pd.ExcelFile(io.BytesIO(excel_bytes)) as xl:
        sheet_name = next((s for s in sheet_names_priority if s in xl.sheet_names), None)
        if sheet_name is None:
            raise ValueError(f"No se encontro ninguna hoja valida: {sheet_names_priority}")

        raw = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=str).fillna("")
        if raw.empty:
            raise ValueError(f"La hoja '{sheet_name}' esta vacia")

    header_idx = -1
    for i, row in raw.iterrows():
        vals = [normalize_header_name(v) for v in row.values]
        if "AUX_FACT" in vals and any(v in batch_candidates for v in vals):
            header_idx = i
            break

    if header_idx < 0:
        raise ValueError("No se encontro encabezado con Aux_Fact y columna Batch/Lote")

    headers = [str(v).strip() for v in raw.iloc[header_idx].values]
    df = raw.iloc[header_idx + 1 :].copy().reset_index(drop=True)
    df.columns = headers

    if df.empty:
        return {
            "aux_facts": [],
            "selected_rows": pd.DataFrame(),
            "stats": {"rows_total": 0, "rows_batch": 0, "rows_pending": 0},
            "total_amount": 0.0,
        }

    normalized_cols = {normalize_header_name(c): c for c in df.columns}
    aux_col = normalized_cols.get("AUX_FACT")
    conc_col = normalized_cols.get("CONCILIADO")
    amount_col = normalized_cols.get("IMPORTE")
    desc_col = normalized_cols.get("EXPLICACION -OBSERVACION-") or normalized_cols.get("NOMBRE ALFA EXPLICACION")

    batch_col = None
    for candidate in batch_candidates:
        if candidate in normalized_cols:
            batch_col = normalized_cols[candidate]
            break

    if not aux_col:
        raise ValueError("No se encontro columna Aux_Fact")
    if not batch_col:
        raise ValueError("No se encontro columna Batch/Lote")

    work = df.copy()
    work["_batch_norm"] = work[batch_col].apply(canonical_batch_token)
    work["_aux_norm"] = work[aux_col].astype(str).str.strip()

    batch_mask = work["_batch_norm"].isin(batch_tokens)
    rows_batch = int(batch_mask.sum())

    if only_pending and conc_col:
        conc_norm = work[conc_col].astype(str).str.strip().str.upper()
        pending_mask = conc_norm.isin(["", "NAN", "NONE", "NAT", "0", "0.0"])
    else:
        pending_mask = pd.Series(True, index=work.index)

    selected = work[batch_mask & pending_mask].copy()

    aux_facts = []
    for value in selected["_aux_norm"].tolist():
        v = str(value or "").strip()
        if v and v.upper() not in {"NAN", "NONE"}:
            try:
                v = str(int(float(v)))
            except (ValueError, OverflowError):
                pass
            aux_facts.append(v)

    aux_facts = sorted(set(aux_facts))

    if amount_col:
        selected["_amount_num"] = selected[amount_col].apply(parse_amount)
        total_amount = float(selected["_amount_num"].sum())
    else:
        selected["_amount_num"] = 0.0
        total_amount = 0.0

    preview = pd.DataFrame({
        "batch": selected[batch_col].astype(str),
        "aux_fact": selected[aux_col].astype(str),
        "importe": selected[amount_col].astype(str) if amount_col else "",
        "importe_num": selected["_amount_num"],
        "conciliado": selected[conc_col].astype(str) if conc_col else "",
        "descripcion": selected[desc_col].astype(str) if desc_col else "",
    })

    stats = {
        "sheet": sheet_name,
        "rows_total": int(len(work)),
        "rows_batch": rows_batch,
        "rows_pending": int(len(selected)),
        "aux_facts": int(len(aux_facts)),
        "batch_column": str(batch_col),
        "amount_column": str(amount_col or ""),
    }

    return {
        "aux_facts": aux_facts,
        "selected_rows": preview.reset_index(drop=True),
        "stats": stats,
        "total_amount": total_amount,
    }
