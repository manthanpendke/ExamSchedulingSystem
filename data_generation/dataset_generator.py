
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from data_generation.id_generator import IDGenerator
from data_generation.random_context import RandomContext


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "dataset_config.json"
OUTPUT_ROOT = PROJECT_ROOT / "output"

GENERATOR_FORMAT_VERSION = 2

# These values match the current SQL Server ExamCode CHECK constraint.
SCHEMA_ACADEMIC_YEAR = 2026

EXAM_START = datetime(2026, 11, 16, 8, 0)
EXAM_END = datetime(2026, 11, 20, 18, 0)
EFFECTIVE_DATE = date(2026, 1, 1)

DEPARTMENTS = [
    "Computer Science",
    "Electronics",
    "Mechanical",
    "Civil",
    "Electrical",
    "Information Technology",
    "Mathematics",
    "Physics",
]

EQUIPMENT = [
    ("EQP-000001", "Projector", "DISPLAY"),
    ("EQP-000002", "Desktop Computer", "COMPUTING"),
    ("EQP-000003", "Accessible Desk", "ACCESSIBILITY"),
    ("EQP-000004", "Hearing Loop", "ACCESSIBILITY"),
    ("EQP-000005", "Laboratory Kit", "LABORATORY"),
    ("EQP-000006", "External Monitor", "COMPUTING"),
]

# Explicit column definitions allow empty tables to be exported with headers.
TABLE_COLUMNS = {
    "Student": [
        "StudentCode", "FirstName", "LastName", "Email",
        "Department", "Status",
    ],
    "Course": [
        "CourseCode", "CourseName", "Department", "Credits", "Status",
    ],
    "Room": [
        "RoomCode", "Building", "Floor", "RoomType", "IsActive",
    ],
    "Invigilator": [
        "InvigilatorCode", "FullName", "Department",
        "MaxDailyHours", "Status",
    ],
    "Equipment": [
        "EquipmentCode", "EquipmentName", "EquipmentCategory", "IsActive",
    ],
    "Enrollment": [
        "StudentCode", "CourseCode", "EnrollmentDate",
        "EnrollmentStatus", "EffectiveFrom", "EffectiveTo",
    ],
    "Accommodation": [
        "StudentCode", "AccommodationType", "ExtensionPercentage",
        "RequiresSeparateRoom", "EffectiveFrom", "EffectiveTo",
        "AccommodationStatus",
    ],
    "Availability": [
        "InvigilatorCode", "AvailableFrom", "AvailableTo",
        "AvailabilityStatus", "AvailabilityReason",
    ],
    "Exam": [
        "ExamCode", "CourseCode", "ExamName",
        "ExamWindowStart", "ExamWindowEnd", "ExamStatus",
    ],
    "ExamRequirement": [
        "ExamCode", "DurationMinutes", "RequiredEquipment",
        "AccessibilityRequired", "SpecialInstructions",
    ],
    "ExamRequiredEquipment": [
        "ExamCode", "EquipmentCode", "QuantityRequired", "IsMandatory",
    ],
    "ExamEnrollment": [
        "ExamCode", "StudentCode", "CourseCode", "ParticipationStatus",
    ],
    "RoomCapacity": [
        "RoomCode", "Capacity", "EffectiveFrom", "EffectiveTo",
        "CapacityReason",
    ],
    "RoomEquipment": [
        "RoomCode", "EquipmentCode", "Quantity",
        "EffectiveFrom", "EffectiveTo",
    ],
    "RoomClosure": [
        "RoomCode", "ClosureStart", "ClosureEnd",
        "ClosureReason", "ClosureStatus",
    ],
    "GroundTruth": [
        "DatasetVersion", "ScenarioCode", "EntityType", "EntityCode",
        "IssueType", "ExpectedOutcome", "ExpectedReasonCode",
        "Severity", "Description",
    ],
}


# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    required_sections = (
        "dataset",
        "profiles",
        "generation",
        "reproducibility",
    )

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing configuration section: {section}")

    for key in ("name", "version", "random_seed", "academic_year", "output_format"):
        if key not in config["dataset"]:
            raise ValueError(f"Missing dataset configuration: {key}")

    for key in (
        "default_profile",
        "enrollment_min_courses",
        "enrollment_max_courses",
        "anomaly_injection_enabled",
        "ground_truth_separate",
        "validate_before_export",
    ):
        if key not in config["generation"]:
            raise ValueError(f"Missing generation configuration: {key}")

    if not config["generation"]["ground_truth_separate"]:
        raise ValueError(
            "Ground truth must remain separate from baseline scheduling data."
        )

    supported_formats = {"csv", "json", "sql"}
    configured_formats = set(config["dataset"]["output_format"])

    if not configured_formats:
        raise ValueError("At least one output format must be configured.")

    if not configured_formats.issubset(supported_formats):
        raise ValueError(
            f"Unsupported output formats: "
            f"{configured_formats - supported_formats}"
        )

    return config


# ---------------------------------------------------------------------
# SERIALIZATION AND SQL HELPERS
# ---------------------------------------------------------------------

def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    raise TypeError(
        f"Cannot serialize object of type {type(value).__name__}"
    )


