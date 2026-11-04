from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(request: Request) -> dict:
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute("select count(*) as n from job_sources")
        row = await cur.fetchone()
    return {"db": "ok", "job_sources": row["n"]}