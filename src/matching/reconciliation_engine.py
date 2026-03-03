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

        return {
            "_bank_df_full":           bank_df,
            "_jde_df_full":            jde_df,
            "exact_matches":           exact_matches,
            "proposed_grouped_matches": proposed_groups,
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

        conciliated_bank = bank_df[bank_df["is_matched"]].copy()
        conciliated_jde  = jde_df[jde_df["is_matched"]].copy()
        pending_bank     = bank_df[~bank_df["is_matched"]].copy()
        pending_jde      = jde_df[~jde_df["is_matched"]].copy()

        summary = {
            "total_bank_movements":  len(bank_df),
            "total_jde_movements":   len(jde_df),
            "exact_matches_count":   len(interactive_result["exact_matches"]),
            "grouped_matches_count": len(confirmed_grouped),
            "pending_bank_count":    len(pending_bank),
            "pending_jde_count":     len(pending_jde),
        }

        return {
            "conciliated_bank_movements": conciliated_bank,
            "conciliated_jde_movements":  conciliated_jde,
            "pending_bank_movements":     pending_bank,
            "pending_jde_movements":      pending_jde,
            "exact_matches":              interactive_result["exact_matches"],
            "grouped_matches":            confirmed_grouped,
            "proposed_grouped_matches":   interactive_result["proposed_grouped_matches"],
            "summary":                    summary,
            "_bank_df_full":              bank_df,
            "_jde_df_full":               jde_df,
            # Pass-through metadata de la fuente JDE
            "_jde_source_path":           interactive_result.get("_jde_source_path"),
            "_is_papel_trabajo":          interactive_result.get("_is_papel_trabajo", False),
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
        if hasattr(bank_row, "get"):
            bank_tienda = str(bank_row.get("tienda") or "").strip().upper()
        else:
            try:
                bank_tienda = str(bank_row["tienda"]).strip().upper()
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

            # Refinar por tienda+tipo si hay info disponible
            potential_jde_candidates = self._filter_by_tienda(
                potential_jde_candidates, bank_row, jde_dataframe
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

            filtered = available_jde[
                available_jde["abs_amount"] <= target_amount + self.amount_tolerance
            ].copy()

            if filtered.empty:
                continue

            candidate_rows = list(filtered.nsmallest(25, "abs_amount").iterrows())
            subset_result  = self._find_subset_sum_with_limit(
                candidate_rows, target_amount
            )

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

                alt_filtered = alt_jde[
                    alt_jde["abs_amount"] <= target_amount + self.amount_tolerance
                ].copy()

                if alt_filtered.empty:
                    continue

                alt_candidates = list(
                    alt_filtered.nsmallest(25, "abs_amount").iterrows()
                )
                alt_result = self._find_subset_sum_with_limit(
                    alt_candidates, target_amount
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
    # SUBSET SUM CON BACKTRACKING Y PODA
    # ============================================================

    def _find_subset_sum_with_limit(self, candidate_rows, target_amount):

        # Ordenar descendente: los montos más grandes primero → poda más rápida
        sorted_candidates = sorted(
            candidate_rows,
            key=lambda row: round(
                row[1]["abs_amount"],
                self.rounding_decimals
            ),
            reverse=True,
        )

        # Suma de sufijos para poda adicional
        amounts = [round(r[1]["abs_amount"], self.rounding_decimals) for r in sorted_candidates]
        suffix_sums = [0.0] * (len(amounts) + 1)
        for i in range(len(amounts) - 1, -1, -1):
            suffix_sums[i] = suffix_sums[i + 1] + amounts[i]

        def backtracking_search(
                start_position,
                current_combination,
                current_sum):

            if len(current_combination) > self.maximum_group_size:
                return None

            if self._is_amount_within_tolerance(
                    current_sum,
                    target_amount):
                return current_combination

            if current_sum > target_amount + self.amount_tolerance:
                return None

            # Poda: ni sumando todo lo que queda podemos alcanzar el target
            remaining = target_amount - current_sum
            if suffix_sums[start_position] < remaining - self.amount_tolerance:
                return None

            for index in range(start_position, len(sorted_candidates)):

                jde_index, jde_row = sorted_candidates[index]

                movement_amount = round(
                    jde_row["abs_amount"],
                    self.rounding_decimals
                )

                result = backtracking_search(
                    index + 1,
                    current_combination + [(jde_index, jde_row)],
                    round(current_sum + movement_amount,
                          self.rounding_decimals)
                )

                if result:
                    return result

            return None

        return backtracking_search(0, [], 0)

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