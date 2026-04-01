import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.parsers.bank_parser import BankParser


class TestBankParserReporteCajaSheetDetection(unittest.TestCase):
    def test_prefers_sheet_with_tienda_header(self):
        mov_dia = pd.DataFrame([
            ["FECHA", "Banco", "Monto", "CLIENTE", "UUID REP"],
            ["2026-03-02", "BANORTE 6614", "1000", "CLIENTE X", "ABC"],
        ])

        hoja4 = pd.DataFrame([
            ["FECHA", "Banco", "Monto", "TIENDA", "OBSERVACION"],
            ["2026-03-02", "BANORTE 6614", "1000", "OUTLET JALPA", "TR"],
        ])

        with tempfile.TemporaryDirectory() as td:
            file_path = Path(td) / "03M-MOV DIA MARZO 2026.xlsx"
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                mov_dia.to_excel(writer, index=False, header=False, sheet_name="MOV-DIA")
                hoja4.to_excel(writer, index=False, header=False, sheet_name="Hoja4")

            out = BankParser().parse(str(file_path))

        self.assertEqual(len(out), 1)
        self.assertEqual(out.loc[0, "bank"], "REPORTE_CAJA")
        self.assertEqual(out.loc[0, "tipo_banco"], "TR")


if __name__ == "__main__":
    unittest.main()
