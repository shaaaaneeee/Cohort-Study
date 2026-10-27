"""Create the cohort tables and fill them with synthetic data or your own CSV exports.

    SEED_DATABASE_URL=postgresql://owner:...@host:5432/cohort python -m app.seed
    python -m app.seed --patients 20000 --seed 7       # synthetic data (the default)
    python -m app.seed --csv path/to/exports/         # master_patient.csv, ed_episodes.csv, ...
    python -m app.seed --if-empty                     # do nothing if data is already loaded

SEED_DATABASE_URL must be a role that can create tables (the database
owner), never the app's read-only role. It is read from the environment only,
so the password never appears in the process list or shell history.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from app.seed import synthetic
from app.seed.load import apply_schema, connect, is_empty, load_tables, read_csv_folder

log = logging.getLogger("app.seed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", default=os.environ.get("SEED_SCHEMA", "cohort"))
    parser.add_argument("--csv", type=Path, help="load <table>.csv files from this folder instead")
    parser.add_argument("--patients", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--if-empty", action="store_true", help="skip loading when master_patient already has rows"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    url = os.environ.get("SEED_DATABASE_URL")
    if not url:
        log.error("Set SEED_DATABASE_URL to a database owner connection URL.")
        return 2

    with connect(url) as conn:
        apply_schema(conn, args.schema)
        if args.if_empty and not is_empty(conn, args.schema):
            log.info("schema %s already has data; nothing loaded", args.schema)
            return 0
        if args.csv:
            tables = read_csv_folder(args.csv)
        else:
            tables = synthetic.generate(patients=args.patients, seed=args.seed)
        for table, rows in load_tables(conn, tables, args.schema).items():
            log.info("%s.%s: %d rows loaded", args.schema, table, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
