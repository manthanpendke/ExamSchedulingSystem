
from __future__ import annotations

import csv
import hashlib
import json
import sys

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v2.json"

ERROR_LIMIT = 200


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def as_int(value, field: str, errors: list[str], context: str):
    try:
        if value is None or str(value).strip() == "":
            raise ValueError
        return int(value)
    except (ValueError, TypeError):
        errors.append(f"{context}: invalid integer in {field}: {value!r}")
        return None


def as_float(value, field: str, errors: list[str], context: str):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        errors.append(f"{context}: invalid number in {field}: {value!r}")
        return None


def parse_datetime(value, field: str, errors: list[str], context: str):
    try:
        if not value:
            raise ValueError
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        errors.append(f"{context}: invalid datetime in {field}: {value!r}")
        return None


def check_unique(rows, field, table, errors):
    values = [row.get(field) for row in rows]
    counts = Counter(values)

    duplicates = [
        value for value, count in counts.items()
        if count > 1
    ]

    if duplicates:
        errors.append(
            f"{table}.{field}: {len(duplicates)} duplicate values; "
            f"examples={duplicates[:5]}"
        )


def check_fk(rows, field, parent_ids, table, errors):
    for index, row in enumerate(rows, start=2):
        value = as_int(
            row.get(field),
            field,
            errors,
            f"{table} CSV row {index}"
        )

        if value is not None and value not in parent_ids:
            errors.append(
                f"{table} row {index}: {field}={value} "
                "does not reference a parent record"
            )


def check_enum(rows, field, allowed, table, errors):
    for index, row in enumerate(rows, start=2):
        value = row.get(field)

        if value not in allowed:
            errors.append(
                f"{table} row {index}: invalid {field}={value!r}; "
                f"allowed={sorted(allowed)}"
            )


def check_positive(rows, field, table, errors, maximum=None):
    for index, row in enumerate(rows, start=2):
        value = as_float(
            row.get(field),
            field,
            errors,
            f"{table} CSV row {index}"
        )

        if value is None:
            continue

        if value <= 0:
            errors.append(
                f"{table} row {index}: {field} must be positive"
            )

        if maximum is not None and value > maximum:
            errors.append(
                f"{table} row {index}: {field} exceeds {maximum}"
            )


def check_date_order(
    rows,
    start_field,
    end_field,
    table,
    errors
):
    for index, row in enumerate(rows, start=2):
        start = parse_datetime(
            row.get(start_field),
            start_field,
            errors,
            f"{table} CSV row {index}"
        )

        end_value = row.get(end_field)

        # EffectiveTo may be NULL.
        if not end_value:
            continue

        end = parse_datetime(
            end_value,
            end_field,
            errors,
            f"{table} CSV row {index}"
        )

        if start and end and end <= start:
            errors.append(
                f"{table} row {index}: {end_field} must be "
                f"later than {start_field}"
            )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_dataset(output_dir: Path) -> dict:
    table_names = [
        "Student",
        "Course",
        "Enrollment",
        "Exam",
        "ExamEnrollment",
        "ExamRequirement",
        "Room",
        "RoomCapacity",
        "RoomClosure",
        "Equipment",
        "RoomEquipment",
        "Invigilator",
        "Availability",
        "Accommodation",
        "GroundTruth"
    ]

    return {
        name: read_csv(output_dir / f"{name}.csv")
        for name in table_names
    }


