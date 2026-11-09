from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pyodbc

# Ensure the project root is available for package imports.
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings


DATA_DIR = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED_DIR = DATA_DIR / "scheduling"
META_DIR = DATA_DIR / "metadata"

REPORT_PATH = SCHED_DIR / "sql_import_readiness_inventory_v220.json"

def connect_read_only():
    connection_string = (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE=ExamSchedulingDB;"
        f"Trusted_Connection={settings.DB_TRUSTED_CONNECTION};"
        f"Encrypt={settings.DB_ENCRYPT};"
        f"TrustServerCertificate="
        f"{settings.DB_TRUST_SERVER_CERTIFICATE};"
        f"Connection Timeout={settings.DB_TIMEOUT};"
        "Application Name=ExamScheduling-v220-ReadOnly-Audit;"
    )

    return pyodbc.connect(connection_string, timeout=15)


def query_dicts(cursor, sql):
    cursor.execute(sql)
    names = [column[0] for column in cursor.description]
    return [
        dict(zip(names, row))
        for row in cursor.fetchall()
    ]


def inspect_database(cursor):
    # Only dbo metadata is inspected.
    # The evaluation schema and GroundTruth are excluded.

    tables = query_dicts(
        cursor,
        """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            t.create_date,
            t.modify_date
        FROM sys.tables t
        INNER JOIN sys.schemas s
            ON s.schema_id = t.schema_id
        WHERE s.name = 'dbo'
          AND t.is_ms_shipped = 0
        ORDER BY t.name;
        """
    )

    columns = query_dicts(
        cursor,
        """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            c.column_id,
            c.name AS column_name,
            ty.name AS data_type,
            c.max_length,
            c.precision,
            c.scale,
            c.is_nullable,
            c.is_identity,
            c.is_computed,
            dc.definition AS default_definition
        FROM sys.tables t
        INNER JOIN sys.schemas s
            ON s.schema_id = t.schema_id
        INNER JOIN sys.columns c
            ON c.object_id = t.object_id
        INNER JOIN sys.types ty
            ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.default_constraints dc
            ON dc.object_id = c.default_object_id
        WHERE s.name = 'dbo'
          AND t.is_ms_shipped = 0
        ORDER BY t.name, c.column_id;
        """
    )

    keys = query_dicts(
        cursor,
        """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            i.name AS index_name,
            i.is_primary_key,
            i.is_unique,
            c.name AS column_name,
            ic.key_ordinal
        FROM sys.tables t
        INNER JOIN sys.schemas s
            ON s.schema_id = t.schema_id
        INNER JOIN sys.indexes i
            ON i.object_id = t.object_id
        INNER JOIN sys.index_columns ic
            ON ic.object_id = i.object_id
           AND ic.index_id = i.index_id
        INNER JOIN sys.columns c
            ON c.object_id = ic.object_id
           AND c.column_id = ic.column_id
        WHERE s.name = 'dbo'
          AND t.is_ms_shipped = 0
          AND i.is_hypothetical = 0
          AND (i.is_primary_key = 1 OR i.is_unique = 1)
          AND ic.key_ordinal > 0
        ORDER BY t.name, i.name, ic.key_ordinal;
        """
    )

    foreign_keys = query_dicts(
        cursor,
        """
        SELECT
            fk.name AS constraint_name,
            OBJECT_SCHEMA_NAME(fk.parent_object_id)
                AS child_schema,
            OBJECT_NAME(fk.parent_object_id)
                AS child_table,
            pc.name AS child_column,
            OBJECT_SCHEMA_NAME(fk.referenced_object_id)
                AS parent_schema,
            OBJECT_NAME(fk.referenced_object_id)
                AS parent_table,
            rc.name AS parent_column,
            fkc.constraint_column_id,
            fk.is_disabled,
            fk.is_not_trusted
        FROM sys.foreign_keys fk
        INNER JOIN sys.foreign_key_columns fkc
            ON fkc.constraint_object_id = fk.object_id
        INNER JOIN sys.columns pc
            ON pc.object_id = fkc.parent_object_id
           AND pc.column_id = fkc.parent_column_id
        INNER JOIN sys.columns rc
            ON rc.object_id = fkc.referenced_object_id
           AND rc.column_id = fkc.referenced_column_id
        WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = 'dbo'
        ORDER BY child_table, constraint_name,
                 fkc.constraint_column_id;
        """
    )

    checks = query_dicts(
        cursor,
        """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            cc.name AS constraint_name,
            cc.definition,
            cc.is_disabled,
            cc.is_not_trusted
        FROM sys.check_constraints cc
        INNER JOIN sys.tables t
            ON t.object_id = cc.parent_object_id
        INNER JOIN sys.schemas s
            ON s.schema_id = t.schema_id
        WHERE s.name = 'dbo'
        ORDER BY t.name, cc.name;
        """
    )

    triggers = query_dicts(
        cursor,
        """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            tr.name AS trigger_name,
            tr.is_disabled
        FROM sys.triggers tr
        INNER JOIN sys.tables t
            ON t.object_id = tr.parent_id
        INNER JOIN sys.schemas s
            ON s.schema_id = t.schema_id
        WHERE s.name = 'dbo'
          AND tr.parent_class = 1
        ORDER BY t.name, tr.name;
        """
    )

    return {
        "tables": tables,
        "columns": columns,
        "keys": keys,
        "foreign_keys": foreign_keys,
        "check_constraints": checks,
        "triggers": triggers,
    }


