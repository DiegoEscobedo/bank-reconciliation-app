import re

import pandas as pd

from config.settings import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    MAX_GROUP_SIZE,
    ROUND_DECIMALS
)
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

    # Mapeo tipo banco → set de tipos JDE compatibles
    # TPV mezcla TDD(28) y TDC(04); TR=transferencia(03); 03 a veces es efectivo
    _TIPO_MAP: dict = {
        "TPV": {"28", "04"},
        "TR":  {"03"},
        "03":  {"01", "03"},
        "01":  {"01"},
        "04":  {"04"},
        "28":  {"28"},
    }

    def __init__(self):
        self.amount_tolerance = AMOUNT_TOLERANCE
        self.date_tolerance_days = DATE_TOLERANCE_DAYS
        self.maximum_group_size = MAX_GROUP_SIZE
        self.rounding_decimals = ROUND_DECIMALS

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
        """
        bank_df = interactive_result["_bank_df_full"]
        jde_df  = interactive_result["_jde_df_full"]

        confirmed_grouped: list = []

        for proposal in interactive_result["proposed_grouped_matches"]:
            if proposal["group_id"] not in approved_group_ids:
                continue

            bank_df.at[proposal["bank_row_index"], "is_matched"] = True
            for jde_idx in proposal["jde_row_indices"]:
                jde_df.at[jde_idx, "is_matched"] = True

            confirmed_grouped.append({
                "match_type":        "grouped",
                "bank_row_index":    proposal["bank_row_index"],
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

            jde_df.at[proposal["jde_row_index"], "is_matched"] = True
            for bi in proposal["bank_row_indices"]:
                bank_df.at[bi, "is_matched"] = True

            confirmed_reverse.append({
                "match_type":        "reverse_grouped",
                "jde_row_index":     proposal["jde_row_index"],
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
            if not pd.isna(_raw) and str(_raw).strip().upper() not in ("", "NAN", "NONE", "NA", "<NA>"):
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

            if potential_jde_candidates.empty:
                logger.warning(
                    "[EXACT] Banco idx=%d  amt=%.2f  fecha=%s → 0 candidatos JDE por fecha (tolerancia=%d días)",
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

            for jde_index, jde_row in potential_jde_candidates.iterrows():

                jde_amount = round(
                    jde_row["abs_amount"],
                    self.rounding_decimals
                )

                if self._is_amount_within_tolerance(
                        bank_amount,
                        jde_amount
                ):

                    bank_dataframe.at[bank_index, "is_matched"] = True
                    jde_dataframe.at[jde_index, "is_matched"] = True

                    amount_difference = round(
                        bank_amount - jde_amount,
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
        """
        Genera propuestas de agrupación en DOS FASES para evitar que el
        orden de procesamiento cause que un movimiento bancario "consuma"
        registros JDE que otro necesita con mayor precisión.

        FASE 1 — Exploración global (sin reservar):
            Para cada movimiento bancario pendiente busca el mejor subconjunto
            JDE posible ignorando conflictos. Se obtiene una propuesta
            candidata por banco.

        FASE 2 — Resolución de conflictos:
            Ordena todas las propuestas por precisión (menor diferencia de
            monto → mayor prioridad). Acepta en orden; si una propuesta
            comparte índices JDE con otra ya aceptada, intenta encontrar
            un subconjunto alternativo usando solo los JDE aún disponibles.
            Así ambos movimientos bancarios tienen la misma oportunidad de
            quedar conciliados.

        NO marca ``is_matched`` — eso lo hace ``confirm_grouped_matches``.
        """

        # ── FASE 1: exploración global sin reservar ──────────────────────
        raw_proposals: list = []

        for bank_index, bank_row in bank_dataframe.iterrows():

            if bank_row["is_matched"]:
                continue

            target_amount = round(bank_row["abs_amount"], self.rounding_decimals)
            bank_date     = bank_row["movement_date"]

            available_jde = jde_dataframe[
                (jde_dataframe["is_matched"] == False)
                & (self._is_date_within_tolerance(
                    bank_date, jde_dataframe["movement_date"]
                ))
            ]

            if available_jde.empty:
                continue

            available_jde = self._filter_by_tienda(
                available_jde, bank_row, jde_dataframe
            )

            if available_jde.empty:
                continue

            # Refinar por comisión (simétrico)
            available_jde = self._filter_by_comision(available_jde, bank_row)

            if available_jde.empty:
                continue

            filtered = available_jde[
                available_jde["abs_amount"] <= target_amount + self.amount_tolerance
            ].copy()

            if filtered.empty:
                continue

            subset_result = self._try_subsets_per_tienda(filtered, target_amount)

            if not subset_result:
                continue

            matched_jde_indices = [idx for idx, _ in subset_result]
            accumulated = round(
                sum(round(r["abs_amount"], self.rounding_decimals)
                    for _, r in subset_result),
                self.rounding_decimals,
            )

            raw_proposals.append({
                "bank_row_index":    bank_index,
                "bank_snapshot":     bank_row.to_dict(),
                "jde_row_indices":   matched_jde_indices,
                "jde_snapshots":     [row.to_dict() for _, row in subset_result],
                "amount_difference": round(target_amount - accumulated,
                                           self.rounding_decimals),
                "jde_count":         len(matched_jde_indices),
            })

        # ── FASE 2: resolución de conflictos ─────────────────────────────
        # Prioridad: menor |diferencia de monto|, en empate menos registros JDE
        raw_proposals.sort(
            key=lambda p: (abs(p["amount_difference"]), p["jde_count"])
        )

        reserved_jde: set  = set()
        final_proposals: list = []
        group_id: int      = 0

        for proposal in raw_proposals:
            jde_set = set(proposal["jde_row_indices"])

            if jde_set.isdisjoint(reserved_jde):
                # Sin conflicto → aceptar directamente
                reserved_jde.update(jde_set)
                proposal["group_id"] = group_id
                final_proposals.append(proposal)
                group_id += 1
            else:
                # Conflicto → reintentar con solo los JDE disponibles
                bank_index    = proposal["bank_row_index"]
                bank_row      = bank_dataframe.loc[bank_index]
                target_amount = round(bank_row["abs_amount"], self.rounding_decimals)
                bank_date     = bank_row["movement_date"]

                alt_jde = jde_dataframe[
                    (~jde_dataframe.index.isin(reserved_jde))
                    & (jde_dataframe["is_matched"] == False)
                    & (self._is_date_within_tolerance(
                        bank_date, jde_dataframe["movement_date"]
                    ))
                ]

                if alt_jde.empty:
                    continue

                alt_jde = self._filter_by_tienda(
                    alt_jde, bank_row, jde_dataframe
                )

                # Refinar por comisión (simétrico)
                alt_jde = self._filter_by_comision(alt_jde, bank_row)

                alt_filtered = alt_jde[
                    alt_jde["abs_amount"] <= target_amount + self.amount_tolerance
                ].copy()

                if alt_filtered.empty:
                    continue

                alt_result = self._try_subsets_per_tienda(
                    alt_filtered, target_amount
                )

                if not alt_result:
                    continue

                alt_indices = [idx for idx, _ in alt_result]
                reserved_jde.update(alt_indices)
                alt_accumulated = round(
                    sum(round(r["abs_amount"], self.rounding_decimals)
                        for _, r in alt_result),
                    self.rounding_decimals,
                )

                final_proposals.append({
                    "group_id":          group_id,
                    "bank_row_index":    bank_index,
                    "bank_snapshot":     bank_row.to_dict(),
                    "jde_row_indices":   alt_indices,
                    "jde_snapshots":     [row.to_dict() for _, row in alt_result],
                    "amount_difference": round(target_amount - alt_accumulated,
                                               self.rounding_decimals),
                    "jde_count":         len(alt_indices),
                })
                group_id += 1

        return final_proposals

    # ============================================================
    # SUBSET SUM POR TIENDA — garantiza homogeneidad en grupos
    # ============================================================

    def _try_subsets_per_tienda(
        self,
        filtered_candidates: "pd.DataFrame",
        target_amount: float,
    ) -> "list | None":
        """
        Intenta encontrar el mejor subset sum garantizando que todos los
        registros JDE del grupo pertenezcan a la MISMA tienda.

        Si los candidatos no tienen columna ``tienda`` o todos son de la
        misma tienda, se comporta igual que ``_find_subset_sum_with_limit``
        directamente.  Si hay varias tiendas, prueba cada una por separado
        y devuelve el resultado con menor diferencia de monto absoluta.
        """
        has_tienda = (
            "tienda" in filtered_candidates.columns
            and filtered_candidates["tienda"].notna().any()
            and (filtered_candidates["tienda"].str.strip() != "").any()
        )

        if not has_tienda:
            # Sin info de tienda → comportamiento original
            candidate_rows = list(
                filtered_candidates.nsmallest(25, "abs_amount").iterrows()
            )
            return self._find_subset_sum_with_limit(candidate_rows, target_amount)

        # Obtener tiendas únicas presentes en los candidatos
        tiendas = (
            filtered_candidates["tienda"]
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()
        )

        if len(tiendas) <= 1:
            # Una sola tienda → sin riesgo de mezcla, camino directo
            candidate_rows = list(
                filtered_candidates.nsmallest(25, "abs_amount").iterrows()
            )
            return self._find_subset_sum_with_limit(candidate_rows, target_amount)

        # Múltiples tiendas → probar cada una y conservar el mejor resultado
        best_result = None
        best_diff   = float("inf")

        for tienda in tiendas:
            grupo = filtered_candidates[
                filtered_candidates["tienda"].str.strip() == tienda
            ]
            candidate_rows = list(grupo.nsmallest(25, "abs_amount").iterrows())
            result = self._find_subset_sum_with_limit(candidate_rows, target_amount)
            if result is None:
                continue
            accumulated = round(
                sum(
                    round(r["abs_amount"], self.rounding_decimals)
                    for _, r in result
                ),
                self.rounding_decimals,
            )
            diff = abs(target_amount - accumulated)
            if diff < best_diff:
                best_diff   = diff
                best_result = result

        return best_result

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
        """
        Para cada movimiento JDE pendiente, busca un subconjunto de
        movimientos bancarios pendientes cuya SUMA iguale el monto JDE
        (dentro de la tolerancia). Solo aplica cuando se necesitan 2+
        movimientos bancarios (si fuera 1, el matching exacto ya lo cubriría).

        Caso típico: varias comisiones bancarias separadas (−10, −5, −1.60, −0.80)
        que juntas suman la comisión registrada en JDE (−17.40).
        """
        # Bank rows reclamados por propuestas forward (para evitar doble uso)
        claimed_bank = {p["bank_row_index"] for p in forward_proposals}

        proposals: list = []
        group_id = start_group_id

        for jde_index, jde_row in jde_dataframe.iterrows():
            if jde_row["is_matched"]:
                continue

            target_amount = round(jde_row["abs_amount"], self.rounding_decimals)
            jde_date      = jde_row["movement_date"]
            jde_mvtype    = jde_row.get("movement_type", "")

            # Candidatos bancarios: pendientes, mismo tipo, dentro de fecha,
            # cada uno menor que el total JDE (si fuera igual, exacto ya matcheó)
            available_bank = bank_dataframe[
                (~bank_dataframe["is_matched"])
                & (~bank_dataframe.index.isin(claimed_bank))
                & (self._is_date_within_tolerance(jde_date, bank_dataframe["movement_date"]))
                & (bank_dataframe["movement_type"] == jde_mvtype)
                & (bank_dataframe["abs_amount"] < target_amount - self.amount_tolerance)
            ].copy()

            if len(available_bank) < 2:
                continue

            # ── Filtro de tienda: los movimientos bancarios deben pertenecer
            # a la misma tienda que el registro JDE.
            # Si el JDE no tiene tienda, o el banco no tiene la columna,
            # se deja pasar (sin info no se puede discriminar).
            jde_tienda = ""
            try:
                _t = jde_row.get("tienda") if hasattr(jde_row, "get") else jde_row["tienda"]
                if not pd.isna(_t) and str(_t).strip().upper() not in ("", "NAN", "NONE", "NA", "<NA>"):
                    jde_tienda = str(_t).strip().upper()
            except (KeyError, TypeError):
                pass

            if jde_tienda and "tienda" in available_bank.columns:
                bank_tienda_upper = available_bank["tienda"].fillna("").str.strip().str.upper()
                # Aceptar filas cuya tienda coincida con JDE o no tengan tienda asignada
                available_bank = available_bank[
                    (bank_tienda_upper == jde_tienda) | (bank_tienda_upper == "")
                ].copy()

            if len(available_bank) < 2:
                continue

            candidate_rows = list(
                available_bank.nsmallest(25, "abs_amount").iterrows()
            )
            result = self._find_subset_sum_with_limit(candidate_rows, target_amount)

            if result is None or len(result) < 2:
                continue

            bank_indices = [idx for idx, _ in result]
            accumulated  = round(
                sum(round(r["abs_amount"], self.rounding_decimals) for _, r in result),
                self.rounding_decimals,
            )
            diff = round(target_amount - accumulated, self.rounding_decimals)

            # Marcar como reclamados para evitar solapamientos dentro de esta fase
            claimed_bank.update(bank_indices)

            proposals.append({
                "group_id":          group_id,
                "jde_row_index":     jde_index,
                "jde_snapshot":      jde_row.to_dict(),
                "bank_row_indices":  bank_indices,
                "bank_snapshots":    [r.to_dict() for _, r in result],
                "amount_difference": diff,
                "bank_count":        len(bank_indices),
            })
            group_id += 1
            logger.info(
                "[REV-GROUPED] JDE idx=%d  amt=%.2f → %d filas banco  diff=%.2f",
                jde_index, target_amount, len(bank_indices), diff,
            )

        return proposals

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
            
            # Filtro: solo procesar si Estado contiene "Aprobado"
            raw_status = str(row.get("raw_status", "")).strip().lower()
            if "aprobado" not in raw_status:
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
        """
        Encuentra un subconjunto de candidate_rows cuya suma sea lo más
        cercano posible al target_amount (dentro de tolerancia).
        
        Estrategia: busca la solución MEJOR (más montos incluidos, menor
        diferencia) en lugar de retornar la PRIMERA solución encontrada.
        Esto evita casos donde se ignoran centavos pequeños innecesariamente.
        """
        # Ordenar ascendente: los montos más pequeños primero → maximiza inclusión
        sorted_candidates = sorted(
            candidate_rows,
            key=lambda row: round(
                row[1]["abs_amount"],
                self.rounding_decimals
            ),
            reverse=False,  # ← MENOR a MAYOR (para preferir incluir más montos)
        )

        # Suma de sufijos para poda adicional
        amounts = [round(r[1]["abs_amount"], self.rounding_decimals) for r in sorted_candidates]
        suffix_sums = [0.0] * (len(amounts) + 1)
        for i in range(len(amounts) - 1, -1, -1):
            suffix_sums[i] = suffix_sums[i + 1] + amounts[i]

        best_result = None
        best_diff = float('inf')

        def backtracking_search(
                start_position,
                current_combination,
                current_sum):
            nonlocal best_result, best_diff

            if len(current_combination) > self.maximum_group_size:
                return

            current_diff = abs(round(current_sum - target_amount, self.rounding_decimals))

            # Si esta solución es mejor (menor diferencia, o misma diferencia pero más montos)
            if current_diff <= self.amount_tolerance:
                if (current_diff < best_diff or 
                    (current_diff == best_diff and len(current_combination) > len(best_result or []))):
                    best_diff = current_diff
                    best_result = current_combination

            if current_sum > target_amount + self.amount_tolerance:
                return

            # Poda: ni sumando todo lo que queda podemos alcanzar el target
            remaining = target_amount - current_sum
            if suffix_sums[start_position] < remaining - self.amount_tolerance:
                return

            for index in range(start_position, len(sorted_candidates)):

                jde_index, jde_row = sorted_candidates[index]

                movement_amount = round(
                    jde_row["abs_amount"],
                    self.rounding_decimals
                )

                backtracking_search(
                    index + 1,
                    current_combination + [(jde_index, jde_row)],
                    round(current_sum + movement_amount,
                          self.rounding_decimals)
                )

        backtracking_search(0, [], 0)
        return best_result

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