def validate_dataset(data: dict, config: dict, output_dir: Path) -> list[str]:
    errors = []

    # ---------------------------------------------------------
    # 1. Primary keys and business-code uniqueness
    # ---------------------------------------------------------

    primary_keys = {
        "Student": "StudentID",
        "Course": "CourseID",
        "Enrollment": "EnrollmentID",
        "Exam": "ExamID",
        "ExamEnrollment": "ExamEnrollmentID",
        "ExamRequirement": "RequirementID",
        "Room": "RoomID",
        "RoomCapacity": "RoomCapacityID",
        "RoomClosure": "RoomClosureID",
        "Equipment": "EquipmentID",
        "RoomEquipment": "RoomEquipmentID",
        "Invigilator": "InvigilatorID",
        "Availability": "AvailabilityID",
        "Accommodation": "AccommodationID",
        "GroundTruth": "ScenarioCode"
    }

    business_codes = {
        "Student": "StudentCode",
        "Course": "CourseCode",
        "Exam": "ExamCode",
        "Room": "RoomCode",
        "Invigilator": "InvigilatorCode"
    }

    for table, field in primary_keys.items():
        check_unique(data[table], field, table, errors)

    for table, field in business_codes.items():
        check_unique(data[table], field, table, errors)

    # ---------------------------------------------------------
    # 2. Build parent ID sets
    # ---------------------------------------------------------

    def ids(table, field):
        result = set()

        for index, row in enumerate(data[table], start=2):
            value = as_int(
                row.get(field),
                field,
                errors,
                f"{table} CSV row {index}"
            )

            if value is not None:
                result.add(value)

        return result

    student_ids = ids("Student", "StudentID")
    course_ids = ids("Course", "CourseID")
    enrollment_ids = ids("Enrollment", "EnrollmentID")
    exam_ids = ids("Exam", "ExamID")
    room_ids = ids("Room", "RoomID")
    equipment_ids = ids("Equipment", "EquipmentID")
    invigilator_ids = ids("Invigilator", "InvigilatorID")

    # ---------------------------------------------------------
    # 3. Foreign key integrity
    # ---------------------------------------------------------

    fk_rules = [
        ("Enrollment", "StudentID", student_ids),
        ("Enrollment", "CourseID", course_ids),

        ("Exam", "CourseID", course_ids),

        ("ExamEnrollment", "ExamID", exam_ids),
        ("ExamEnrollment", "EnrollmentID", enrollment_ids),
        ("ExamEnrollment", "CourseID", course_ids),

        ("ExamRequirement", "ExamID", exam_ids),
        ("RoomCapacity", "RoomID", room_ids),
        ("RoomClosure", "RoomID", room_ids),

        ("RoomEquipment", "RoomID", room_ids),
        ("RoomEquipment", "EquipmentID", equipment_ids),

        ("Availability", "InvigilatorID", invigilator_ids),
        ("Accommodation", "StudentID", student_ids)
    ]

    for table, field, parent_ids in fk_rules:
        check_fk(data[table], field, parent_ids, table, errors)

    # ---------------------------------------------------------
    # 4. Required status and type values
    # ---------------------------------------------------------

    check_enum(
        data["Student"],
        "Status",
        {"ACTIVE", "INACTIVE", "GRADUATED"},
        "Student",
        errors
    )

    check_enum(
        data["Course"],
        "Status",
        {"ACTIVE", "INACTIVE"},
        "Course",
        errors
    )

    check_enum(
        data["Enrollment"],
        "EnrollmentStatus",
        {"ENROLLED", "DROPPED", "COMPLETED"},
        "Enrollment",
        errors
    )

    check_enum(
        data["Exam"],
        "ExamStatus",
        {"DRAFT", "READY", "SCHEDULED", "CANCELLED"},
        "Exam",
        errors
    )

    check_enum(
        data["ExamEnrollment"],
        "ParticipationStatus",
        {"REGISTERED", "WITHDRAWN", "EXEMPT"},
        "ExamEnrollment",
        errors
    )

    check_enum(
        data["Room"],
        "RoomType",
        {"STANDARD", "LAB", "ACCESSIBLE"},
        "Room",
        errors
    )

    check_enum(
        data["RoomClosure"],
        "ClosureStatus",
        {"ACTIVE", "COMPLETED", "CANCELLED"},
        "RoomClosure",
        errors
    )

    check_enum(
        data["Invigilator"],
        "Status",
        {"ACTIVE", "INACTIVE"},
        "Invigilator",
        errors
    )

    check_enum(
        data["Availability"],
        "AvailabilityStatus",
        {"AVAILABLE", "UNAVAILABLE"},
        "Availability",
        errors
    )

    check_enum(
        data["Accommodation"],
        "AccommodationType",
        {
            "EXTENDED_TIME",
            "SPECIAL_EQUIPMENT",
            "SEPARATE_ROOM",
            "ACCESSIBLE_ROOM"
        },
        "Accommodation",
        errors
    )

    check_enum(
        data["Accommodation"],
        "AccommodationStatus",
        {"ACTIVE", "EXPIRED", "REVOKED"},
        "Accommodation",
        errors
    )

    # ---------------------------------------------------------
    # 5. Business code formats
    # ---------------------------------------------------------

    for row in data["Student"]:
        expected = f"STU-{int(row['StudentID']):06d}"
        if row["StudentCode"] != expected:
            errors.append(
                f"Student {row['StudentID']}: expected code {expected}"
            )

    for row in data["Exam"]:
        expected = f"EXAM-2026-{int(row['ExamID']):06d}"
        if row["ExamCode"] != expected:
            errors.append(
                f"Exam {row['ExamID']}: expected code {expected}"
            )

    for row in data["Room"]:
        expected = f"ROOM-{int(row['RoomID']):06d}"
        if row["RoomCode"] != expected:
            errors.append(
                f"Room {row['RoomID']}: expected code {expected}"
            )

    for row in data["Invigilator"]:
        expected = f"INV-{int(row['InvigilatorID']):06d}"
        if row["InvigilatorCode"] != expected:
            errors.append(
                f"Invigilator {row['InvigilatorID']}: expected code {expected}"
            )

    # ---------------------------------------------------------
    # 6. Three exams per course
    # ---------------------------------------------------------

    exam_counts = Counter(
        int(row["CourseID"])
        for row in data["Exam"]
    )

    for course_id in course_ids:
        if exam_counts[course_id] != 3:
            errors.append(
                f"Course {course_id}: expected 3 exams, "
                f"found {exam_counts[course_id]}"
            )

    expected_exam_count = (
        config["scale"]["courses"] *
        config["scale"]["exams_per_course"]
    )

    if len(data["Exam"]) != expected_exam_count:
        errors.append(
            f"Expected {expected_exam_count} exams; "
            f"found {len(data['Exam'])}"
        )

    # ---------------------------------------------------------
    # 7. Exactly one sitting for each student-course enrollment
    # ---------------------------------------------------------

    enrollment_lookup = {
        int(row["EnrollmentID"]): row
        for row in data["Enrollment"]
    }

    exam_lookup = {
        int(row["ExamID"]): row
        for row in data["Exam"]
    }

    sitting_counts = Counter()

    for row in data["ExamEnrollment"]:
        enrollment_id = int(row["EnrollmentID"])
        exam_id = int(row["ExamID"])

        enrollment = enrollment_lookup.get(enrollment_id)
        exam = exam_lookup.get(exam_id)

        if enrollment is None or exam is None:
            continue

        sitting_counts[enrollment_id] += 1

        if int(row["CourseID"]) != int(enrollment["CourseID"]):
            errors.append(
                f"ExamEnrollment {row['ExamEnrollmentID']}: "
                "CourseID does not match Enrollment"
            )

        if int(row["CourseID"]) != int(exam["CourseID"]):
            errors.append(
                f"ExamEnrollment {row['ExamEnrollmentID']}: "
                "CourseID does not match Exam"
            )

    for enrollment_id in enrollment_ids:
        if sitting_counts[enrollment_id] != 1:
            errors.append(
                f"Enrollment {enrollment_id}: expected one sitting, "
                f"found {sitting_counts[enrollment_id]}"
            )

    # ---------------------------------------------------------
    # 8. Student course enrollment limits
    # ---------------------------------------------------------

    enrollment_counts = Counter(
        int(row["StudentID"])
        for row in data["Enrollment"]
    )

    for student_id in student_ids:
        count = enrollment_counts[student_id]

        if not 2 <= count <= 4:
            errors.append(
                f"Student {student_id}: expected 2-4 course enrollments, "
                f"found {count}"
            )

    # ---------------------------------------------------------
    # 9. One requirement per exam
    # ---------------------------------------------------------

    requirement_counts = Counter(
        int(row["ExamID"])
        for row in data["ExamRequirement"]
    )

    for exam_id in exam_ids:
        if requirement_counts[exam_id] != 1:
            errors.append(
                f"Exam {exam_id}: expected one requirement record, "
                f"found {requirement_counts[exam_id]}"
            )

    # ---------------------------------------------------------
    # 10. Numeric business constraints
    # ---------------------------------------------------------

    check_positive(
        data["ExamRequirement"],
        "DurationMinutes",
        "ExamRequirement",
        errors,
        maximum=600
    )

    check_positive(
        data["RoomCapacity"],
        "Capacity",
        "RoomCapacity",
        errors
    )

    check_positive(
        data["RoomEquipment"],
        "Quantity",
        "RoomEquipment",
        errors
    )

    check_positive(
        data["Invigilator"],
        "MaxDailyHours",
        "Invigilator",
        errors,
        maximum=24
    )

    check_positive(
        data["Availability"],
        "AvailabilityID",
        "Availability",
        errors
    )

    # ---------------------------------------------------------
    # 11. Accommodation constraints
    # ---------------------------------------------------------

    for index, row in enumerate(data["Accommodation"], start=2):
        accommodation_type = row["AccommodationType"]
        percentage = as_float(
            row.get("ExtensionPercentage"),
            "ExtensionPercentage",
            errors,
            f"Accommodation CSV row {index}"
        )

        separate = as_int(
            row.get("RequiresSeparateRoom"),
            "RequiresSeparateRoom",
            errors,
            f"Accommodation CSV row {index}"
        )

        if accommodation_type == "EXTENDED_TIME":
            if percentage is None or not 0 < percentage <= 200:
                errors.append(
                    f"Accommodation row {index}: "
                    "EXTENDED_TIME requires percentage > 0 and <= 200"
                )
        elif percentage is not None:
            errors.append(
                f"Accommodation row {index}: "
                "non-extended accommodation must have NULL percentage"
            )

        if separate not in (0, 1):
            errors.append(
                f"Accommodation row {index}: "
                "RequiresSeparateRoom must be 0 or 1"
            )

    # ---------------------------------------------------------
    # 12. Date validity
    # ---------------------------------------------------------

    check_date_order(
        data["RoomClosure"],
        "ClosureStart",
        "ClosureEnd",
        "RoomClosure",
        errors
    )

    check_date_order(
        data["Availability"],
        "AvailableFrom",
        "AvailableTo",
        "Availability",
        errors
    )

    # ---------------------------------------------------------
    # 13. GroundTruth integrity
    # ---------------------------------------------------------

    expected_distribution = config["edge_cases"]["distribution"]

    actual_distribution = Counter(
        row["IssueType"]
        for row in data["GroundTruth"]
    )

    if len(data["GroundTruth"]) != config["edge_cases"]["total"]:
        errors.append(
            f"Expected {config['edge_cases']['total']} GroundTruth rows; "
            f"found {len(data['GroundTruth'])}"
        )

    for issue_type, expected_count in expected_distribution.items():
        actual_count = actual_distribution[issue_type]

        if actual_count != expected_count:
            errors.append(
                f"GroundTruth {issue_type}: expected {expected_count}, "
                f"found {actual_count}"
            )

    for row in data["GroundTruth"]:
        entity_type = row["EntityType"]
        entity_code = row["EntityCode"]

        code_sets = {
            "STUDENT": {
                x["StudentCode"] for x in data["Student"]
            },
            "ROOM": {
                x["RoomCode"] for x in data["Room"]
            },
            "INVIGILATOR": {
                x["InvigilatorCode"] for x in data["Invigilator"]
            },
            "EXAM": {
                x["ExamCode"] for x in data["Exam"]
            }
        }

        if entity_type not in code_sets:
            errors.append(
                f"GroundTruth {row['ScenarioCode']}: "
                f"unsupported EntityType {entity_type}"
            )
        elif entity_code not in code_sets[entity_type]:
            errors.append(
                f"GroundTruth {row['ScenarioCode']}: "
                f"EntityCode {entity_code} does not exist"
            )

    # ---------------------------------------------------------
    # 14. Manifest integrity
    # ---------------------------------------------------------

    manifest_path = output_dir / "manifest.json"

    if manifest_path.exists():
        manifest = load_json(manifest_path)

        for table, details in manifest.get("tables", {}).items():
            file_path = output_dir / details["file"]

            if not file_path.exists():
                errors.append(
                    f"Manifest references missing file: {details['file']}"
                )
                continue

            actual_hash = sha256_file(file_path)

            if actual_hash != details["sha256"]:
                errors.append(
                    f"Checksum mismatch for {details['file']}"
                )

            actual_rows = len(data.get(table, []))

            if actual_rows != details["rows"]:
                errors.append(
                    f"Manifest row count mismatch for {table}: "
                    f"{details['rows']} vs {actual_rows}"
                )
    else:
        errors.append("manifest.json is missing")

    return errors


