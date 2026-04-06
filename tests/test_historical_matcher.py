import unittest

import pandas as pd

from src.matching.historical_matcher import match_historical_pendientes


class TestHistoricalMatcher(unittest.TestCase):
    def test_historical_does_not_reserve_candidates(self):
        hist_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 100.0,
                "abs_amount": 100.0,
                "description": "pendiente 1",
                "section": "mas",
                "type_code": "H",
            },
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 100.0,
                "abs_amount": 100.0,
                "description": "pendiente 2",
                "section": "mas",
                "type_code": "H",
            },
        ])

        conciliated_jde = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 100.0,
                "abs_amount": 100.0,
                "description": "match unico",
            }
        ])

        out = match_historical_pendientes(
            hist_df,
            conciliated_jde=conciliated_jde,
            require_same_account=True,
        )

        self.assertEqual((out["match_status"] == "CONCILIADO").sum(), 2)

    def test_historical_enforces_same_sign_by_default(self):
        hist_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": -27.84,
                "abs_amount": 27.84,
                "description": "comision historica",
                "section": "mas",
                "type_code": "H",
            }
        ])

        conciliated_bank = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 27.84,
                "abs_amount": 27.84,
                "description": "abono",
            }
        ])

        out = match_historical_pendientes(
            hist_df,
            conciliated_bank=conciliated_bank,
            require_same_account=True,
        )

        self.assertEqual(out.loc[0, "match_status"], "AUN_PENDIENTE")

    def test_section_mas_prioritizes_jde_side(self):
        hist_df = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -3845.87,
                "abs_amount": 3845.87,
                "description": "historico mas",
                "section": "mas",
                "type_code": "PN",
            }
        ])

        conciliated_bank = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -3845.87,
                "abs_amount": 3845.87,
                "description": "lado banco",
            }
        ])

        conciliated_jde = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -3845.87,
                "abs_amount": 3845.87,
                "description": "lado jde",
            }
        ])

        out = match_historical_pendientes(
            hist_df,
            conciliated_bank=conciliated_bank,
            conciliated_jde=conciliated_jde,
            require_same_account=True,
        )

        self.assertEqual(out.loc[0, "match_status"], "CONCILIADO")
        self.assertEqual(out.loc[0, "match_source"], "CONCILIADO_JDE")

    def test_section_menos_prioritizes_bank_side(self):
        hist_df = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -1000.0,
                "abs_amount": 1000.0,
                "description": "historico menos",
                "section": "menos",
                "type_code": "PN",
            }
        ])

        pending_bank = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -1000.0,
                "abs_amount": 1000.0,
                "description": "pendiente banco",
            }
        ])

        pending_jde = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "amount_signed": -1000.0,
                "abs_amount": 1000.0,
                "description": "pendiente jde",
            }
        ])

        out = match_historical_pendientes(
            hist_df,
            pending_bank=pending_bank,
            pending_jde=pending_jde,
            require_same_account=True,
        )

        self.assertEqual(out.loc[0, "match_status"], "PENDIENTE_BANCO")
        self.assertEqual(out.loc[0, "match_source"], "PENDIENTE_BANCO")

    def test_section_mas_does_not_fallback_to_bank_side(self):
        hist_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 1520.0,
                "abs_amount": 1520.0,
                "description": "historico mas",
                "section": "mas",
                "type_code": "01",
            }
        ])

        pending_bank = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 1520.0,
                "abs_amount": 1520.0,
                "description": "Deposito en efectivo",
            }
        ])

        out = match_historical_pendientes(
            hist_df,
            pending_bank=pending_bank,
            pending_jde=pd.DataFrame(),
            require_same_account=True,
        )

        self.assertEqual(out.loc[0, "match_status"], "AUN_PENDIENTE")
        self.assertEqual(out.loc[0, "match_source"], "")


if __name__ == "__main__":
    unittest.main()
