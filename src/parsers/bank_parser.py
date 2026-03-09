"""
bank_parser.py — Parser unificado de estados de cuenta bancarios.

Detecta automáticamente el formato del CSV y delega al sub-parser
correspondiente. Actualmente soportados:

    • BBVA     — header en fila 0, columnas DEPÓSITOS / RETIROS
    • BANORTE  — fila 0 tiene el número de cuenta, header en fila 1,
                 columnas Cargo / Abono

Agrega soporte para nuevos bancos implementando un sub-parser que herede
de _BaseBankParser y registrándolo en BankParser._PARSERS.
"""

import pandas as pd

from config.settings import TIENDA_ABBREV as _TIENDA_ABBREV
from src.utils.date_utils import looks_like_date, parse_date_spanish
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════
# BASE
# ════════════════════════════════════════════════════════════

class _BaseBankParser:
    """Interfaz común para todos los sub-parsers bancarios."""

    BANK_NAME: str = "UNKNOWN"

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @staticmethod
    def _read_file(file_path: str) -> pd.DataFrame:
        """
        Lee el archivo bancario (CSV o Excel) y retorna un DataFrame sin header
        donde todas las celdas son strings.
        """
        path = str(file_path).lower()

        if path.endswith(".xlsx") or path.endswith(".xls"):
            # Leer Excel; convertir todo a str para que el resto del pipeline
            # funcione igual que con CSV.
            df = pd.read_excel(file_path, header=None, dtype=str)
            # pd.read_excel con dtype=str convierte fechas a '2026-02-24 00:00:00';
            # strip para limpiar espacios residuales.
            return df.fillna("")

        for encoding in ("utf-8-sig", "latin-1", "cp1252"):
            try:
                return pd.read_csv(
                    file_path,
                    header=None,
                    dtype=str,
                    encoding=encoding,
                    on_bad_lines="skip",
                )
            except UnicodeDecodeError:
                continue
        raise ValueError(f"No se pudo leer el archivo bancario: {file_path}")


# ════════════════════════════════════════════════════════════
# BBVA
# ════════════════════════════════════════════════════════════

class _BBVAParser(_BaseBankParser):
    """
    Formato BBVA:
        Fila 0 (header): CUENTA | FECHA DE OPERACIÓN | FECHA | REFERENCIA |
                         DESCRIPCIÓN | COD. TRANSAC | SUCURSAL |
                         DEPÓSITOS | RETIROS | SALDO | MOVIMIENTO |
                         DESCRIPCIÓN DETALLADA | CHEQUE
        Filas 1..n: datos
    """

    BANK_NAME = "BBVA"

    _COL_CUENTA    = "CUENTA"
    _COL_FECHA     = "FECHA DE OPERACIÓN"
    _COL_DESC      = "DESCRIPCIÓN"
    _COL_DESC_DET  = "DESCRIPCIÓN DETALLADA"
    _COL_DEPOSITOS = "DEPÓSITOS"
    _COL_RETIROS   = "RETIROS"

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        # La primera fila es el header real
        header = [str(c).strip() for c in raw.iloc[0]]
        df = raw.iloc[1:].copy()
        df.columns = header
        df = df.reset_index(drop=True)

        account_id = self._extract_account(df)
        logger.info("[BBVA] Cuenta detectada: %s", account_id)

        # Renombrar a nombres canónicos para el normalizador
        rename_map = {
            self._COL_FECHA:     "raw_date",
            self._COL_DESC:      "description",
            self._COL_DESC_DET:  "description_detail",
            self._COL_DEPOSITOS: "raw_deposit",
            self._COL_RETIROS:   "raw_withdrawal",
        }
        df = df.rename(columns=rename_map)

        # Filtrar filas sin fecha válida
        df = df[df["raw_date"].apply(looks_like_date)].copy()

        df["account_id"] = account_id
        df["bank"] = self.BANK_NAME

        keep = ["account_id", "bank", "raw_date",
                "description", "description_detail",
                "raw_deposit", "raw_withdrawal"]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    def _extract_account(self, df: pd.DataFrame) -> str:
        if self._COL_CUENTA in df.columns:
            val = str(df[self._COL_CUENTA].iloc[0]).strip()
            return val.lstrip("'")          # quitar apóstrofo inicial
        return "UNKNOWN"