def main() -> int:
    config = load_json(CONFIG_PATH)

    output_dir = ROOT / config["output_directory"]

    print("=" * 65)
    print("EXAM SCHEDULING SYSTEM - INDEPENDENT DATASET VALIDATOR")
    print("Version: 2.0.0")
    print("=" * 65)

    try:
        data = load_dataset(output_dir)
        errors = validate_dataset(data, config, output_dir)

    except Exception as exc:
        print(f"\nVALIDATION COULD NOT COMPLETE: {exc}")
        return 1

    total_rows = sum(len(rows) for rows in data.values())

    print("\nTABLE COUNTS")

    for table, rows in data.items():
        print(f"{table:<22} {len(rows):>10,}")

    print("-" * 65)
    print(f"{'TOTAL':<22} {total_rows:>10,}")

    report = {
        "version": config["version"],
        "seed": config["seed"],
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "total_tables": len(data),
        "total_rows": total_rows,
        "status": "FAILED" if errors else "PASSED",
        "error_count": len(errors),
        "errors": errors
    }

    report_path = output_dir / "independent_validation_report.json"

    report_path.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8"
    )

    print("\nVALIDATION RESULT")

    if errors:
        print(f"FAILED: {len(errors)} issue(s) found.")

        for error in errors[:ERROR_LIMIT]:
            print(f" - {error}")

        if len(errors) > ERROR_LIMIT:
            print(
                f"... {len(errors) - ERROR_LIMIT} additional errors "
                "are recorded in the report."
            )

        print(f"\nReport: {report_path}")
        return 1

    print("PASSED")
    print("Independent CSV, relationship, business-rule and checksum checks passed.")
    print(f"Report: {report_path}")
    print("SQL Server database: NOT MODIFIED")

    return 0


if __name__ == "__main__":
    sys.exit(main())
