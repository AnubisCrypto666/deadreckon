"""
Emits `operation` aspects for the nyc-taxi datapack tables, anchored relative
to the day this script runs.

Why this exists: the upstream fixture (datahub-project/static-assets,
datasets/nyc-taxi) plants a real freshness gap in the raw SQLite data
(raw_trips keeps going, staging_trips/mart_daily_summary stop 9 days
earlier - see NOTES.md for how this was verified and why the README's
"3 days" and the SQL profiler approach both turned out not to match
reality for this fixture). None of that gap is visible in DataHub
metadata as shipped: no `operation` aspects are emitted, and the SQL
profiler can't compute min/max on these columns because every column
in the source .db is typed TEXT (see NOTES.md).

This script reads the actual MAX(timestamp) per table directly from the
committed SQLite files (real data, not fabricated), then time-shifts
those timestamps so the freshest table (raw_trips) lands "now" - the day
the script runs - and every other table keeps its real distance behind
that. This is what D1 (frozen training source) reads from the graph.

Run after `datahub ingest` + `add_lineage.py` + `add_metadata.py` from
the upstream fixture have already loaded the tables into DataHub.
"""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import OperationClass, OperationTypeClass

DATAHUB_SERVER = "http://localhost:8080"
PLATFORM = "sqlite"

# table -> (column to read MAX() from, is it a full datetime or a bare date)
TABLES = {
    "raw_trips": "tpep_pickup_datetime",
    "staging_trips": "trip_date",
    "mart_daily_summary": "trip_date",
}


def read_real_max_timestamps(db_path: Path) -> dict[str, datetime]:
    conn = sqlite3.connect(str(db_path))
    try:
        result = {}
        for table, column in TABLES.items():
            (value,) = conn.execute(f'SELECT MAX("{column}") FROM {table}').fetchone()
            # values are either "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
            fmt = "%Y-%m-%d %H:%M:%S" if " " in value else "%Y-%m-%d"
            result[table] = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        return result
    finally:
        conn.close()


def time_shift(real_timestamps: dict[str, datetime], anchor: datetime) -> dict[str, datetime]:
    """Shift so the freshest table lands on `anchor`, preserving real gaps."""
    freshest = max(real_timestamps.values())
    shift = anchor - freshest
    return {table: ts + shift for table, ts in real_timestamps.items()}


def emit_operations(emitter: DatahubRestEmitter, platform_instance: str, shifted: dict[str, datetime]) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for table, last_updated in shifted.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{platform_instance}.main.{table},PROD)"
        emitter.emit(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=OperationClass(
                    timestampMillis=now_ms,
                    operationType=OperationTypeClass.INSERT,
                    lastUpdatedTimestamp=int(last_updated.timestamp() * 1000),
                ),
            )
        )
        age_days = (datetime.now(timezone.utc) - last_updated).days
        print(f"    {platform_instance}.{table}: lastUpdatedTimestamp={last_updated.isoformat()} ({age_days}d ago)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures-dir", type=Path, required=True, help="dir with nyc_taxi.db and nyc_taxi_pipeline.db")
    parser.add_argument("--anchor", type=str, default=None, help="ISO date to treat as 'now' (default: real now)")
    args = parser.parse_args()

    anchor = datetime.now(timezone.utc) if args.anchor is None else datetime.fromisoformat(args.anchor).replace(tzinfo=timezone.utc)
    emitter = DatahubRestEmitter(DATAHUB_SERVER)

    for db_name, instance in [("nyc_taxi.db", "nyc_taxi"), ("nyc_taxi_pipeline.db", "nyc_taxi_pipeline")]:
        db_path = args.fixtures_dir / db_name
        print(f"\n  Instance: {instance} ({db_path.name})")
        real = read_real_max_timestamps(db_path)
        shifted = time_shift(real, anchor)
        emit_operations(emitter, instance, shifted)

    print("\nDone. nyc_taxi is a healthy baseline (all tables shift to 'now').")
    print("nyc_taxi_pipeline has raw_trips fresh and staging/mart frozen behind it — this is what D1 reads.")


if __name__ == "__main__":
    main()
