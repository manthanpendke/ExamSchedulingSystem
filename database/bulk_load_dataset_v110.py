from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyodbc


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "output" / "full" / "v1.1.0"
CSV_DIR = DATASET_DIR / "csv"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth" / "csv" / "GroundTruth.csv"
MANIFEST_PATH = DATASET_DIR / "manifest.json"

SERVER = r"Manthan\SQLEXPRESS"
DATABASE = "ExamSchedulingDB_v110"
DRIVER = "ODBC Driver 17 for SQL Server"
BATCH_SIZE = 1000
EXPECTED_GROUND_TRUTH_COUNT = 33

# Explicit insert columns. Identity, computed, and defaulted columns are omitted.
INSERT_COLUMNS: dict[str, list[str]] = {
    "Student": [
        "StudentCode", "FirstName", "LastName", "Email", "Department", "Status",
    ],
    "Course": [
        "CourseCode", "CourseName", "Department", "Credits", "Status",
    ],
    "Room": [
        "RoomCode", "Building", "Floor", "RoomType", "IsActive",
    ],
    "Invigilator": [
        "InvigilatorCode", "FullName", "Department", "MaxDailyHours", "Status",
    ],
    "Equipment": [
        "EquipmentName", "EquipmentCategory", "IsActive",
    ],
    "Enrollment": [
        "StudentID", "CourseID", "EnrollmentDate", "EnrollmentStatus",
        "EffectiveFrom", "EffectiveTo",
    ],
    "Accommodation": [
        "StudentID", "AccommodationType", "ExtensionPercentage",
        "RequiresSeparateRoom", "EffectiveFrom", "EffectiveTo",
        "AccommodationStatus",
    ],
    "Availability": [
        "InvigilatorID", "AvailableFrom", "AvailableTo",
        "AvailabilityStatus", "AvailabilityReason",
    ],
    "Exam": [
        "ExamCode", "CourseID", "ExamName", "ExamWindowStart",
        "ExamWindowEnd", "ExamStatus",
    ],
    "ExamRequirement": [
        "ExamID", "DurationMinutes", "RequiredEquipment",
        "AccessibilityRequired", "SpecialInstructions",
    ],
    "ExamRequiredEquipment": [
        "ExamID", "EquipmentID", "QuantityRequired", "IsMandatory",
    ],
    "ExamEnrollment": [
        "ExamID", "EnrollmentID", "CourseID", "ParticipationStatus",
    ],
    "RoomCapacity": [
        "RoomID", "Capacity", "EffectiveFrom", "EffectiveTo", "CapacityReason",
    ],
    "RoomEquipment": [
        "RoomID", "EquipmentID", "Quantity", "EffectiveFrom", "EffectiveTo",
    ],
    "RoomClosure": [
        "RoomID", "ClosureStart", "ClosureEnd", "ClosureReason", "ClosureStatus",
    ],
}

# Tables checked before load. Workflow tables must remain empty too.
EMPTY_CHECK_TABLES = [
    "Accommodation", "AssignmentEvent", "AssignmentInvigilator",
    "AssignmentStudent", "Availability", "Course", "Enrollment",
    "Equipment", "Exam", "ExamEnrollment", "ExamRequiredEquipment",
    "ExamRequirement", "Invigilator", "Room", "RoomCapacity",
    "RoomClosure", "RoomEquipment", "ScheduleAssignment",
    "SchedulingException", "SchedulingRun", "Student",
]


def connect() -> pyodbc.Connection:
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, autocommit=False, timeout=20)


def as_bool(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"Invalid Boolean value: {value!r}")


