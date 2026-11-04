import time

import jwt
import pytest
from fastapi import HTTPException

from app.auth import verify_token
from app.config import Settings

SECRET = "test-secret-at-least-32-characters-long!!"


def settings():
    return Settings(supabase_jwt_secret=SECRET, supabase_url="https://x.supabase.co")


def make(payload_extra=None, secret=SECRET, exp_offset=3600, aud="authenticated"):
    payload = {"sub": "user-123", "email": "a@b.com", "aud": aud, "exp": int(time.time()) + exp_offset}
    payload.update(payload_extra or {})
    return jwt.encode(payload, secret, algorithm="HS256")


def test_valid_token():
    claims = verify_token(make(), settings())
    assert claims.subject == "user-123" and claims.email == "a@b.com"


@pytest.mark.parametrize(
    "token",
    [
        make(secret="wrong-secret-wrong-secret-wrong-secret!"),
        make(exp_offset=-10),
        make(aud="someone-else"),
        "not.a.jwt",
    ],
)
def test_rejected_tokens(token):
    with pytest.raises(HTTPException) as e:
        verify_token(token, settings())
    assert e.value.status_code == 401


def test_alg_none_rejected():
    token = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 100}, None, algorithm="none")
    with pytest.raises(HTTPException):
        verify_token(token, settings())


def test_missing_sub_rejected():
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 100}, SECRET, algorithm="HS256")
    with pytest.raises(HTTPException):
        verify_token(token, settings())