# ════════════════════════════════════════════════════════════
# BANORTE
# ════════════════════════════════════════════════════════════

class _BanorteParser(_BaseBankParser):
    """
    Formato Banorte:
        Fila 0: Cuenta | <número de cuenta> | ...
        Fila 1 (header): Fecha Operación | Concepto | Referencia |
                         Referencia Ampliada | Cargo | Abono | Saldo
        Filas 2..n: datos
    """

    BANK_NAME = "BANORTE"

    _COL_FECHA    = "Fecha Operación"
    _COL_CONCEPTO = "Concepto"
    _COL_REF_AMP  = "Referencia Ampliada"
    _COL_CARGO    = "Cargo"
    _COL_ABONO    = "Abono"

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        account_id = self._extract_account(raw)
        logger.info("[BANORTE] Cuenta detectada: %s", account_id)

        # Fila 1 es el header real
        header = [str(c).strip() for c in raw.iloc[1]]
        df = raw.iloc[2:].copy()
        df.columns = header
        df = df.reset_index(drop=True)

        rename_map = {
            self._COL_FECHA:    "raw_date",
            self._COL_CONCEPTO: "description",
            self._COL_REF_AMP:  "description_detail",
            self._COL_CARGO:    "raw_withdrawal",   # Cargo = dinero sale
            self._COL_ABONO:    "raw_deposit",      # Abono = dinero entra
        }
        df = df.rename(columns=rename_map)

        # Filtrar filas sin fecha válida
        df = df[df["raw_date"].apply(looks_like_date)].copy()

        df["account_id"] = account_id
        df["bank"] = self.BANK_NAME

        keep = ["account_id", "bank", "raw_date",
                "description", "description_detail",
                "raw_deposit", "raw_withdrawal"]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    @staticmethod
    def _extract_account(raw: pd.DataFrame) -> str:
        # Fila 0, columna 1 tiene el número de cuenta
        try:
            val = str(raw.iloc[0, 1]).strip()
            return val if val not in ("", "nan") else "UNKNOWN"
        except Exception:
            return "UNKNOWN"


# SCOTIABANK

class _ScotiabankParser(_BaseBankParser):
    """
    Formato Scotiabank (Excel sin fila de header):
        Col 0  → tipo (CHQ…)
        Col 1  → moneda (MXN)
        Col 3  → número de cuenta completo
        Col 4  → fecha (YYYY-MM-DD HH:MM:SS)
        Col 5  → referencia
        Col 6  → monto (siempre positivo)
        Col 7  → 'Cargo' (retiro) | 'Abono' (depósito)
        Col 9  → descripción
        Col 13 → descripción detallada
    """

    BANK_NAME = "SCOTIABANK"

    _IDX_ACCOUNT = 3
    _IDX_DATE    = 4
    _IDX_REF     = 5
    _IDX_AMOUNT  = 6
    _IDX_TYPE    = 7
    _IDX_DESC    = 9
    _IDX_DETAIL  = 13

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        # Filtrar filas con monto vacío (filas en blanco)
        df = raw[raw.iloc[:, self._IDX_AMOUNT].str.strip().ne("")].copy()
        df = df.reset_index(drop=True)

        account_id = str(df.iloc[0, self._IDX_ACCOUNT]).strip() if len(df) else "UNKNOWN"
        logger.info("[SCOTIABANK] Cuenta detectada: %s", account_id)

        result = pd.DataFrame({
            "account_id":          df.iloc[:, self._IDX_ACCOUNT].astype(str).str.strip(),
            "bank":                self.BANK_NAME,
            "raw_date":            df.iloc[:, self._IDX_DATE].astype(str).str.strip(),
            "description":         df.iloc[:, self._IDX_DESC].astype(str).str.strip(),
            "description_detail":  df.iloc[:, self._IDX_DETAIL].astype(str).str.strip().replace("nan", ""),
            "raw_deposit":         df.apply(
                lambda r: r.iloc[self._IDX_AMOUNT] if str(r.iloc[self._IDX_TYPE]).strip() == "Abono" else "",
                axis=1,
            ),
            "raw_withdrawal":      df.apply(
                lambda r: r.iloc[self._IDX_AMOUNT] if str(r.iloc[self._IDX_TYPE]).strip() == "Cargo" else "",
                axis=1,
            ),
        })

        return result.reset_index(drop=True)