def as_date(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    return date.fromisoformat(str(value).strip())


def as_datetime(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    return datetime.fromisoformat(str(value).strip())


def as_decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return Decimal(str(value).strip())


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value if value != "" else None


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Dataset manifest not found: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != "1.1.0":
        raise ValueError(
            f"Expected dataset version 1.1.0; found {manifest.get('dataset_version')!r}"
        )
    if manifest.get("profile") != "full":
        raise ValueError(f"Expected full profile; found {manifest.get('profile')!r}")
    counts = manifest.get("baseline_record_counts")
    if not isinstance(counts, dict) or set(counts) != set(INSERT_COLUMNS):
        raise ValueError("Manifest baseline table list does not match loader table list.")
    if int(manifest.get("ground_truth_record_count", -1)) != EXPECTED_GROUND_TRUTH_COUNT:
        raise ValueError(
            "Manifest GroundTruth count does not match the expected 33 records."
        )
    return manifest


def verify_checksums(manifest: dict[str, Any]) -> int:
    checksum_map = manifest.get("checksums_sha256")
    if not isinstance(checksum_map, dict):
        raise ValueError("Manifest has no SHA-256 checksum map.")

    checked = 0
    for relative_path, expected_hash in checksum_map.items():
        path = DATASET_DIR / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Manifest file is missing: {path}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash.lower() != str(expected_hash).lower():
            raise ValueError(f"SHA-256 mismatch: {relative_path}")
        checked += 1

    required_paths = [
        *(f"csv/{table}.csv" for table in INSERT_COLUMNS),
        "ground_truth/csv/GroundTruth.csv",
    ]
    missing_from_manifest = [p for p in required_paths if p not in checksum_map]
    if missing_from_manifest:
        raise ValueError(
            "Required import files are absent from manifest checksums: "
            + ", ".join(missing_from_manifest)
        )
    return checked


def read_csv_file(path: Path, expected_count: int) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing CSV file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = list(reader)
    if len(rows) != expected_count:
        raise ValueError(
            f"{path.name}: expected {expected_count:,} rows, found {len(rows):,}"
        )
    return rows


def load_source_data(manifest: dict[str, Any]) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    source: dict[str, list[dict[str, str]]] = {}
    counts = manifest["baseline_record_counts"]

    for table in INSERT_COLUMNS:
        path = CSV_DIR / f"{table}.csv"
        rows = read_csv_file(path, int(counts[table]))
        source[table] = rows

    ground_truth = read_csv_file(GROUND_TRUTH_CSV, EXPECTED_GROUND_TRUTH_COUNT)
    return source, ground_truth


def validate_csv_headers(
    source: dict[str, list[dict[str, str]]],
    ground_truth: list[dict[str, str]],
) -> None:
    required_headers = {
        "Student": {"StudentCode", "FirstName", "LastName", "Email", "Department", "Status"},
        "Course": {"CourseCode", "CourseName", "Department", "Credits", "Status"},
        "Room": {"RoomCode", "Building", "Floor", "RoomType", "IsActive"},
        "Invigilator": {"InvigilatorCode", "FullName", "Department", "MaxDailyHours", "Status"},
        "Equipment": {"EquipmentCode", "EquipmentName", "EquipmentCategory", "IsActive"},
        "Enrollment": {"StudentCode", "CourseCode", "EnrollmentDate", "EnrollmentStatus", "EffectiveFrom", "EffectiveTo"},
        "Accommodation": {"StudentCode", "AccommodationType", "ExtensionPercentage", "RequiresSeparateRoom", "EffectiveFrom", "EffectiveTo", "AccommodationStatus"},
        "Availability": {"InvigilatorCode", "AvailableFrom", "AvailableTo", "AvailabilityStatus", "AvailabilityReason"},
        "Exam": {"ExamCode", "CourseCode", "ExamName", "ExamWindowStart", "ExamWindowEnd", "ExamStatus"},
        "ExamRequirement": {"ExamCode", "DurationMinutes", "RequiredEquipment", "AccessibilityRequired", "SpecialInstructions"},
        "ExamRequiredEquipment": {"ExamCode", "EquipmentCode", "QuantityRequired", "IsMandatory"},
        "ExamEnrollment": {"ExamCode", "StudentCode", "CourseCode", "ParticipationStatus"},
        "RoomCapacity": {"RoomCode", "Capacity", "EffectiveFrom", "EffectiveTo", "CapacityReason"},
        "RoomEquipment": {"RoomCode", "EquipmentCode", "Quantity", "EffectiveFrom", "EffectiveTo"},
        "RoomClosure": {"RoomCode", "ClosureStart", "ClosureEnd", "ClosureReason", "ClosureStatus"},
    }

    for table, rows in source.items():
        actual = set(rows[0].keys()) if rows else set()
        missing = required_headers[table] - actual
        if missing:
            raise ValueError(f"{table}.csv is missing columns: {sorted(missing)}")

    gt_required = {
        "DatasetVersion", "ScenarioCode", "EntityType", "EntityCode",
        "IssueType", "ExpectedOutcome", "ExpectedReasonCode", "Severity",
        "Description",
    }
    gt_actual = set(ground_truth[0].keys()) if ground_truth else set()
    gt_missing = gt_required - gt_actual
    if gt_missing:
        raise ValueError(
            f"GroundTruth.csv is missing columns: {sorted(gt_missing)}"
        )


def fetch_map(cursor: pyodbc.Cursor, table: str, code_column: str, id_column: str) -> dict[str, int]:
    cursor.execute(
        f"SELECT [{code_column}], [{id_column}] FROM [dbo].[{table}]"
    )
    return {str(code): int(identity) for code, identity in cursor.fetchall()}


def require_code(mapping: dict[str, int], code: str, context: str) -> int:
    try:
        return mapping[str(code)]
    except KeyError:
        raise ValueError(
            f"Unresolved business code {code!r} in {context}"
        ) from None


def insert_rows(cursor: pyodbc.Cursor, table: str, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    columns = INSERT_COLUMNS[table]
    column_sql = ", ".join(f"[{column}]" for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO [dbo].[{table}] ({column_sql}) "
        f"VALUES ({placeholders})"
    )

    cursor.fast_executemany = True
    for offset in range(0, len(rows), BATCH_SIZE):
        batch = rows[offset:offset + BATCH_SIZE]
        cursor.executemany(sql, batch)
        print(
            f"    {table}: {min(offset + len(batch), len(rows)):,}/{len(rows):,}",
            flush=True,
        )


def prepare_rows(
    table: str,
    source_rows: list[dict[str, str]],
    maps: dict[str, Any],
) -> list[tuple[Any, ...]]:
    prepared: list[tuple[Any, ...]] = []

    for row in source_rows:
        if table == "Student":
            values = (
                row["StudentCode"], row["FirstName"], row["LastName"],
                row["Email"], row["Department"], row["Status"],
            )
        elif table == "Course":
            values = (
                row["CourseCode"], row["CourseName"], row["Department"],
                int(row["Credits"]), row["Status"],
            )
        elif table == "Room":
            values = (
                row["RoomCode"], row["Building"], int(row["Floor"]),
                row["RoomType"], as_bool(row["IsActive"]),
            )
        elif table == "Invigilator":
            values = (
                row["InvigilatorCode"], row["FullName"], row["Department"],
                as_decimal(row["MaxDailyHours"]), row["Status"],
            )
        elif table == "Equipment":
            # EquipmentCode is a persisted computed column in SQL Server.
            values = (
                row["EquipmentName"], row["EquipmentCategory"],
                as_bool(row["IsActive"]),
            )
        elif table == "Enrollment":
            values = (
                require_code(maps["student"], row["StudentCode"], table),
                require_code(maps["course"], row["CourseCode"], table),
                as_date(row["EnrollmentDate"]), row["EnrollmentStatus"],
                as_date(row["EffectiveFrom"]), as_date(row["EffectiveTo"]),
            )
        elif table == "Accommodation":
            values = (
                require_code(maps["student"], row["StudentCode"], table),
                row["AccommodationType"], as_decimal(row["ExtensionPercentage"]),
                as_bool(row["RequiresSeparateRoom"]), as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]), row["AccommodationStatus"],
            )
        elif table == "Availability":
            values = (
                require_code(maps["invigilator"], row["InvigilatorCode"], table),
                as_datetime(row["AvailableFrom"]), as_datetime(row["AvailableTo"]),
                row["AvailabilityStatus"], optional_text(row["AvailabilityReason"]),
            )
        elif table == "Exam":
            values = (
                row["ExamCode"],
                require_code(maps["course"], row["CourseCode"], table),
                row["ExamName"], as_datetime(row["ExamWindowStart"]),
                as_datetime(row["ExamWindowEnd"]), row["ExamStatus"],
            )
        elif table == "ExamRequirement":
            values = (
                require_code(maps["exam"], row["ExamCode"], table),
                int(row["DurationMinutes"]), optional_text(row["RequiredEquipment"]),
                as_bool(row["AccessibilityRequired"]),
                optional_text(row["SpecialInstructions"]),
            )
        elif table == "ExamRequiredEquipment":
            values = (
                require_code(maps["exam"], row["ExamCode"], table),
                require_code(maps["equipment"], row["EquipmentCode"], table),
                int(row["QuantityRequired"]), as_bool(row["IsMandatory"]),
            )
        elif table == "ExamEnrollment":
            student_id = require_code(maps["student"], row["StudentCode"], table)
            course_id = require_code(maps["course"], row["CourseCode"], table)
            enrollment_id = maps["enrollment"].get((student_id, course_id))
            if enrollment_id is None:
                raise ValueError(
                    f"No Enrollment for student {row['StudentCode']} "
                    f"and course {row['CourseCode']}"
                )
            exam_id = require_code(maps["exam"], row["ExamCode"], table)
            if maps["exam_course"].get(exam_id) != course_id:
                raise ValueError(f"Exam/course mismatch for {row['ExamCode']}")
            values = (
                exam_id, enrollment_id, course_id, row["ParticipationStatus"],
            )
        elif table == "RoomCapacity":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                int(row["Capacity"]), as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]), optional_text(row["CapacityReason"]),
            )
        elif table == "RoomEquipment":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                require_code(maps["equipment"], row["EquipmentCode"], table),
                int(row["Quantity"]), as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]),
            )
        elif table == "RoomClosure":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                as_datetime(row["ClosureStart"]), as_datetime(row["ClosureEnd"]),
                row["ClosureReason"], row["ClosureStatus"],
            )
        else:
            raise ValueError(f"Unsupported table: {table}")

        prepared.append(values)

    return prepared


