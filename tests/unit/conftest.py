"""Unit tests touch no database: override the autouse DB fixtures."""
import pytest


@pytest.fixture(scope="session")
def db():
    return None


@pytest.fixture(autouse=True)
def clean_db():
    yield
