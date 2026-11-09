"""
Read-only SQL validation for Exam Scheduling System v2.2.0.

Checks:
- Import report status and expected row counts.
- Actual row counts in the 21 approved dbo tables.
- Enabled/trusted foreign keys and check constraints.
- Enabled expected scheduling triggers.
- SQL Server DBCC CHECKCONSTRAINTS output.

This script never accesses evaluation schema / GroundTruth and performs no writes.
Run from the project root:
    python .\data_validation\sql_post_import_validation_v220.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root is importable when this script is run directly
# from the data_validation directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import get_connection


EXPECTED_TABLES = {
    "Accommodation", "AssignmentEvent", "AssignmentInvigilator",
    "AssignmentStudent", "Availability", "Course", "Enrollment",
    "Equipment", "Exam", "ExamEnrollment", "ExamRequiredEquipment",
    "ExamRequirement", "Invigilator", "Room", "RoomCapacity",
    "RoomClosure", "RoomEquipment", "ScheduleAssignment",
    "SchedulingException", "SchedulingRun", "Student",
}

EXPECTED_TRIGGERS = {
    "TR_ScheduleAssignment_RoomOverlap",
    "TR_AssignmentInvigilator_NoOverlap",
    "TR_AssignmentStudent_NoOverlap",
}

REPORT_PATH = (
    Path("output_v2") / "full" / "v2.2.0" / "scheduling"
    / "sql_full_refresh_import_report_v220.json"
)


def qname(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def main() -> int:
    if not REPORT_PATH.is_file():
        print(f"ERROR: Import report not found: {REPORT_PATH}")
        return 2

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("status") != "COMMITTED" or report.get("dataset_version") != "2.2.0":
        print("ERROR: Import report is not a committed v2.2.0 report.")
        return 2

    expected = report.get("row_counts", {})
    if set(expected) != EXPECTED_TABLES:
        print("ERROR: Report table list does not exactly match the approved 21-table allowlist.")
        print("Missing:", sorted(EXPECTED_TABLES - set(expected)))
        print("Unexpected:", sorted(set(expected) - EXPECTED_TABLES))
        return 2

    failures: list[str] = []
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = True
        cur = conn.cursor()

        print("=" * 78)
        print("EXAM SCHEDULING SYSTEM v2.2.0 - READ-ONLY POST-IMPORT VALIDATION")
        print("Only approved dbo metadata and tables are queried.")
        print("evaluation.GroundTruth and evaluation schema are excluded.")
        print("=" * 78)

        # Confirm the current database without querying any evaluation objects.
        cur.execute("SELECT DB_NAME();")
        database_name = cur.fetchone()[0]
        print(f"\nDatabase: {database_name}")

        print("\n1. ROW-COUNT VERIFICATION")
        actual_counts = {}
        for table in sorted(EXPECTED_TABLES):
            cur.execute(f"SELECT COUNT_BIG(*) FROM dbo.{qname(table)};")
            actual = int(cur.fetchone()[0])
            wanted = int(expected[table])
            actual_counts[table] = actual
            ok = actual == wanted
            print(f"  [{'PASS' if ok else 'FAIL'}] {table:<27} {actual:>9,} / {wanted:>9,}")
            if not ok:
                failures.append(f"Row count mismatch: dbo.{table}: {actual} != {wanted}")

        actual_total = sum(actual_counts.values())
        report_total = int(report.get("total_rows", -1))
        print(f"  Total actual rows: {actual_total:,}; report total: {report_total:,}")
        if actual_total != report_total:
            failures.append(f"Total row mismatch: {actual_total} != {report_total}")

        print("\n2. FOREIGN-KEY STATUS")
        cur.execute("""
            SELECT name, is_disabled, is_not_trusted
            FROM sys.foreign_keys
            WHERE schema_id = SCHEMA_ID(N'dbo')
            ORDER BY name;
        """)
        fk_rows = cur.fetchall()
        if not fk_rows:
            failures.append("No dbo foreign keys found.")
        for row in fk_rows:
            name, disabled, not_trusted = row
            ok = not bool(disabled) and not bool(not_trusted)
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: disabled={disabled}, not_trusted={not_trusted}")
            if not ok:
                failures.append(f"Foreign key not enabled/trusted: {name}")

        print("\n3. CHECK-CONSTRAINT STATUS")
        cur.execute("""
            SELECT name, is_disabled, is_not_trusted
            FROM sys.check_constraints
            WHERE schema_id = SCHEMA_ID(N'dbo')
            ORDER BY name;
        """)
        check_rows = cur.fetchall()
        for row in check_rows:
            name, disabled, not_trusted = row
            ok = not bool(disabled) and not bool(not_trusted)
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: disabled={disabled}, not_trusted={not_trusted}")
            if not ok:
                failures.append(f"Check constraint not enabled/trusted: {name}")

        print("\n4. UNIQUE / PRIMARY-KEY INDEX STATUS")
        cur.execute("""
            SELECT t.name AS table_name, i.name AS index_name,
                   i.is_primary_key, i.is_unique, i.is_disabled
            FROM sys.indexes i
            JOIN sys.tables t ON t.object_id = i.object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = N'dbo'
              AND (i.is_primary_key = 1 OR i.is_unique = 1)
              AND i.name IS NOT NULL
            ORDER BY t.name, i.name;
        """)
        index_rows = cur.fetchall()
        for row in index_rows:
            table_name, index_name, is_pk, is_unique, disabled = row
            ok = not bool(disabled)
            print(f"  [{'PASS' if ok else 'FAIL'}] {table_name}.{index_name} "
                  f"(PK={is_pk}, unique={is_unique}, disabled={disabled})")
            if not ok:
                failures.append(f"Unique/PK index disabled: {table_name}.{index_name}")

        print("\n5. EXPECTED SCHEDULING TRIGGERS")
        cur.execute("""
            SELECT name, is_disabled
            FROM sys.triggers
            WHERE parent_class = 1
              AND parent_id IN (
                  SELECT t.object_id
                  FROM sys.tables t
                  JOIN sys.schemas s ON s.schema_id = t.schema_id
                  WHERE s.name = N'dbo'
              )
              AND name IN (?, ?, ?)
            ORDER BY name;
        """, tuple(sorted(EXPECTED_TRIGGERS)))
        trigger_rows = cur.fetchall()
        found = {row[0]: bool(row[1]) for row in trigger_rows}
        for trigger in sorted(EXPECTED_TRIGGERS):
            if trigger not in found:
                print(f"  [FAIL] {trigger}: NOT FOUND")
                failures.append(f"Expected trigger missing: {trigger}")
            elif found[trigger]:
                print(f"  [FAIL] {trigger}: DISABLED")
                failures.append(f"Expected trigger disabled: {trigger}")
            else:
                print(f"  [PASS] {trigger}: ENABLED")

        print("\n6. DBCC CHECKCONSTRAINTS")
        try:
            cur.execute("DBCC CHECKCONSTRAINTS WITH ALL_CONSTRAINTS, NO_INFOMSGS;")
            violations = []
            while True:
                if cur.description:
                    columns = [column[0] for column in cur.description]
                    for result_row in cur.fetchall():
                        violations.append(dict(zip(columns, result_row)))
                if not cur.nextset():
                    break
            if violations:
                print(f"  [FAIL] {len(violations)} constraint violation row(s) returned.")
                for violation in violations[:20]:
                    print("   ", violation)
                failures.append(f"DBCC CHECKCONSTRAINTS returned {len(violations)} violation(s)")
            else:
                print("  [PASS] No constraint violations returned.")
        except Exception as exc:
            print(f"  [UNVERIFIED] DBCC CHECKCONSTRAINTS could not complete: {exc}")
            failures.append(f"DBCC CHECKCONSTRAINTS could not be completed: {exc}")

        print("\n" + "=" * 78)
        if failures:
            print(f"VALIDATION RESULT: NEEDS ATTENTION ({len(failures)} issue(s))")
            for item in failures:
                print(" -", item)
            print("No data was modified by this validation script.")
            return 1

        print("VALIDATION RESULT: PASSED")
        print(f"Verified {len(EXPECTED_TABLES)} table counts; "
              f"{len(fk_rows)} foreign keys; {len(check_rows)} check constraints; "
              f"{len(index_rows)} unique/PK indexes; 3 expected triggers.")
        print("DBCC CHECKCONSTRAINTS returned no violations.")
        print("No data was modified.")
        return 0

    except Exception as exc:
        print(f"\nVALIDATION ERROR: {type(exc).__name__}: {exc}")
        print("No data was intentionally modified.")
        return 2
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