def prepare_and_insert(
    cursor: pyodbc.Cursor,
    table: str,
    source_rows: list[dict[str, str]],
    maps: dict[str, Any],
) -> None:
    insert_rows(cursor, table, prepare_rows(table, source_rows, maps))


def check_database_identity_and_empty(cursor: pyodbc.Cursor) -> None:
    cursor.execute("SELECT DB_NAME()")
    actual_database = str(cursor.fetchone()[0])
    if actual_database != DATABASE:
        raise RuntimeError(
            f"Safety stop: connected to {actual_database!r}, expected {DATABASE!r}."
        )

    nonempty: list[str] = []
    for table in EMPTY_CHECK_TABLES:
        cursor.execute(f"SELECT COUNT_BIG(*) FROM [dbo].[{table}]")
        count = int(cursor.fetchone()[0])
        if count:
            nonempty.append(f"dbo.{table}={count}")

    cursor.execute("SELECT COUNT_BIG(*) FROM [evaluation].[GroundTruth]")
    ground_truth_count = int(cursor.fetchone()[0])
    if ground_truth_count:
        nonempty.append(f"evaluation.GroundTruth={ground_truth_count}")

    if nonempty:
        raise RuntimeError(
            "Refusing to load: target database is not empty: "
            + ", ".join(nonempty)
        )


