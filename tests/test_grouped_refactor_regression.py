import unittest

import pandas as pd

from src.matching.reconciliation_engine import ReconciliationEngine


class TestGroupedRefactorRegression(unittest.TestCase):
    def test_forward_grouped_does_not_propose_single_row_group(self):
        engine = ReconciliationEngine()
        engine.forward_grouped_min_size = 2

        bank_df = pd.DataFrame([
            {
                "abs_amount": 100.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "abono tienda",
                "tienda": "A1",
                "tipo_banco": "TPV",
                "raw_deposit": 100.0,
            }
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 100.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta unica",
                "tienda": "A1",
                "tipo_jde": "28",
                "raw_deposit": 100.0,
            }
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        self.assertEqual(len(interactive["proposed_grouped_matches"]), 0)

    def test_forward_grouped_bank_without_tienda_uses_only_jde_without_tienda(self):
        engine = ReconciliationEngine()
        engine.enforce_grouped_strict_tienda = True
        engine.forward_grouped_min_size = 2

        bank_df = pd.DataFrame([
            {
                "abs_amount": 100.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "abono sin tienda",
                "tienda": "",
                "tipo_banco": "TPV",
                "raw_deposit": 100.0,
            }
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 60.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta con tienda",
                "tienda": "A1",
                "tipo_jde": "28",
                "raw_deposit": 60.0,
            },
            {
                "abs_amount": 40.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta sin tienda",
                "tienda": "",
                "tipo_jde": "28",
                "raw_deposit": 40.0,
            },
            {
                "abs_amount": 60.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta sin tienda 2",
                "tienda": "NO ENCONTRADO",
                "tipo_jde": "28",
                "raw_deposit": 60.0,
            },
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        proposals = interactive["proposed_grouped_matches"]

        self.assertEqual(len(proposals), 1)
        self.assertEqual(set(proposals[0]["jde_row_indices"]), {1, 2})

    def test_forward_grouped_proposal_and_confirmation(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "abs_amount": 100.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "abono tienda",
                "tienda": "A1",
                "tipo_banco": "TPV",
                "raw_deposit": 100.0,
            }
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 60.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta 1",
                "tienda": "A1",
                "tipo_jde": "28",
                "raw_deposit": 60.0,
            },
            {
                "abs_amount": 40.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta 2",
                "tienda": "A1",
                "tipo_jde": "28",
                "raw_deposit": 40.0,
            },
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        proposals = interactive["proposed_grouped_matches"]

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["bank_row_index"], 0)
        self.assertEqual(set(proposals[0]["jde_row_indices"]), {0, 1})
        self.assertAlmostEqual(proposals[0]["amount_difference"], 0.0)

        result = engine.confirm_grouped_matches(interactive, {proposals[0]["group_id"]})
        self.assertEqual(result["summary"]["grouped_matches_count"], 1)
        self.assertEqual(result["summary"]["pending_bank_count"], 0)
        self.assertEqual(result["summary"]["pending_jde_count"], 0)

    def test_grouped_strict_tipo_pago_rejects_mismatch_without_store(self):
        engine = ReconciliationEngine()
        engine.enforce_grouped_strict_tienda = True
        engine.forward_grouped_min_size = 2

        bank_df = pd.DataFrame([
            {
                "abs_amount": 200.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "abono sin tienda",
                "tienda": "",
                "tipo_banco": "TPV",
                "raw_deposit": 200.0,
            }
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 120.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta sin tienda 1",
                "tienda": "",
                "tipo_jde": "02",
                "raw_deposit": 120.0,
            },
            {
                "abs_amount": 80.0,
                "movement_date": pd.Timestamp("2026-03-01"),
                "movement_type": "DEP",
                "description": "venta sin tienda 2",
                "tienda": "NO ENCONTRADO",
                "tipo_jde": "02",
                "raw_deposit": 80.0,
            },
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        proposals = interactive["proposed_grouped_matches"]

        self.assertEqual(len(proposals), 0)

    def test_reverse_grouped_proposal(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "abs_amount": 10.0,
                "movement_date": pd.Timestamp("2026-03-02"),
                "movement_type": "COM",
                "description": "comision uno",
                "tienda": "A1",
                "tipo_banco": "03",
                "raw_deposit": 10.0,
            },
            {
                "abs_amount": 5.0,
                "movement_date": pd.Timestamp("2026-03-02"),
                "movement_type": "COM",
                "description": "comision dos",
                "tienda": "A1",
                "tipo_banco": "03",
                "raw_deposit": 5.0,
            },
            {
                "abs_amount": 2.4,
                "movement_date": pd.Timestamp("2026-03-02"),
                "movement_type": "COM",
                "description": "comision tres",
                "tienda": "A1",
                "tipo_banco": "03",
                "raw_deposit": 2.4,
            },
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 17.4,
                "movement_date": pd.Timestamp("2026-03-02"),
                "movement_type": "COM",
                "description": "comision agrupada",
                "tienda": "A1",
                "tipo_jde": "03",
                "raw_deposit": 17.4,
            }
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        reverse = interactive["proposed_reverse_grouped_matches"]

        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]["jde_row_index"], 0)
        self.assertEqual(set(reverse[0]["bank_row_indices"]), {0, 1, 2})
        self.assertAlmostEqual(reverse[0]["amount_difference"], 0.0)

        result = engine.confirm_grouped_matches(interactive, {reverse[0]["group_id"]})
        self.assertEqual(result["summary"]["reverse_grouped_matches_count"], 1)
        self.assertEqual(result["summary"]["pending_bank_count"], 0)
        self.assertEqual(result["summary"]["pending_jde_count"], 0)

    def test_reverse_grouped_allows_empty_bank_tipo_for_jde_01(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "abs_amount": 15.0,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "comision uno",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 15.0,
            },
            {
                "abs_amount": 5.0,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "comision dos",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 5.0,
            },
            {
                "abs_amount": 4.0,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "comision tres",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 4.0,
            },
            {
                "abs_amount": 2.4,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "iva comision",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 2.4,
            },
            {
                "abs_amount": 0.8,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "iva spei",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 0.8,
            },
            {
                "abs_amount": 0.64,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "iva comision dos",
                "tienda": "",
                "tipo_banco": "",
                "raw_deposit": 0.64,
            },
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 27.84,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "COM",
                "description": "06 COMISION BANCARIA ALA",
                "tienda": "",
                "tipo_jde": "01",
                "raw_deposit": 27.84,
            }
        ])

        interactive = engine.reconcile_interactive(bank_df, jde_df)
        reverse = interactive["proposed_reverse_grouped_matches"]

        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]["jde_row_index"], 0)
        self.assertEqual(set(reverse[0]["bank_row_indices"]), {0, 1, 2, 3, 4, 5})


if __name__ == "__main__":
    unittest.main()
