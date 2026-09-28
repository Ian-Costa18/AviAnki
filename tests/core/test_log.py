"""Tests for avianki.core.log."""

from __future__ import annotations

import logging

import pytest

from avianki.core.log import LOGGER_NAME, TqdmHandler, setup_logging, teardown_logging


@pytest.fixture(autouse=True)
def _restore_logger():
    logger = logging.getLogger(LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    teardown_logging()
    logger.handlers[:] = saved[0]
    logger.setLevel(saved[1])
    logger.propagate = saved[2]


def _console(logger: logging.Logger) -> TqdmHandler:
    (h,) = [h for h in logger.handlers if isinstance(h, TqdmHandler)]
    return h


def test_setup_configures_bird_deck_logger(tmp_path):
    log_file = tmp_path / "a.log"
    logger = setup_logging(log_file, verbose=False, quiet=False)
    assert logger.name == "bird_deck"
    assert logger.level == logging.DEBUG
    assert logger.propagate is False
    assert _console(logger).level == logging.INFO
    logger.debug("debug line")
    logger.info("info line")
    teardown_logging()
    text = log_file.read_text(encoding="utf-8")
    assert "debug line" in text and "info line" in text
    assert "INFO" in text


def test_verbose_and_quiet_set_console_level(tmp_path):
    assert _console(setup_logging(None, verbose=True, quiet=False)).level == logging.DEBUG
    assert _console(setup_logging(None, verbose=False, quiet=True)).level == logging.WARNING


def test_setup_is_idempotent(tmp_path):
    setup_logging(tmp_path / "a.log", verbose=False, quiet=False)
    logger = setup_logging(tmp_path / "b.log", verbose=False, quiet=False)
    assert len(logger.handlers) == 2  # one console, one file


def test_console_writes_through_tqdm(capsys):
    logger = setup_logging(None, verbose=False, quiet=False)
    logger.info("hello there")
    assert "hello there" in capsys.readouterr().out


def test_teardown_closes_file_handler(tmp_path):
    logger = setup_logging(tmp_path / "a.log", verbose=False, quiet=False)
    teardown_logging()
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
