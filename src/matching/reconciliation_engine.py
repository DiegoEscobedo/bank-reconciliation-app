import re

import pandas as pd

from config.settings import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    GROUPED_CANDIDATE_LIMIT,
    MAX_GROUP_SIZE,
    ROUND_DECIMALS,
    TIPO_BANCO_TO_JDE_COMPAT,
)
from src.matching.grouped_matcher import GroupedMatcher
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ReconciliationEngine:
    """
    Motor principal de conciliación bancaria.
    Ejecuta:
    1) Matching exacto uno a uno con tolerancia
    2) Matching agrupado (subset sum limitado)
    Cuando los DataFrames contienen las columnas ``tienda`` y ``tipo_banco`` /
    ``tipo_jde`` (presentes al usar el REPORTE enriquecido), el motor las usa
    como extra de discriminación antes de intentar el matching de
    montos para reducir falsos positivos.
    """

    # Mapeo tipo banco → set de tipos JDE compatibles (centralizado en settings)
    _TIPO_MAP: dict = TIPO_BANCO_TO_JDE_COMPAT

    def __init__(self):
        self.amount_tolerance = AMOUNT_TOLERANCE
        self.date_tolerance_days = DATE_TOLERANCE_DAYS
        self.maximum_group_size = MAX_GROUP_SIZE
        self.grouped_candidate_limit = GROUPED_CANDIDATE_LIMIT
        # Reglas globales de agrupacion
        self.enforce_grouped_strict_tienda = True
        self.forward_grouped_min_size = 2
        self.rounding_decimals = ROUND_DECIMALS
        self.grouped_matcher = GroupedMatcher(self)

    # ============================================================
    # MÉTODO PÚBLICO PRINCIPAL
    # ============================================================

    def reconcile(
        self,
        bank_movements_dataframe,
        jde_movements_dataframe,
    ):
        interactive = self.reconcile_interactive(
            bank_movements_dataframe,
            jde_movements_dataframe,
        )
        all_ids = {p["group_id"] for p in interactive["proposed_grouped_matches"]}
        all_ids |= {p["group_id"] for p in interactive.get("proposed_reverse_grouped_matches", [])}
        return self.confirm_grouped_matches(interactive, all_ids)

    # ============================================================
    # FLUJO INTERACTIVO EN 2 FASES — para la UI de validación
    # ============================================================

    def reconcile_interactive(
        self,
        bank_movements_dataframe,
        jde_movements_dataframe,
    ):
        """
        Fase 1: matching exacto (auto-aprobado) + propuesta de agrupaciones
        SIN aplicarlas.  Devuelve un dict intermedio para pasarlo a
        ``confirm_grouped_matches`` tras la revisión del usuario.
        """
        bank_df = bank_movements_dataframe.copy()
        jde_df  = jde_movements_dataframe.copy()
        bank_df["is_matched"] = False
        jde_df["is_matched"]  = False

        exact_matches   = self._perform_exact_matching(bank_df, jde_df)
        proposed_groups = self._propose_grouped_matches(bank_df, jde_df)

        # IDs ya usados por propuestas forward para evitar colisión
        next_id = max((p["group_id"] for p in proposed_groups), default=-1) + 1
        proposed_reverse = self._propose_reverse_grouped_matches(
            bank_df, jde_df, proposed_groups, start_group_id=next_id
        )

        # Color-based matching para Mercado Pago
        proposed_color = self._propose_color_based_matches(bank_df, jde_df)

        return {
            "_bank_df_full":                    bank_df,
            "_jde_df_full":                     jde_df,
            "exact_matches":                    exact_matches,
            "proposed_grouped_matches":         proposed_groups,
            "proposed_reverse_grouped_matches": proposed_reverse,
            "proposed_color_based_matches":     proposed_color,
        }

    def confirm_grouped_matches(self, interactive_result, approved_group_ids):
        """
        Fase 2: aplica únicamente los grupos con ``group_id`` en
        ``approved_group_ids`` y construye el resultado final con el
        mismo esquema que ``reconcile``.
        
        Valida prevención de falsos positivos por tienda en agrupados.
        """
        bank_df = interactive_result["_bank_df_full"]
        jde_df  = interactive_result["_jde_df_full"]

        confirmed_grouped: list = []

        for proposal in interactive_result["proposed_grouped_matches"]:
            if proposal["group_id"] not in approved_group_ids:
                continue

            # Validación de tienda: prevenir falsos positivos en agrupados
            # Si todos los JDE comparten tienda y es diferente a la del banco → RECHAZAR
            bank_idx = proposal["bank_row_index"]
            bank_row = bank_df.loc[bank_idx]
            bank_tienda = str(bank_row.get("tienda") or "").strip().upper()
            
            if "tienda" in jde_df.columns and bank_tienda:
                jde_tiendas = set()
                for jde_idx in proposal["jde_row_indices"]:
                    jde_tienda = str(jde_df.at[jde_idx, "tienda"] or "").strip().upper()
                    if jde_tienda:  # Solo contar tiendas definidas
                        jde_tiendas.add(jde_tienda)
                
                # Si TODOS los JDE de la agrupación son de UNA tienda diferente → prevenir
                if len(jde_tiendas) == 1 and list(jde_tiendas)[0] != bank_tienda:
                    logger.warning(
                        "[GROUPED-TIENDA-FILTER] Agrupación %d rechazada: "
                        "Banco tienda='%s' pero todos JDE son tienda='%s' (posible falso positivo)",
                        proposal["group_id"], bank_tienda, list(jde_tiendas)[0]
                    )
                    continue  # Saltarse esta agrupación para evitar falso positivo

            bank_df.at[bank_idx, "is_matched"] = True
            for jde_idx in proposal["jde_row_indices"]:
                jde_df.at[jde_idx, "is_matched"] = True

            confirmed_grouped.append({
                "match_type":        "grouped",
                "bank_row_index":    bank_idx,
                "jde_row_indices":   proposal["jde_row_indices"],
                "amount_difference": proposal["amount_difference"],
            })

        # ── Agrupaciones inversas (N banco → 1 JDE) ─────────────────────
        confirmed_reverse: list = []
        for proposal in interactive_result.get("proposed_reverse_grouped_matches", []):
            if proposal["group_id"] not in approved_group_ids:
                continue
            # Verificar que ninguna fila ya fue tomada por otra agrupación
            if jde_df.at[proposal["jde_row_index"], "is_matched"]:
                continue
            if any(bank_df.at[bi, "is_matched"] for bi in proposal["bank_row_indices"]):
                continue

            # Validación de tienda para inverso: todos los bancos deben ser de la MISMA tienda
            jde_idx = proposal["jde_row_index"]
            jde_row = jde_df.loc[jde_idx]
            jde_tienda = str(jde_row.get("tienda") or "").strip().upper()
            
            if "tienda" in bank_df.columns and jde_tienda:
                bank_tiendas = set()
                for bank_idx in proposal["bank_row_indices"]:
                    bank_tienda = str(bank_df.at[bank_idx, "tienda"] or "").strip().upper()
                    if bank_tienda:  # Solo contar tiendas definidas
                        bank_tiendas.add(bank_tienda)
                
                # Si bancos son de MÚLTIPLES tiendas O de tienda diferente a JDE → prevenir
                if len(bank_tiendas) > 1:
                    logger.warning(
                        "[REVERSE-TIENDA-FILTER] Inverso %d rechazado: "
                        "JDE tienda='%s' pero bancos provienen de múltiples tiendas %s (falso positivo)",
                        proposal["group_id"], jde_tienda, bank_tiendas
                    )
                    continue
                elif len(bank_tiendas) == 1 and list(bank_tiendas)[0] != jde_tienda:
                    logger.warning(
                        "[REVERSE-TIENDA-FILTER] Inverso %d rechazado: "
                        "JDE tienda='%s' pero todos bancos son tienda='%s' (falso positivo)",
                        proposal["group_id"], jde_tienda, list(bank_tiendas)[0]
                    )
                    continue

            jde_df.at[jde_idx, "is_matched"] = True
            for bi in proposal["bank_row_indices"]:
                bank_df.at[bi, "is_matched"] = True

            confirmed_reverse.append({
                "match_type":        "reverse_grouped",
                "jde_row_index":     jde_idx,
                "bank_row_indices":  proposal["bank_row_indices"],
                "amount_difference": proposal["amount_difference"],
            })

        # ── Color-based matches (Mercado Pago) ──────────────────────
        confirmed_color: list = []
        for proposal in interactive_result.get("proposed_color_based_matches", []):
            if proposal["group_id"] not in approved_group_ids:
                continue
            
            # Verificar que JDE y banco aún no estén matched
            jde_already_matched = any(jde_df.at[ji, "is_matched"] for ji in proposal["jde_row_indices"])
            if jde_already_matched:
                continue
            
            bank_idx = proposal.get("matched_bank_row_index")
            if bank_idx is not None and bank_df.at[bank_idx, "is_matched"]:
                continue
            
            # Validación de tienda para color: prevenir falsos positivos
            if bank_idx is not None and "tienda" in jde_df.columns:
                bank_row = bank_df.at[bank_idx]
                bank_tienda = str(bank_row.get("tienda", "") or "").strip().upper()
                
                if bank_tienda:
                    jde_tiendas = set()
                    for ji in proposal["jde_row_indices"]:
                        jde_tienda = str(jde_df.at[ji, "tienda"] or "").strip().upper()
                        if jde_tienda:
                            jde_tiendas.add(jde_tienda)
                    
                    # Si TODOS los JDE son de UNA tienda diferente → prevenir
                    if len(jde_tiendas) == 1 and list(jde_tiendas)[0] != bank_tienda:
                        logger.warning(
                            "[COLOR-TIENDA-FILTER] Color %s rechazado: "
                            "Banco tienda='%s' pero JDE tienda='%s' (falso positivo)",
                            proposal["color"], bank_tienda, list(jde_tiendas)[0]
                        )
                        continue
            
            # Marcar JDE como conciliadas
            for ji in proposal["jde_row_indices"]:
                jde_df.at[ji, "is_matched"] = True
            
            # Marcar BANCO como conciliado (si hay match)
            if bank_idx is not None:
                bank_df.at[bank_idx, "is_matched"] = True
            
            confirmed_color.append({
                "match_type":         "color_based",
                "color":              proposal["color"],
                "jde_row_indices":    proposal["jde_row_indices"],
                "bank_row_index":     bank_idx,
                "color_sum":          proposal["jde_color_sum"],
                "amount_difference":  proposal["amount_difference"],
                "is_matched":         bank_idx is not None,
            })

        conciliated_bank = bank_df[bank_df["is_matched"]].copy()
        conciliated_jde  = jde_df[jde_df["is_matched"]].copy()
        pending_bank     = bank_df[~bank_df["is_matched"]].copy()
        pending_jde      = jde_df[~jde_df["is_matched"]].copy()

        summary = {
            "total_bank_movements":          len(bank_df),
            "total_jde_movements":           len(jde_df),
            "exact_matches_count":           len(interactive_result["exact_matches"]),
            "grouped_matches_count":         len(confirmed_grouped),
            "reverse_grouped_matches_count": len(confirmed_reverse),
            "color_based_matches_count":     len(confirmed_color),
            "pending_bank_count":            len(pending_bank),
            "pending_jde_count":             len(pending_jde),
        }

        return {
            "conciliated_bank_movements":       conciliated_bank,
            "conciliated_jde_movements":        conciliated_jde,
            "pending_bank_movements":           pending_bank,
            "pending_jde_movements":            pending_jde,
            "exact_matches":                    interactive_result["exact_matches"],
            "grouped_matches":                  confirmed_grouped,
            "reverse_grouped_matches":          confirmed_reverse,
            "color_based_matches":              confirmed_color,
            "proposed_grouped_matches":         interactive_result["proposed_grouped_matches"],
            "proposed_reverse_grouped_matches": interactive_result.get("proposed_reverse_grouped_matches", []),
            "proposed_color_based_matches":     interactive_result.get("proposed_color_based_matches", []),
            "summary":                          summary,
            "_bank_df_full":                    bank_df,
            "_jde_df_full":                     jde_df,
            # Pass-through metadata de la fuente JDE
            "_jde_source_path":           interactive_result.get("_jde_source_path"),
            "_jde_bytes":                 interactive_result.get("_jde_bytes"),
            "_is_papel_trabajo":          interactive_result.get("_is_papel_trabajo", False),
            "_bank_accounts":             interactive_result.get("_bank_accounts", []),
        }

    # ============================================================
    # FILTRADO POR TIENDA + TIPO  (helper compartido)
    # ============================================================

    def _filter_by_tienda(
        self,
        candidates: "pd.DataFrame",
        bank_row,
        jde_dataframe: "pd.DataFrame",
    ) -> "pd.DataFrame":
        """
        Si bank_row tiene ``tienda`` no vacía y jde_dataframe tiene
        columna ``tienda``, filtra ``candidates`` para que coincidan en
        tienda y en tipo compatible.  Si no hay info, devuelve los mismos
        candidates sin cambios (comportamiento backward-compatible).
        """
        # Verificar que exista info de tienda en ambos lados
        bank_tienda = ""
        try:
            _raw = bank_row.get("tienda") if hasattr(bank_row, "get") else bank_row["tienda"]
            # pd.isna cubre float('nan'), None, pd.NA, pd.NaT
            # NO ENCONTRADO se trata como "sin tienda".
            if not pd.isna(_raw) and str(_raw).strip().upper() not in (
                "", "NAN", "NONE", "NA", "<NA>", "NO ENCONTRADO"
            ):
                bank_tienda = str(_raw).strip().upper()
        except (KeyError, TypeError):
            pass

        # NETPAY: el matching por tienda no aplica — el filtro de monto+fecha
        # es suficiente para evitar falsos positivos. La tienda solo es informativa.
        try:
            _bank_src = bank_row.get("bank") if hasattr(bank_row, "get") else bank_row["bank"]
            if str(_bank_src).strip().upper() == "NETPAY":
                return candidates
        except (KeyError, TypeError):
            pass

        # Determinar si la columna tienda existe en los candidatos JDE
        jde_tiene_tienda = (
            "tienda" in candidates.columns
            and candidates["tienda"].notna().any()
            and (candidates["tienda"].str.strip() != "").any()
        )

        # ── Caso 1: banco SIN tienda ─────────────────────────────────────
        # Si el banco no fue enriquecido pero los candidatos JDE sí tienen
        # tienda definida, se agrupan por tienda JDE para que al menos
        # no se mezclen entre sí (no hay base para discriminar más).
        if not bank_tienda:
            return candidates  # sin info bancaria no se puede filtrar

        # ── Caso 2: banco CON tienda ─────────────────────────────────────
        if not jde_tiene_tienda:
            # JDE no tiene info de tienda → no se puede discriminar, aceptar todos
            return candidates

        # Ambos lados tienen tienda → filtrar estrictamente (sin fallback)
        mask = candidates["tienda"].str.strip().str.upper() == bank_tienda

        # Filtrar por tipo compatible si existe
        bank_tipo = ""
        try:
            bank_tipo = str(bank_row.get("tipo_banco") or bank_row["tipo_banco"]).strip().upper()
        except (KeyError, AttributeError, TypeError):
            pass

        compatible_tipos = self._TIPO_MAP.get(bank_tipo, set())
        if compatible_tipos and "tipo_jde" in candidates.columns:
            tipo_mask = candidates["tipo_jde"].isin(compatible_tipos)
            mask = mask & tipo_mask

        filtered = candidates[mask]

        subconjunto_tiene_tienda = (
            candidates["tienda"].str.strip() != ""
        ).any()
        if filtered.empty and not subconjunto_tiene_tienda:
            return candidates  # JDE del subconjunto no tiene tienda → aceptar todos
        return filtered  # filtrado estricto por tienda+tipo

    # ============================================================
    # FILTRADO POR COMISIÓN  (helper compartido)
    # ============================================================

    # Palabras que identifican un movimiento de comisión en la descripción
    _COMISION_RE = re.compile(r"comisi[oó]n|comision", re.IGNORECASE)

    @staticmethod
    def _normalize_account_token(value) -> str:
        if pd.isna(value):
            return ""
        token = str(value).strip().replace(" ", "")
        if token.upper() in {"UNKNOWN", "NOENCONTRADO", "N/A", "NA", "NONE", "NULL", "NAN", "<NA>"}:
            return ""
        # Algunos orígenes Excel traen cuentas numéricas como texto float (ej. 20305077133.0).
        if re.fullmatch(r"\d+\.0+", token):
            token = token.split(".", 1)[0]

        digits_only = re.sub(r"\D", "", token)
        if digits_only:
            return digits_only
        return token

    @classmethod
    def _accounts_compatible(cls, bank_account, jde_account) -> bool:
        """
        Compatibilidad cuenta larga/corta por sufijo (ej. 20305077133 vs 7133).
        Si alguno viene vacío, no bloquea el matching.
        """
        b = cls._normalize_account_token(bank_account)
        j = cls._normalize_account_token(jde_account)
        if not b or not j:
            return True
        return b == j or b.endswith(j) or j.endswith(b)

    @classmethod
    def _es_comision(cls, description: str) -> bool:
        return bool(cls._COMISION_RE.search(str(description or "")))

    def _filter_by_comision(
        self,
        candidates: "pd.DataFrame",
        bank_row,
    ) -> "pd.DataFrame":
        """
        Aplica discriminación simétrica por comisión:
          - Banco ES comisión   → solo candidatos JDE con comisión
          - Banco NO es comisión → excluye candidatos JDE con comisión

        Si ningún candidato JDE tiene comisión en la descripción el filtro
        no provoca cambios (backward-compatible).
        """
        if "description" not in candidates.columns or candidates.empty:
            return candidates

        try:
            bank_desc = str(
                bank_row.get("description") if hasattr(bank_row, "get")
                else bank_row["description"]
            )
        except (KeyError, TypeError):
            bank_desc = ""

        bank_comision = self._es_comision(bank_desc)
        jde_comision_mask = candidates["description"].apply(self._es_comision)

        # Si ningún JDE tiene comisión, el filtro no aporta información
        if not jde_comision_mask.any():
            return candidates

        if bank_comision:
            # Banco es comisión → solo candidatos JDE con comisión
            filtered = candidates[jde_comision_mask]
        else:
            # Banco no es comisión → excluir candidatos JDE con comisión
            filtered = candidates[~jde_comision_mask]

        # Si el filtro dejó vacío y el banco SI es comisión, devolver vacío
        # (genuinamente no hay match de comisión).  Si el banco NO es
        # comisión y al excluirlas queda vacío, idem.
        return filtered

    # ============================================================
    # MATCHING EXACTO UNO A UNO
    # ============================================================

    def _perform_exact_matching(self, bank_dataframe, jde_dataframe):

        exact_matches = []

        bank_candidate_pool = []

        for bank_index, bank_row in bank_dataframe.iterrows():

            if bank_row["is_matched"]:
                continue

            bank_amount = round(
                bank_row["abs_amount"],
                self.rounding_decimals
            )

            bank_date = bank_row["movement_date"]

            potential_jde_candidates = jde_dataframe[
                (jde_dataframe["is_matched"] == False)
                & (self._is_date_within_tolerance(
                    bank_date,
                    jde_dataframe["movement_date"]
                ))
            ]

            # Evitar cruces por monto absoluto entre deposito/retiro.
            if "movement_type" in potential_jde_candidates.columns:
                potential_jde_candidates = potential_jde_candidates[
                    potential_jde_candidates["movement_type"] == bank_row.get("movement_type")
                ]

            if potential_jde_candidates.empty:
                logger.warning(
                    "[EXACT] Banco idx=%d  amt=%.2f  fecha=%s -> 0 candidatos JDE por fecha (tolerancia=%d dias)",
                    bank_index, bank_amount,
                    str(bank_date)[:10] if pd.notna(bank_date) else "NaT",
                    self.date_tolerance_days,
                )

            # Refinar por tienda+tipo si hay info disponible
            potential_jde_candidates = self._filter_by_tienda(
                potential_jde_candidates, bank_row, jde_dataframe
            )
            # Refinar por comisión (simétrico)
            potential_jde_candidates = self._filter_by_comision(
                potential_jde_candidates, bank_row
            )

            # Si ambos lados tienen cuenta, exigir compatibilidad por cuenta/sufijo.
            if "account_id" in potential_jde_candidates.columns:
                bank_account = bank_row.get("account_id")
                potential_jde_candidates = potential_jde_candidates[
                    potential_jde_candidates["account_id"].apply(
                        lambda jde_acc: self._accounts_compatible(bank_account, jde_acc)
                    )
                ]

            # EXACT MATCH: Validación OBLIGATORIA de tienda
            # Si existe tienda en banco O JDE, DEBEN coincidir exactamente
            bank_tienda = str(bank_row.get("tienda") or "").strip().upper()
            if bank_tienda == "NO ENCONTRADO":
                bank_tienda = ""
            enforce_store_ambiguity_on_amount = False
            if "tienda" in potential_jde_candidates.columns:
                potential_jde_candidates["jde_tienda"] = (
                    potential_jde_candidates["tienda"].fillna("").astype(str).str.strip().str.upper()
                )
                # Si banco tiene tienda, solo exacto match
                if bank_tienda:
                    potential_jde_candidates = potential_jde_candidates[
                        potential_jde_candidates["jde_tienda"] == bank_tienda
                    ]
                else:
                    # Si banco NO tiene tienda, preferir JDE sin tienda.
                    # Si no hay candidatos sin tienda, aceptar solo cuando la
                    # tienda JDE sea no-ambigua entre candidatos por monto.
                    empty_store_mask = potential_jde_candidates["jde_tienda"].isin(["", "NO ENCONTRADO"])
                    if empty_store_mask.any():
                        potential_jde_candidates = potential_jde_candidates[empty_store_mask]
                    else:
                        enforce_store_ambiguity_on_amount = True

            if enforce_store_ambiguity_on_amount and not potential_jde_candidates.empty:
                amount_matching_candidates = potential_jde_candidates[
                    potential_jde_candidates["abs_amount"].apply(
                        lambda jde_amt: self._is_amount_within_tolerance(
                            bank_amount,
                            round(jde_amt, self.rounding_decimals),
                        )
                    )
                ]
                if not amount_matching_candidates.empty:
                    known_stores = set(
                        amount_matching_candidates["jde_tienda"]
                        .dropna()
                        .astype(str)
                        .str.strip()
                        .str.upper()
                        .tolist()
                    )
                    known_stores.discard("")
                    known_stores.discard("NO ENCONTRADO")
                    if len(known_stores) > 1:
                        potential_jde_candidates = potential_jde_candidates.iloc[0:0]

            if "jde_tienda" in potential_jde_candidates.columns:
                potential_jde_candidates = potential_jde_candidates.drop(columns=["jde_tienda"])

            amount_filtered_candidates = []
            for jde_index, jde_row in potential_jde_candidates.iterrows():
                jde_amount = round(jde_row["abs_amount"], self.rounding_decimals)
                if self._is_amount_within_tolerance(bank_amount, jde_amount):
                    amount_filtered_candidates.append((jde_index, jde_amount))

            bank_candidate_pool.append({
                "bank_index": bank_index,
                "bank_amount": bank_amount,
                "candidates": amount_filtered_candidates,
            })

        # Resolver conflictos priorizando filas banco con menos candidatos exactos.
        bank_candidate_pool.sort(
            key=lambda item: (len(item["candidates"]), item["bank_index"])
        )

        for item in bank_candidate_pool:
            bank_index = item["bank_index"]
            if bank_dataframe.at[bank_index, "is_matched"]:
                continue

            for jde_index, jde_amount in item["candidates"]:
                if jde_dataframe.at[jde_index, "is_matched"]:
                    continue

                bank_dataframe.at[bank_index, "is_matched"] = True
                jde_dataframe.at[jde_index, "is_matched"] = True

                amount_difference = round(
                    item["bank_amount"] - jde_amount,
                    self.rounding_decimals
                )

                exact_matches.append({
                    "match_type": "exact",
                    "bank_row_index": bank_index,
                    "jde_row_index": jde_index,
                    "amount_difference": amount_difference
                })
                break

        return exact_matches

    # ============================================================
    # PROPUESTA DE AGRUPACIONES (SUBSET SUM — sin marcar is_matched)
    # ============================================================

    def _propose_grouped_matches(self, bank_dataframe, jde_dataframe):
        return self.grouped_matcher.propose_grouped_matches(
            bank_dataframe,
            jde_dataframe,
        )

    # ============================================================
    # SUBSET SUM POR TIENDA — garantiza homogeneidad en grupos
    # ============================================================

    def _try_subsets_per_tienda(
        self,
        filtered_candidates: "pd.DataFrame",
        target_amount: float,
    ) -> "list | None":
        return self.grouped_matcher.try_subsets_per_tienda(
            filtered_candidates,
            target_amount,
        )

    # ============================================================
    # AGRUPACIÓN INVERSA — N banco → 1 JDE
    # ============================================================

    def _propose_reverse_grouped_matches(
        self,
        bank_dataframe: "pd.DataFrame",
        jde_dataframe: "pd.DataFrame",
        forward_proposals: list,
        start_group_id: int = 10000,
    ) -> list:
        return self.grouped_matcher.propose_reverse_grouped_matches(
            bank_dataframe,
            jde_dataframe,
            forward_proposals,
            start_group_id=start_group_id,
        )

    # ============================================================
    # COLOR-BASED MATCHING (Mercado Pago)
    # ============================================================

    def _is_gray_color(self, hex_color: str) -> bool:
        """
        Detecta si un color hex es gris (cuando R=G=B, es un gris).
        
        Formatos aceptados:
        - "FF808080" (ARGB con alpha)
        - "#808080" (RGB con #)
        - "808080" (RGB sin #)
        
        Retorna True si es gris (incluyendo blanco y negro).
        """
        if not hex_color:
            return True
        
        hex_color = str(hex_color).strip().upper()
        
        # Remover '#' si existe
        if hex_color.startswith("#"):
            hex_color = hex_color[1:]
        
        # Si tiene 8 caracteres (ARGB), tomar solo los últimos 6 (RGB)
        if len(hex_color) == 8:
            hex_color = hex_color[2:]
        
        # Validar que sea válido hex de 6 caracteres
        if len(hex_color) != 6:
            return False
        
        try:
            # Extraer componentes R, G, B
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            # Es gris si R = G = B
            return r == g == b
        except ValueError:
            return False

    def _propose_color_based_matches(self, bank_dataframe, jde_dataframe):
        """
        Para Mercado Pago: agrupa filas por color de celda ("cell_color"),
        suma montos por color, e intenta matching de esos sumas contra
        movimientos bancarios.
        
        Filtro adicional: Solo procesa filas con Estado="Aprobado"
        Excluye: colores grises (gris, blanco, negro)
        
        Retorna lista de propuestas de tipo "color" con:
        - color: hex color string
        - jde_row_indices: list of JDE row indices para ese color
        - jde_color_sum: suma total del color
        - matched_bank_row_index: índice del movimiento banco (si hay match)
        - amount_difference: diferencia de montos
        """
        proposals = []
        
        # Si JDE no tiene "cell_color", no hay matching por color
        if "cell_color" not in jde_dataframe.columns:
            return proposals
        
        # Agrupar por color (ignorar NaN / None / vacío)
        jde_df = jde_dataframe.copy()
        jde_df["cell_color"] = jde_df["cell_color"].fillna("")
        
        # Colores a ignorar (vacío)
        ignored_colors = {"", "FFFFFFFF"}  # Blanco puro
        color_groups = {}
        
        for idx, row in jde_df.iterrows():
            color = str(row.get("cell_color", "")).strip().upper()
            
            # Ignorar si está en lista de excluidos O si es color gris
            if color in ignored_colors or self._is_gray_color(color):
                logger.debug(
                    "[COLOR-MATCH FILTER] Fila JDE idx=%d color=%s - IGNORADA (gris o vacío)",
                    idx, color
                )
                continue
            
            # Filtro: solo procesar si Estado contiene Aprobado/Aprovado
            raw_status = str(row.get("raw_status", "")).strip().lower()
            is_approved_status = ("aprobado" in raw_status) or ("aprovado" in raw_status)
            if not is_approved_status:
                logger.debug(
                    "[COLOR-MATCH FILTER] Fila JDE idx=%d color=%s Estado='%s' - IGNORADA (no Aprobado)",
                    idx, color, raw_status
                )
                continue  # Saltar esta fila
            
            if color not in color_groups:
                color_groups[color] = []
            color_groups[color].append((idx, row))
        
        # Por cada grupo de color, buscar matching
        group_id = 1000  # Usar IDs altos para no colisionar con otros matching types
        
        for color, jde_rows in color_groups.items():
            # Sumar montos del grupo de color
            color_sum = 0.0
            for idx, r in jde_rows:
                try:
                    amount = float(r["raw_deposit"]) if pd.notna(r.get("raw_deposit")) else 0.0
                    color_sum += amount
                except (ValueError, TypeError) as e:
                    logger.warning("[COLOR-MATCH] Fila JDE idx=%d: no se pudo convertir monto '%s' a float (%s)", 
                                 idx, r.get("raw_deposit"), str(e))
            
            color_sum = round(color_sum, self.rounding_decimals)
            
            if color_sum == 0.0:
                continue  # Ignorar colores sin movimiento
            
            # Buscar match exacto en banco
            matched_bank_idx = None
            matched_diff = None
            
            for bank_idx, bank_row in bank_dataframe.iterrows():
                if bank_dataframe.at[bank_idx, "is_matched"]:
                    continue  # Ya fue conciliado
                
                bank_amount = round(
                    float(bank_row.get("raw_deposit", 0.0)) if pd.notna(bank_row.get("raw_deposit")) else 0.0,
                    self.rounding_decimals
                )
                
                if self._is_amount_within_tolerance(color_sum, bank_amount):
                    matched_bank_idx = bank_idx
                    matched_diff = round(color_sum - bank_amount, self.rounding_decimals)
                    break
            
            jde_indices = [idx for idx, _ in jde_rows]
            
            proposals.append({
                "group_id":            group_id,
                "match_type":          "color_based",
                "color":               color,
                "jde_row_indices":     jde_indices,
                "jde_color_sum":       color_sum,
                "matched_bank_row_index": matched_bank_idx,
                "amount_difference":   matched_diff if matched_bank_idx is not None else None,
                "is_matched":          matched_bank_idx is not None,
            })
            
            if matched_bank_idx is not None:
                logger.info(
                    "[COLOR-MATCH] Color %s sum=%.2f aprobado=True banco_idx=%d diff=%.2f",
                    color, color_sum, matched_bank_idx, matched_diff
                )
            else:
                logger.info(
                    "[COLOR-UNMATCHED] Color %s sum=%.2f aprobado=True (sin match en banco)",
                    color, color_sum
                )
            
            group_id += 1
        
        logger.info("[COLOR-MATCH] Propuestas totales: %d grupos de color", len(proposals))
        return proposals

    # ============================================================
    # SUBSET SUM CON BACKTRACKING Y PODA
    # ============================================================

    def _find_subset_sum_with_limit(self, candidate_rows, target_amount):
        return self.grouped_matcher.find_subset_sum_with_limit(
            candidate_rows,
            target_amount,
        )

    # ============================================================
    # FUNCIONES AUXILIARES
    # ============================================================

    def _is_amount_within_tolerance(self, amount_a, amount_b):
        return abs(
            round(amount_a, self.rounding_decimals)
            - round(amount_b, self.rounding_decimals)
        ) <= self.amount_tolerance

    def _is_date_within_tolerance(self, reference_date, comparison_dates):
        return abs(
            (comparison_dates - reference_date).dt.days
        ) <= self.date_tolerance_days