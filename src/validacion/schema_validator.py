from datetime import datetime
import pandas as pd


class SchemaValidationError(Exception):
    """Error personalizado para validación de schema."""
    pass


class DataFrameSchemaValidator:
    """
    Valida que los DataFrames de banco y JDE cumplan
    con el formato estándar requerido por el motor.
    """

    REQUIRED_COLUMNS = {
        "account_id",
        "movement_date",
        "description",
        "amount_signed",
        "abs_amount",
        "movement_type",
        "source"
    }

    @classmethod
    def validate_bank_dataframe(cls, bank_dataframe: pd.DataFrame):
        cls._validate_required_columns(bank_dataframe, "BANK")
        cls._validate_data_types(bank_dataframe, "BANK")
        cls._validate_null_values(bank_dataframe, "BANK")

    @classmethod
    def validate_jde_dataframe(cls, jde_dataframe: pd.DataFrame):
        cls._validate_required_columns(jde_dataframe, "JDE")
        cls._validate_data_types(jde_dataframe, "JDE")
        cls._validate_null_values(jde_dataframe, "JDE")

    # ============================================================
    # VALIDACIONES INTERNAS
    # ============================================================

    @classmethod
    def _validate_required_columns(cls, dataframe, source_name):

        missing_columns = cls.REQUIRED_COLUMNS - set(dataframe.columns)

        if missing_columns:
            raise SchemaValidationError(
                f"[{source_name}] Faltan columnas obligatorias: {missing_columns}"
            )

    @classmethod
    def _validate_data_types(cls, dataframe, source_name):

        if not pd.api.types.is_datetime64_any_dtype(dataframe["movement_date"]):
            raise SchemaValidationError(
                f"[{source_name}] 'movement_date' debe ser tipo datetime"
            )

        if not pd.api.types.is_numeric_dtype(dataframe["amount_signed"]):
            raise SchemaValidationError(
                f"[{source_name}] 'amount_signed' debe ser numérico"
            )

        if not pd.api.types.is_numeric_dtype(dataframe["abs_amount"]):
            raise SchemaValidationError(
                f"[{source_name}] 'abs_amount' debe ser numérico"
            )

        if not pd.api.types.is_string_dtype(dataframe["account_id"]):
            raise SchemaValidationError(
                f"[{source_name}] 'account_id' debe ser string"
            )

    @classmethod
    def _validate_null_values(cls, dataframe, source_name):

        critical_columns = [
            "account_id",
            "movement_date",
            "abs_amount"
        ]

        for column in critical_columns:
            if dataframe[column].isnull().any():
                raise SchemaValidationError(
                    f"[{source_name}] La columna '{column}' contiene valores nulos"
                )