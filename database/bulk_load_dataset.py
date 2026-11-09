
from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyodbc


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "output" / "full" / "v1.1.0" / "csv"
BATCH_SIZE = 1000

SERVER = r"Manthan\SQLEXPRESS"
DATABASE = "ExamSchedulingDB"

EXPECTED_COUNTS = {
    "Student": 5000,
    "Course": 100,
    "Room": 100,
    "Invigilator": 200,
    "Equipment": 6,
    "Enrollment": 20045,
    "Accommodation": 494,
    "Availability": 1000,
    "Exam": 300,
    "ExamRequirement": 300,
    "ExamRequiredEquipment": 150,
    "ExamEnrollment": 20045,
    "RoomCapacity": 100,
    "RoomEquipment": 267,
    "RoomClosure": 12,
}

# Explicit insert columns. Identity, computed and defaulted
# columns are intentionally omitted.
INSERT_COLUMNS = {
    "Student": [
        "StudentCode", "FirstName", "LastName",
        "Email", "Department", "Status",
    ],
    "Course": [
        "CourseCode", "CourseName", "Department",
        "Credits", "Status",
    ],
    "Room": [
        "RoomCode", "Building", "Floor", "RoomType", "IsActive",
    ],
    "Invigilator": [
        "InvigilatorCode", "FullName", "Department",
        "MaxDailyHours", "Status",
    ],
    "Equipment": [
        "EquipmentName", "EquipmentCategory", "IsActive",
    ],
    "Enrollment": [
        "StudentID", "CourseID", "EnrollmentDate",
        "EnrollmentStatus", "EffectiveFrom", "EffectiveTo",
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
        "ExamCode", "CourseID", "ExamName",
        "ExamWindowStart", "ExamWindowEnd", "ExamStatus",
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
        "RoomID", "Capacity", "EffectiveFrom",
        "EffectiveTo", "CapacityReason",
    ],
    "RoomEquipment": [
        "RoomID", "EquipmentID", "Quantity",
        "EffectiveFrom", "EffectiveTo",
    ],
    "RoomClosure": [
        "RoomID", "ClosureStart", "ClosureEnd",
        "ClosureReason", "ClosureStatus",
    ],
}

# Source CSV name for each destination table.
CSV_FILES = {name: f"{name}.csv" for name in EXPECTED_COUNTS}


def connect():
    connection_string = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, autocommit=False)


def read_csv(table):
    path = DATA_DIR / CSV_FILES[table]
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    expected = EXPECTED_COUNTS[table]
    if len(rows) != expected:
        raise ValueError(
            f"{table}: expected {expected} CSV rows, found {len(rows)}"
        )

    return rows


def as_bool(value):
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise ValueError(f"Invalid Boolean value: {value!r}")


def as_date(value):
    if not value:
        return None
    return date.fromisoformat(value)


def as_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def as_decimal(value):
    if not value:
        return None
    return Decimal(str(value))


def insert_rows(cursor, table, rows):
    columns = INSERT_COLUMNS[table]
    column_sql = ", ".join(f"[{c}]" for c in columns)
    placeholders = ", ".join("?" for _ in columns)

    sql = (
        f"INSERT INTO [dbo].[{table}] "
        f"({column_sql}) VALUES ({placeholders})"
    )

    cursor.fast_executemany = True

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        cursor.executemany(sql, batch)
        completed = min(start + len(batch), len(rows))
        print(
            f"    {table}: {completed:,}/{len(rows):,}",
            flush=True,
        )


def fetch_map(cursor, table, code_column, id_column):
    cursor.execute(
        f"SELECT [{code_column}], [{id_column}] "
        f"FROM [dbo].[{table}]"
    )
    return {str(code): int(identity) for code, identity in cursor.fetchall()}


def require_code(mapping, code, context):
    try:
        return mapping[str(code)]
    except KeyError:
        raise ValueError(
            f"Unresolved business code {code!r} in {context}"
        ) from None


