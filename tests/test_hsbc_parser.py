import unittest

import pandas as pd

from src.parsers.bank_parser import BankParser, _HSBCParser


class TestHSBCParser(unittest.TestCase):
    def test_detect_format_with_accented_headers(self):
        header = [
            "Nombre de cuenta",
            "Número de cuenta",
            "Nombre del banco",
            "Moneda",
            "Ubicación",
            "BIC",
            "IBAN",
            "Estatus de cuenta",
            "Tipo de cuenta",
            "Saldo en libros al cierre",
            "Saldo en libros final al cierre del ejercicio anterior de",
            "Saldo disponible al cierre",
            "Saldo final disponible del ejercicio anterior de",
            "Saldo actual en libros",
            "Saldo actual en libros al",
            "Saldo actual disponible",
            "Saldo actual disponible al",
            "Referencia bancaria",
            "Descripción",
            "Referencia de cliente",
            "Tipo de TRN",
            "Fecha valor",
            "Importe de crédito",
            "Importe del débito",
            "Saldo",
            "Hora de cargo o abono",
            "Fecha del apunte",
        ]
        row = ["CESANTONI, S.A. DE C.V.", "4066730177", "HSBC Mexico"] + [""] * (len(header) - 3)
        raw = pd.DataFrame([header, row])

        detected = BankParser._detect_format(raw)
        self.assertIs(detected, _HSBCParser)

    def test_parse_extracts_account_id_from_numero_de_cuenta(self):
        raw = pd.DataFrame([
            [
                "Nombre de cuenta", "Número de cuenta", "Nombre del banco", "Moneda", "Ubicación",
                "BIC", "IBAN", "Estatus de cuenta", "Tipo de cuenta", "Saldo en libros al cierre",
                "Saldo en libros final al cierre del ejercicio anterior de", "Saldo disponible al cierre",
                "Saldo final disponible del ejercicio anterior de", "Saldo actual en libros",
                "Saldo actual en libros al", "Saldo actual disponible", "Saldo actual disponible al",
                "Referencia bancaria", "Descripción", "Referencia de cliente", "Tipo de TRN",
                "Fecha valor", "Importe de crédito", "Importe del débito", "Saldo",
                "Hora de cargo o abono", "Fecha del apunte",
            ],
            [
                "CESANTONI, S.A. DE C.V.", "4066730177", "HSBC Mexico", "MXN", "MEXICO",
                "BIMEMXMM", "No disponible", "Activo", "Cuenta de cheques", "71,775.29",
                "01/04/2026", "71,775.29", "01/04/2026", "71,775.29", "No disponible",
                "71,775.29", "No disponible", "5629", "TRANSF SOL X HSBCNET VICTOR JESUS",
                "A2000 09004", "00005629", "01/04/2026", "", "-3,845.87", "72,446.31",
                "12:27", "01/04/2026",
            ],
        ])

        parsed = _HSBCParser().parse_raw(raw)
        self.assertFalse(parsed.empty)
        self.assertEqual(str(parsed.iloc[0]["account_id"]), "4066730177")
        self.assertEqual(str(parsed.iloc[0]["bank"]), "HSBC")


if __name__ == "__main__":
    unittest.main()
