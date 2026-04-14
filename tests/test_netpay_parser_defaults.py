import unittest

import pandas as pd

from src.parsers.bank_parser import _NetPayParser


class TestNetPayParserDefaults(unittest.TestCase):
    def test_netpay_parser_sets_tipo_banco_tpv_by_default(self):
        raw = pd.DataFrame([
            ["FECHA TRX", "CUENTA DESTINO", "SUCURSAL", "MONTO DE TRX"],
            ["2026-04-10", "0884166614", "CESANTONI", "1000.00"],
        ])

        out = _NetPayParser().parse_raw(raw)

        self.assertFalse(out.empty)
        self.assertIn("tipo_banco", out.columns)
        self.assertTrue((out["tipo_banco"] == "TPV").all())

    def test_netpay_parser_generates_single_consolidated_commission_row(self):
        raw = pd.DataFrame([
            [
                "FECHA TRX", "CUENTA DESTINO", "SUCURSAL", "MONTO DE TRX",
                "COMISIONES", "IVA",
            ],
            ["2026-04-10", "0884166614", "CESANTONI", "1000.00", "10.00", "1.60"],
            ["2026-04-11", "0884166614", "CESANTONI", "500.00", "5.00", "0.80"],
        ])

        out = _NetPayParser().parse_raw(raw)

        self.assertFalse(out.empty)
        commission_rows = out[out["description"].str.contains("COMISION TOTAL \+ IVA", case=False, na=False)]
        self.assertEqual(len(commission_rows), 1)
        self.assertEqual(commission_rows.iloc[0]["raw_withdrawal"], "17.40")
        self.assertEqual(commission_rows.iloc[0]["raw_deposit"], "")

    def test_netpay_parser_consolidates_commission_even_without_trx_amount_and_negative_values(self):
        raw = pd.DataFrame([
            [
                "FECHA TRX", "CUENTA DESTINO", "SUCURSAL", "MONTO DE TRX",
                "COMISIONES", "IVA",
            ],
            ["2026-04-10", "0884166614", "CESANTONI", "", "-10.00", "-1.60"],
            ["2026-04-11", "0884166614", "CESANTONI", "", "-5.00", "-0.80"],
        ])

        out = _NetPayParser().parse_raw(raw)

        commission_rows = out[out["description"].str.contains("COMISION TOTAL \+ IVA", case=False, na=False)]
        self.assertEqual(len(commission_rows), 1)
        self.assertEqual(commission_rows.iloc[0]["raw_withdrawal"], "17.40")

    def test_netpay_parser_does_not_double_count_when_combined_commission_column_exists(self):
        # Caso real NetPay: el header puede incluir "IVA Comisiones" y
        # "Comisiones + IVA"; se debe usar el total combinado sin duplicar.
        raw = pd.DataFrame([
            [
                "FECHA TRX", "CUENTA DESTINO", "SUCURSAL", "MONTO DE TRX",
                "IVA Comisiones (16%)", "Comisiones + IVA",
            ],
            ["2026-04-10", "0884166614", "CESANTONI", "1000.00", "1.60", "11.60"],
            ["2026-04-11", "0884166614", "CESANTONI", "500.00", "0.80", "5.80"],
        ])

        out = _NetPayParser().parse_raw(raw)

        commission_rows = out[out["description"].str.contains("COMISION TOTAL \+ IVA", case=False, na=False)]
        self.assertEqual(len(commission_rows), 1)
        self.assertEqual(commission_rows.iloc[0]["raw_withdrawal"], "17.40")


if __name__ == "__main__":
    unittest.main()