def prepare_and_insert(cursor, table, source_rows, maps):
    prepared = []

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
                row["InvigilatorCode"], row["FullName"],
                row["Department"], as_decimal(row["MaxDailyHours"]),
                row["Status"],
            )

        elif table == "Equipment":
            # EquipmentCode is computed by SQL Server.
            values = (
                row["EquipmentName"], row["EquipmentCategory"],
                as_bool(row["IsActive"]),
            )

        elif table == "Enrollment":
            values = (
                require_code(maps["student"], row["StudentCode"], table),
                require_code(maps["course"], row["CourseCode"], table),
                as_date(row["EnrollmentDate"]),
                row["EnrollmentStatus"],
                as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]),
            )

        elif table == "Accommodation":
            values = (
                require_code(maps["student"], row["StudentCode"], table),
                row["AccommodationType"],
                as_decimal(row["ExtensionPercentage"]),
                as_bool(row["RequiresSeparateRoom"]),
                as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]),
                row["AccommodationStatus"],
            )

        elif table == "Availability":
            values = (
                require_code(maps["invigilator"], row["InvigilatorCode"], table),
                as_datetime(row["AvailableFrom"]),
                as_datetime(row["AvailableTo"]),
                row["AvailabilityStatus"],
                row["AvailabilityReason"] or None,
            )

        elif table == "Exam":
            values = (
                row["ExamCode"],
                require_code(maps["course"], row["CourseCode"], table),
                row["ExamName"],
                as_datetime(row["ExamWindowStart"]),
                as_datetime(row["ExamWindowEnd"]),
                row["ExamStatus"],
            )

        elif table == "ExamRequirement":
            values = (
                require_code(maps["exam"], row["ExamCode"], table),
                int(row["DurationMinutes"]),
                row["RequiredEquipment"] or None,
                as_bool(row["AccessibilityRequired"]),
                row["SpecialInstructions"] or None,
            )

        elif table == "ExamRequiredEquipment":
            values = (
                require_code(maps["exam"], row["ExamCode"], table),
                require_code(maps["equipment"], row["EquipmentCode"], table),
                int(row["QuantityRequired"]),
                as_bool(row["IsMandatory"]),
            )

        elif table == "ExamEnrollment":
            student_id = require_code(
                maps["student"], row["StudentCode"], table
            )
            course_id = require_code(
                maps["course"], row["CourseCode"], table
            )
            enrollment_id = maps["enrollment"].get(
                (student_id, course_id)
            )
            if enrollment_id is None:
                raise ValueError(
                    f"No Enrollment for student {row['StudentCode']} "
                    f"and course {row['CourseCode']}"
                )

            exam_id = require_code(maps["exam"], row["ExamCode"], table)

            # Enforce the cross-table course consistency explicitly.
            if maps["exam_course"][exam_id] != course_id:
                raise ValueError(
                    f"Exam/course mismatch for {row['ExamCode']}"
                )

            values = (
                exam_id, enrollment_id, course_id,
                row["ParticipationStatus"],
            )

        elif table == "RoomCapacity":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                int(row["Capacity"]),
                as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]),
                row["CapacityReason"] or None,
            )

        elif table == "RoomEquipment":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                require_code(maps["equipment"], row["EquipmentCode"], table),
                int(row["Quantity"]),
                as_date(row["EffectiveFrom"]),
                as_date(row["EffectiveTo"]),
            )

        elif table == "RoomClosure":
            values = (
                require_code(maps["room"], row["RoomCode"], table),
                as_datetime(row["ClosureStart"]),
                as_datetime(row["ClosureEnd"]),
                row["ClosureReason"],
                row["ClosureStatus"],
            )

        else:
            raise ValueError(f"Unsupported table: {table}")

        prepared.append(values)

    insert_rows(cursor, table, prepared)