def verify_schema_health(cursor: pyodbc.Cursor) -> None:
    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0),
            (SELECT COUNT(*) FROM sys.foreign_keys
             WHERE is_disabled = 0 AND is_not_trusted = 0),
            (SELECT COUNT(*) FROM sys.check_constraints
             WHERE is_disabled = 0 AND is_not_trusted = 0),
            (SELECT COUNT(*) FROM sys.triggers
             WHERE parent_class = 1 AND is_disabled = 0)
    """)
    actual = tuple(int(v) for v in cursor.fetchone())
    expected = (22, 24, 49, 3)
    if actual != expected:
        raise RuntimeError(
            f"Target schema health mismatch: expected {expected}, found {actual}"
        )


def verify_counts(
    cursor: pyodbc.Cursor,
    expected_counts: dict[str, int],
    expected_ground_truth: int,
) -> None:
    failures: list[str] = []
    print("\nFINAL DATABASE COUNTS")
    for table in INSERT_COLUMNS:
        expected = int(expected_counts[table])
        cursor.execute(f"SELECT COUNT_BIG(*) FROM [dbo].[{table}]")
        actual = int(cursor.fetchone()[0])
        print(f"{table:28} {actual:>8,} / {expected:,}")
        if actual != expected:
            failures.append(f"{table}: expected {expected}, found {actual}")

    cursor.execute("SELECT COUNT_BIG(*) FROM [evaluation].[GroundTruth]")
    actual_gt = int(cursor.fetchone()[0])
    print(
        f"{'evaluation.GroundTruth':28} "
        f"{actual_gt:>8,} / {expected_ground_truth:,}"
    )
    if actual_gt != expected_ground_truth:
        failures.append(
            f"GroundTruth: expected {expected_ground_truth}, found {actual_gt}"
        )

    if failures:
        raise RuntimeError("; ".join(failures))


def insert_ground_truth(
    cursor: pyodbc.Cursor,
    rows: list[dict[str, str]],
) -> None:
    columns = [
        "DatasetVersion", "ScenarioCode", "EntityType", "EntityCode",
        "IssueType", "ExpectedOutcome", "ExpectedReasonCode", "Severity",
        "Description",
    ]
    sql = (
        "INSERT INTO [evaluation].[GroundTruth] "
        f"({', '.join(f'[{c}]' for c in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    values = [
        (
            row["DatasetVersion"], row["ScenarioCode"], row["EntityType"],
            row["EntityCode"], row["IssueType"], row["ExpectedOutcome"],
            optional_text(row["ExpectedReasonCode"]), row["Severity"],
            row["Description"],
        )
        for row in rows
    ]
    cursor.fast_executemany = True
    cursor.executemany(sql, values)
    print(f"    evaluation.GroundTruth: {len(values):,}/{len(values):,}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight or transactionally load Exam Scheduling dataset v1.1.0."
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Commit the import. Without this flag, only perform read-only preflight checks.",
    )
    args = parser.parse_args()

    print("=" * 68)
    print("EXAM SCHEDULING DATASET v1.1.0 — CONTROLLED SQL SERVER LOADER")
    print("=" * 68)
    print(f"Dataset directory : {DATASET_DIR}")
    print(f"SQL Server        : {SERVER}")
    print(f"Target database   : {DATABASE}")
    print(f"Mode              : {'IMPORT' if args.load else 'READ-ONLY PREFLIGHT'}")

    manifest = load_manifest()
    checksum_count = verify_checksums(manifest)
    source, ground_truth = load_source_data(manifest)
    validate_csv_headers(source, ground_truth)

    print(f"\nDataset version   : {manifest['dataset_version']}")
    print(f"Baseline tables   : {len(source)}")
    print(f"GroundTruth rows  : {len(ground_truth)}")
    print(f"Checksums verified: {checksum_count}")
    print("CSV row counts and required headers: PASS")

    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute("SET XACT_ABORT ON;")
        verify_schema_health(cursor)
        check_database_identity_and_empty(cursor)
        print("\nTarget database identity, schema health, and emptiness: PASS")

        if not args.load:
            connection.rollback()
            print("\nPREFLIGHT PASSED. No database records were changed.")
            print("To perform the controlled import after reviewing this output:")
            print("  python -m database.bulk_load_dataset_v110 --load")
            return 0

        maps: dict[str, Any] = {}

        # Master tables first.
        for table in ("Student", "Course", "Room", "Invigilator", "Equipment"):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

            if table == "Student":
                maps["student"] = fetch_map(cursor, "Student", "StudentCode", "StudentID")
            elif table == "Course":
                maps["course"] = fetch_map(cursor, "Course", "CourseCode", "CourseID")
            elif table == "Room":
                maps["room"] = fetch_map(cursor, "Room", "RoomCode", "RoomID")
            elif table == "Invigilator":
                maps["invigilator"] = fetch_map(
                    cursor, "Invigilator", "InvigilatorCode", "InvigilatorID"
                )
            elif table == "Equipment":
                maps["equipment"] = fetch_map(
                    cursor, "Equipment", "EquipmentCode", "EquipmentID"
                )
                expected_codes = {f"EQP-{i:06d}" for i in range(1, 7)}
                if set(maps["equipment"]) != expected_codes:
                    raise RuntimeError(
                        "Computed EquipmentCode values differ from expected: "
                        f"{sorted(maps['equipment'])}"
                    )

        print("\nLoading Enrollment...")
        prepare_and_insert(cursor, "Enrollment", source["Enrollment"], maps)
        cursor.execute(
            "SELECT StudentID, CourseID, EnrollmentID FROM [dbo].[Enrollment]"
        )
        maps["enrollment"] = {
            (int(student_id), int(course_id)): int(enrollment_id)
            for student_id, course_id, enrollment_id in cursor.fetchall()
        }
        if len(maps["enrollment"]) != int(manifest["baseline_record_counts"]["Enrollment"]):
            raise RuntimeError(
                "Enrollment mapping is not one-to-one by StudentID/CourseID."
            )

        for table in ("Accommodation", "Availability"):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

        print("\nLoading Exam...")
        prepare_and_insert(cursor, "Exam", source["Exam"], maps)
        maps["exam"] = fetch_map(cursor, "Exam", "ExamCode", "ExamID")
        cursor.execute("SELECT ExamID, CourseID FROM [dbo].[Exam]")
        maps["exam_course"] = {
            int(exam_id): int(course_id)
            for exam_id, course_id in cursor.fetchall()
        }

        for table in (
            "ExamRequirement", "ExamRequiredEquipment", "ExamEnrollment",
            "RoomCapacity", "RoomEquipment", "RoomClosure",
        ):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

        # Evaluation labels are loaded into their separate schema/table.
        print("\nLoading separate evaluation GroundTruth...")
        insert_ground_truth(cursor, ground_truth)

        verify_counts(
            cursor,
            manifest["baseline_record_counts"],
            EXPECTED_GROUND_TRUTH_COUNT,
        )

        connection.commit()
        print("\nBASELINE DATASET AND SEPARATE GROUNDTRUTH COMMITTED SUCCESSFULLY.")
        print("No scheduling runs or schedule assignments were created.")
        return 0

    except Exception:
        connection.rollback()
        print(
            "\nERROR: import failed. The transaction was rolled back.",
            file=sys.stderr,
        )
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