# ════════════════════════════════════════════════════════════
# NETPAY
# ════════════════════════════════════════════════════════════

class _NetPayParser(_BaseBankParser):
    """
    Formato NetPay (Excel): encabezados en una fila variable (busca
    dinámicamente hasta la fila 30). Columnas detectadas por nombre:
        Fecha de Movimiento / Fecha  → raw_date
        Clave de Rastreo / Referencia → description
        Cuenta Destino / Cuenta Depósito → account_id
        Monto de Trx / Monto TRX / Monto Depósito → raw_deposit
    Todos los movimientos son DEPÓSITOS al banco destino.
    """

    BANK_NAME = "NETPAY"

    # Palabras clave para mapear columnas (orden: preferida → fallback)
    _COL_DATE    = ("FECHA DE MOVIMIENTO", "FECHA MOVIMIENTO", "FECHA")
    _COL_ACCOUNT = ("CUENTA DESTINO", "CUENTA DEPÓSITO", "CUENTA DEPOSITO", "CUENTA")
    _COL_DESC    = ("DESCRIPCIÓN", "DESCRIPCION", "CLAVE DE RASTREO", "REFERENCIA")
    _COL_AMOUNT  = ("MONTO DE TRX", "MONTO DE TRANSACCIÓN", "MONTO TRX", "MONTO TRANSACCION", "MONTO DEPÓSITO", "MONTO DEPOSITO", "MONTO")

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        # ── 1. Detectar fila de encabezado ────────────────────────────
        header_row_idx = None
        col_map: dict[str, int] = {}

        for _ri in range(min(30, len(raw))):
            row_vals = raw.iloc[_ri].fillna("").astype(str)
            row_upper = [v.strip().upper() for v in row_vals]
            # Buscar al menos fecha + monto en esta fila
            has_fecha = any("FECHA" in v for v in row_upper)
            has_monto = any("MONTO" in v for v in row_upper)
            if has_fecha and has_monto:
                header_row_idx = _ri
                for _ci, _v in enumerate(row_upper):
                    col_map[_v] = _ci
                break

        if header_row_idx is None:
            logger.warning("[NETPAY] No se encontró fila de encabezado, usando defaults.")
            header_row_idx = 9
            # Fallback a índices fijos legacy
            col_map = {}

        def _find_col(keywords, default=None):
            for kw in keywords:
                if kw in col_map:
                    return col_map[kw]
            # Búsqueda parcial
            for kw in keywords:
                for k, v in col_map.items():
                    if kw in k:
                        return v
            return default

        idx_date    = _find_col(self._COL_DATE,    default=2)
        idx_account = _find_col(self._COL_ACCOUNT, default=4)
        idx_desc    = _find_col(self._COL_DESC,    default=5)
        idx_amount  = _find_col(self._COL_AMOUNT,  default=6)

        logger.info(
            "[NETPAY] Header fila=%d | fecha=%d cuenta=%d desc=%d monto=%d",
            header_row_idx, idx_date, idx_account, idx_desc, idx_amount,
        )

        # ── 2. Extraer filas de datos ─────────────────────────────────
        data = raw.iloc[header_row_idx + 1:].copy().reset_index(drop=True)
        data = data.fillna("").astype(str)

        # Filtrar filas vacías o de totales
        data = data[
            data.iloc[:, idx_date].str.strip().ne("") &
            data.iloc[:, idx_date].str.strip().str.upper().ne("TOTAL") &
            data.iloc[:, idx_amount].str.strip().ne("")
        ].copy().reset_index(drop=True)

        if data.empty:
            return pd.DataFrame(columns=["account_id", "bank", "raw_date",
                                         "description", "description_detail",
                                         "raw_deposit", "raw_withdrawal"])

        # account_id desde primera fila válida
        account_id = str(data.iloc[0, idx_account]).strip()
        logger.info("[NETPAY] Cuenta destino: %s", account_id)

        result = pd.DataFrame({
            "account_id":         account_id,
            "bank":               self.BANK_NAME,
            "raw_date":           data.iloc[:, idx_date].str.strip(),
            "description":        data.iloc[:, idx_desc].str.strip(),
            "description_detail": "",
            "raw_deposit":        data.iloc[:, idx_amount].str.strip(),
            "raw_withdrawal":     "",
        })
        return result.reset_index(drop=True)