def inspect_dataset_csvs():
    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"v2.2.0 dataset directory not found: {DATA_DIR}"
        )

    files = []

    for path in sorted(DATA_DIR.rglob("*.csv")):
        relative_parts = [
            part.lower() for part in path.relative_to(DATA_DIR).parts
        ]

        # Never open GroundTruth or evaluation files.
        if any(
            "groundtruth" in part or "evaluation" in part
            for part in relative_parts
        ):
            continue

        with path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.reader(handle)
            header = next(reader, [])

            if not header:
                row_count = 0
            else:
                row_count = sum(1 for _ in reader)

        files.append({
            "relative_path": str(path.relative_to(DATA_DIR)),
            "file_name": path.name,
            "row_count": row_count,
            "columns": header,
            "column_count": len(header),
        })

    return files


def build_summary(database, csv_files):
    dbo_tables = {
        item["table_name"] for item in database["tables"]
    }

    dataset_names = {
        Path(item["file_name"]).stem for item in csv_files
    }

    return {
        "database_dbo_table_count": len(dbo_tables),
        "database_dbo_column_count": len(database["columns"]),
        "primary_or_unique_index_column_rows": len(database["keys"]),
        "foreign_key_column_rows": len(database["foreign_keys"]),
        "check_constraint_count": len(database["check_constraints"]),
        "trigger_count": len(database["triggers"]),
        "dataset_csv_count": len(csv_files),
        "dataset_csv_row_total": sum(
            item["row_count"] for item in csv_files
        ),
        "same_name_csv_and_table": sorted(
            dataset_names.intersection(dbo_tables)
        ),
        "csv_without_same_name_dbo_table": sorted(
            dataset_names.difference(dbo_tables)
        ),
        "dbo_table_without_same_name_csv": sorted(
            dbo_tables.difference(dataset_names)
        ),
    }


def main():
    print("=" * 76)
    print("EXAM SCHEDULING SYSTEM v2.2.0")
    print("PYTHON SQL IMPORT READINESS INVENTORY")
    print("=" * 76)

    if not DATA_DIR.exists():
        raise FileNotFoundError(DATA_DIR)

    print("\n[1/4] Connecting to ExamSchedulingDB...")
    connection = connect_read_only()

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT DB_NAME() AS database_name, "
            "@@SERVERNAME AS server_name;"
        )
        identity = cursor.fetchone()

        if identity.database_name != "ExamSchedulingDB":
            raise RuntimeError(
                "Safety check failed: unexpected database."
            )

        print(f"Server   : {identity.server_name}")
        print(f"Database : {identity.database_name}")

        print("\n[2/4] Reading dbo schema metadata...")
        database = inspect_database(cursor)

        print("\n[3/4] Inspecting v2.2.0 CSV headers and row counts...")
        csv_files = inspect_dataset_csvs()

        summary = build_summary(database, csv_files)

        report = {
            "report_name": "SQL Import Readiness Inventory v2.2.0",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "database": identity.database_name,
            "server": identity.server_name,
            "operation_mode": "READ_ONLY_METADATA_AUDIT",
            "sql_data_rows_read": False,
            "sql_data_modified": False,
            "groundtruth_accessed": False,
            "evaluation_schema_queried": False,
            "source_csv_modified": False,
            "summary": summary,
            "database_metadata": database,
            "dataset_csv_inventory": csv_files,
        }

        print("\n[4/4] Writing local JSON report...")
        SCHED_DIR.mkdir(parents=True, exist_ok=True)

        temporary = REPORT_PATH.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(REPORT_PATH)

        print("\n" + "=" * 76)
        print("SQL IMPORT READINESS INVENTORY SUMMARY")
        print("=" * 76)

        for key, value in summary.items():
            print(f"{key:42}: {value}")

        print("\nReport:")
        print(REPORT_PATH)

        print("\nSQL operations : SELECT metadata only")
        print("SQL data       : NOT READ")
        print("SQL modified   : NO")
        print("GroundTruth    : NOT ACCESSED")
        print("Source CSVs    : NOT MODIFIED")
        print("=" * 76)

    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"\nSQL IMPORT READINESS INVENTORY FAILED: "
            f"{type(exc).__name__}: {exc}"
        )
        sys.exit(1)
