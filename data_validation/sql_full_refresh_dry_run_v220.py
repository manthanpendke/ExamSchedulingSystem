from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.connection import get_connection

DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"
REPORT = SCHED / "sql_full_refresh_dry_run_v220.json"

# Explicit allowlist only. No backups, previews, GroundTruth, or evaluation files.
SOURCE_FILES = {
    "Student": DATA / "Student.csv",
    "Course": DATA / "Course.csv",
    "Equipment": DATA / "Equipment.csv",
    "Room": DATA / "Room.csv",
    "Invigilator": DATA / "Invigilator.csv",
    "Enrollment": DATA / "Enrollment.csv",
    "Exam": DATA / "Exam.csv",
    "RoomCapacity": DATA / "RoomCapacity.csv",
    "RoomClosure": DATA / "RoomClosure.csv",
    "RoomEquipment": DATA / "RoomEquipment.csv",
    "Availability": DATA / "Availability.csv",
    "Accommodation": DATA / "Accommodation.csv",
    "ExamRequirement": DATA / "ExamRequirement.csv",
    "ExamRequiredEquipment": DATA / "ExamRequiredEquipment.csv",
    "ExamEnrollment": DATA / "ExamEnrollment.csv",
}

SCHEDULING_SOURCES = {
    "ScheduleAssignment": SCHED / "RoomAllocation.csv",
    "AssignmentStudent": SCHED / "RoomStudentAllocation.csv",
    "AssignmentInvigilator": SCHED / "InvigilatorAssignment.csv",
    "SchedulingException": SCHED / "RoomAllocationExceptions.csv",
}

EXPECTED_DBO_TABLES = {
    "Student", "Course", "Enrollment", "Exam", "ExamRequirement",
    "ExamEnrollment", "Accommodation", "Room", "RoomCapacity",
    "RoomClosure", "Equipment", "RoomEquipment", "ExamRequiredEquipment",
    "Invigilator", "Availability", "SchedulingRun", "ScheduleAssignment",
    "AssignmentStudent", "AssignmentInvigilator", "AssignmentEvent",
    "SchedulingException",
}

NATURAL_KEYS = {
    "Student": ["StudentCode"],
    "Course": ["CourseCode"],
    "Equipment": ["EquipmentName"],
    "Room": ["RoomCode"],
    "Invigilator": ["InvigilatorCode"],
    "Exam": ["ExamCode"],
    "SchedulingRun": ["RunCode"],
}

def read_csv_info(path: Path):
    if not path.is_file():
        return {"exists": False, "rows": None, "columns": [], "duplicate_key_count": None}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)
    return {"exists": True, "rows": len(rows), "columns": columns, "duplicate_key_count": None}