def check_database_empty(cursor):
    tables = [
        "Accommodation", "AssignmentEvent", "AssignmentInvigilator",
        "AssignmentStudent", "Availability", "Course", "Enrollment",
        "Equipment", "Exam", "ExamEnrollment", "ExamRequiredEquipment",
        "ExamRequirement", "Invigilator", "Room", "RoomCapacity",
        "RoomClosure", "RoomEquipment", "ScheduleAssignment",
        "SchedulingException", "SchedulingRun", "Student",
    ]

    nonempty = []
    for table in tables:
        cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}]")
        count = int(cursor.fetchone()[0])
        if count:
            nonempty.append(f"dbo.{table}={count}")

    cursor.execute("SELECT COUNT_BIG(*) FROM evaluation.GroundTruth")
    ground_truth_count = int(cursor.fetchone()[0])
    if ground_truth_count:
        nonempty.append(f"evaluation.GroundTruth={ground_truth_count}")

    if nonempty:
        raise RuntimeError(
            "Refusing to load: target database is not empty: "
            + ", ".join(nonempty)
        )


def verify_counts(cursor):
    failures = []

    print("\nFINAL DATABASE COUNTS")
    for table, expected in EXPECTED_COUNTS.items():
        cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}]")
        actual = int(cursor.fetchone()[0])
        print(f"{table:28} {actual:>8,} / {expected:,}")
        if actual != expected:
            failures.append(
                f"{table}: expected {expected}, found {actual}"
            )

    if failures:
        raise RuntimeError("; ".join(failures))


def main():
    print("=" * 64)
    print("EXAM SCHEDULING — V1.1.0 BULK DATA LOADER")
    print("=" * 64)
    print(f"Dataset: {DATA_DIR}")
    print(f"SQL Server: {SERVER}")
    print(f"Database: {DATABASE}")

    source = {table: read_csv(table) for table in EXPECTED_COUNTS}

    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute("SET XACT_ABORT ON;")

        check_database_empty(cursor)

        maps = {}

        # Parent/master records.
        for table in ("Student", "Course", "Room", "Invigilator", "Equipment"):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

            if table == "Student":
                maps["student"] = fetch_map(
                    cursor, "Student", "StudentCode", "StudentID"
                )
            elif table == "Course":
                maps["course"] = fetch_map(
                    cursor, "Course", "CourseCode", "CourseID"
                )
            elif table == "Room":
                maps["room"] = fetch_map(
                    cursor, "Room", "RoomCode", "RoomID"
                )
            elif table == "Invigilator":
                maps["invigilator"] = fetch_map(
                    cursor, "Invigilator", "InvigilatorCode", "InvigilatorID"
                )
            elif table == "Equipment":
                maps["equipment"] = fetch_map(
                    cursor, "Equipment", "EquipmentCode", "EquipmentID"
                )

                expected_codes = {
                    f"EQP-{i:06d}" for i in range(1, 7)
                }
                if set(maps["equipment"]) != expected_codes:
                    raise RuntimeError(
                        "Computed EquipmentCode values differ from "
                        f"expected values: {sorted(maps['equipment'])}"
                    )

        # Course-dependent exam records.
        print("\nLoading Enrollment...")
        prepare_and_insert(cursor, "Enrollment", source["Enrollment"], maps)

        cursor.execute(
            "SELECT StudentID, CourseID, EnrollmentID FROM dbo.Enrollment"
        )
        maps["enrollment"] = {
            (int(student_id), int(course_id)): int(enrollment_id)
            for student_id, course_id, enrollment_id in cursor.fetchall()
        }

        for table in ("Accommodation", "Availability"):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

        print("\nLoading Exam...")
        prepare_and_insert(cursor, "Exam", source["Exam"], maps)
        maps["exam"] = fetch_map(
            cursor, "Exam", "ExamCode", "ExamID"
        )

        cursor.execute("SELECT ExamID, CourseID FROM dbo.Exam")
        maps["exam_course"] = {
            int(exam_id): int(course_id)
            for exam_id, course_id in cursor.fetchall()
        }

        for table in (
            "ExamRequirement",
            "ExamRequiredEquipment",
            "ExamEnrollment",
            "RoomCapacity",
            "RoomEquipment",
            "RoomClosure",
        ):
            print(f"\nLoading {table}...")
            prepare_and_insert(cursor, table, source[table], maps)

        verify_counts(cursor)

        connection.commit()
        print("\nBASELINE BULK LOAD COMMITTED SUCCESSFULLY.")

    except Exception:
        connection.rollback()
        print(
            "\nERROR: bulk load failed. The transaction was rolled back.",
            file=sys.stderr,
        )
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