# ════════════════════════════════════════════════════════════
# MERCADO PAGO
# ════════════════════════════════════════════════════════════

class _MercadoPagoParser(_BaseBankParser):
    """
    Formato Mercado Pago (Excel):
        Fila 3  → header con 38 columnas
        Fila 4+ → datos
    Columnas usadas:
        col0  → Número de operación
        col1  → Fecha de la compra  ('18 feb 19:14 hs')
        col2  → Estado              (filtrar solo 'Aprobado')
        col8  → Total a recibir     (neto después de comisiones)
        col34 → Sucursal            (descripción)
    Todos son DEPÓSITOS. account_id = "7133" (Scotiabank destino).
    """

    BANK_NAME        = "MERCADOPAGO"
    _DESTINATION_ACT = "7133"   # Scotiabank donde deposita MP

    _HEADER_ROW  = 3
    _IDX_FOLIO   = 0
    _IDX_DATE    = 1
    _IDX_STATUS  = 2
    _IDX_AMOUNT  = 8
    _IDX_SUCURSAL = 34

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        data = raw.iloc[self._HEADER_ROW + 1:].copy().reset_index(drop=True)

        # Filtrar solo aprobados con monto válido
        status  = data.iloc[:, self._IDX_STATUS].astype(str).str.strip()
        amounts = data.iloc[:, self._IDX_AMOUNT].astype(str).str.strip()
        data = data[
            status.str.lower().eq("aprobado") &
            amounts.ne("") & amounts.ne("nan") & amounts.ne("0")
        ].copy().reset_index(drop=True)

        if data.empty:
            return pd.DataFrame(columns=["account_id", "bank", "raw_date",
                                         "description", "description_detail",
                                         "raw_deposit", "raw_withdrawal"])

        logger.info("[MERCADOPAGO] Cuenta destino: %s", self._DESTINATION_ACT)

        # Las fechas vienen como '18 feb 19:14 hs' → convertir a DD/MM/YYYY
        dates_raw = data.iloc[:, self._IDX_DATE].astype(str).str.strip()
        dates_fmt = dates_raw.apply(
            lambda v: parse_date_spanish(v).strftime("%d/%m/%Y")
            if parse_date_spanish(v) is not pd.NaT else v
        )

        folio     = data.iloc[:, self._IDX_FOLIO].astype(str).str.strip()
        sucursales = data.iloc[:, self._IDX_SUCURSAL].astype(str).str.strip().replace("nan", "")

        result = pd.DataFrame({
            "account_id":         self._DESTINATION_ACT,
            "bank":               self.BANK_NAME,
            "raw_date":           dates_fmt,
            "description":        "MERCADO PAGO | " + sucursales,
            "description_detail": folio,
            "raw_deposit":        data.iloc[:, self._IDX_AMOUNT].astype(str).str.strip(),
            "raw_withdrawal":     "",
        })
        return result.reset_index(drop=True)


