import unittest

import pandas as pd

from src.parsers.bank_parser import _ReporteCajaParser


class TestReporteCajaParserTipo(unittest.TestCase):
    def test_tipo_detected_without_tienda_when_present_in_obs(self):
        raw = pd.DataFrame([
            ["FECHA", "Banco", "Monto", "TIENDA", "OBSERVACION"],
            ["2026-03-15", "BANORTE 6614", "1500", "TIENDA DESCONOCIDA", "Deposito TPV"],
        ])

        parser = _ReporteCajaParser()
        out = parser.parse_raw(raw)

        self.assertEqual(len(out), 1)
        self.assertEqual(out.loc[0, "tienda"], "NO ENCONTRADO")
        self.assertEqual(out.loc[0, "tipo_banco"], "TPV")

    def test_tipo_defaults_to_01_when_obs_is_empty(self):
        raw = pd.DataFrame([
            ["FECHA", "Banco", "Monto", "TIENDA", "OBSERVACION"],
            ["2026-03-15", "BANORTE 6614", "1500", "OUTLET JALPA", ""],
            ["2026-03-15", "BANORTE 6614", "900", "TIENDA NO MAPEADA", ""],
        ])

        parser = _ReporteCajaParser()
        out = parser.parse_raw(raw)

        self.assertEqual(len(out), 2)
        self.assertEqual(list(out["tipo_banco"]), ["01", "01"])

    def test_tipo_uses_obs_text_when_not_tr_or_tpv(self):
        raw = pd.DataFrame([
            ["FECHA", "Banco", "Monto", "TIENDA", "OBSERVACION"],
            ["2026-03-15", "BANORTE 6614", "700", "OUTLET JALPA", "EFECTIVO"],
            ["2026-03-15", "BANORTE 6614", "650", "TIENDA NO MAPEADA", "DEPOSITO MANUAL"],
        ])

        parser = _ReporteCajaParser()
        out = parser.parse_raw(raw)

        self.assertEqual(len(out), 2)
        self.assertEqual(list(out["tipo_banco"]), ["EFECTIVO", "DEPOSITO MANUAL"])


if __name__ == "__main__":
    unittest.main()
