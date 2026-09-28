"""Setup for the single ``bird_deck`` logger every module logs through.

Modules only ever call ``logging.getLogger("bird_deck")``; entry points call
`setup_logging` once and `teardown_logging` when done.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import tqdm

LOGGER_NAME = "bird_deck"
FORMATTER = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


class TqdmHandler(logging.StreamHandler):
    """Routes log output through tqdm.write() so progress bars aren't clobbered."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


def setup_logging(log_file: Path | None, verbose: bool, quiet: bool) -> logging.Logger:
    """Configure ``bird_deck``: console via tqdm (INFO; DEBUG if verbose, WARNING if quiet)
    plus, when ``log_file`` is given, a DEBUG file log (overwritten each run).

    Replaces any handlers from an earlier call, so it's safe to call more than once.
    """
    logger = logging.getLogger(LOGGER_NAME)
    teardown_logging()
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = TqdmHandler(sys.stdout)
    console.setFormatter(FORMATTER)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO)
    logger.addHandler(console)

    if log_file is not None:
        fh = logging.FileHandler(log_file, encoding="utf-8", mode="w")
        fh.setFormatter(FORMATTER)
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    return logger


def teardown_logging() -> None:
    """Close and remove the file handler(s) `setup_logging` added."""
    logger = logging.getLogger(LOGGER_NAME)
    for h in [h for h in logger.handlers if isinstance(h, logging.FileHandler)]:
        h.close()
        logger.removeHandler(h)
