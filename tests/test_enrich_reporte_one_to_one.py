import unittest

import pandas as pd

from main import _enrich_bank_with_reporte


class TestEnrichReporteOneToOne(unittest.TestCase):
    def test_does_not_reuse_same_reporte_row(self):
        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 15.0,
                "abs_amount": 15.0,
                "tienda": "",
                "tipo_banco": "",
            },
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 15.0,
                "abs_amount": 15.0,
                "tienda": "",
                "tipo_banco": "",
            },
        ])

        reporte_df = pd.DataFrame([
            {
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 15.0,
                "abs_amount": 15.0,
                "tienda": "JER",
                "tipo_banco": "01",
            }
        ])

        out = _enrich_bank_with_reporte(bank_df, reporte_df)
        tipos = out["tipo_banco"].fillna("").astype(str).str.strip().tolist()
        tiendas = out["tienda"].fillna("").astype(str).str.strip().tolist()

        self.assertEqual(tipos.count("01"), 1)
        self.assertEqual(tiendas.count("JER"), 1)

    def test_requires_signed_amount_match(self):
        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": -15.0,
                "abs_amount": 15.0,
                "tienda": "",
                "tipo_banco": "",
            }
        ])

        reporte_df = pd.DataFrame([
            {
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 15.0,
                "abs_amount": 15.0,
                "tienda": "JER",
                "tipo_banco": "01",
            }
        ])

        out = _enrich_bank_with_reporte(bank_df, reporte_df)
        tipo = out.loc[0, "tipo_banco"]
        tienda = out.loc[0, "tienda"]

        self.assertIn(tipo, ["", None])
        self.assertIn(tienda, ["", None])

    def test_allows_date_tolerance_for_same_signed_amount(self):
        bank_df = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-03-28"),
                "amount_signed": 1144.33,
                "abs_amount": 1144.33,
                "tienda": "",
                "tipo_banco": "",
            }
        ])

        reporte_df = pd.DataFrame([
            {
                "movement_date": pd.Timestamp("2026-03-30"),
                "amount_signed": 1144.33,
                "abs_amount": 1144.33,
                "tienda": "BLVD",
                "tipo_banco": "TR",
            }
        ])

        out = _enrich_bank_with_reporte(bank_df, reporte_df)
        self.assertEqual(out.loc[0, "tienda"], "BLVD")
        self.assertEqual(out.loc[0, "tipo_banco"], "TR")


if __name__ == "__main__":
    unittest.main()
