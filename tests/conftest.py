"""Fixtures compartilhadas pelos testes da MarketPulse API."""

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture(autouse=True)
def base_limpa():
    """Cada teste começa com o catálogo inicial e sem pedidos (testes independentes)."""
    database.inicializar_base()
    yield
    database.inicializar_base()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
