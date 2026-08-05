from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine, text


def apply_migrations(database_url: str, migrations_dir: Path) -> None:
    engine = create_engine(database_url, future=True)
    files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(100) PRIMARY KEY,"
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )

        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_migrations"))
        }

        for sql_file in files:
            version = sql_file.name
            if version in applied:
                continue

            sql_text = sql_file.read_text(encoding="utf-8")
            conn.execute(text(sql_text))
            conn.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": version},
            )
            print(f"applied_migration={version}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply SQL migrations to target database")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///artifacts/fleet_mvp.db"))
    parser.add_argument("--migrations-dir", default="migrations")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    apply_migrations(database_url=args.database_url, migrations_dir=Path(args.migrations_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
