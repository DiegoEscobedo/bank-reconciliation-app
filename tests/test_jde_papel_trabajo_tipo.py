import unittest

import pandas as pd

from src.parsers.jde_parser import PapelTrabajoParser


class TestJdePapelTrabajoTipo(unittest.TestCase):
    def test_forma_pago_variant_header_and_default_01(self):
        df = pd.DataFrame(
            {
                "Aux_Fact": ["A1", "A2", "A3"],
                "Descripcion": ["CUENTA 6614", "CUENTA 6614", "CUENTA 6614"],
                "Tp doc": ["RC", "RC", "RC"],
                "Numero documento": ["1001", "1002", "1003"],
                "Fecha LM": ["2026-03-01", "2026-03-01", "2026-03-01"],
                "Importe": ["100", "200", "300"],
                "Explicacion -observacion-": ["x", "y", "z"],
                "Nombre alfa explicacion": ["x", "y", "z"],
                "Forma de pago": ["3", "", "999"],
                "TIENDA": ["", "", ""],
                "CONCILIADO": ["", "", ""],
                "_excel_row": [10, 11, 12],
            }
        )

        parser = PapelTrabajoParser()
        out = parser._build_output(df, "dummy.xlsx")

        self.assertEqual(len(out), 3)
        self.assertEqual(list(out["tipo_jde"]), ["03", "01", "01"])


if __name__ == "__main__":
    unittest.main()