# ════════════════════════════════════════════════════════════
# REPORTE (banco enriquecido con tienda+tipo por el usuario)
# ════════════════════════════════════════════════════════════

class _ReporteParser(_BaseBankParser):
    """
    Formato REPORTE.xlsx — Hoja2:
        Fila 0 (header): CUENTA | FECHA DE OPERACIÓN | FECHA | REFERENCIA |
                         DESCRIPCIÓN | COD. TRANSAC | SUCURSAL |
                         DEPÓSITOS | RETIROS | SALDO | MOVIMIENTO |
                         DESCRIPCIÓN DETALLADA | CHEQUE | TPV
        Filas 1..n: datos

    La columna 13 ("TPV") contiene la clasificación que el usuario agregó
    con fórmulas Excel: p. ej. "OUG TPV", "FAB TR", "FRE 03".
    Esta se parsea para extraer tienda y tipo_banco.
    """

    BANK_NAME = "REPORTE"

    _TIPOS_BANCO = {"TPV", "TR", "01", "03", "04", "28"}

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        # raw = Hoja2, fila 0 = cabeceras
        header = [str(c).strip() for c in raw.iloc[0]]
        df = raw.iloc[1:].copy()
        # Asignar nombres de columna; si hay más columnas que cabeceras, usar índice
        df.columns = [
            header[i] if i < len(header) else f"_col{i}"
            for i in range(len(raw.columns))
        ]
        df = df.reset_index(drop=True)

        # Cuenta (col 0 = CUENTA)
        raw_cuenta = df.get("CUENTA", df.iloc[:, 0]).astype(str)
        df["account_id"] = raw_cuenta.str.strip().str.lstrip("'")
        account_id = df["account_id"].mode()[0] if not df.empty else "UNKNOWN"
        logger.info("[REPORTE] Cuenta detectada: %s", account_id)

        # Fecha de liquidación (col 2 = FECHA)
        fecha_col = header[2] if len(header) > 2 else "FECHA"
        df["raw_date"] = df.get(fecha_col, df.iloc[:, 2]).astype(str)

        # Montos: col 7 = DEPÓSITOS, col 8 = RETIROS
        col_dep = header[7] if len(header) > 7 else "DEPÓSITOS"
        col_ret = header[8] if len(header) > 8 else "RETIROS"
        df["raw_deposit"]    = df.get(col_dep, df.iloc[:, 7]).astype(str)
        df["raw_withdrawal"] = df.get(col_ret, df.iloc[:, 8]).astype(str)

        # Descripción: col 4 y col 11
        col_desc = header[4] if len(header) > 4 else "DESCRIPCIÓN"
        col_det  = header[11] if len(header) > 11 else "DESCRIPCIÓN DETALLADA"
        df["description"]        = df.get(col_desc, df.iloc[:, 4]).astype(str)
        df["description_detail"] = (
            df.get(col_det, df.iloc[:, 11]).astype(str)
            if len(df.columns) > 11 else ""
        )

        # Clasificación tienda+tipo (col 13 = TPV)
        col_tpv = header[13] if len(header) > 13 else "TPV"
        clasificacion = df.get(col_tpv, df.iloc[:, 13]).astype(str)
        parsed_tpv   = clasificacion.apply(self._parse_clasificacion)
        df["tienda"]     = parsed_tpv.apply(lambda x: x[0])
        df["tipo_banco"] = parsed_tpv.apply(lambda x: x[1])

        # Filtrar filas sin fecha válida
        df = df[df["raw_date"].apply(looks_like_date)].copy()
        df["account_id"] = account_id
        df["bank"]       = self.BANK_NAME

        keep = [
            "account_id", "bank", "raw_date",
            "description", "description_detail",
            "raw_deposit", "raw_withdrawal",
            "tienda", "tipo_banco",
        ]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    def _parse_clasificacion(self, value: str):
        """Parsea "OUG TPV" → ("OUG", "TPV"),  "FRE 03" → ("FRE", "03")."""
        value = str(value).strip()
        if not value or value in ("", "nan", "-"):
            return (None, None)
        parts = value.split()
        if len(parts) >= 2:
            tipo = parts[-1].upper()
            if tipo in self._TIPOS_BANCO:
                tienda = " ".join(parts[:-1]).upper()
                return (tienda, tipo)
        return (None, None)


