from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def make_pool(database_url: str) -> AsyncConnectionPool:
    # prepare_threshold=None keeps this compatible with Supabase's pooled connections.
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
    )
