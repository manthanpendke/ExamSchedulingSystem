from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.connection import get_connection

BASE = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = BASE / "scheduling"
CONFIG = ROOT / "config" / "dataset_config_v220.json"
REPORT = SCHED / "sql_full_refresh_import_report_v220.json"

SOURCE_FILES = {
    "Student": BASE / "Student.csv",
    "Course": BASE / "Course.csv",
    "Equipment": BASE / "Equipment.csv",
    "Room": BASE / "Room.csv",
    "Invigilator": BASE / "Invigilator.csv",
    "Enrollment": BASE / "Enrollment.csv",
    "Exam": BASE / "Exam.csv",
    "RoomCapacity": BASE / "RoomCapacity.csv",
    "RoomClosure": BASE / "RoomClosure.csv",
    "RoomEquipment": BASE / "RoomEquipment.csv",
    "Availability": BASE / "Availability.csv",
    "Accommodation": BASE / "Accommodation.csv",
    "ExamRequirement": BASE / "ExamRequirement.csv",
    "ExamRequiredEquipment": BASE / "ExamRequiredEquipment.csv",
    "ExamEnrollment": BASE / "ExamEnrollment.csv",
}
SCHEDULE_FILES = {
    "ScheduleAssignment": SCHED / "RoomAllocation.csv",
    "AssignmentStudent": SCHED / "RoomStudentAllocation.csv",
    "AssignmentInvigilator": SCHED / "InvigilatorAssignment.csv",
    "SchedulingException": SCHED / "RoomAllocationExceptions.csv",
}
EXPECTED_TABLES = {
    "Student", "Course", "Enrollment", "Exam", "ExamRequirement",
    "ExamEnrollment", "Accommodation", "Room", "RoomCapacity",
    "RoomClosure", "Equipment", "RoomEquipment", "ExamRequiredEquipment",
    "Invigilator", "Availability", "SchedulingRun", "ScheduleAssignment",
    "AssignmentStudent", "AssignmentInvigilator", "AssignmentEvent",
    "SchedulingException",
}
BATCH_SIZE = 250

def read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Required source file missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return None if v == "" else v
    return v

def parse_datetime(v):
    v = clean(v)
    if v is None:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))

def parse_date(v):
    v = clean(v)
    if v is None:
        return None
    return date.fromisoformat(v[:10])

def to_bool(v):
    v = clean(v)
    if v is None:
        return None
    if str(v).lower() in ("true", "1", "yes"):
        return True
    if str(v).lower() in ("false", "0", "no"):
        return False
    raise ValueError(f"Invalid boolean value: {v!r}")

