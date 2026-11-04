from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..auth import User, get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class MeOut(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    preferred_language: str
    has_consented: bool


class MeUpdate(BaseModel):
    preferred_language: Literal["en", "am"] | None = None
    display_name: str | None = None
    give_consent: bool | None = None


def _out(u: User) -> MeOut:
    return MeOut(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        preferred_language=u.preferred_language,
        has_consented=u.consent_at is not None,
    )


@router.get("", response_model=MeOut)
async def read_me(user: User = Depends(get_current_user)) -> MeOut:
    return _out(user)


@router.patch("", response_model=MeOut)
async def update_me(body: MeUpdate, request: Request, user: User = Depends(get_current_user)) -> MeOut:
    # Ownership is enforced in our own SQL (WHERE id = current user), not only by RLS.
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            """
            update users set
              preferred_language = coalesce(%s, preferred_language),
              display_name       = coalesce(%s, display_name),
              consent_at         = case when %s then coalesce(consent_at, now()) else consent_at end
            where id = %s
            returning id, email, display_name, preferred_language, consent_at
            """,
            (body.preferred_language, body.display_name, bool(body.give_consent), user.id),
        )
        row = await cur.fetchone()
    return _out(User(**row))
