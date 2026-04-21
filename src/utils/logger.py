"""
logger.py — Configuración centralizada de logging para el proyecto.

Uso:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Mensaje informativo")
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Directorio de logs en la raíz del proyecto
_LOGS_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_LOG_FILE = _LOGS_DIR / "reconciliation.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Flag para evitar configurar el root logger más de una vez
_configured = False


def _parse_log_level(name: str, default: int) -> int:
    return getattr(logging, str(name or "").upper(), default)


def _parse_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except Exception:
        return default


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(fmt=_FORMAT, datefmt=_DATE_FORMAT)

    root_level = _parse_log_level(os.getenv("BANKREC_LOG_LEVEL", "INFO"), logging.INFO)
    console_level = _parse_log_level(os.getenv("BANKREC_CONSOLE_LOG_LEVEL", "INFO"), root_level)
    file_level = _parse_log_level(os.getenv("BANKREC_FILE_LOG_LEVEL", "DEBUG"), root_level)
    max_bytes = _parse_env_int("BANKREC_LOG_MAX_BYTES", 5 * 1024 * 1024)
    backup_count = _parse_env_int("BANKREC_LOG_BACKUP_COUNT", 5)

    # Handler consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    # Handler archivo con rotacion para limitar crecimiento en produccion
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(root_level)

    # Evitar duplicar handlers si alguien llama esto dos veces
    if not root.handlers:
        root.addHandler(console_handler)
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger configurado con el nombre dado.

    Parámetros
    ----------
    name : str
        Normalmente se pasa __name__ desde el módulo que lo llama.

    Retorna
    -------
    logging.Logger
    """
    _configure_root_logger()
    return logging.getLogger(name)
