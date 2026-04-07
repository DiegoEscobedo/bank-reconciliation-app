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

    def test_conciliado_zero_is_kept_as_pending(self):
        df = pd.DataFrame(
            {
                "Aux_Fact": ["A1", "A2"],
                "Descripcion": ["CUENTA 7133", "CUENTA 7133"],
                "Tp doc": ["AA", "AA"],
                "Numero documento": ["2756125", "2756126"],
                "Fecha LM": ["2026-04-01", "2026-04-01"],
                "Importe": ["-350000", "-100"],
                "Explicacion -observacion-": ["13 TRASPASO ALA", "OTRO"],
                "Nombre alfa explicacion": ["13 TRASPASO", "OTRO"],
                "Forma de pago": ["3", "3"],
                "TIENDA": ["NO ENCONTRADO", "NO ENCONTRADO"],
                "CONCILIADO": ["0", "X"],
                "_excel_row": [50, 51],
            }
        )

        parser = PapelTrabajoParser()
        out = parser._build_output(df, "dummy.xlsx")

        # Solo debe conservar la fila con CONCILIADO=0 como pendiente.
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]["document"]), "2756125")


if __name__ == "__main__":
    unittest.main()