# ════════════════════════════════════════════════════════════
# REPORTE CAJA  (resumen diario por tienda: fecha|banco|monto|tienda|tipo)
# ════════════════════════════════════════════════════════════


class _ReporteCajaParser(_BaseBankParser):
    """
    Formato REPORTE CAJA.xlsx — Hoja1:
        Filas 0..N: título / vacías (cantidad variable)
        Fila N+1 (header): FECHA | Banco | Monto | TIENDA | OBSERVACION(ES)
        Filas N+2..n: datos

    El parser detecta automáticamente la fila de cabeceras buscando
    la palabra "FECHA" en la columna 0 o "TIENDA" en cualquier columna.

    Columnas:
        Col 0  → FECHA (fecha del depósito)
        Col 1  → Banco  (p. ej. "BANORTE 6614", "BBVA 4640")
        Col 2  → Monto  (depósito)
        Col 3  → TIENDA (nombre completo, p. ej. "OUTLET JALPA")
        Col 4  → OBSERVACION / OBSERVACIONES ("TR", "TPV" o vacío=efectivo)
    """

    BANK_NAME = "REPORTE_CAJA"

    # Palabras clave que identifican la fila de cabeceras
    _HEADER_KEYWORDS = {"FECHA", "TIENDA", "MONTO", "BANCO"}

    def _find_header_row(self, raw: pd.DataFrame) -> int:
        """Devuelve el índice (0-based) de la fila de cabeceras."""
        for i, row in raw.iterrows():
            row_vals = {str(v).strip().upper() for v in row.values if str(v).strip()}
            if len(row_vals & self._HEADER_KEYWORDS) >= 2:
                return i
        return 0  # fallback: primera fila

    def parse_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        header_idx = self._find_header_row(raw)
        # La fila de cabeceras se usa como nombres de columna
        header_row  = raw.iloc[header_idx]
        df = raw.iloc[header_idx + 1:].copy().reset_index(drop=True)
        df.columns = [str(c).strip() for c in header_row.values]

        # Resolver nombres de columna con variantes posibles
        def _col(candidates):
            """Devuelve el nombre de columna que coincida (case-insensitive)."""
            for c in df.columns:
                if c.strip().upper() in {x.upper() for x in candidates}:
                    return c
            return None

        col_fecha  = _col(["FECHA"])
        col_banco  = _col(["BANCO", "BANK"])
        col_monto  = _col(["MONTO", "IMPORTE", "AMOUNT"])
        col_tienda = _col(["TIENDA", "SUCURSAL", "STORE"])
        col_obs    = _col(["OBSERVACION", "OBSERVACIONES", "OBS", "TIPO", "TIPO PAGO"])

        rows = []
        for _, row in df.iterrows():
            fecha      = str(row[col_fecha]).strip()  if col_fecha  else str(row.iloc[0]).strip()
            banco      = str(row[col_banco]).strip()  if col_banco  else str(row.iloc[1]).strip()
            monto      = str(row[col_monto]).strip()  if col_monto  else str(row.iloc[2]).strip()
            tienda_raw = str(row[col_tienda]).strip() if col_tienda else (str(row.iloc[3]).strip() if len(row) > 3 else "")
            obs        = str(row[col_obs]).strip()    if col_obs    else (str(row.iloc[4]).strip() if len(row) > 4 else "")

            # Saltar filas vacías o sin fecha/monto
            if not looks_like_date(fecha) or monto in ("", "nan", "0"):
                continue

            # Extraer account_id del campo Banco ("BANORTE 6614" → "6614")
            account_id = self._extract_account_from_banco(banco)

            # Mapear tienda a abreviatura JDE
            tienda_abbrev = _TIENDA_ABBREV.get(tienda_raw.upper(), None)

            # Tipo banco: TR / TPV / None (efectivo sin tipo explícito)
            obs_clean = obs.strip().upper()
            tipo_banco = obs_clean if obs_clean in ("TR", "TPV") else None

            rows.append({
                "account_id":        account_id,
                "bank":              self.BANK_NAME,
                "raw_date":          fecha,
                "description":       f"{tienda_raw} | {obs_clean}" if obs_clean else tienda_raw,
                "description_detail": banco,
                "raw_deposit":       monto,
                "raw_withdrawal":    "",
                "tienda":            tienda_abbrev,
                "tipo_banco":        tipo_banco,
            })

        result = pd.DataFrame(rows)
        if result.empty:
            return result

        # Agrupar multiples cuentas por si el reporte mezcla (6614, 4640…)
        accounts = result["account_id"].unique()
        logger.info("[REPORTE_CAJA] Cuentas detectadas: %s", accounts.tolist())
        return result.reset_index(drop=True)

    @staticmethod
    def _extract_account_from_banco(banco: str) -> str:
        """"BANORTE 6614" → "6614",  "BBVA 4640" → "4640"."""
        parts = banco.split()
        if parts:
            return parts[-1]  # último token es el número de cuenta
        return "UNKNOWN"


