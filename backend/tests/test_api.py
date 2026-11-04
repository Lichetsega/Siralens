from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import health


def test_health():
    app = FastAPI()
    app.include_router(health.router)
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_me_requires_token():
    # Importing main builds the real app; no DB is touched because auth fails first.
    from app.main import app

    app.router.lifespan_context = None  # skip pool startup in this unit test
    r = TestClient(app).get("/me")
    assert r.status_code == 401
