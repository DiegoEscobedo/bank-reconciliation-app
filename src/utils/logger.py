"""
logger.py — Configuración centralizada de logging para el proyecto.

Uso:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Mensaje informativo")
"""

import logging
import sys
from pathlib import Path

# Directorio de logs en la raíz del proyecto
_LOGS_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_LOG_FILE = _LOGS_DIR / "reconciliation.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Flag para evitar configurar el root logger más de una vez
_configured = False


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(fmt=_FORMAT, datefmt=_DATE_FORMAT)

    # Handler consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Handler archivo (rotación manual: se acumula por sesión)
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

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