def convert_value(value, sql_type):
    value = clean(value)
    if value is None:
        return None
    t = sql_type.lower()
    if t in ("int", "bigint", "smallint", "tinyint"):
        return int(value)
    if t in ("bit",):
        return to_bool(value)
    if t in ("decimal", "numeric", "money", "smallmoney", "float", "real"):
        return Decimal(str(value)) if t in ("decimal", "numeric", "money", "smallmoney") else float(value)
    if t == "date":
        return parse_date(value)
    if t in ("datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        return parse_datetime(value)
    return value

def q(name):
    return "[" + name.replace("]", "]]") + "]"

def load_all_sources():
    sources = {t: read_rows(p) for t, p in SOURCE_FILES.items()}
    for t, p in SCHEDULE_FILES.items():
        sources[t] = read_rows(p)
    return sources

def check_unique(rows, table, keys):
    seen = set()
    for i, row in enumerate(rows, 1):
        k = tuple(str(row.get(col, "")).strip().casefold() for col in keys)
        if any(x == "" for x in k):
            raise ValueError(f"{table} row {i}: blank natural key {keys}")
        if k in seen:
            raise ValueError(f"{table}: duplicate natural key {keys}={k}")
        seen.add(k)

def find_seed(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).casefold() in {"seed", "random_seed", "randomseed"} and value is not None:
                return int(value)
        for value in obj.values():
            found = find_seed(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_seed(value)
            if found is not None:
                return found
    return None

def build_run_row(sources, config_obj, run_id, run_code, run_started, run_completed):
    seed = find_seed(config_obj)
    if seed is None:
        raise ValueError(
            "The v2.2.0 config does not contain a declared random seed, but dbo.SchedulingRun.RandomSeed "
            "is NOT NULL. Refusing to invent a seed. Recover the actual generation seed from the dataset "
            "manifest/run metadata before importing."
        )
    cfg = {
        "dataset_version": "2.2.0",
        "source_config": config_obj,
        "source_dataset": "output_v2/full/v2.2.0",
        "room_allocation_rows": len(sources["ScheduleAssignment"]),
        "student_allocation_rows": len(sources["AssignmentStudent"]),
        "invigilator_assignment_rows": len(sources["AssignmentInvigilator"]),
        "exception_rows": len(sources["SchedulingException"]),
        "groundtruth_loaded": False,
    }
    return {
        "SchedulingRunID": run_id,
        "RunCode": run_code,
        "AlgorithmVersion": "2.2.0",
        "RandomSeed": seed,
        "RunStatus": "COMPLETED",
        "Configuration": json.dumps(cfg, separators=(",", ":"), default=str),
        "StartedAt": run_started,
        "CompletedAt": run_completed,
    }

def prepare_payload(sources, config_obj, schema_cols):
    # Use source identity values explicitly after clearing the old dbo dataset.
    payload = {}
    direct_tables = [
        "Student", "Course", "Equipment", "Room", "Invigilator",
        "Enrollment", "Exam", "RoomCapacity", "RoomClosure", "RoomEquipment",
        "Availability", "Accommodation", "ExamRequirement",
        "ExamRequiredEquipment", "ExamEnrollment",
    ]
    for table in direct_tables:
        cols = schema_cols[table]
        allowed = {c["name"]: c for c in cols}
        rows = []
        for src in sources[table]:
            row = {}
            for name, value in src.items():
                meta = allowed.get(name)
                if meta and not meta["computed"] and not meta["identity"]:
                    row[name] = convert_value(value, meta["type"])
            # Preserve CSV IDs as SQL identity values, maintaining source FK references.
            id_col = next((c for c in cols if c["identity"]), None)
            if id_col:
                source_id = id_col["name"]
                if source_id not in src:
                    raise ValueError(f"{table}: source is missing identity column {source_id}")
                row[source_id] = convert_value(src[source_id], id_col["type"])
            rows.append(row)
        payload[table] = rows

    # Source identity keys must be unique and positive.
    for table in direct_tables:
        id_col = next(c["name"] for c in schema_cols[table] if c["identity"])
        ids = [r[id_col] for r in payload[table]]
        if len(ids) != len(set(ids)) or any(x is None or x <= 0 for x in ids):
            raise ValueError(f"{table}: duplicate, null, or non-positive source identity values")

    # Build validated lookup keys from the v2.2.0 source files.
    exam_enroll_lookup = {}
    for r in payload["ExamEnrollment"]:
        key = (int(r["ExamID"]), int(r["EnrollmentID"]))
        if key in exam_enroll_lookup:
            raise ValueError(f"Duplicate ExamEnrollment business key: {key}")
        exam_enroll_lookup[key] = int(r["ExamEnrollmentID"])

    room_alloc_lookup = {}
    room_alloc_rows = []
    for src in sources["ScheduleAssignment"]:
        rid = int(src["RoomAllocationID"])
        key = (int(src["ExamID"]), int(src["RoomID"]), parse_datetime(src["StartDateTime"]))
        if key in room_alloc_lookup:
            raise ValueError(f"Duplicate room allocation lookup key: {key}")
        room_alloc_lookup[key] = rid
        room_alloc_rows.append({
            "AssignmentID": rid,
            "AssignmentCode": f"ASG-V220-{rid:06d}",
            "ExamID": int(src["ExamID"]),
            "RoomID": int(src["RoomID"]),
            "SchedulingRunID": 1,
            "StartTime": parse_datetime(src["StartDateTime"]),
            "EndTime": parse_datetime(src["EndDateTime"]),
            "AssignedCapacity": int(src["AssignedCapacity"]),
            "AssignmentStatus": "CONFIRMED",
        })
    payload["ScheduleAssignment"] = room_alloc_rows

    # Derive deterministic seat labels within each room allocation.
    students_by_assignment = defaultdict(list)
    for src in sources["AssignmentStudent"]:
        key = (int(src["ExamID"]), int(src["RoomID"]), parse_datetime(src["StartDateTime"]))
        assignment_id = room_alloc_lookup.get(key)
        if assignment_id is None:
            raise ValueError(f"RoomStudentAllocation has no matching RoomAllocation: {key}")
        ee_key = (int(src["ExamID"]), int(src["EnrollmentID"]))
        exam_enrollment_id = exam_enroll_lookup.get(ee_key)
        if exam_enrollment_id is None:
            raise ValueError(f"No ExamEnrollment for (ExamID, EnrollmentID)={ee_key}")
        students_by_assignment[assignment_id].append({
            "ExamID": int(src["ExamID"]),
            "ExamEnrollmentID": exam_enrollment_id,
            "StudentID": int(src["StudentID"]),
            "EnrollmentID": int(src["EnrollmentID"]),
        })

    assignment_student_rows = []
    for assignment_id, group in students_by_assignment.items():
        group.sort(key=lambda r: (r["StudentID"], r["EnrollmentID"]))
        for n, r in enumerate(group, 1):
            assignment_student_rows.append({
                "AssignmentID": assignment_id,
                "ExamID": r["ExamID"],
                "ExamEnrollmentID": r["ExamEnrollmentID"],
                "SchedulingRunID": 1,
                "SeatNumber": f"S{n:03d}",
                "AllocationStatus": "ALLOCATED",
            })
    payload["AssignmentStudent"] = assignment_student_rows

    inv_rows = []
    seen_inv_pairs = set()
    for src in sources["AssignmentInvigilator"]:
        assignment_id = int(src["RoomAllocationID"])
        if assignment_id not in {r["AssignmentID"] for r in room_alloc_rows}:
            raise ValueError(f"Invigilator assignment references unknown RoomAllocationID={assignment_id}")
        pair = (assignment_id, int(src["InvigilatorID"]))
        if pair in seen_inv_pairs:
            raise ValueError(f"Duplicate invigilator assignment: {pair}")
        seen_inv_pairs.add(pair)
        inv_rows.append({
            "AssignmentID": assignment_id,
            "ExamID": int(src["ExamID"]),
            "InvigilatorID": int(src["InvigilatorID"]),
            "SchedulingRunID": 1,
            "AssignedRole": "PRIMARY",
            "CreatedAt": parse_datetime(src.get("CreatedAt")),
            "AssignmentStatus": "ASSIGNED",
        })
    payload["AssignmentInvigilator"] = inv_rows

    exception_rows = []
    for src in sources["SchedulingException"]:
        reason = src["ReasonCode"]
        if reason not in {
            "OTHER", "INVALID_REQUIREMENT", "NO_ELIGIBLE_STUDENTS",
            "NO_VALID_TIMESLOT", "ACCOMMODATION_CONFLICT", "STUDENT_CONFLICT",
            "NO_INVIGILATOR", "ROOM_CLOSED", "NO_EQUIPMENT", "NO_ROOM_CAPACITY",
        }:
            raise ValueError(f"Unsupported SchedulingException reason code: {reason}")
        details = {
            "source": "RoomAllocationExceptions.csv",
            "details": src.get("Details"),
            "unassigned_student_count": int(src["UnassignedStudentCount"]),
            "course_id": int(src["CourseID"]),
            "exam_code": src["ExamCode"],
        }
        exception_rows.append({
            "SchedulingRunID": 1,
            "ExamID": int(src["ExamID"]),
            "IssueType": "ROOM_ALLOCATION",
            "ReasonCode": reason,
            "Severity": "HIGH" if reason == "ACCOMMODATION_CONFLICT" else "MEDIUM",
            "ExceptionDetails": json.dumps(details, separators=(",", ":")),
            "ExceptionStatus": "OPEN",
            "DetectedAt": parse_datetime(
                next((r.get("CreatedAt") for r in sources["AssignmentInvigilator"] if r.get("CreatedAt")), None)
            ),
            "ResolvedAt": None,
        })
    payload["SchedulingException"] = exception_rows
    payload["AssignmentEvent"] = []

    # SchedulingRun metadata: derive dates from the dataset's CreatedAt timestamps.
    created = []
    for table in direct_tables:
        for r in sources[table]:
            value = clean(r.get("CreatedAt"))
            if value:
                created.append(parse_datetime(value))
    for r in sources["AssignmentInvigilator"]:
        value = clean(r.get("CreatedAt"))
        if value:
            created.append(parse_datetime(value))
    if not created:
        raise ValueError("Cannot derive SchedulingRun timestamps from source CreatedAt values")
    started = min(created)
    completed = max(created)
    run = build_run_row(
        sources, config_obj, 1, "V220-20261109-0001", started, completed
    )
    payload["SchedulingRun"] = [run]
    for exception in payload["SchedulingException"]:
        exception["DetectedAt"] = completed

    # Validate required fields and types against SQL metadata.
    for table, rows in payload.items():
        cols = schema_cols[table]
        by_name = {c["name"]: c for c in cols}
        for i, row in enumerate(rows, 1):
            for name, meta in by_name.items():
                if meta["identity"] or meta["computed"]:
                    continue
                if name in row:
                    if row[name] is None and not meta["nullable"] and meta["default"] is None:
                        raise ValueError(f"{table} row {i}: required {name} is NULL")
                elif not meta["nullable"] and meta["default"] is None:
                    raise ValueError(f"{table} row {i}: required column {name} has no value/default")
    return payload

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Execute the full dbo refresh (requires interactive exact confirmation)")
    args = ap.parse_args()

    print("=" * 78)
    print("EXAM SCHEDULING SYSTEM v2.2.0 - TRANSACTIONAL SQL REFRESH")
    print("Default mode is READ-ONLY DRY-RUN. --execute is destructive to dbo data.")
    print("evaluation.GroundTruth is never queried, deleted, inserted, or modified.")
    print("=" * 78)

    sources = load_all_sources()
    with CONFIG.open("r", encoding="utf-8") as f:
        config_obj = json.load(f)

    # Source-level uniqueness checks before connecting to SQL.
    for table, key in {
        "Student": ["StudentCode"], "Course": ["CourseCode"],
        "Room": ["RoomCode"], "Invigilator": ["InvigilatorCode"],
        "Exam": ["ExamCode"],
    }.items():
        check_unique(sources[table], table, key)

    cn = get_connection()
    try:
        cn.autocommit = False
        cur = cn.cursor()

        cur.execute("""
            SELECT t.name, c.name, ty.name, c.is_nullable, c.is_identity,
                   c.is_computed, dc.definition
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id=t.schema_id
            JOIN sys.columns c ON c.object_id=t.object_id
            JOIN sys.types ty ON ty.user_type_id=c.user_type_id
            LEFT JOIN sys.default_constraints dc
              ON dc.parent_object_id=t.object_id AND dc.parent_column_id=c.column_id
            WHERE s.name='dbo'
            ORDER BY t.name, c.column_id
        """)
        schema_cols = defaultdict(list)
        for table, name, typ, nullable, identity, computed, default in cur.fetchall():
            schema_cols[table].append({
                "name": name, "type": typ, "nullable": bool(nullable),
                "identity": bool(identity), "computed": bool(computed),
                "default": default,
            })
        missing = sorted(EXPECTED_TABLES - set(schema_cols))
        if missing:
            raise RuntimeError(f"Expected dbo tables missing: {missing}")
        extra = sorted(set(schema_cols) - EXPECTED_TABLES)
        if extra:
            raise RuntimeError(f"Unexpected dbo tables present; refusing broad refresh: {extra}")

        cur.execute("""
            SELECT pt.name, ct.name
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
            JOIN sys.tables pt ON pt.object_id=fk.referenced_object_id
            JOIN sys.schemas ps ON ps.schema_id=pt.schema_id
            JOIN sys.tables ct ON ct.object_id=fk.parent_object_id
            JOIN sys.schemas cs ON cs.schema_id=ct.schema_id
            WHERE ps.name='dbo' AND cs.name='dbo'
        """)
        edges = {(row[0], row[1]) for row in cur.fetchall()}
        nodes = set(EXPECTED_TABLES)
        indegree = {n: 0 for n in nodes}
        children = defaultdict(set)
        for parent, child in edges:
            if parent != child and child not in children[parent]:
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
        if len(insert_order) != len(nodes):
            raise RuntimeError("FK dependency cycle detected; refusing import")
        delete_order = list(reversed(insert_order))

        payload = prepare_payload(sources, config_obj, schema_cols)

        # Validate all FK references inside the in-memory replacement payload.
        id_sets = {}
        for table, rows in payload.items():
            identity = next((c["name"] for c in schema_cols[table] if c["identity"]), None)
            if identity and all(identity in r for r in rows):
                id_sets[table] = {int(r[identity]) for r in rows}
        ref_checks = [
            ("Enrollment", "StudentID", "Student", "StudentID"),
            ("Enrollment", "CourseID", "Course", "CourseID"),
            ("Exam", "CourseID", "Course", "CourseID"),
            ("ExamEnrollment", "ExamID", "Exam", "ExamID"),
            ("ExamEnrollment", "EnrollmentID", "Enrollment", "EnrollmentID"),
            ("ExamEnrollment", "CourseID", "Course", "CourseID"),
            ("Accommodation", "StudentID", "Student", "StudentID"),
            ("Availability", "InvigilatorID", "Invigilator", "InvigilatorID"),
            ("RoomCapacity", "RoomID", "Room", "RoomID"),
            ("RoomClosure", "RoomID", "Room", "RoomID"),
            ("RoomEquipment", "RoomID", "Room", "RoomID"),
            ("RoomEquipment", "EquipmentID", "Equipment", "EquipmentID"),
            ("ExamRequirement", "ExamID", "Exam", "ExamID"),
            ("ExamRequiredEquipment", "ExamID", "Exam", "ExamID"),
            ("ExamRequiredEquipment", "EquipmentID", "Equipment", "EquipmentID"),
            ("ScheduleAssignment", "ExamID", "Exam", "ExamID"),
            ("ScheduleAssignment", "RoomID", "Room", "RoomID"),
            ("ScheduleAssignment", "SchedulingRunID", "SchedulingRun", "SchedulingRunID"),
            ("AssignmentStudent", "AssignmentID", "ScheduleAssignment", "AssignmentID"),
            ("AssignmentStudent", "ExamEnrollmentID", "ExamEnrollment", "ExamEnrollmentID"),
            ("AssignmentStudent", "SchedulingRunID", "SchedulingRun", "SchedulingRunID"),
            ("AssignmentInvigilator", "AssignmentID", "ScheduleAssignment", "AssignmentID"),
            ("AssignmentInvigilator", "InvigilatorID", "Invigilator", "InvigilatorID"),
            ("AssignmentInvigilator", "SchedulingRunID", "SchedulingRun", "SchedulingRunID"),
            ("SchedulingException", "ExamID", "Exam", "ExamID"),
            ("SchedulingException", "SchedulingRunID", "SchedulingRun", "SchedulingRunID"),
        ]
        for child, child_col, parent, parent_col in ref_checks:
            parent_ids = id_sets[parent]
            for i, row in enumerate(payload[child], 1):
                if int(row[child_col]) not in parent_ids:
                    raise ValueError(
                        f"FK precheck failed: {child}.{child_col} row {i} "
                        f"references missing {parent}.{parent_col}={row[child_col]}"
                    )

        # Check the natural composite consistency of ExamEnrollment against both Exam and Enrollment.
        enrollment_course = {int(r["EnrollmentID"]): int(r["CourseID"]) for r in payload["Enrollment"]}
        exam_course = {int(r["ExamID"]): int(r["CourseID"]) for r in payload["Exam"]}
        for i, r in enumerate(payload["ExamEnrollment"], 1):
            if int(r["CourseID"]) != enrollment_course[int(r["EnrollmentID"])]:
                raise ValueError(f"ExamEnrollment row {i}: CourseID differs from Enrollment.CourseID")
            if int(r["CourseID"]) != exam_course[int(r["ExamID"])]:
                raise ValueError(f"ExamEnrollment row {i}: CourseID differs from Exam.CourseID")

        exam_enrollment_exam = {
            int(r["ExamEnrollmentID"]): int(r["ExamID"])
            for r in payload["ExamEnrollment"]
        }
        seen_student_exam = set()
        for i, r in enumerate(payload["AssignmentStudent"], 1):
            eeid = int(r["ExamEnrollmentID"])
            if exam_enrollment_exam.get(eeid) != int(r["ExamID"]):
                raise ValueError(
                    f"AssignmentStudent row {i}: ExamEnrollmentID does not belong to the same ExamID"
                )
            key = (int(r["ExamID"]), eeid)
            if key in seen_student_exam:
                raise ValueError(f"Duplicate student exam allocation detected: {key}")
            seen_student_exam.add(key)

        # Confirm required identity mappings before showing a plan.
        for table in ("Student", "Course", "Equipment", "Room", "Invigilator",
                      "Enrollment", "Exam", "RoomCapacity", "RoomClosure",
                      "RoomEquipment", "Availability", "Accommodation",
                      "ExamRequirement", "ExamRequiredEquipment", "ExamEnrollment",
                      "ScheduleAssignment", "SchedulingRun"):
            if not any(c["identity"] for c in schema_cols[table]):
                raise RuntimeError(f"{table} is expected to have an identity PK")

        print("\nSOURCE ROW COUNTS")
        for table in sorted(payload):
            print(f"  {table:<27} {len(payload[table]):>8,}")
        print(f"\nFK-safe delete order: {' -> '.join(delete_order)}")
        print(f"FK-safe insert order: {' -> '.join(insert_order)}")
        print(f"Total rows to insert: {sum(len(v) for v in payload.values()):,}")
        print("In-memory FK and ExamEnrollment.CourseID consistency checks: PASSED")
        print("GroundTruth/evaluation schema: EXCLUDED")
        print("AssignmentEvent rows: 0 (no fabricated audit history)")

        if not args.execute:
            cn.rollback()
            print("\nDRY-RUN COMPLETE. SQL MODIFIED: NO.")
            print("To execute, first obtain explicit approval in chat, then run with --execute.")
            return 0

        print("\nWARNING: THIS WILL DELETE ALL EXISTING ROWS IN dbo TABLES AND RELOAD v2.2.0.")
        typed = input("Type exactly REFRESH-DATABASE-V2.2.0 to continue: ").strip()
        if typed != "REFRESH-DATABASE-V2.2.0":
            cn.rollback()
            print("Confirmation did not match. No SQL changes committed.")
            return 3

        try:
            print("\n[EXECUTION] Deleting old dbo rows in child-first order...")
            for table in delete_order:
                cur.execute(f"DELETE FROM dbo.{q(table)};")

            print("[EXECUTION] Inserting v2.2.0 rows in parent-first order...")
            for table in insert_order:
                rows = payload.get(table, [])
                if not rows:
                    continue
                # Determine columns in schema order, excluding computed and identity columns
                # unless identity is explicitly supplied by the source payload.
                cols_meta = schema_cols[table]
                include_cols = []
                for c in cols_meta:
                    name = c["name"]
                    if c["computed"]:
                        continue
                    if c["identity"]:
                        if rows and name in rows[0]:
                            include_cols.append(c)
                    elif any(name in r for r in rows):
                        include_cols.append(c)
                col_names = [c["name"] for c in include_cols]
                if not col_names:
                    raise RuntimeError(f"No insertable columns for {table}")
                sql = (
                    f"INSERT INTO dbo.{q(table)} "
                    f"({', '.join(q(n) for n in col_names)}) "
                    f"VALUES ({', '.join('?' for _ in col_names)})"
                )
                identity_insert = any(c["identity"] for c in include_cols)
                if identity_insert:
                    cur.execute(f"SET IDENTITY_INSERT dbo.{q(table)} ON;")
                try:
                    batch = []
                    for r in rows:
                        batch.append(tuple(r.get(n) for n in col_names))
                    for start in range(0, len(batch), BATCH_SIZE):
                        cur.executemany(sql, batch[start:start+BATCH_SIZE])
                finally:
                    if identity_insert:
                        cur.execute(f"SET IDENTITY_INSERT dbo.{q(table)} OFF;")

            # Validate post-insert counts in the same transaction.
            expected = {t: len(v) for t, v in payload.items()}
            actual = {}
            for table in sorted(EXPECTED_TABLES):
                cur.execute(f"SELECT COUNT_BIG(*) FROM dbo.{q(table)};")
                actual[table] = int(cur.fetchone()[0])
                if actual[table] != expected.get(table, 0):
                    raise RuntimeError(
                        f"Post-insert row-count mismatch for {table}: "
                        f"expected {expected.get(table, 0)}, got {actual[table]}"
                    )

            # Validate core cross-table data invariants.
            cur.execute("""
                SELECT COUNT_BIG(*)
                FROM dbo.ExamEnrollment ee
                JOIN dbo.Exam e ON e.ExamID=ee.ExamID
                JOIN dbo.Enrollment en ON en.EnrollmentID=ee.EnrollmentID
                WHERE ee.CourseID<>e.CourseID OR ee.CourseID<>en.CourseID
            """)
            mismatch = int(cur.fetchone()[0])
            if mismatch:
                raise RuntimeError(f"ExamEnrollment course consistency violations: {mismatch}")

            cur.execute("""
                SELECT COUNT_BIG(*)
                FROM dbo.AssignmentStudent ast
                JOIN dbo.ScheduleAssignment sa ON sa.AssignmentID=ast.AssignmentID
                WHERE ast.ExamID<>sa.ExamID OR ast.SchedulingRunID<>sa.SchedulingRunID
            """)
            mismatch = int(cur.fetchone()[0])
            if mismatch:
                raise RuntimeError(f"AssignmentStudent parent consistency violations: {mismatch}")

            cur.execute("""
                SELECT COUNT_BIG(*)
                FROM dbo.AssignmentInvigilator ai
                JOIN dbo.ScheduleAssignment sa ON sa.AssignmentID=ai.AssignmentID
                WHERE ai.ExamID<>sa.ExamID OR ai.SchedulingRunID<>sa.SchedulingRunID
            """)
            mismatch = int(cur.fetchone()[0])
            if mismatch:
                raise RuntimeError(f"AssignmentInvigilator parent consistency violations: {mismatch}")

            cn.commit()
            report = {
                "status": "COMMITTED",
                "dataset_version": "2.2.0",
                "committed_at": datetime.now().isoformat(timespec="seconds"),
                "row_counts": actual,
                "total_rows": sum(actual.values()),
                "groundtruth_accessed": False,
                "evaluation_schema_accessed": False,
                "source_csv_modified": False,
                "schema_modified": False,
            }
            REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("\n< SUCCESS > TRANSACTION COMMITTED")
            for table, count in sorted(actual.items()):
                print(f"  {table:<27} {count:>8,}")
            print(f"Report: {REPORT}")
            return 0
        except Exception:
            cn.rollback()
            print("\nIMPORT FAILED. TRANSACTION ROLLED BACK; dbo data restored to pre-run state.")
            raise
    finally:
        cn.close()

if __name__ == "__main__":
    raise SystemExit(main())
