import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GroupedMatcher:
	"""
	Encapsula la logica de matching agrupado para mantener el
	ReconciliationEngine mas enfocado en orquestacion.

	Depende de helpers del engine (filtro por tienda/comision, tolerancias,
	redondeo y validacion de fecha), para preservar exactamente el
	comportamiento existente.
	"""

	def __init__(self, engine):
		self.engine = engine
		self._commission_codes_6614 = {"537", "517", "600", "601"}

	@staticmethod
	def _normalize_tienda(value) -> str:
		if pd.isna(value):
			return ""
		return str(value).strip().upper()

	@staticmethod
	def _normalize_text(value) -> str:
		if pd.isna(value):
			return ""
		text = str(value).strip().upper()
		return (
			text.replace("Á", "A")
			.replace("É", "E")
			.replace("Í", "I")
			.replace("Ó", "O")
			.replace("Ú", "U")
		)

	@staticmethod
	def _normalize_code(value) -> str:
		if pd.isna(value):
			return ""
		text = str(value).strip()
		if text.endswith(".0"):
			text = text[:-2]
		return "".join(ch for ch in text if ch.isdigit())

	@staticmethod
	def _is_account_6614(value) -> bool:
		if pd.isna(value):
			return False
		text = str(value).strip().replace(" ", "")
		if text.endswith(".0"):
			text = text[:-2]
		digits = "".join(ch for ch in text if ch.isdigit())
		return digits.endswith("6614")

	@classmethod
	def _is_jde_commission_row(cls, row) -> bool:
		mvtype = cls._normalize_text(row.get("movement_type", "") if hasattr(row, "get") else "")
		desc = cls._normalize_text(row.get("description", "") if hasattr(row, "get") else "")
		return mvtype == "COM" or "COMISION" in desc

	@classmethod
	def _is_bank_commission_row(cls, row) -> bool:
		desc = cls._normalize_text(row.get("description", "") if hasattr(row, "get") else "")
		mvtype = cls._normalize_text(row.get("movement_type", "") if hasattr(row, "get") else "")
		code = cls._normalize_code(row.get("cod_transac", "") if hasattr(row, "get") else "")
		return "COMISION" in desc or mvtype == "COM" or code in {"537", "517", "600", "601"}

	def _get_6614_commission_candidates(self, available_bank: "pd.DataFrame", jde_row) -> "pd.DataFrame":
		"""
		Sesgo opcional para 6614:
		- Solo aplica a filas JDE de comisión.
		- Toma solo movimientos banco 6614 con COD. TRANSAC en {537,517,600,601}.
		Si no aplica o no hay columnas requeridas, retorna DataFrame vacío.
		"""
		if available_bank.empty:
			return available_bank.iloc[0:0].copy()

		if not self._is_jde_commission_row(jde_row):
			return available_bank.iloc[0:0].copy()

		if "account_id" not in available_bank.columns or "cod_transac" not in available_bank.columns:
			return available_bank.iloc[0:0].copy()

		is_6614 = available_bank["account_id"].apply(self._is_account_6614)
		code_mask = available_bank["cod_transac"].apply(
			lambda v: self._normalize_code(v) in self._commission_codes_6614
		)
		return available_bank[is_6614 & code_mask].copy()

	@classmethod
	def _is_cargo_por_dispersion(cls, value) -> bool:
		text = cls._normalize_text(value)
		return "CARGO POR DISPERSION" in text or "CARGO DISPERSION" in text

	@classmethod
	def _is_nomina_jde_row(cls, row) -> bool:
		tipo = cls._normalize_text(row.get("tipo_jde", "") if hasattr(row, "get") else "")
		desc = cls._normalize_text(row.get("description", "") if hasattr(row, "get") else "")
		return tipo == "NOMINA" or "NOMINA" in desc

	def _apply_dispersion_nomina_rule_forward(self, candidates: "pd.DataFrame", bank_row) -> "pd.DataFrame":
		"""
		Regla de negocio: si el banco es CARGO POR DISPERSION,
		solo puede agrupar contra movimientos JDE de NOMINA.
		"""
		bank_desc = ""
		try:
			bank_desc = bank_row.get("description") if hasattr(bank_row, "get") else bank_row["description"]
		except (KeyError, TypeError):
			pass

		if not self._is_cargo_por_dispersion(bank_desc):
			return candidates

		if candidates.empty:
			return candidates

		nomina_mask = candidates.apply(self._is_nomina_jde_row, axis=1)
		return candidates[nomina_mask].copy()

	def _apply_dispersion_nomina_rule_reverse(self, candidates: "pd.DataFrame", jde_row) -> "pd.DataFrame":
		"""
		Regla simetrica para agrupacion inversa:
		- JDE NOMINA -> solo bancos CARGO POR DISPERSION.
		- JDE no NOMINA -> excluir bancos CARGO POR DISPERSION.
		"""
		if candidates.empty or "description" not in candidates.columns:
			return candidates

		jde_es_nomina = self._is_nomina_jde_row(jde_row)
		bank_dispersion_mask = candidates["description"].apply(self._is_cargo_por_dispersion)

		if jde_es_nomina:
			return candidates[bank_dispersion_mask].copy()
		return candidates[~bank_dispersion_mask].copy()

	def _enforce_strict_tienda(self, candidates: "pd.DataFrame", bank_row) -> "pd.DataFrame":
		"""
		Regla estricta de tienda para agrupaciones:
		- Si banco tiene tienda -> solo esa tienda exacta.
		- Si banco no tiene tienda -> solo JDE sin tienda/NO ENCONTRADO.
		"""
		if not getattr(self.engine, "enforce_grouped_strict_tienda", False):
			return candidates

		if "tienda" not in candidates.columns:
			return candidates

		bank_tienda = self._normalize_tienda(bank_row.get("tienda") if hasattr(bank_row, "get") else bank_row["tienda"])
		jde_tienda = candidates["tienda"].apply(self._normalize_tienda)

		if bank_tienda:
			return candidates[jde_tienda == bank_tienda].copy()

		return candidates[jde_tienda.isin(["", "NO ENCONTRADO"])].copy()

	def _enforce_strict_tipo_pago(self, candidates: "pd.DataFrame", bank_row) -> "pd.DataFrame":
		"""
		Regla estricta de tipo de pago para agrupaciones:
		- Si banco tiene tipo_banco -> solo tipos JDE compatibles (_TIPO_MAP).
		- Si banco no tiene tipo_banco -> solo JDE sin tipo definido.
		"""
		if "tipo_jde" not in candidates.columns:
			return candidates

		bank_tipo = ""
		try:
			_raw = bank_row.get("tipo_banco") if hasattr(bank_row, "get") else bank_row["tipo_banco"]
			if not pd.isna(_raw):
				bank_tipo = str(_raw).strip().upper()
		except (KeyError, TypeError):
			pass

		jde_tipo = candidates["tipo_jde"].fillna("").astype(str).str.strip().str.upper()

		if bank_tipo:
			compatible = self.engine._TIPO_MAP.get(bank_tipo, set())
			if compatible:
				return candidates[jde_tipo.isin(compatible)].copy()
			# Si no existe mapeo explícito, exigir igualdad textual.
			return candidates[jde_tipo == bank_tipo].copy()

		return candidates[jde_tipo.isin(["", "NO ENCONTRADO", "NAN", "NONE", "<NA>"])].copy()

	def propose_grouped_matches(self, bank_dataframe, jde_dataframe):
		"""
		Genera propuestas de agrupacion en DOS FASES para evitar que el
		orden de procesamiento cause que un movimiento bancario "consuma"
		registros JDE que otro necesita con mayor precision.

		FASE 1 - Exploracion global (sin reservar):
			Para cada movimiento bancario pendiente busca el mejor subconjunto
			JDE posible ignorando conflictos. Se obtiene una propuesta
			candidata por banco.

		FASE 2 - Resolucion de conflictos:
			Ordena todas las propuestas por precision (menor diferencia de
			monto -> mayor prioridad). Acepta en orden; si una propuesta
			comparte indices JDE con otra ya aceptada, intenta encontrar
			un subconjunto alternativo usando solo los JDE aun disponibles.
			Asi ambos movimientos bancarios tienen la misma oportunidad de
			quedar conciliados.

		NO marca ``is_matched`` - eso lo hace ``confirm_grouped_matches``.
		"""

		# FASE 1: exploracion global sin reservar
		raw_proposals: list = []

		for bank_index, bank_row in bank_dataframe.iterrows():

			if bank_row["is_matched"]:
				continue

			target_amount = round(bank_row["abs_amount"], self.engine.rounding_decimals)
			bank_date = bank_row["movement_date"]

			available_jde = jde_dataframe[
				(jde_dataframe["is_matched"] == False)
				& (self.engine._is_date_within_tolerance(
					bank_date, jde_dataframe["movement_date"]
				))
			]

			if available_jde.empty:
				continue

			available_jde = self.engine._filter_by_tienda(
				available_jde, bank_row, jde_dataframe
			)

			if available_jde.empty:
				continue

			# Refinar por comision (simetrico)
			available_jde = self.engine._filter_by_comision(available_jde, bank_row)
			# Regla: CARGO POR DISPERSION solo con NOMINA
			available_jde = self._apply_dispersion_nomina_rule_forward(available_jde, bank_row)

			# Tienda estricta para agrupaciones
			available_jde = self._enforce_strict_tienda(available_jde, bank_row)
			# Tipo de pago estricto para agrupaciones
			available_jde = self._enforce_strict_tipo_pago(available_jde, bank_row)

			if available_jde.empty:
				continue

			filtered = available_jde[
				available_jde["abs_amount"] <= target_amount + self.engine.amount_tolerance
			].copy()

			if filtered.empty:
				continue

			subset_result = self.try_subsets_per_tienda(filtered, target_amount)

			min_group_size = getattr(self.engine, "forward_grouped_min_size", 1)
			if not subset_result or len(subset_result) < min_group_size:
				continue

			matched_jde_indices = [idx for idx, _ in subset_result]
			accumulated = round(
				sum(round(r["abs_amount"], self.engine.rounding_decimals)
					for _, r in subset_result),
				self.engine.rounding_decimals,
			)

			raw_proposals.append({
				"bank_row_index": bank_index,
				"bank_snapshot": bank_row.to_dict(),
				"jde_row_indices": matched_jde_indices,
				"jde_snapshots": [row.to_dict() for _, row in subset_result],
				"amount_difference": round(target_amount - accumulated,
										   self.engine.rounding_decimals),
				"jde_count": len(matched_jde_indices),
			})

		# FASE 2: resolucion de conflictos
		# Prioridad: menor |diferencia de monto|, en empate menos registros JDE
		raw_proposals.sort(
			key=lambda p: (abs(p["amount_difference"]), p["jde_count"])
		)

		reserved_jde: set = set()
		final_proposals: list = []
		group_id: int = 0

		for proposal in raw_proposals:
			jde_set = set(proposal["jde_row_indices"])

			if jde_set.isdisjoint(reserved_jde):
				# Sin conflicto -> aceptar directamente
				reserved_jde.update(jde_set)
				proposal["group_id"] = group_id
				final_proposals.append(proposal)
				group_id += 1
			else:
				# Conflicto -> reintentar con solo los JDE disponibles
				bank_index = proposal["bank_row_index"]
				bank_row = bank_dataframe.loc[bank_index]
				target_amount = round(bank_row["abs_amount"], self.engine.rounding_decimals)
				bank_date = bank_row["movement_date"]

				alt_jde = jde_dataframe[
					(~jde_dataframe.index.isin(reserved_jde))
					& (jde_dataframe["is_matched"] == False)
					& (self.engine._is_date_within_tolerance(
						bank_date, jde_dataframe["movement_date"]
					))
				]

				if alt_jde.empty:
					continue

				alt_jde = self.engine._filter_by_tienda(
					alt_jde, bank_row, jde_dataframe
				)

				# Refinar por comision (simetrico)
				alt_jde = self.engine._filter_by_comision(alt_jde, bank_row)
				# Regla: CARGO POR DISPERSION solo con NOMINA
				alt_jde = self._apply_dispersion_nomina_rule_forward(alt_jde, bank_row)

				# Tienda estricta para agrupaciones
				alt_jde = self._enforce_strict_tienda(alt_jde, bank_row)
				# Tipo de pago estricto para agrupaciones
				alt_jde = self._enforce_strict_tipo_pago(alt_jde, bank_row)

				if alt_jde.empty:
					continue

				alt_filtered = alt_jde[
					alt_jde["abs_amount"] <= target_amount + self.engine.amount_tolerance
				].copy()

				if alt_filtered.empty:
					continue

				alt_result = self.try_subsets_per_tienda(
					alt_filtered, target_amount
				)

				min_group_size = getattr(self.engine, "forward_grouped_min_size", 1)
				if not alt_result or len(alt_result) < min_group_size:
					continue

				alt_indices = [idx for idx, _ in alt_result]
				reserved_jde.update(alt_indices)
				alt_accumulated = round(
					sum(round(r["abs_amount"], self.engine.rounding_decimals)
						for _, r in alt_result),
					self.engine.rounding_decimals,
				)

				final_proposals.append({
					"group_id": group_id,
					"bank_row_index": bank_index,
					"bank_snapshot": bank_row.to_dict(),
					"jde_row_indices": alt_indices,
					"jde_snapshots": [row.to_dict() for _, row in alt_result],
					"amount_difference": round(target_amount - alt_accumulated,
											   self.engine.rounding_decimals),
					"jde_count": len(alt_indices),
				})
				group_id += 1

		return final_proposals

	def try_subsets_per_tienda(
		self,
		filtered_candidates: "pd.DataFrame",
		target_amount: float,
	) -> "list | None":
		"""
		Intenta encontrar el mejor subset sum garantizando que todos los
		registros JDE del grupo pertenezcan a la MISMA tienda.

		Si los candidatos no tienen columna ``tienda`` o todos son de la
		misma tienda, se comporta igual que ``find_subset_sum_with_limit``
		directamente. Si hay varias tiendas, prueba cada una por separado
		y devuelve el resultado con menor diferencia de monto absoluta.
		"""
		has_tienda = (
			"tienda" in filtered_candidates.columns
			and filtered_candidates["tienda"].notna().any()
			and (filtered_candidates["tienda"].str.strip() != "").any()
		)

		if not has_tienda:
			# Sin info de tienda -> comportamiento original
			candidate_rows = list(
				filtered_candidates.nsmallest(
					self.engine.grouped_candidate_limit,
					"abs_amount",
				).iterrows()
			)
			return self.find_subset_sum_with_limit(candidate_rows, target_amount)

		# Obtener tiendas unicas presentes en los candidatos
		tiendas = (
			filtered_candidates["tienda"]
			.str.strip()
			.replace("", pd.NA)
			.dropna()
			.unique()
		)

		if len(tiendas) <= 1:
			# Una sola tienda -> sin riesgo de mezcla, camino directo
			candidate_rows = list(
				filtered_candidates.nsmallest(
					self.engine.grouped_candidate_limit,
					"abs_amount",
				).iterrows()
			)
			return self.find_subset_sum_with_limit(candidate_rows, target_amount)

		# Multiples tiendas -> probar cada una y conservar el mejor resultado
		best_result = None
		best_diff = float("inf")

		for tienda in tiendas:
			grupo = filtered_candidates[
				filtered_candidates["tienda"].str.strip() == tienda
			]
			candidate_rows = list(
				grupo.nsmallest(
					self.engine.grouped_candidate_limit,
					"abs_amount",
				).iterrows()
			)
			result = self.find_subset_sum_with_limit(candidate_rows, target_amount)
			if result is None:
				continue
			accumulated = round(
				sum(
					round(r["abs_amount"], self.engine.rounding_decimals)
					for _, r in result
				),
				self.engine.rounding_decimals,
			)
			diff = abs(target_amount - accumulated)
			if diff < best_diff:
				best_diff = diff
				best_result = result

		return best_result

	def propose_reverse_grouped_matches(
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
		movimientos bancarios (si fuera 1, el matching exacto ya lo cubriria).

		Caso tipico: varias comisiones bancarias separadas (-10, -5, -1.60, -0.80)
		que juntas suman la comision registrada en JDE (-17.40).
		"""
		# Bank rows reclamados por propuestas forward (para evitar doble uso)
		claimed_bank = {p["bank_row_index"] for p in forward_proposals}

		proposals: list = []
		group_id = start_group_id

		for jde_index, jde_row in jde_dataframe.iterrows():
			if jde_row["is_matched"]:
				continue

			target_amount = round(jde_row["abs_amount"], self.engine.rounding_decimals)
			jde_date = jde_row["movement_date"]
			jde_mvtype = jde_row.get("movement_type", "")
			jde_is_commission = self._is_jde_commission_row(jde_row)

			# Candidatos base: pendientes, dentro de fecha y cada uno menor que
			# el total JDE (si fuera igual, exacto ya matcheo).
			available_bank = bank_dataframe[
				(~bank_dataframe["is_matched"])
				& (~bank_dataframe.index.isin(claimed_bank))
				& (self.engine._is_date_within_tolerance(jde_date, bank_dataframe["movement_date"]))
				& (bank_dataframe["abs_amount"] < target_amount - self.engine.amount_tolerance)
			].copy()

			if jde_is_commission:
				# En datos reales banco, las comisiones llegan como RETIRO.
				# Permitir RETIRO/COM y reforzar por descripcion de comision.
				bank_mvtype = available_bank["movement_type"].fillna("").astype(str).str.strip().str.upper()
				available_bank = available_bank[bank_mvtype.isin(["RETIRO", "COM", "WDR"])].copy()
				if not available_bank.empty:
					commission_mask = available_bank.apply(self._is_bank_commission_row, axis=1)
					if commission_mask.any():
						available_bank = available_bank[commission_mask].copy()
			else:
				available_bank = available_bank[
					available_bank["movement_type"] == jde_mvtype
				].copy()

			if len(available_bank) < 2:
				continue

			# Regla simetrica: NOMINA <-> CARGO POR DISPERSION
			available_bank = self._apply_dispersion_nomina_rule_reverse(available_bank, jde_row)

			if len(available_bank) < 2:
				continue

			# Filtro estricto de tienda para inversos:
			# - JDE con tienda -> bancos de misma tienda exacta.
			# - JDE sin tienda -> solo bancos sin tienda/NO ENCONTRADO.
			jde_tienda = ""
			try:
				_t = jde_row.get("tienda") if hasattr(jde_row, "get") else jde_row["tienda"]
				if not pd.isna(_t) and str(_t).strip().upper() not in ("", "NAN", "NONE", "NA", "<NA>", "NO ENCONTRADO"):
					jde_tienda = str(_t).strip().upper()
			except (KeyError, TypeError):
				pass

			if "tienda" in available_bank.columns and getattr(self.engine, "enforce_grouped_strict_tienda", False):
				bank_tienda_upper = available_bank["tienda"].fillna("").str.strip().str.upper()
				if jde_tienda:
					available_bank = available_bank[
						bank_tienda_upper == jde_tienda
					].copy()
				else:
					available_bank = available_bank[
						bank_tienda_upper.isin(["", "NO ENCONTRADO"])
					].copy()

			# Tipo de pago estricto para inversos:
			# - JDE con tipo_jde -> bancos solo con tipo_banco compatible.
			# - JDE sin tipo_jde -> bancos solo sin tipo_banco.
			if "tipo_banco" in available_bank.columns:
				jde_tipo = str(jde_row.get("tipo_jde") or "").strip().upper()
				bank_tipo = available_bank["tipo_banco"].fillna("").astype(str).str.strip().str.upper()
				if jde_tipo:
					allowed_bank_tipos = {
						b_tipo for b_tipo, jde_set in self.engine._TIPO_MAP.items()
						if jde_tipo in jde_set
					}
					# Para efectivo (01), permitir también banco sin tipo explícito.
					if jde_tipo == "01":
						allowed_bank_tipos |= {"", "NO ENCONTRADO", "NAN", "NONE", "<NA>"}
					if allowed_bank_tipos:
						available_bank = available_bank[bank_tipo.isin(allowed_bank_tipos)].copy()
					else:
						available_bank = available_bank[bank_tipo == jde_tipo].copy()
				else:
					available_bank = available_bank[bank_tipo.isin(["", "NO ENCONTRADO", "NAN", "NONE", "<NA>"])].copy()

			if len(available_bank) < 2:
				continue

			# Sesgo 6614 comisiones: intentar primero subset solo con codigos
			# de comision (537/517/600/601). Si no cuadra, fallback normal.
			result = None
			used_bias_6614 = False
			bias_candidates = self._get_6614_commission_candidates(available_bank, jde_row)
			if len(bias_candidates) >= 2:
				# En 6614 comisiones, los grupos pueden requerir muchas piezas
				# (p. ej. multiples 100 + 16 + 5 + 0.8). No recortar por nsmallest.
				biased_rows = list(bias_candidates.iterrows())
				# Sin limite artificial de tamano de grupo en este sesgo.
				# El limite real queda dado por el total de candidatos con cod_transac objetivo.
				dynamic_max_group_size = len(biased_rows)
				bias_result = self.find_subset_sum_with_limit(
					biased_rows,
					target_amount,
					max_group_size=dynamic_max_group_size,
				)
				if bias_result is not None and len(bias_result) >= 2:
					result = bias_result
					used_bias_6614 = True

			if result is None:
				candidate_rows = list(
					available_bank.nsmallest(
						self.engine.grouped_candidate_limit,
						"abs_amount",
					).iterrows()
				)
				result = self.find_subset_sum_with_limit(candidate_rows, target_amount)

			if result is None or len(result) < 2:
				continue

			bank_indices = [idx for idx, _ in result]
			accumulated = round(
				sum(round(r["abs_amount"], self.engine.rounding_decimals) for _, r in result),
				self.engine.rounding_decimals,
			)
			diff = round(target_amount - accumulated, self.engine.rounding_decimals)

			# Marcar como reclamados para evitar solapamientos dentro de esta fase
			claimed_bank.update(bank_indices)

			proposals.append({
				"group_id": group_id,
				"jde_row_index": jde_index,
				"jde_snapshot": jde_row.to_dict(),
				"bank_row_indices": bank_indices,
				"bank_snapshots": [r.to_dict() for _, r in result],
				"amount_difference": diff,
				"bank_count": len(bank_indices),
			})
			group_id += 1
			if used_bias_6614:
				logger.info(
					"[REV-GROUPED-6614-BIAS] JDE idx=%d conciliado con sesgo COD.TRANSAC 537/517/600/601",
					jde_index,
				)
			logger.info(
				"[REV-GROUPED] JDE idx=%d  amt=%.2f -> %d filas banco  diff=%.2f",
				jde_index, target_amount, len(bank_indices), diff,
			)

		return proposals

	def find_subset_sum_with_limit(self, candidate_rows, target_amount, max_group_size=None):
		"""
		Encuentra un subconjunto de candidate_rows cuya suma sea lo mas
		cercano posible al target_amount (dentro de tolerancia).

		Estrategia: busca la solucion MEJOR (mas montos incluidos, menor
		diferencia) en lugar de retornar la PRIMERA solucion encontrada.
		Esto evita casos donde se ignoran centavos pequenos innecesariamente.
		"""
		# Ordenar ascendente: los montos mas pequenos primero -> maximiza inclusion
		sorted_candidates = sorted(
			candidate_rows,
			key=lambda row: round(
				row[1]["abs_amount"],
				self.engine.rounding_decimals
			),
			reverse=False,
		)

		# Suma de sufijos para poda adicional
		amounts = [round(r[1]["abs_amount"], self.engine.rounding_decimals) for r in sorted_candidates]
		suffix_sums = [0.0] * (len(amounts) + 1)
		for i in range(len(amounts) - 1, -1, -1):
			suffix_sums[i] = suffix_sums[i + 1] + amounts[i]

		best_result = None
		best_diff = float("inf")
		effective_max_group_size = (
			self.engine.maximum_group_size
			if max_group_size is None
			else max(1, int(max_group_size))
		)

		def backtracking_search(
			start_position,
			current_combination,
			current_sum,
		):
			nonlocal best_result, best_diff

			if len(current_combination) > effective_max_group_size:
				return

			current_diff = abs(round(current_sum - target_amount, self.engine.rounding_decimals))

			# Si esta solucion es mejor (menor diferencia, o misma diferencia pero mas montos)
			if current_diff <= self.engine.amount_tolerance:
				if (
					current_diff < best_diff
					or (current_diff == best_diff and len(current_combination) > len(best_result or []))
				):
					best_diff = current_diff
					best_result = current_combination

			if current_sum > target_amount + self.engine.amount_tolerance:
				return

			# Poda: ni sumando todo lo que queda podemos alcanzar el target
			remaining = target_amount - current_sum
			if suffix_sums[start_position] < remaining - self.engine.amount_tolerance:
				return

			for index in range(start_position, len(sorted_candidates)):

				jde_index, jde_row = sorted_candidates[index]

				movement_amount = round(
					jde_row["abs_amount"],
					self.engine.rounding_decimals
				)

				backtracking_search(
					index + 1,
					current_combination + [(jde_index, jde_row)],
					round(current_sum + movement_amount,
						  self.engine.rounding_decimals)
				)

		backtracking_search(0, [], 0)
		return best_result
