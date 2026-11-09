from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from database.connection import get_connection

DATA_DIR = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED_DIR = DATA_DIR / "scheduling"
REPORT = SCHED_DIR / "sql_integration_preflight_v220.json"

# Explicitly approved source files only. No backups, previews, or evaluation data.
SOURCE_FILES = [
    "Student.csv", "Course.csv", "Equipment.csv", "Room.csv", "Invigilator.csv",
    "Enrollment.csv", "Exam.csv", "RoomCapacity.csv", "RoomClosure.csv",
    "RoomEquipment.csv", "Availability.csv", "Accommodation.csv",
    "ExamRequirement.csv", "ExamRequiredEquipment.csv", "ExamEnrollment.csv",
]

TABLES = [
    "Student", "Course", "Equipment", "Room", "Invigilator", "Enrollment",
    "Exam", "RoomCapacity", "RoomClosure", "RoomEquipment", "Availability",
    "Accommodation", "ExamRequirement", "ExamRequiredEquipment", "ExamEnrollment",
    "SchedulingRun", "ScheduleAssignment", "AssignmentStudent",
    "AssignmentInvigilator", "SchedulingException", "AssignmentEvent",
]

def inspect_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        count = 0
        blank_rows = 0
        duplicate_pk = 0
        seen = set()
        id_column = next((h for h in headers if h.lower().endswith("id")), None)
        min_id = max_id = None
        for row in reader:
            if not any((v or "").strip() for v in row.values()):
                blank_rows += 1
                continue
            count += 1
            if id_column:
                raw = (row.get(id_column) or "").strip()
                if raw:
                    try:
                        value = int(raw)
                        min_id = value if min_id is None else min(min_id, value)
                        max_id = value if max_id is None else max(max_id, value)
                    except ValueError:
                        pass
                    if raw in seen:
                        duplicate_pk += 1
                    seen.add(raw)
        return {
            "path": str(path.relative_to(DATA_DIR)),
            "rows": count,
            "headers": headers,
            "candidate_id_column": id_column,
            "candidate_id_min": min_id,
            "candidate_id_max": max_id,
            "duplicate_candidate_ids": duplicate_pk,
            "blank_rows": blank_rows,
        }

def main() -> int:
    print("=" * 76)
    print("EXAM SCHEDULING SYSTEM v2.2.0 - SQL INTEGRATION PREFLIGHT")
    print("READ-ONLY DATABASE CHECK; NO INSERT/UPDATE/DELETE/TRUNCATE")
    print("=" * 76)

    missing = [name for name in SOURCE_FILES if not (DATA_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing approved source CSV(s): " + ", ".join(missing))

    csv_report = [inspect_csv(DATA_DIR / name) for name in SOURCE_FILES]

    print("\n[1/3] Connecting to SQL Server...")
    cn = get_connection()
    cur = cn.cursor()

    print("[2/3] Reading dbo table row counts only...")
    sql_counts = {}
    for table in TABLES:
        cur.execute(
            "SELECT COUNT_BIG(*) FROM dbo." + "[" + table + "]"
        )
        sql_counts[table] = int(cur.fetchone()[0])

    print("[3/3] Writing preflight report...")
    result = {
        "report_name": "SQL Integration Preflight v2.2.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database": settings.DB_NAME,
        "operation_mode": "READ_ONLY_ROW_COUNT_AND_CSV_PREFLIGHT",
        "sql_data_values_read": False,
        "sql_data_modified": False,
        "groundtruth_accessed": False,
        "evaluation_schema_queried": False,
        "source_csv_modified": False,
        "approved_source_files": csv_report,
        "sql_dbo_row_counts": sql_counts,
        "total_approved_source_rows": sum(x["rows"] for x in csv_report),
        "warnings": [
            "This is a preflight only; it does not import data.",
            "Identity and foreign-key mapping must be resolved before any write.",
            "Existing SQL records are preserved; no table is cleared or recreated.",
            "GroundTruth and evaluation schema are excluded.",
        ],
    }
    SCHED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\nSQL TABLE ROW COUNTS")
    for name, count in sql_counts.items():
        print(f"{name:28} {count:>10,}")
    print("\nAPPROVED SOURCE CSV ROW COUNTS")
    for item in csv_report:
        print(f"{item['path']:36} {item['rows']:>10,}")
    print(f"\nTotal approved source rows: {result['total_approved_source_rows']:,}")
    print(f"Report: {REPORT}")
    print("\nSQL modified: NO | GroundTruth accessed: NO | Source CSVs modified: NO")
    cn.close()
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nPREFLIGHT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