def iso_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def sql_literal(value: Any) -> str:
    """
    Convert Python values into safe SQL Server literals.

    String values use the N prefix so Unicode characters are
    preserved when inserted into NVARCHAR columns.
    """
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        return repr(value)

    if isinstance(value, datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"

    if isinstance(value, date):
        return "'" + value.isoformat() + "'"

    escaped = str(value).replace("'", "''")
    return "N'" + escaped + "'"

def sql_insert(
    schema: str,
    table: str,
    columns: list[str],
    expressions: list[str],
) -> str:
    column_sql = ", ".join(f"[{column}]" for column in columns)
    value_sql = ", ".join(expressions)

    return (
        f"INSERT INTO [{schema}].[{table}] "
        f"({column_sql}) VALUES ({value_sql});"
    )


def lookup(
    table: str,
    key_column: str,
    key_value: str,
    id_column: str,
) -> str:
    return (
        f"(SELECT [{id_column}] FROM [dbo].[{table}] "
        f"WHERE [{key_column}] = {sql_literal(key_value)})"
    )


# ---------------------------------------------------------------------
# SQL EXPORT
# ---------------------------------------------------------------------

def generate_sql(data: dict[str, list[dict]]) -> str:
    """
    Generate baseline SQL seed statements.

    Identity columns are deliberately omitted.
    Foreign keys are resolved using unique business codes.
    Ground truth is not included in this SQL file.
    """

    statements = [
        "-- Exam Scheduling Synthetic Dataset",
        "-- BASELINE DATA ONLY",
        "-- Review before execution.",
        "-- Intended for an appropriately prepared target database.",
        "-- This script does not clear existing database records.",
        "SET XACT_ABORT ON;",
        "BEGIN TRANSACTION;",
        "",
    ]

    direct_tables = {
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
    }

    # 1. Master data
    for table, columns in direct_tables.items():
        for row in data[table]:
            statements.append(
                sql_insert(
                    "dbo",
                    table,
                    columns,
                    [sql_literal(row[column]) for column in columns],
                )
            )

        # EquipmentCode is computed by SQL Server from EquipmentID.
    # Never include the computed column in an INSERT statement.
    for row in data["Equipment"]:
        statements.append(
            sql_insert(
                "dbo",
                "Equipment",
                ["EquipmentName", "EquipmentCategory", "IsActive"],
                [
                    sql_literal(row["EquipmentName"]),
                    sql_literal(row["EquipmentCategory"]),
                    sql_literal(row["IsActive"]),
                ],
            )
        )
    
    # 2. Enrollment
    for row in data["Enrollment"]:
        columns = [
            "StudentID",
            "CourseID",
            "EnrollmentDate",
            "EnrollmentStatus",
            "EffectiveFrom",
            "EffectiveTo",
        ]

        expressions = [
            lookup(
                "Student", "StudentCode",
                row["StudentCode"], "StudentID",
            ),
            lookup(
                "Course", "CourseCode",
                row["CourseCode"], "CourseID",
            ),
            sql_literal(row["EnrollmentDate"]),
            sql_literal(row["EnrollmentStatus"]),
            sql_literal(row["EffectiveFrom"]),
            sql_literal(row["EffectiveTo"]),
        ]

        statements.append(
            sql_insert("dbo", "Enrollment", columns, expressions)
        )

    # 3. Accommodation
    for row in data["Accommodation"]:
        columns = [
            "StudentID",
            "AccommodationType",
            "ExtensionPercentage",
            "RequiresSeparateRoom",
            "EffectiveFrom",
            "EffectiveTo",
            "AccommodationStatus",
        ]

        expressions = [
            lookup(
                "Student", "StudentCode",
                row["StudentCode"], "StudentID",
            ),
            sql_literal(row["AccommodationType"]),
            sql_literal(row["ExtensionPercentage"]),
            sql_literal(row["RequiresSeparateRoom"]),
            sql_literal(row["EffectiveFrom"]),
            sql_literal(row["EffectiveTo"]),
            sql_literal(row["AccommodationStatus"]),
        ]

        statements.append(
            sql_insert("dbo", "Accommodation", columns, expressions)
        )

    # 4. Invigilator availability
    for row in data["Availability"]:
        columns = [
            "InvigilatorID",
            "AvailableFrom",
            "AvailableTo",
            "AvailabilityStatus",
            "AvailabilityReason",
        ]

        expressions = [
            lookup(
                "Invigilator", "InvigilatorCode",
                row["InvigilatorCode"], "InvigilatorID",
            ),
            sql_literal(row["AvailableFrom"]),
            sql_literal(row["AvailableTo"]),
            sql_literal(row["AvailabilityStatus"]),
            sql_literal(row["AvailabilityReason"]),
        ]

        statements.append(
            sql_insert("dbo", "Availability", columns, expressions)
        )

    # 5. Exams
    for row in data["Exam"]:
        columns = [
            "ExamCode",
            "CourseID",
            "ExamName",
            "ExamWindowStart",
            "ExamWindowEnd",
            "ExamStatus",
        ]

        expressions = [
            sql_literal(row["ExamCode"]),
            lookup(
                "Course", "CourseCode",
                row["CourseCode"], "CourseID",
            ),
            sql_literal(row["ExamName"]),
            sql_literal(row["ExamWindowStart"]),
            sql_literal(row["ExamWindowEnd"]),
            sql_literal(row["ExamStatus"]),
        ]

        statements.append(
            sql_insert("dbo", "Exam", columns, expressions)
        )

    # 6. Exam requirements
    for row in data["ExamRequirement"]:
        columns = [
            "ExamID",
            "DurationMinutes",
            "RequiredEquipment",
            "AccessibilityRequired",
            "SpecialInstructions",
        ]

        expressions = [
            lookup(
                "Exam", "ExamCode",
                row["ExamCode"], "ExamID",
            ),
            sql_literal(row["DurationMinutes"]),
            sql_literal(row["RequiredEquipment"]),
            sql_literal(row["AccessibilityRequired"]),
            sql_literal(row["SpecialInstructions"]),
        ]

        statements.append(
            sql_insert("dbo", "ExamRequirement", columns, expressions)
        )

    # 7. Normalized exam equipment
    for row in data["ExamRequiredEquipment"]:
        columns = [
            "ExamID",
            "EquipmentID",
            "QuantityRequired",
            "IsMandatory",
        ]

        expressions = [
            lookup(
                "Exam", "ExamCode",
                row["ExamCode"], "ExamID",
            ),
            lookup(
                "Equipment", "EquipmentCode",
                row["EquipmentCode"], "EquipmentID",
            ),
            sql_literal(row["QuantityRequired"]),
            sql_literal(row["IsMandatory"]),
        ]

        statements.append(
            sql_insert(
                "dbo", "ExamRequiredEquipment", columns, expressions
            )
        )

    # 8. Exam enrollment.
    # The same CourseID is used for both composite foreign-key relationships.
    for row in data["ExamEnrollment"]:
        student_lookup = lookup(
            "Student", "StudentCode",
            row["StudentCode"], "StudentID",
        )

        course_lookup = lookup(
            "Course", "CourseCode",
            row["CourseCode"], "CourseID",
        )

        exam_lookup = lookup(
            "Exam", "ExamCode",
            row["ExamCode"], "ExamID",
        )

        enrollment_lookup = (
            "(SELECT e.[EnrollmentID] "
            "FROM [dbo].[Enrollment] AS e "
            f"WHERE e.[StudentID] = {student_lookup} "
            f"AND e.[CourseID] = {course_lookup})"
        )

        columns = [
            "ExamID",
            "EnrollmentID",
            "CourseID",
            "ParticipationStatus",
        ]

        expressions = [
            exam_lookup,
            enrollment_lookup,
            course_lookup,
            sql_literal(row["ParticipationStatus"]),
        ]

        statements.append(
            sql_insert("dbo", "ExamEnrollment", columns, expressions)
        )

    # 9. Room capacity
    for row in data["RoomCapacity"]:
        columns = [
            "RoomID",
            "Capacity",
            "EffectiveFrom",
            "EffectiveTo",
            "CapacityReason",
        ]

        expressions = [
            lookup(
                "Room", "RoomCode",
                row["RoomCode"], "RoomID",
            ),
            sql_literal(row["Capacity"]),
            sql_literal(row["EffectiveFrom"]),
            sql_literal(row["EffectiveTo"]),
            sql_literal(row["CapacityReason"]),
        ]

        statements.append(
            sql_insert("dbo", "RoomCapacity", columns, expressions)
        )

    # 10. Room equipment
    for row in data["RoomEquipment"]:
        columns = [
            "RoomID",
            "EquipmentID",
            "Quantity",
            "EffectiveFrom",
            "EffectiveTo",
        ]

        expressions = [
            lookup(
                "Room", "RoomCode",
                row["RoomCode"], "RoomID",
            ),
            lookup(
                "Equipment", "EquipmentCode",
                row["EquipmentCode"], "EquipmentID",
            ),
            sql_literal(row["Quantity"]),
            sql_literal(row["EffectiveFrom"]),
            sql_literal(row["EffectiveTo"]),
        ]

        statements.append(
            sql_insert("dbo", "RoomEquipment", columns, expressions)
        )

    # 11. Room closures
    for row in data["RoomClosure"]:
        columns = [
            "RoomID",
            "ClosureStart",
            "ClosureEnd",
            "ClosureReason",
            "ClosureStatus",
        ]

        expressions = [
            lookup(
                "Room", "RoomCode",
                row["RoomCode"], "RoomID",
            ),
            sql_literal(row["ClosureStart"]),
            sql_literal(row["ClosureEnd"]),
            sql_literal(row["ClosureReason"]),
            sql_literal(row["ClosureStatus"]),
        ]

        statements.append(
            sql_insert("dbo", "RoomClosure", columns, expressions)
        )

    statements.extend([
        "",
        "COMMIT TRANSACTION;",
        "",
    ])

    return "\n".join(statements)


def generate_ground_truth_sql(rows: list[dict]) -> str:
    """Generate a separate SQL script for evaluation ground truth."""

    statements = [
        "-- Exam Scheduling Synthetic Dataset",
        "-- GROUND TRUTH ONLY",
        "-- Keep separate from baseline scheduling input data.",
        "SET XACT_ABORT ON;",
        "BEGIN TRANSACTION;",
        "",
    ]

    columns = TABLE_COLUMNS["GroundTruth"]

    for row in rows:
        statements.append(
            sql_insert(
                "evaluation",
                "GroundTruth",
                columns,
                [sql_literal(row[column]) for column in columns],
            )
        )

    statements.extend([
        "",
        "COMMIT TRANSACTION;",
        "",
    ])

    return "\n".join(statements)


# ---------------------------------------------------------------------
# DATA GENERATION
# ---------------------------------------------------------------------

def generate_dataset(
    config: dict,
    profile_name: str,
) -> dict[str, list[dict]]:

    if profile_name not in config["profiles"]:
        raise ValueError(f"Unknown dataset profile: {profile_name}")

    profile = config["profiles"][profile_name]
    generation = config["generation"]

    seed = int(config["dataset"]["random_seed"])
    academic_year = int(config["dataset"]["academic_year"])

    if config["reproducibility"].get("fixed_seed_required") and seed <= 0:
        raise ValueError("A positive fixed random seed is required.")

    if academic_year != SCHEMA_ACADEMIC_YEAR:
        raise ValueError(
            f"The current SQL Server ExamCode CHECK constraint requires "
            f"academic year {SCHEMA_ACADEMIC_YEAR}. "
            f"Configured year: {academic_year}"
        )

    if not config["reproducibility"].get("deterministic_ids", False):
        raise ValueError("Deterministic ID generation must be enabled.")

    random_context = RandomContext(seed)
    rng = random_context.python
    fake = random_context.faker

    ids = IDGenerator(academic_year=academic_year)

    student_count = int(profile["students"])
    course_count = int(profile["courses"])
    exam_count = int(profile["exams"])
    room_count = int(profile["rooms"])
    invigilator_count = int(profile["invigilators"])

    counts = {
        "students": student_count,
        "courses": course_count,
        "exams": exam_count,
        "rooms": room_count,
        "invigilators": invigilator_count,
    }

    for name, count in counts.items():
        if count <= 0:
            raise ValueError(f"Profile count must be positive: {name}")

    minimum = int(generation["enrollment_min_courses"])
    maximum = int(generation["enrollment_max_courses"])

    if minimum < 1:
        raise ValueError("Minimum enrollment courses must be at least 1.")

    if maximum < minimum:
        raise ValueError("Maximum enrollment cannot be below minimum.")

    if maximum > course_count:
        raise ValueError(
            "Maximum enrollment cannot exceed the number of courses."
        )

    data: dict[str, list[dict]] = {
        table: []
        for table in TABLE_COLUMNS
    }

    # -------------------------------------------------------------
    # 1. MASTER DATA
    # -------------------------------------------------------------

    for number in range(1, student_count + 1):
        data["Student"].append({
            "StudentCode": ids.student(number),
            "FirstName": fake.first_name(),
            "LastName": fake.last_name(),
            "Email": f"student{number:06d}@exam-synthetic.edu",
            "Department": rng.choice(DEPARTMENTS),
            "Status": "ACTIVE",
        })

    for number in range(1, course_count + 1):
        course_prefix = rng.choice([
            "Applied",
            "Advanced",
            "Introduction to",
            "Fundamentals of",
        ])

        subject = rng.choice([
            "Computing",
            "Electronics",
            "Mathematics",
            "Networks",
            "Systems",
            "Engineering",
        ])

        data["Course"].append({
            "CourseCode": ids.course(number),
            "CourseName": f"{course_prefix} {subject} {number:03d}",
            "Department": rng.choice(DEPARTMENTS),
            "Credits": rng.randint(2, 6),
            "Status": "ACTIVE",
        })

    for number in range(1, room_count + 1):
        if number <= max(1, room_count // 5):
            room_type = "ACCESSIBLE"
        elif number <= max(2, room_count // 2):
            room_type = "LAB"
        else:
            room_type = "STANDARD"

        data["Room"].append({
            "RoomCode": ids.room(number),
            "Building": f"Academic Block {rng.randint(1, 5)}",
            "Floor": rng.randint(0, 5),
            "RoomType": room_type,
            "IsActive": True,
        })

    for number in range(1, invigilator_count + 1):
        data["Invigilator"].append({
            "InvigilatorCode": ids.invigilator(number),
            "FullName": fake.name(),
            "Department": rng.choice(DEPARTMENTS),
            "MaxDailyHours": float(rng.choice([4, 5, 6, 7, 8])),
            "Status": "ACTIVE",
        })

    for equipment_code, equipment_name, category in EQUIPMENT:
        data["Equipment"].append({
            "EquipmentCode": equipment_code,
            "EquipmentName": equipment_name,
            "EquipmentCategory": category,
            "IsActive": True,
        })

    # -------------------------------------------------------------
    # 2. STUDENT COURSE ENROLLMENT
    # -------------------------------------------------------------

    for student in data["Student"]:
        course_total = rng.randint(minimum, maximum)

        selected_courses = rng.sample(
            data["Course"],
            course_total,
        )

        for course in sorted(
            selected_courses,
            key=lambda item: item["CourseCode"],
        ):
            data["Enrollment"].append({
                "StudentCode": student["StudentCode"],
                "CourseCode": course["CourseCode"],
                "EnrollmentDate": date(2026, 1, 5),
                "EnrollmentStatus": "ENROLLED",
                "EffectiveFrom": date(2026, 1, 5),
                "EffectiveTo": None,
            })

    data["Enrollment"].sort(
        key=lambda row: (
            row["StudentCode"],
            row["CourseCode"],
        )
    )

    # -------------------------------------------------------------
    # 3. STUDENT ACCOMMODATIONS
    # -------------------------------------------------------------

    accommodation_types = [
        "EXTENDED_TIME",
        "ACCESSIBLE_ROOM",
        "SEPARATE_ROOM",
    ]

    for student in data["Student"]:
        if rng.random() < 0.10:
            accommodation_type = rng.choice(accommodation_types)

            data["Accommodation"].append({
                "StudentCode": student["StudentCode"],
                "AccommodationType": accommodation_type,
                "ExtensionPercentage": (
                    rng.choice([25, 50, 100])
                    if accommodation_type == "EXTENDED_TIME"
                    else None
                ),
                "RequiresSeparateRoom": (
                    accommodation_type == "SEPARATE_ROOM"
                ),
                "EffectiveFrom": date(2026, 1, 1),
                "EffectiveTo": None,
                "AccommodationStatus": "ACTIVE",
            })

    # -------------------------------------------------------------
    # 4. EXAMS AND REQUIREMENTS
    # -------------------------------------------------------------

    course_exam_codes: dict[str, list[str]] = defaultdict(list)

    for number in range(1, exam_count + 1):
        # Supports 300 exams across 100 courses.
        # Multiple exam sittings for a course are separate exam records.
        course = data["Course"][(number - 1) % course_count]
        course_code = course["CourseCode"]

        exam_code = ids.exam(number)
        sitting_number = len(course_exam_codes[course_code]) + 1

        course_exam_codes[course_code].append(exam_code)

        duration = rng.choice([
            60,
            90,
            120,
            150,
            180,
        ])

        required_items = []

        if rng.random() < 0.30:
            required_items.append(("EQP-000001", 1, True))

        if rng.random() < 0.15:
            required_items.append(("EQP-000005", 1, True))

        required_json = [
            {
                "equipment_code": code,
                "quantity_required": quantity,
                "is_mandatory": mandatory,
            }
            for code, quantity, mandatory in required_items
        ]

        data["Exam"].append({
            "ExamCode": exam_code,
            "CourseCode": course_code,
            "ExamName": (
                f"{course['CourseName']} Examination "
                f"- Sitting {sitting_number}"
            ),
            "ExamWindowStart": EXAM_START,
            "ExamWindowEnd": EXAM_END,
            "ExamStatus": "READY",
        })

        data["ExamRequirement"].append({
            "ExamCode": exam_code,
            "DurationMinutes": duration,
            "RequiredEquipment": json.dumps(
                required_json,
                sort_keys=True,
            ),
            "AccessibilityRequired": False,
            "SpecialInstructions": None,
        })

        for equipment_code, quantity, mandatory in required_items:
            data["ExamRequiredEquipment"].append({
                "ExamCode": exam_code,
                "EquipmentCode": equipment_code,
                "QuantityRequired": quantity,
                "IsMandatory": mandatory,
            })

    # -------------------------------------------------------------
    # 5. EXAM ENROLLMENT
    # -------------------------------------------------------------

    # Students enrolled in a course are distributed deterministically
    # across that course's exam sittings.
    for enrollment in data["Enrollment"]:
        course_code = enrollment["CourseCode"]
        exam_codes = course_exam_codes.get(course_code, [])

        if not exam_codes:
            continue

        student_number = int(
            enrollment["StudentCode"].split("-")[-1]
        )

        sitting_index = (student_number - 1) % len(exam_codes)
        selected_exam = exam_codes[sitting_index]

        data["ExamEnrollment"].append({
            "ExamCode": selected_exam,
            "StudentCode": enrollment["StudentCode"],
            "CourseCode": course_code,
            "ParticipationStatus": "REGISTERED",
        })

    data["ExamEnrollment"].sort(
        key=lambda row: (
            row["ExamCode"],
            row["StudentCode"],
        )
    )

    # -------------------------------------------------------------
    # 6. ROOM CAPACITY AND EQUIPMENT
    # -------------------------------------------------------------

    for room in data["Room"]:
        data["RoomCapacity"].append({
            "RoomCode": room["RoomCode"],
            "Capacity": rng.randint(25, 60),
            "EffectiveFrom": EFFECTIVE_DATE,
            "EffectiveTo": None,
            "CapacityReason": "Baseline synthetic capacity",
        })

        for equipment_code, _, _ in EQUIPMENT:
            if equipment_code == "EQP-000001":
                include = True
            elif equipment_code == "EQP-000003":
                include = room["RoomType"] == "ACCESSIBLE"
            elif equipment_code == "EQP-000005":
                include = room["RoomType"] == "LAB"
            else:
                include = rng.random() < 0.35

            if include:
                data["RoomEquipment"].append({
                    "RoomCode": room["RoomCode"],
                    "EquipmentCode": equipment_code,
                    "Quantity": rng.randint(1, 5),
                    "EffectiveFrom": EFFECTIVE_DATE,
                    "EffectiveTo": None,
                })

    # -------------------------------------------------------------
    # 7. INVIGILATOR AVAILABILITY
    # -------------------------------------------------------------

    for invigilator in data["Invigilator"]:
        for day_offset in range(5):
            current_day = EXAM_START.date() + timedelta(
                days=day_offset
            )

            available_from = datetime.combine(
                current_day,
                time(8, 0),
            )

            available_to = datetime.combine(
                current_day,
                time(18, 0),
            )

            is_available = rng.random() >= 0.10

            data["Availability"].append({
                "InvigilatorCode": invigilator["InvigilatorCode"],
                "AvailableFrom": available_from,
                "AvailableTo": available_to,
                "AvailabilityStatus": (
                    "AVAILABLE" if is_available else "UNAVAILABLE"
                ),
                "AvailabilityReason": (
                    None if is_available
                    else "Synthetic unavailability"
                ),
            })

    # -------------------------------------------------------------
    # 8. ROOM CLOSURES
    # -------------------------------------------------------------

    # The first room always receives a closure.
    # Other rooms receive closures probabilistically.
    # All closures are outside the baseline exam window.
    for index, room in enumerate(data["Room"]):
        if index == 0 or rng.random() < 0.10:
            closure_start = datetime(2026, 12, 1, 8, 0)

            data["RoomClosure"].append({
                "RoomCode": room["RoomCode"],
                "ClosureStart": closure_start,
                "ClosureEnd": closure_start + timedelta(hours=8),
                "ClosureReason": "Synthetic maintenance closure",
                "ClosureStatus": "ACTIVE",
            })

    # -------------------------------------------------------------
    # 9. SEPARATE NEGATIVE-SCENARIO GROUND TRUTH
    # -------------------------------------------------------------

        # -------------------------------------------------------------
    # 9. SEPARATE NEGATIVE-SCENARIO GROUND TRUTH
    # -------------------------------------------------------------

    if generation["anomaly_injection_enabled"]:
        first_student = data["Student"][0]["StudentCode"]
        first_room = data["Room"][0]["RoomCode"]
        first_invigilator = data["Invigilator"][0]["InvigilatorCode"]

        # Select a student who actually has an active accommodation.
        accommodated_students = sorted({
            row["StudentCode"]
            for row in data["Accommodation"]
            if row["AccommodationStatus"] == "ACTIVE"
        })

        if not accommodated_students:
            raise ValueError(
                "Cannot create NEG_ACCOMMODATION_IGNORED: "
                "no student has an active accommodation."
            )

        accommodation_student = accommodated_students[0]

        scenarios = [
            (
                "NEG_STUDENT_OVERLAP",
                "STUDENT",
                first_student,
                "STUDENT_CONFLICT",
                "REJECT",
                "STUDENT_CONFLICT",
                "HIGH",
                "Student is assigned overlapping examinations.",
            ),
            (
                "NEG_ROOM_CAPACITY",
                "ROOM",
                first_room,
                "ROOM_CAPACITY_EXCEEDED",
                "REJECT",
                "NO_ROOM_CAPACITY",
                "CRITICAL",
                "Assigned students exceed room capacity.",
            ),
            (
                "NEG_INVIGILATOR_DOUBLE_BOOKING",
                "INVIGILATOR",
                first_invigilator,
                "INVIGILATOR_DOUBLE_BOOKED",
                "REJECT",
                "NO_INVIGILATOR",
                "HIGH",
                "Invigilator is assigned to overlapping examinations.",
            ),
            (
                "NEG_ACCOMMODATION_IGNORED",
                "STUDENT",
                accommodation_student,
                "ACCOMMODATION_IGNORED",
                "FLAG",
                "ACCOMMODATION_CONFLICT",
                "HIGH",
                "Student accommodation requirements are not respected.",
            ),
            (
                "NEG_ROOM_CLOSED",
                "ROOM",
                first_room,
                "EXAM_OUTSIDE_ROOM_AVAILABILITY",
                "REJECT",
                "ROOM_CLOSED",
                "CRITICAL",
                "Exam is assigned during a room closure.",
            ),
        ]

        for (
            scenario_code,
            entity_type,
            entity_code,
            issue_type,
            outcome,
            reason_code,
            severity,
            description,
        ) in scenarios:
            data["GroundTruth"].append({
                "DatasetVersion": config["dataset"]["version"],
                "ScenarioCode": scenario_code,
                "EntityType": entity_type,
                "EntityCode": entity_code,
                "IssueType": issue_type,
                "ExpectedOutcome": outcome,
                "ExpectedReasonCode": reason_code,
                "Severity": severity,
                "Description": description,
            })
            
    return data


# ---------------------------------------------------------------------
# DATA VALIDATION
# ---------------------------------------------------------------------

def validate_dataset(
    data: dict[str, list[dict]],
    config: dict,
    profile_name: str,
) -> None:
    """Validate baseline data and separate ground truth."""

    profile = config["profiles"][profile_name]
    generation = config["generation"]

    def require_unique(
        table: str,
        fields: tuple[str, ...],
    ) -> None:
        seen = set()

        for row in data[table]:
            key = tuple(row[field] for field in fields)

            if key in seen:
                raise ValueError(
                    f"Duplicate key in {table}: {fields} = {key}"
                )

            seen.add(key)

    def require_reference(
        value: str,
        valid_values: set[str],
        description: str,
    ) -> None:
        if value not in valid_values:
            raise ValueError(
                f"Invalid reference in {description}: {value}"
            )

    # 1. Exact profile counts
    expected_counts = {
        "Student": int(profile["students"]),
        "Course": int(profile["courses"]),
        "Room": int(profile["rooms"]),
        "Invigilator": int(profile["invigilators"]),
        "Exam": int(profile["exams"]),
    }

    for table, expected in expected_counts.items():
        actual = len(data[table])

        if actual != expected:
            raise ValueError(
                f"{table} count mismatch: expected {expected}, got {actual}"
            )

    # 2. Unique business keys
    unique_definitions = {
        "Student": [("StudentCode",), ("Email",)],
        "Course": [("CourseCode",)],
        "Room": [("RoomCode",)],
        "Invigilator": [("InvigilatorCode",)],
        "Equipment": [("EquipmentCode",)],
        "Exam": [("ExamCode",)],
        "Enrollment": [("StudentCode", "CourseCode")],
        "ExamRequirement": [("ExamCode",)],
        "ExamEnrollment": [("ExamCode", "StudentCode")],
        "RoomCapacity": [("RoomCode", "EffectiveFrom")],
        "RoomEquipment": [
            ("RoomCode", "EquipmentCode", "EffectiveFrom")
        ],
        "GroundTruth": [
            ("DatasetVersion", "ScenarioCode")
        ],
    }

    for table, definitions in unique_definitions.items():
        for fields in definitions:
            require_unique(table, fields)

    # 3. Master reference sets
    students = {
        row["StudentCode"] for row in data["Student"]
    }

    courses = {
        row["CourseCode"] for row in data["Course"]
    }

    rooms = {
        row["RoomCode"] for row in data["Room"]
    }

    invigilators = {
        row["InvigilatorCode"] for row in data["Invigilator"]
    }

    equipment = {
        row["EquipmentCode"] for row in data["Equipment"]
    }

    exams = {
        row["ExamCode"] for row in data["Exam"]
    }

    # 4. Master data CHECK constraints
    for row in data["Student"]:
        if row["Status"] not in {"ACTIVE", "INACTIVE", "GRADUATED"}:
            raise ValueError("Invalid student status.")

    for row in data["Course"]:
        if not 1 <= row["Credits"] <= 10:
            raise ValueError("Course credits violate database CHECK.")

        if row["Status"] not in {"ACTIVE", "INACTIVE"}:
            raise ValueError("Invalid course status.")

    for row in data["Room"]:
        if row["RoomType"] not in {
            "ACCESSIBLE", "LAB", "STANDARD"
        }:
            raise ValueError("Invalid room type.")

        if row["Floor"] < 0:
            raise ValueError("Room floor cannot be negative.")

    for row in data["Invigilator"]:
        if not 0 < row["MaxDailyHours"] <= 24:
            raise ValueError("Invalid invigilator daily hours.")

        if row["Status"] not in {"ACTIVE", "INACTIVE"}:
            raise ValueError("Invalid invigilator status.")

    # 5. Enrollment validation
    enrollment_pairs = set()
    student_enrollment_counts = defaultdict(int)

    for row in data["Enrollment"]:
        require_reference(
            row["StudentCode"], students, "Enrollment.StudentCode"
        )

        require_reference(
            row["CourseCode"], courses, "Enrollment.CourseCode"
        )

        if row["EnrollmentStatus"] not in {
            "ENROLLED", "COMPLETED", "DROPPED"
        }:
            raise ValueError("Invalid enrollment status.")

        if (
            row["EffectiveTo"] is not None
            and row["EffectiveTo"] < row["EffectiveFrom"]
        ):
            raise ValueError("Invalid enrollment effective dates.")

        pair = (row["StudentCode"], row["CourseCode"])

        if pair in enrollment_pairs:
            raise ValueError("Duplicate student-course enrollment.")

        enrollment_pairs.add(pair)
        student_enrollment_counts[row["StudentCode"]] += 1

    minimum = int(generation["enrollment_min_courses"])
    maximum = int(generation["enrollment_max_courses"])

    for student_code in students:
        count = student_enrollment_counts[student_code]

        if not minimum <= count <= maximum:
            raise ValueError(
                f"Enrollment count outside configured range for "
                f"{student_code}: {count}"
            )

    # 6. Accommodation validation
    allowed_accommodations = {
        "SPECIAL_EQUIPMENT",
        "SEPARATE_ROOM",
        "ACCESSIBLE_ROOM",
        "EXTENDED_TIME",
    }

    for row in data["Accommodation"]:
        require_reference(
            row["StudentCode"], students, "Accommodation.StudentCode"
        )

        if row["AccommodationType"] not in allowed_accommodations:
            raise ValueError("Invalid accommodation type.")

        if row["AccommodationStatus"] not in {
            "ACTIVE", "EXPIRED", "REVOKED"
        }:
            raise ValueError("Invalid accommodation status.")

        if (
            row["EffectiveTo"] is not None
            and row["EffectiveTo"] < row["EffectiveFrom"]
        ):
            raise ValueError("Invalid accommodation effective dates.")

        if row["AccommodationType"] == "EXTENDED_TIME":
            percentage = row["ExtensionPercentage"]

            if percentage is None or not 0 < percentage <= 200:
                raise ValueError("Invalid extended-time percentage.")
        elif row["ExtensionPercentage"] is not None:
            raise ValueError(
                "Non-extended accommodation has an extension percentage."
            )

        if (
            row["AccommodationType"] == "SEPARATE_ROOM"
            and not row["RequiresSeparateRoom"]
        ):
            raise ValueError(
                "SEPARATE_ROOM accommodation must require a separate room."
            )

    # 7. Exam validation
    exam_course_by_code = {}
    exam_counts_by_course = defaultdict(int)

    for row in data["Exam"]:
        require_reference(
            row["CourseCode"], courses, "Exam.CourseCode"
        )

        if row["ExamWindowEnd"] <= row["ExamWindowStart"]:
            raise ValueError("Invalid exam window.")

        if row["ExamStatus"] not in {
            "DRAFT", "READY", "SCHEDULED", "CANCELLED"
        }:
            raise ValueError("Invalid exam status.")

        expected_prefix = f"EXAM-{SCHEMA_ACADEMIC_YEAR}-"

        if not row["ExamCode"].startswith(expected_prefix):
            raise ValueError("Exam code violates database CHECK.")

        exam_course_by_code[row["ExamCode"]] = row["CourseCode"]
        exam_counts_by_course[row["CourseCode"]] += 1

    # 8. Exam requirement validation
    requirements_by_exam = {}

    for row in data["ExamRequirement"]:
        require_reference(
            row["ExamCode"], exams, "ExamRequirement.ExamCode"
        )

        if not 15 <= row["DurationMinutes"] <= 600:
            raise ValueError("Exam duration violates database CHECK.")

        required_json = json.loads(row["RequiredEquipment"])

        if not isinstance(required_json, list):
            raise ValueError("RequiredEquipment JSON must be a list.")

        requirements_by_exam[row["ExamCode"]] = required_json

    if len(requirements_by_exam) != len(exams):
        raise ValueError("Every exam must have exactly one requirement.")

    # 9. Normalized exam equipment consistency
    normalized_equipment = set()

    for row in data["ExamRequiredEquipment"]:
        require_reference(
            row["ExamCode"], exams, "ExamRequiredEquipment.ExamCode"
        )

        require_reference(
            row["EquipmentCode"], equipment,
            "ExamRequiredEquipment.EquipmentCode",
        )

        if row["QuantityRequired"] <= 0:
            raise ValueError("Required equipment quantity must be positive.")

        normalized_equipment.add((
            row["ExamCode"],
            row["EquipmentCode"],
            row["QuantityRequired"],
            row["IsMandatory"],
        ))

    json_equipment = set()

    for exam_code, items in requirements_by_exam.items():
        for item in items:
            equipment_code = item["equipment_code"]

            require_reference(
                equipment_code, equipment,
                "ExamRequirement.RequiredEquipment",
            )

            quantity = int(item["quantity_required"])
            mandatory = bool(item["is_mandatory"])

            json_equipment.add((
                exam_code,
                equipment_code,
                quantity,
                mandatory,
            ))

    if normalized_equipment != json_equipment:
        raise ValueError(
            "ExamRequirement JSON and ExamRequiredEquipment "
            "records are inconsistent."
        )

    # 10. Exam enrollment and composite relationship validation
    exam_enrollment_counts = defaultdict(int)

    for row in data["ExamEnrollment"]:
        require_reference(
            row["ExamCode"], exams, "ExamEnrollment.ExamCode"
        )

        require_reference(
            row["StudentCode"], students, "ExamEnrollment.StudentCode"
        )

        require_reference(
            row["CourseCode"], courses, "ExamEnrollment.CourseCode"
        )

        if (
            row["StudentCode"],
            row["CourseCode"],
        ) not in enrollment_pairs:
            raise ValueError(
                "ExamEnrollment does not match an Enrollment record."
            )

        if exam_course_by_code[row["ExamCode"]] != row["CourseCode"]:
            raise ValueError(
                "ExamEnrollment.CourseCode does not match Exam.CourseID."
            )

        if row["ParticipationStatus"] not in {
            "EXEMPT", "WITHDRAWN", "REGISTERED"
        }:
            raise ValueError("Invalid exam participation status.")

        exam_enrollment_counts[row["ExamCode"]] += 1

    for exam_code in exams:
        if exam_enrollment_counts[exam_code] == 0:
            raise ValueError(
                f"Exam has no registered students: {exam_code}"
            )

    # 11. Availability validation
    for row in data["Availability"]:
        require_reference(
            row["InvigilatorCode"], invigilators,
            "Availability.InvigilatorCode",
        )

        if row["AvailabilityStatus"] not in {
            "AVAILABLE", "UNAVAILABLE"
        }:
            raise ValueError("Invalid availability status.")

        if row["AvailableTo"] <= row["AvailableFrom"]:
            raise ValueError("Invalid availability interval.")

    # 12. Room capacity validation
    for row in data["RoomCapacity"]:
        require_reference(
            row["RoomCode"], rooms, "RoomCapacity.RoomCode"
        )

        if row["Capacity"] <= 0:
            raise ValueError("Room capacity must be positive.")

        if (
            row["EffectiveTo"] is not None
            and row["EffectiveTo"] < row["EffectiveFrom"]
        ):
            raise ValueError("Invalid room capacity effective dates.")

    if len(data["RoomCapacity"]) != len(rooms):
        raise ValueError("Every room must have one capacity record.")

    # 13. Room equipment validation
    for row in data["RoomEquipment"]:
        require_reference(
            row["RoomCode"], rooms, "RoomEquipment.RoomCode"
        )

        require_reference(
            row["EquipmentCode"], equipment,
            "RoomEquipment.EquipmentCode",
        )

        if row["Quantity"] <= 0:
            raise ValueError("Room equipment quantity must be positive.")

        if (
            row["EffectiveTo"] is not None
            and row["EffectiveTo"] < row["EffectiveFrom"]
        ):
            raise ValueError("Invalid room equipment effective dates.")

    # 14. Room closure validation
    if not data["RoomClosure"]:
        raise ValueError(
            "At least one room closure is required for availability testing."
        )

    for row in data["RoomClosure"]:
        require_reference(
            row["RoomCode"], rooms, "RoomClosure.RoomCode"
        )

        if row["ClosureStatus"] not in {
            "COMPLETED", "CANCELLED", "ACTIVE"
        }:
            raise ValueError("Invalid room closure status.")

        if row["ClosureEnd"] <= row["ClosureStart"]:
            raise ValueError("Invalid room closure interval.")

        overlaps_exam_window = (
            row["ClosureStart"] < EXAM_END
            and row["ClosureEnd"] > EXAM_START
        )

        if overlaps_exam_window:
            raise ValueError(
                "Baseline room closure overlaps the exam window."
            )

    # 15. Ground-truth validation
    allowed_outcomes = {
        "FLAG", "UNASSIGNED", "REJECT", "ACCEPT"
    }

    allowed_reasons = {
        "OTHER",
        "INVALID_REQUIREMENT",
        "NO_ELIGIBLE_STUDENTS",
        "NO_VALID_TIMESLOT",
        "ACCOMMODATION_CONFLICT",
        "STUDENT_CONFLICT",
        "NO_INVIGILATOR",
        "ROOM_CLOSED",
        "NO_EQUIPMENT",
        "NO_ROOM_CAPACITY",
    }

    allowed_severities = {
        "CRITICAL", "HIGH", "MEDIUM", "LOW"
    }

    for row in data["GroundTruth"]:
        if row["ExpectedOutcome"] not in allowed_outcomes:
            raise ValueError("Invalid ground-truth expected outcome.")

        if row["ExpectedReasonCode"] not in allowed_reasons:
            raise ValueError("Invalid ground-truth reason code.")

        if row["Severity"] not in allowed_severities:
            raise ValueError("Invalid ground-truth severity.")

    if (
        data["GroundTruth"]
        and not generation["ground_truth_separate"]
    ):
        raise ValueError("Ground truth must remain separate.")

    if (
        generation["anomaly_injection_enabled"]
        and len(data["GroundTruth"]) != 5
    ):
        raise ValueError(
            "Expected five labelled negative-scenario ground-truth records."
        )
        
        # 16. Ground-truth entity reference validation

    accommodation_scenarios = [
        row for row in data["GroundTruth"]
        if row["ScenarioCode"] == "NEG_ACCOMMODATION_IGNORED"
    ]

    if generation["anomaly_injection_enabled"]:
        if len(accommodation_scenarios) != 1:
            raise ValueError(
                "Expected exactly one accommodation negative scenario."
            )

        accommodation_target = (
            accommodation_scenarios[0]["EntityCode"]
        )

        active_accommodation_students = {
            row["StudentCode"]
            for row in data["Accommodation"]
            if row["AccommodationStatus"] == "ACTIVE"
        }

        if accommodation_target not in active_accommodation_students:
            raise ValueError(
                "NEG_ACCOMMODATION_IGNORED must reference a student "
                "with an active accommodation."
            )

    # Validate that every ground-truth entity exists.
    entity_maps = {
        "STUDENT": students,
        "ROOM": rooms,
        "INVIGILATOR": invigilators,
        "EXAM": exams,
    }

    for row in data["GroundTruth"]:
        entity_type = row["EntityType"]

        if entity_type not in entity_maps:
            raise ValueError(
                f"Invalid ground-truth entity type: {entity_type}"
            )

        if row["EntityCode"] not in entity_maps[entity_type]:
            raise ValueError(
                f"Ground-truth entity does not exist: "
                f"{entity_type} {row['EntityCode']}"
            )


# ---------------------------------------------------------------------
# CSV AND JSON EXPORT
# ---------------------------------------------------------------------

def write_csv_files(
    data: dict[str, list[dict]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for table, rows in data.items():
        columns = TABLE_COLUMNS[table]
        path = output_dir / f"{table}.csv"

        with path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=columns,
                extrasaction="raise",
            )

            writer.writeheader()

            for row in rows:
                writer.writerow({
                    key: iso_value(value)
                    for key, value in row.items()
                })


def write_json_files(
    data: dict[str, list[dict]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for table, rows in data.items():
        path = output_dir / f"{table}.json"

        with path.open("w", encoding="utf-8") as file:
            json.dump(
                rows,
                file,
                indent=2,
                ensure_ascii=False,
                default=json_default,
                sort_keys=True,
            )

            file.write("\n")


# ---------------------------------------------------------------------
# SQL EXPORT
# ---------------------------------------------------------------------

def write_sql_file(
    data: dict[str, list[dict]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    sql = generate_sql(data)

    (output_dir / "seed_dataset.sql").write_text(
        sql,
        encoding="utf-8",
    )


def write_ground_truth_sql_file(
    rows: list[dict],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    sql = generate_ground_truth_sql(rows)

    (output_dir / "ground_truth.sql").write_text(
        sql,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------
# REPRODUCIBILITY AND MANIFEST
# ---------------------------------------------------------------------

def calculate_checksums(output_dir: Path) -> dict[str, str]:
    checksums = {}

    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue

        if path.name == "manifest.json":
            continue

        relative_path = str(path.relative_to(output_dir)).replace("\\", "/")

        checksums[relative_path] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    return checksums


def load_previous_manifest(output_dir: Path) -> dict | None:
    path = output_dir / "manifest.json"

    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def compare_previous_checksums(
    previous_manifest: dict | None,
    current_checksums: dict[str, str],
    comparison_enabled: bool,
) -> str:

    if not comparison_enabled:
        return "DISABLED"

    if previous_manifest is None:
        return "NO_PREVIOUS_MANIFEST"

    if previous_manifest.get("generator_format_version") != GENERATOR_FORMAT_VERSION:
        return "NOT_COMPARABLE_LEGACY_MANIFEST"

    previous_checksums = previous_manifest.get("checksums_sha256")

    if not isinstance(previous_checksums, dict):
        return "NO_PREVIOUS_CHECKSUMS"

    if previous_checksums == current_checksums:
        return "MATCH"

    return "DIFFERENT"


def write_manifest(
    output_dir: Path,
    config: dict,
    profile_name: str,
    data: dict[str, list[dict]],
    previous_manifest: dict | None,
) -> str:

    checksums = calculate_checksums(output_dir)

    comparison = compare_previous_checksums(
        previous_manifest,
        checksums,
        bool(config["reproducibility"].get("compare_checksums", False)),
    )

    baseline_counts = {
        table: len(rows)
        for table, rows in data.items()
        if table != "GroundTruth"
    }

    manifest = {
        "generator_format_version": GENERATOR_FORMAT_VERSION,
        "dataset_name": config["dataset"]["name"],
        "dataset_version": config["dataset"]["version"],
        "profile": profile_name,
        "random_seed": config["dataset"]["random_seed"],
        "academic_year": config["dataset"]["academic_year"],
        "output_formats": sorted(config["dataset"]["output_format"]),
        "baseline_record_counts": baseline_counts,
        "ground_truth_record_count": len(data["GroundTruth"]),
        "checksums_sha256": checksums,
        "reproducibility": {
            "deterministic_ids": True,
            "fixed_seed": True,
            "previous_run_comparison": comparison,
        },
        "identity_policy": (
            "SQL Server identity columns are omitted from generated seed data."
        ),
        "ground_truth_policy": (
            "Ground truth is exported separately and is not mixed into "
            "baseline scheduling inputs."
        ),
        "sql_execution_policy": (
            "Generated SQL is for review and controlled execution only. "
            "The generator does not execute SQL against the database."
        ),
    }

    manifest_path = output_dir / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    return comparison


# ---------------------------------------------------------------------
# OUTPUT CLEANUP
# ---------------------------------------------------------------------

def remove_legacy_ground_truth_files(output_dir: Path) -> None:
    """
    Remove only the two legacy GroundTruth exports created by the
    previous generator, which placed them beside baseline CSV/JSON files.
    """

    legacy_files = [
        output_dir / "csv" / "GroundTruth.csv",
        output_dir / "json" / "GroundTruth.json",
    ]

    for path in legacy_files:
        if path.exists() and path.is_file():
            path.unlink()


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def main() -> None:
    config = load_config()

    profile_name = config["generation"]["default_profile"]

    output_dir = (
        OUTPUT_ROOT
        / profile_name
        / f"v{config['dataset']['version']}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    previous_manifest = load_previous_manifest(output_dir)

    print("=" * 60)
    print("EXAM SCHEDULING SYNTHETIC DATA GENERATOR")
    print("=" * 60)
    print(f"Profile: {profile_name}")
    print(f"Seed: {config['dataset']['random_seed']}")
    print(f"Academic year: {config['dataset']['academic_year']}")

    data = generate_dataset(config, profile_name)

    baseline_data = {
        table: rows
        for table, rows in data.items()
        if table != "GroundTruth"
    }

    ground_truth_data = {
        "GroundTruth": data["GroundTruth"]
    }

    print("\n[1/6] Validating generated records...")

    if config["generation"]["validate_before_export"]:
        validate_dataset(data, config, profile_name)
        print("Baseline and ground-truth validation: PASS")
    else:
        print("Validation skipped by configuration.")

    formats = set(config["dataset"]["output_format"])

    remove_legacy_ground_truth_files(output_dir)

    print("\n[2/6] Exporting baseline CSV...")

    if "csv" in formats:
        write_csv_files(
            baseline_data,
            output_dir / "csv",
        )
        print("Baseline CSV export: PASS")

    print("\n[3/6] Exporting baseline JSON...")

    if "json" in formats:
        write_json_files(
            baseline_data,
            output_dir / "json",
        )
        print("Baseline JSON export: PASS")

    print("\n[4/6] Exporting baseline SQL...")

    if "sql" in formats:
        write_sql_file(
            baseline_data,
            output_dir / "sql",
        )
        print("Baseline SQL export: PASS")

    print("\n[5/6] Exporting separate ground truth...")

    if "csv" in formats:
        write_csv_files(
            ground_truth_data,
            output_dir / "ground_truth" / "csv",
        )

    if "json" in formats:
        write_json_files(
            ground_truth_data,
            output_dir / "ground_truth" / "json",
        )

    if "sql" in formats:
        write_ground_truth_sql_file(
            data["GroundTruth"],
            output_dir / "ground_truth" / "sql",
        )

    print("Separate ground-truth export: PASS")

    print("\n[6/6] Writing manifest and checksums...")

    if config["reproducibility"].get("compare_checksums", False):
        comparison = write_manifest(
            output_dir,
            config,
            profile_name,
            data,
            previous_manifest,
        )

        print("Manifest and checksums: PASS")
        print(f"Previous run checksum comparison: {comparison}")
    else:
        write_manifest(
            output_dir,
            config,
            profile_name,
            data,
            previous_manifest,
        )
        print("Manifest generated; checksum comparison disabled.")

    print("\nBASELINE RECORD COUNTS")

    for table, rows in baseline_data.items():
        print(f"{table:25} {len(rows):>8}")

    print(f"{'GroundTruth (separate)':25} {len(data['GroundTruth']):>8}")

    print("\nOUTPUT STRUCTURE")
    print(output_dir)
    print("  csv/")
    print("  json/")
    print("  sql/")
    print("  ground_truth/csv/")
    print("  ground_truth/json/")
    print("  ground_truth/sql/")
    print("  manifest.json")

    print("\n" + "=" * 60)
    print("DATASET GENERATION COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
