from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def configure_logging(
    name: str = "asamint",
    level: int = logging.INFO,
    logfile: Path | None = None,
) -> logging.Logger:
    """Erzeuge einen konfigurierten Logger.

    Args:
        name: Logger-Name.
        level: Log-Level (logging.*).
        logfile: Optionaler Dateipfad für FileHandler.

    Returns:
        Konfigurierter Logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(logfile, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
