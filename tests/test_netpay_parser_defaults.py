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


if __name__ == "__main__":
    unittest.main()
