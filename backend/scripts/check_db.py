"""Smoke-check that Postgres is reachable with the app's Settings (root/.env)."""

import asyncio
import sys

import asyncpg

from app.config import settings


async def check_db() -> str:
    conn = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )
    try:
        return await conn.fetchval("SELECT version()")
    finally:
        await conn.close()


def main() -> None:
    target = f"{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    try:
        version = asyncio.run(check_db())
    except OSError as exc:
        print(f"FAIL  cannot reach {target}: {exc}", file=sys.stderr)
        sys.exit(1)
    except asyncpg.PostgresError as exc:
        print(f"FAIL  {target}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"OK    {target}")
    print(version)


if __name__ == "__main__":
    main()