def duplicate_key_count(path: Path, keys: list[str]) -> int:
    seen = set()
    duplicates = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [k for k in keys if k not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing natural-key columns {missing}")
        for row in reader:
            key = tuple((row.get(k) or "").strip().casefold() for k in keys)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
    return duplicates

def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"

def main() -> int:
    print("=" * 78)
    print("EXAM SCHEDULING SYSTEM v2.2.0 - FULL REFRESH DRY-RUN")
    print("READ-ONLY: NO DELETE / INSERT / UPDATE / TRUNCATE / DDL")
    print("GroundTruth and evaluation schema are explicitly excluded")
    print("=" * 78)

    issues = []
    source_info = {}
    planned_insert_counts = {}

    print("\n[1/5] Checking the explicit v2.2.0 source allowlist...")
    for table, path in SOURCE_FILES.items():
        info = read_csv_info(path)
        source_info[f"dbo.{table}"] = {"path": str(path), **info}
        if not info["exists"]:
            issues.append(f"Missing source file: {path}")
            continue
        if table in NATURAL_KEYS:
            dupes = duplicate_key_count(path, NATURAL_KEYS[table])
            source_info[f"dbo.{table}"]["duplicate_natural_keys"] = dupes
            if dupes:
                issues.append(f"{table}: {dupes} duplicate natural keys")
        planned_insert_counts[table] = info["rows"]
        print(f"  {table:<28} {info['rows']:>8,} rows")

    print("\n[2/5] Checking scheduling output files...")
    for table, path in SCHEDULING_SOURCES.items():
        info = read_csv_info(path)
        source_info[f"dbo.{table}"] = {"path": str(path), **info}
        if not info["exists"]:
            issues.append(f"Missing scheduling source file: {path}")
            continue
        planned_insert_counts[table] = info["rows"]
        print(f"  {table:<28} {info['rows']:>8,} rows")

    # A completed run is represented by one metadata row; no fabricated event rows.
    planned_insert_counts["SchedulingRun"] = 1
    planned_insert_counts["AssignmentEvent"] = 0

    cn = None
    try:
        print("\n[3/5] Connecting and reading dbo counts/schema metadata only...")
        cn = get_connection()
        cur = cn.cursor()

        cur.execute("""
            SELECT t.name, SUM(p.rows)
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id=t.schema_id
            LEFT JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1)
            WHERE s.name='dbo'
            GROUP BY t.name
            ORDER BY t.name
        """)
        db_counts = {name: int(rows or 0) for name, rows in cur.fetchall()}
        db_tables = set(db_counts)
        missing_tables = sorted(EXPECTED_DBO_TABLES - db_tables)
        unexpected_tables = sorted(db_tables - EXPECTED_DBO_TABLES)
        if missing_tables:
            issues.append(f"Expected dbo tables missing: {missing_tables}")
        if unexpected_tables:
            issues.append(f"Unexpected dbo tables require review: {unexpected_tables}")

        cur.execute("""
            SELECT fk.name, pt.name, pc.name, ct.name, cc.name,
                   fkc.constraint_column_id
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
            JOIN sys.tables pt ON pt.object_id=fk.referenced_object_id
            JOIN sys.schemas ps ON ps.schema_id=pt.schema_id
            JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.referenced_column_id
            JOIN sys.tables ct ON ct.object_id=fk.parent_object_id
            JOIN sys.schemas cs ON cs.schema_id=ct.schema_id
            JOIN sys.columns cc ON cc.object_id=ct.object_id AND cc.column_id=fkc.parent_column_id
            WHERE ps.name='dbo' AND cs.name='dbo'
            ORDER BY ct.name, fk.name, fkc.constraint_column_id
        """)
        fk_rows = cur.fetchall()
        edges = set()
        fk_details = []
        for fk_name, parent_table, parent_col, child_table, child_col, ordinal in fk_rows:
            edges.add((parent_table, child_table))
            fk_details.append({
                "constraint": fk_name,
                "parent_table": parent_table,
                "parent_column": parent_col,
                "child_table": child_table,
                "child_column": child_col,
                "column_ordinal": int(ordinal),
            })

        cur.execute("""
            SELECT t.name, tr.name, tr.is_disabled
            FROM sys.triggers tr
            JOIN sys.tables t ON t.object_id=tr.parent_id
            JOIN sys.schemas s ON s.schema_id=t.schema_id
            WHERE s.name='dbo' AND tr.is_ms_shipped=0
            ORDER BY t.name, tr.name
        """)
        triggers = [
            {"table": t, "name": n, "disabled": bool(d)}
            for t, n, d in cur.fetchall()
        ]

        print("\n  Existing dbo row counts:")
        for table in sorted(db_counts):
            print(f"    {table:<27} {db_counts[table]:>8,}")

        # Parent-before-child order for inserts; reverse for deletes.
        nodes = set(db_tables)
        indegree = {n: 0 for n in nodes}
        children = defaultdict(set)
        for parent, child in edges:
            if parent in nodes and child in nodes and parent != child:
                if child not in children[parent]:
                    children[parent].add(child)
                    indegree[child] += 1
        queue = deque(sorted(n for n, d in indegree.items() if d == 0))
        insert_order = []
        while queue:
            n = queue.popleft()
            insert_order.append(n)
            for child in sorted(children[n]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        cyclic = sorted(nodes - set(insert_order))
        if cyclic:
            issues.append(f"FK dependency cycle detected; manual handling required: {cyclic}")
        delete_order = list(reversed(insert_order))

        # Sanity-check FK direction using known schema relationships.
        # Student must precede Enrollment on insert and follow it on delete.
        if ("Student", "Enrollment") not in edges:
            issues.append("FK direction check failed: expected Student -> Enrollment")
        elif insert_order.index("Student") > insert_order.index("Enrollment"):
            issues.append("Unsafe insert order: Student must precede Enrollment")
        elif delete_order.index("Student") < delete_order.index("Enrollment"):
            issues.append("Unsafe delete order: Enrollment must precede Student")

        print("\n[4/5] Building the proposed full-refresh scope (no writes)...")
        proposed_delete_counts = {t: db_counts.get(t, 0) for t in sorted(db_tables)}
        proposed_insert_counts = {
            t: planned_insert_counts.get(t, 0) for t in sorted(EXPECTED_DBO_TABLES)
        }

        print("  DELETE scope: every existing dbo table row, child tables first")
        for table in delete_order:
            print(f"    {table:<27} {proposed_delete_counts.get(table, 0):>8,}")
        print("  INSERT scope: v2.2.0 sources / scheduling outputs")
        for table in insert_order:
            if table in proposed_insert_counts:
                print(f"    {table:<27} {proposed_insert_counts[table]:>8,}")

        # Schema/trigger readiness checks.
        disabled_triggers = [x for x in triggers if x["disabled"]]
        if disabled_triggers:
            issues.append(f"Disabled dbo triggers found: {disabled_triggers}")
        absent_mappings = sorted(EXPECTED_DBO_TABLES - set(planned_insert_counts))
        if absent_mappings:
            issues.append(f"No approved v2.2.0 source/mapping for dbo tables: {absent_mappings}")

        report = {
            "report_name": "v2.2.0 SQL Full Refresh Dry-Run",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "database": "ExamSchedulingDB",
            "server": "Manthan\\SQLEXPRESS",
            "operation_mode": "READ_ONLY_DRY_RUN",
            "sql_data_rows_read": False,
            "sql_data_modified": False,
            "ddl_modified": False,
            "groundtruth_accessed": False,
            "evaluation_schema_queried": False,
            "source_csv_modified": False,
            "strategy": "REPLACE_ALL_DBO_DATA_WITH_V2.2.0",
            "existing_dbo_row_counts": db_counts,
            "proposed_delete_counts": proposed_delete_counts,
            "proposed_insert_counts": proposed_insert_counts,
            "source_files": source_info,
            "foreign_keys": fk_details,
            "insert_order_parent_first": insert_order,
            "delete_order_child_first": delete_order,
            "triggers": triggers,
            "issues": issues,
            "ready_for_import_script_generation": not issues,
            "important_mapping_notes": [
                "CSV identity IDs must be remapped; do not assume they equal SQL identity IDs.",
                "Equipment.EquipmentCode is computed and must not be inserted.",
                "AssignmentEvent receives zero rows; no event history is fabricated.",
                "RoomAllocationExceptions is the approved source for room allocation exceptions.",
                "AssignmentStudent seat numbers must be generated deterministically during import.",
                "RoomEquipmentReservation and timetable-only metadata are not dbo destinations.",
                "GroundTruth and evaluation schema are never accessed.",
            ],
        }
        SCHED.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

        print("\n[5/5] Dry-run report written.")
        print(f"  Report: {REPORT}")
        print(f"  Existing dbo rows to replace: {sum(db_counts.values()):,}")
        print(f"  Planned v2.2.0 dbo rows: {sum(proposed_insert_counts.values()):,}")
        print(f"  FK constraints inspected: {len(fk_details)} column mappings")
        print(f"  dbo triggers inspected: {len(triggers)}")
        print(f"  Issues: {len(issues)}")
        for issue in issues:
            print(f"  ISSUE: {issue}")
        print("\nSQL modified: NO | DDL modified: NO | GroundTruth accessed: NO")
        print("Source CSVs modified: NO")
        return 0 if not issues else 2
    finally:
        if cn is not None:
            cn.close()

if __name__ == "__main__":
    raise SystemExit(main())
