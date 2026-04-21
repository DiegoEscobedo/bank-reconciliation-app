import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.reporting.excel_reporter import ExcelReporter


class TestExcelPendingBankReason(unittest.TestCase):
    def test_pending_bank_sheet_includes_unmatched_reason_column(self):
        reporter = ExcelReporter()

        pending_bank = pd.DataFrame([
            {
                "account_id": "6614",
                "movement_date": pd.Timestamp("2026-04-17"),
                "bank": "NETPAY",
                "tienda": "",
                "tipo_banco": "03",
                "description": "NETPAY | COMISION TOTAL + IVA",
                "amount_signed": -250.0,
                "source": "BANK",
                "no_match_reason": "Monto encontrado, pero fecha fuera de tolerancia",
            }
        ])

        empty_cols = [
            "account_id", "movement_date", "tienda", "tipo_jde",
            "doc_type", "document", "description", "amount_signed", "source"
        ]

        results = {
            "summary": {
                "total_bank_movements": 1,
                "total_jde_movements": 0,
                "exact_matches_count": 0,
                "grouped_matches_count": 0,
                "reverse_grouped_matches_count": 0,
                "pending_bank_count": 1,
                "pending_jde_count": 0,
            },
            "exact_matches": [],
            "grouped_matches": [],
            "reverse_grouped_matches": [],
            "pending_bank_movements": pending_bank,
            "pending_jde_movements": pd.DataFrame(columns=empty_cols),
            "conciliated_bank_movements": pd.DataFrame(),
            "conciliated_jde_movements": pd.DataFrame(),
        }

        with TemporaryDirectory() as tmp:
            output_path = reporter.generate(results, Path(tmp))
            df = pd.read_excel(output_path, sheet_name="Pendientes Banco")

        self.assertIn("Por qué no concilió", df.columns)
        self.assertEqual(
            str(df.loc[0, "Por qué no concilió"]),
            "Monto encontrado, pero fecha fuera de tolerancia",
        )


if __name__ == "__main__":
    unittest.main()
