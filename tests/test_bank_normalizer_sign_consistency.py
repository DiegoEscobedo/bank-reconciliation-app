import unittest

import pandas as pd

from src.normalizers.bank_normalizer import BankNormalizer


class TestBankNormalizerSignConsistency(unittest.TestCase):
    def setUp(self):
        self.normalizer = BankNormalizer()

    def test_negative_amount_in_deposit_column_is_treated_as_retiro(self):
        raw_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "raw_date": "01/04/2026",
                "description": "SPEI salida",
                "description_detail": "",
                "raw_deposit": "-350,000.00",
                "raw_withdrawal": "",
            }
        ])

        out = self.normalizer.normalize(raw_df)

        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.loc[0, "amount_signed"], -350000.0)
        self.assertEqual(out.loc[0, "movement_type"], "RETIRO")

    def test_positive_amount_in_withdrawal_column_is_treated_as_retiro(self):
        raw_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "raw_date": "01/04/2026",
                "description": "ajuste entrada",
                "description_detail": "",
                "raw_deposit": "",
                "raw_withdrawal": "257.76",
            }
        ])

        out = self.normalizer.normalize(raw_df)

        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.loc[0, "amount_signed"], -257.76)
        self.assertEqual(out.loc[0, "movement_type"], "RETIRO")

    def test_regular_deposit_keeps_existing_behavior(self):
        raw_df = pd.DataFrame([
            {
                "account_id": "20305077133",
                "raw_date": "01/04/2026",
                "description": "deposito normal",
                "description_detail": "",
                "raw_deposit": "1,000.00",
                "raw_withdrawal": "",
            }
        ])

        out = self.normalizer.normalize(raw_df)

        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.loc[0, "amount_signed"], 1000.0)
        self.assertEqual(out.loc[0, "movement_type"], "DEPOSITO")


if __name__ == "__main__":
    unittest.main()