# ════════════════════════════════════════════════════════════
# PARSER PRINCIPAL (auto-detección)
# ════════════════════════════════════════════════════════════

class BankParser:
    """
    Parser unificado. Detecta el formato automáticamente por las columnas
    del CSV y delega al sub-parser correcto.

    Uso:
        df_raw = BankParser().parse("estado_cuenta.csv")
    """

    # Registro de sub-parsers. Para agregar un banco nuevo:
    # 1. Crear clase _MiBancoParser(_BaseBankParser)
    # 2. Añadirla aquí
    _PARSERS: list[type[_BaseBankParser]] = [
        _BBVAParser,
        _BanorteParser,
        _ScotiabankParser,
        _NetPayParser,
        _MercadoPagoParser,
    ]

    def parse(self, file_path: str) -> pd.DataFrame:
        logger.info("Parseando banco: %s", file_path)

        # Detección especial REPORTE: xlsx con hoja "Hoja2" y columna "TPV"
        path_lower = str(file_path).lower()
        if path_lower.endswith((".xlsx", ".xls")):
            try:
                xl = pd.ExcelFile(file_path)

                # REPORTE CAJA: intentar primero por nombre de archivo,
                # luego por contenido (independientemente de las hojas presentes).
                _fname_upper = str(file_path).upper()
                _force_reporte_caja = (
                    "REPORTE CAJA" in _fname_upper
                    or "REPORTE_CAJA" in _fname_upper
                )

                hoja1 = pd.read_excel(
                    file_path, sheet_name=0,
                    header=None, dtype=str
                ).fillna("")

                _is_reporte_caja = False
                if _force_reporte_caja:
                    _is_reporte_caja = True
                else:
                    # Detectar si alguna de las primeras 5 filas tiene cabeceras de caja
                    _keywords = {"FECHA", "TIENDA", "BANCO", "MONTO"}
                    for _i in range(min(5, len(hoja1))):
                        _row_vals = {str(v).strip().upper() for v in hoja1.iloc[_i].values}
                        if len(_row_vals & _keywords) >= 3:
                            _is_reporte_caja = True
                            break
                    # También detectar por A1 == "TIENDAS" (formato anterior)
                    if not _is_reporte_caja and len(hoja1) > 0:
                        _is_reporte_caja = str(hoja1.iloc[0, 0]).strip().upper() == "TIENDAS"

                if _is_reporte_caja:
                    logger.info("Formato bancario detectado: REPORTE_CAJA")
                    result = _ReporteCajaParser().parse_raw(hoja1)
                    logger.info("[REPORTE_CAJA] Filas parseadas: %d", len(result))
                    return result

                # REPORTE (banco enriquecido con Hoja2 + columna TPV)
                if "Hoja2" in xl.sheet_names:
                    hoja2 = pd.read_excel(
                        file_path, sheet_name="Hoja2",
                        header=None, dtype=str
                    ).fillna("")
                    if len(hoja2) > 0 and len(hoja2.columns) > 13:
                        if "TPV" in str(hoja2.iloc[0, 13]).upper():
                            logger.info("Formato bancario detectado: REPORTE")
                            result = _ReporteParser().parse_raw(hoja2)
                            logger.info("[REPORTE] Filas parseadas: %d", len(result))
                            return result
            except Exception:
                pass  # no es REPORTE, continuar con detección normal

        raw = _BaseBankParser._read_file(file_path)
        fmt = self._detect_format(raw)

        if fmt is None:
            raise ValueError(
                f"Formato bancario no reconocido en: {file_path}\n"
                "Bancos soportados: BBVA, Banorte/Bancomer."
            )

        logger.info("Formato bancario detectado: %s", fmt.BANK_NAME)
        result = fmt().parse_raw(raw)
        logger.info("[%s] Filas parseadas: %d", fmt.BANK_NAME, len(result))
        return result

    @staticmethod
    def _detect_format(raw: pd.DataFrame) -> type[_BaseBankParser] | None:
        if raw.empty:
            return None

        # Leer las 2 primeras filas como texto plano para detección
        row0 = " ".join(raw.iloc[0].fillna("").astype(str).tolist())
        row1 = " ".join(raw.iloc[1].fillna("").astype(str).tolist()) if len(raw) > 1 else ""

        row0_upper = row0.upper()
        row1_upper = row1.upper()

        # BBVA: header en fila 0 con DEPÓSITOS / RETIROS
        if "DEPOSITOS" in row0_upper or "DEPÓSITOS" in row0_upper or "FECHA DE OPERACI" in row0_upper:
            return _BBVAParser

        # BANORTE: fila 0 comienza con "Cuenta" y fila 1 tiene "Cargo" / "Abono"
        if str(raw.iloc[0, 0]).strip().lower() == "cuenta" and (
            "CARGO" in row1_upper or "ABONO" in row1_upper
        ):
            return _BanorteParser

        # SCOTIABANK: datos directamente desde fila 0, col 7 tiene "Cargo" o "Abono"
        if len(raw.columns) > 7 and str(raw.iloc[0, 7]).strip() in ("Cargo", "Abono"):
            return _ScotiabankParser

        # NETPAY: busca en las primeras 30 filas alguna que contenga
        # "Monto de Trx" / "Monto TRX" o "Fecha de Movimiento" + "Monto"
        _np_text = " ".join(
            raw.iloc[:min(30, len(raw))].fillna("").astype(str).values.flatten()
        ).upper()
        if "MONTO DE TRX" in _np_text or "MONTO TRX" in _np_text or "FECHA DE MOVIMIENTO" in _np_text:
            return _NetPayParser

        # MERCADO PAGO: fila 0 contiene "Ventas" o fila 3 col 0 = "Número de operación"
        row0_text = " ".join(raw.iloc[0].fillna("").astype(str).tolist()).upper()
        if "MERCADO PAGO" in row0_text or "VENTAS" in row0_text:
            return _MercadoPagoParser
        if len(raw) > 3 and "operaci" in str(raw.iloc[3, 0]).lower():
            return _MercadoPagoParser

        return None
