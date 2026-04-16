import unittest

import pandas as pd

from src.matching.reconciliation_engine import ReconciliationEngine


class TestExactMatchingGuards(unittest.TestCase):
    def test_exact_accepts_unique_jde_tienda_when_bank_tienda_empty(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro banco",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
                "bank": "SCOTIABANK",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "OUG",
                "tipo_jde": "03",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)

    def test_exact_rejects_ambiguous_jde_tiendas_when_bank_tienda_empty(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro banco",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
                "bank": "SCOTIABANK",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde 1",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "OUG",
                "tipo_jde": "03",
            },
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde 2",
                "doc_type": "JE",
                "document": "2",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "FAB",
                "tipo_jde": "03",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 0)

    def test_exact_allows_unique_amount_match_even_with_multiple_stores_on_date(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro banco",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
                "bank": "SCOTIABANK",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde monto objetivo",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "OUG",
                "tipo_jde": "03",
            },
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde otro monto",
                "doc_type": "JE",
                "document": "2",
                "amount_signed": -6000.0,
                "abs_amount": 6000.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "FAB",
                "tipo_jde": "03",
            },
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)

    def test_exact_does_not_cross_deposit_with_withdrawal(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro banco",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
                "bank": "SCOTIABANK",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "deposito jde",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": 5040.0,
                "abs_amount": 5040.0,
                "movement_type": "DEPOSITO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "03",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 0)

    def test_exact_requires_account_compatibility_when_present(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro banco",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
                "bank": "SCOTIABANK",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde otra cuenta",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "03",
            },
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-03-26"),
                "description": "retiro jde cuenta correcta",
                "doc_type": "JE",
                "document": "2",
                "amount_signed": -5040.0,
                "abs_amount": 5040.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "03",
            },
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)
        matched = result["exact_matches"][0]
        self.assertEqual(matched["jde_row_index"], 1)

    def test_exact_treats_no_encontrado_as_missing_store(self):
        bank_df = pd.DataFrame([
            {
                "abs_amount": 43.74,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "DEPOSITO",
                "description": "SPEI RECIBIDO",
                "tienda": "NO ENCONTRADO",
                "tipo_banco": "01",
                "account_id": "0884166614",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "abs_amount": 43.74,
                "movement_date": pd.Timestamp("2026-03-30"),
                "movement_type": "DEPOSITO",
                "description": "SOB DE GTOS 300326",
                "tienda": "",
                "tipo_jde": "01",
                "account_id": "6614",
            }
        ])

        engine = ReconciliationEngine()
        interactive = engine.reconcile_interactive(bank_df.copy(), jde_df.copy())

        assert len(interactive["exact_matches"]) == 1

    def test_exact_treats_unknown_account_as_missing(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "UNKNOWN",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "TRANSF SOL X HSBCNET VICTOR JESUS",
                "amount_signed": -3845.87,
                "abs_amount": 3845.87,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "0177",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "CUELLAR REYNA VICTOR JESUS",
                "doc_type": "PN",
                "document": "11",
                "amount_signed": -3845.87,
                "abs_amount": 3845.87,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "01",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)

    def test_exact_matches_when_bank_account_has_float_suffix(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "20305077133.0",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "SPEI TRASPASO",
                "amount_signed": -350000.0,
                "abs_amount": 350000.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "13 TRASPASO ALA",
                "doc_type": "AA",
                "document": "2756125",
                "amount_signed": -350000.0,
                "abs_amount": 350000.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "NO ENCONTRADO",
                "tipo_jde": "03",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)

    def test_exact_prioritizes_bank_rows_with_fewer_candidates(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "UNKNOWN",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "mov flexible",
                "amount_signed": -100.0,
                "abs_amount": 100.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
            },
            {
                "account_id": "1234",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "mov restringido",
                "amount_signed": -100.0,
                "abs_amount": 100.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "tienda": "",
            },
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "1234",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "jde cuenta 1234",
                "doc_type": "AA",
                "document": "1",
                "amount_signed": -100.0,
                "abs_amount": 100.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "03",
            },
            {
                "account_id": "5678",
                "movement_date": pd.Timestamp("2026-04-01"),
                "description": "jde cuenta 5678",
                "doc_type": "AA",
                "document": "2",
                "amount_signed": -100.0,
                "abs_amount": 100.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "",
                "tipo_jde": "03",
            },
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 2)

    def test_netpay_does_not_match_jde_efectivo_tipo_01(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "NETPAY VENTA TARJETA",
                "amount_signed": 1000.0,
                "abs_amount": 1000.0,
                "movement_type": "DEPOSITO",
                "source": "BANK",
                "bank": "NETPAY",
                "tienda": "FAB",
                "tipo_banco": "04",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "COBRO EFECTIVO",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": 1000.0,
                "abs_amount": 1000.0,
                "movement_type": "DEPOSITO",
                "source": "JDE",
                "tienda": "OUZ",
                "tipo_jde": "01",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 0)

    def test_netpay_exact_respects_tienda(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "NETPAY VENTA TARJETA",
                "amount_signed": 1000.0,
                "abs_amount": 1000.0,
                "movement_type": "DEPOSITO",
                "source": "BANK",
                "bank": "NETPAY",
                "tienda": "FAB",
                "tipo_banco": "TPV",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "COBRO TARJETA OTRA TIENDA",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": 1000.0,
                "abs_amount": 1000.0,
                "movement_type": "DEPOSITO",
                "source": "JDE",
                "tienda": "OUZ",
                "tipo_jde": "04",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 0)

    def test_mercadopago_tpv_does_not_match_jde_efectivo_tipo_01(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "MERCADO PAGO | OUTLET ZACATECAS",
                "amount_signed": 1500.0,
                "abs_amount": 1500.0,
                "movement_type": "DEPOSITO",
                "source": "BANK",
                "bank": "MERCADOPAGO",
                "tienda": "OUZ",
                "tipo_banco": "TPV",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "7133",
                "movement_date": pd.Timestamp("2026-04-10"),
                "description": "COBRO EFECTIVO",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": 1500.0,
                "abs_amount": 1500.0,
                "movement_type": "DEPOSITO",
                "source": "JDE",
                "tienda": "OUZ",
                "tipo_jde": "01",
            }
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 0)

    def test_netpay_commission_exact_ignores_store_ambiguity(self):
        engine = ReconciliationEngine()

        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-11"),
                "description": "NETPAY | COMISION TOTAL + IVA",
                "amount_signed": -250.0,
                "abs_amount": 250.0,
                "movement_type": "RETIRO",
                "source": "BANK",
                "bank": "NETPAY",
                "tienda": "",
                "tipo_banco": "03",
            }
        ])

        jde_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-11"),
                "description": "COMISION TARJETA SUC A",
                "doc_type": "JE",
                "document": "1",
                "amount_signed": -250.0,
                "abs_amount": 250.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "A1",
                "tipo_jde": "03",
            },
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-11"),
                "description": "COMISION TARJETA SUC B",
                "doc_type": "JE",
                "document": "2",
                "amount_signed": -250.0,
                "abs_amount": 250.0,
                "movement_type": "RETIRO",
                "source": "JDE",
                "tienda": "B1",
                "tipo_jde": "03",
            },
        ])

        result = engine.reconcile(bank_df, jde_df)
        self.assertEqual(result["summary"]["exact_matches_count"], 1)

if __name__ == "__main__":
    unittest.main()
