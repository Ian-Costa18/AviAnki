import pytest


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False, help="Run integration tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="pass --integration to run")
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def _restore_bird_deck_logger():
    """``cli.main`` calls ``setup_logging``, which replaces the logger's handlers and turns off
    propagation. Put the logger back after every test so caplog keeps working in the next one."""
    import logging

    logger = logging.getLogger("bird_deck")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    logger.handlers[:] = saved[0]
    logger.setLevel(saved[1])
    logger.propagate = saved[2]
