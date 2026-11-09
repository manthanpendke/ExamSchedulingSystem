
from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sys

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


# ============================================================
# PATHS AND CONSTANTS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v220.json"

FIRST_NAMES = [
    "Aarav", "Vihaan", "Aditya", "Arjun", "Ishaan",
    "Ananya", "Aadhya", "Diya", "Myra", "Sara",
    "Rohan", "Karan", "Neha", "Priya", "Rahul",
    "Ira", "Kabir", "Saanvi", "Reyansh", "Meera",
]

LAST_NAMES = [
    "Sharma", "Patil", "Kulkarni", "Deshmukh", "Joshi",
    "Mehta", "Shah", "Pawar", "Gupta", "Verma",
    "Kadam", "More", "Jadhav", "Mishra", "Rao",
]

DEPARTMENTS = [
    "Computer Science",
    "Electronics",
    "Mechanical Engineering",
    "Information Technology",
    "Civil Engineering",
]

EQUIPMENT_DEFINITIONS = [
    ("Desktop Computer", "COMPUTING"),
    ("Projector", "VISUAL"),
    ("Laboratory Kit", "LABORATORY"),
    ("Accessible Desk", "ACCESSIBILITY"),
    ("Audio Equipment", "AUDIO"),
    ("Network Equipment", "NETWORK"),
]

CREATED_AT = "2026-01-01 09:00:00"
ENROLLMENT_DATE = "2026-01-10"
EXAM_CREATED_AT = "2026-01-15 09:00:00"


# ============================================================
# CONFIGURATION
# ============================================================

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    validate_config(config)
    return config


def validate_config(config):
    if config["project"]["version"] != "2.2.0":
        raise ValueError("This generator only supports v2.2.0.")

    dataset = config["dataset"]
    track = config["track_rules"]
    calendar = config["calendar"]
    infrastructure = config["physical_infrastructure"]

    if dataset["students"] != 5000:
        raise ValueError("Expected exactly 5000 students.")

    if dataset["tracks"] != 75:
        raise ValueError("Expected exactly 75 tracks.")

    if dataset["courses"] != 300:
        raise ValueError("Expected exactly 300 courses.")

    if dataset["compulsory_courses"] != 225:
        raise ValueError("Expected exactly 225 compulsory courses.")

    if dataset["optional_courses"] != 75:
        raise ValueError("Expected exactly 75 optional courses.")

    if dataset["total_enrollments"] != 20000:
        raise ValueError("Expected exactly 20000 enrollments.")

    if dataset["total_exam_sittings"] != 900:
        raise ValueError("Expected exactly 900 exam sittings.")

    distribution = track["balanced_distribution"]

    expected_students = (
        distribution["tracks_with_67_students"] * 67
        + distribution["tracks_with_66_students"] * 66
    )

    expected_tracks = (
        distribution["tracks_with_67_students"]
        + distribution["tracks_with_66_students"]
    )

    if expected_students != dataset["students"]:
        raise ValueError("Track distribution does not total 5000.")

    if expected_tracks != dataset["tracks"]:
        raise ValueError("Track distribution does not total 75.")

    if calendar["number_of_days"] * calendar["slots_per_day"] != 36:
        raise ValueError("The timetable must contain exactly 36 slots.")

    physical = (
        infrastructure["rooms"]
        * infrastructure["days"]
        * infrastructure["slots_per_day"]
    )

    if physical != infrastructure["total_room_slot_units"]:
        raise ValueError("Physical grid dimensions are inconsistent.")


# ============================================================
# CSV AND FILE HELPERS
# ============================================================

def write_csv(path: Path, rows: list[dict], columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(path)


def sha256_file(path: Path):
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def iso_datetime(value: datetime):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def output_path(config):
    return ROOT / config["paths"]["output_root"]


# ============================================================
# TRACK GENERATION
# ============================================================

def generate_tracks(config):
    count = config["dataset"]["tracks"]
    distribution = config["track_rules"]["balanced_distribution"]

    student_counts = (
        [67] * distribution["tracks_with_67_students"]
        + [66] * distribution["tracks_with_66_students"]
    )

    if len(student_counts) != count:
        raise ValueError("Invalid track distribution.")

    tracks = []

    for track_id, student_count in enumerate(student_counts, start=1):
        tracks.append({
            "TrackID": track_id,
            "TrackCode": f"TRK-{track_id:03d}",
            "TrackName": f"Academic Track {track_id:03d}",
            "ExpectedStudentCount": student_count,
            "CompulsoryCourseCount": 3,
        })

    track_courses = []
    course_roles = {}

    for track in tracks:
        track_id = track["TrackID"]

        for sequence in range(1, 4):
            course_id = ((track_id - 1) * 3) + sequence

            track_courses.append({
                "TrackID": track_id,
                "CourseID": course_id,
                "CourseRole": "COMPULSORY",
                "CourseSequence": sequence,
            })

            course_roles[course_id] = "COMPULSORY"

    optional_pool = []

    for course_id in range(226, 301):
        optional_pool.append({
            "CourseID": course_id,
            "CourseRole": "OPTIONAL",
        })
        course_roles[course_id] = "OPTIONAL"

    return tracks, track_courses, optional_pool, course_roles


# ============================================================
# STUDENT GENERATION
# SQL Student table-compatible columns
# ============================================================

def generate_students(count, rng):
    students = []

    for student_id in range(1, count + 1):
        department = DEPARTMENTS[(student_id - 1) % len(DEPARTMENTS)]

        students.append({
            "StudentID": student_id,
            "StudentCode": f"STU-{student_id:06d}",
            "FirstName": rng.choice(FIRST_NAMES),
            "LastName": rng.choice(LAST_NAMES),
            "Email": f"student{student_id:06d}@university.edu",
            "Department": department,
            "Status": "ACTIVE",
            "CreatedAt": CREATED_AT,
        })

    return students


def assign_students_to_tracks(students, tracks):
    assignments = []
    student_track_lookup = {}

    student_position = 0

    for track in tracks:
        track_id = track["TrackID"]
        expected_count = track["ExpectedStudentCount"]

        for _ in range(expected_count):
            student = students[student_position]
            student_id = student["StudentID"]

            primary_course_id = ((track_id - 1) * 3) + 1

            assignments.append({
                "StudentID": student_id,
                "TrackID": track_id,
                "PrimaryCourseID": primary_course_id,
            })

            student_track_lookup[student_id] = {
                "TrackID": track_id,
                "TrackRank": _,
                "PrimaryCourseID": primary_course_id,
            }

            student_position += 1

    if student_position != len(students):
        raise ValueError("Not every student was assigned to a track.")

    return assignments, student_track_lookup


# ============================================================
# COURSE GENERATION
# SQL Course table-compatible columns
# ============================================================

def generate_courses(count, course_roles):
    courses = []

    for course_id in range(1, count + 1):
        department = DEPARTMENTS[(course_id - 1) % len(DEPARTMENTS)]
        role = course_roles[course_id]

        courses.append({
            "CourseID": course_id,
            "CourseCode": f"CRS-{course_id:04d}",
            "CourseName": (
                f"{department} "
                f"{'Core' if role == 'COMPULSORY' else 'Elective'} "
                f"Course {course_id:03d}"
            ),
            "Department": department,
            "Credits": 3 + (course_id % 3),
            "Status": "ACTIVE",
            "CreatedAt": CREATED_AT,
        })

    return courses


# ============================================================
# ENROLLMENT GENERATION
# Exactly 3 compulsory + 1 optional per student
# ============================================================

def generate_enrollments(
    students,
    student_track_lookup,
    track_courses,
    optional_pool,
):
    compulsory_by_track = defaultdict(list)

    for row in track_courses:
        compulsory_by_track[row["TrackID"]].append(row)

    optional_course_ids = [
        row["CourseID"] for row in optional_pool
    ]

    enrollments = []
    classifications = []
    enrollment_id = 1

    for student in students:
        student_id = student["StudentID"]
        track_info = student_track_lookup[student_id]
        track_id = track_info["TrackID"]

        compulsory = sorted(
            compulsory_by_track[track_id],
            key=lambda x: x["CourseSequence"],
        )

        if len(compulsory) != 3:
            raise ValueError(
                f"Track {track_id} does not have exactly 3 compulsory courses."
            )

        # The optional pool is global. Round-robin assignment ensures
        # optional courses are distributed as evenly as possible.
        optional_index = (student_id - 1) % len(optional_course_ids)
        optional_course_id = optional_course_ids[optional_index]

        selected = []

        for item in compulsory:
            selected.append({
                "CourseID": item["CourseID"],
                "EnrollmentType": "COMPULSORY",
                "CourseSequence": item["CourseSequence"],
            })

        selected.append({
            "CourseID": optional_course_id,
            "EnrollmentType": "OPTIONAL",
            "CourseSequence": 4,
        })

        if len({x["CourseID"] for x in selected}) != 4:
            raise ValueError(
                f"Student {student_id} has duplicate course enrollment."
            )

        for item in selected:
            course_id = item["CourseID"]

            enrollments.append({
                "EnrollmentID": enrollment_id,
                "StudentID": student_id,
                "CourseID": course_id,
                "EnrollmentDate": ENROLLMENT_DATE,
                "EnrollmentStatus": "ENROLLED",
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
                "CreatedAt": "2026-01-10 09:00:00",
            })

            classifications.append({
                "EnrollmentID": enrollment_id,
                "StudentID": student_id,
                "CourseID": course_id,
                "EnrollmentType": item["EnrollmentType"],
                "TrackID": track_id,
                "CourseSequence": item["CourseSequence"],
            })

            enrollment_id += 1

    return enrollments, classifications


# ============================================================
# EXAM GENERATION
# ============================================================

def generate_exams(courses, config):
    exams = []
    requirements = []
    normalized_equipment = []

    exam_id = 1
    requirement_id = 1
    equipment_requirement_id = 1

    calendar = config["calendar"]
    start_date = date.fromisoformat(calendar["start_date"])
    final_date = start_date + timedelta(
        days=calendar["number_of_days"] - 1
    )

    window_start = datetime.combine(
        start_date,
        datetime.strptime("08:00", "%H:%M").time(),
    )

    window_end = datetime.combine(
        final_date,
        datetime.strptime("17:00", "%H:%M").time(),
    )

    for course in courses:
        course_id = course["CourseID"]

        # Requirements are deterministic and synchronized between
        # ExamRequirement JSON and ExamRequiredEquipment rows.
        required_equipment_id = None

        if course_id % 15 == 0:
            required_equipment_id = 3  # LAB_KIT
        elif course_id % 10 == 0:
            required_equipment_id = 1  # COMPUTER
        elif course_id % 11 == 0:
            required_equipment_id = 5  # AUDIO

        for sitting in range(1, 4):
            current_exam_id = exam_id

            exams.append({
                "ExamID": current_exam_id,
                "ExamCode": f"EXAM-2026-{current_exam_id:06d}",
                "CourseID": course_id,
                "ExamName": (
                    f"{course['CourseName']} - Sitting {sitting}"
                ),
                "ExamWindowStart": iso_datetime(window_start),
                "ExamWindowEnd": iso_datetime(window_end),
                "ExamStatus": "READY",
                "CreatedAt": EXAM_CREATED_AT,
            })

            if required_equipment_id is None:
                equipment_json = ""
            else:
                equipment_json = json.dumps(
                    [{
                        "EquipmentID": required_equipment_id,
                        "QuantityRequired": 1,
                        "IsMandatory": True,
                    }],
                    separators=(",", ":"),
                )

                normalized_equipment.append({
                    "ExamRequiredEquipmentID": equipment_requirement_id,
                    "ExamID": current_exam_id,
                    "EquipmentID": required_equipment_id,
                    "QuantityRequired": 1,
                    "IsMandatory": 1,
                })

                equipment_requirement_id += 1

            requirements.append({
                "RequirementID": requirement_id,
                "ExamID": current_exam_id,
                "DurationMinutes": 90,
                "RequiredEquipment": equipment_json,
                "AccessibilityRequired": 0,
                "SpecialInstructions": "",
                "CreatedAt": EXAM_CREATED_AT,
            })

            exam_id += 1
            requirement_id += 1

    return exams, requirements, normalized_equipment


# ============================================================
# EXAM ENROLLMENT AND SITTING ALLOCATION
# ============================================================

def generate_exam_enrollments(
    enrollments,
    classifications,
    student_track_lookup,
):
    exam_enrollments = []
    sitting_allocations = []

    exam_enrollment_id = 1

    for enrollment, classification in zip(
        enrollments,
        classifications,
    ):
        student_id = enrollment["StudentID"]
        course_id = enrollment["CourseID"]

        track_info = student_track_lookup[student_id]
        track_id = track_info["TrackID"]
        rank = track_info["TrackRank"]

        if classification["EnrollmentType"] == "COMPULSORY":
            sequence = classification["CourseSequence"]

            # For the three compulsory courses, each student receives
            # three distinct sitting ordinals.
            sitting_ordinal = ((rank + sequence - 1) % 3) + 1

        else:
            # Optional sitting is distributed deterministically.
            # Actual calendar conflict resolution is performed later
            # by the timetable scheduler.
            sitting_ordinal = ((student_id + track_id) % 3) + 1

        exam_id = ((course_id - 1) * 3) + sitting_ordinal

        exam_enrollments.append({
            "ExamEnrollmentID": exam_enrollment_id,
            "ExamID": exam_id,
            "EnrollmentID": enrollment["EnrollmentID"],
            "CourseID": course_id,
            "ParticipationStatus": "REGISTERED",
            "RegisteredAt": "2026-01-15 09:00:00",
        })

        sitting_allocations.append({
            "EnrollmentID": enrollment["EnrollmentID"],
            "StudentID": student_id,
            "CourseID": course_id,
            "ExamID": exam_id,
            "SittingOrdinal": sitting_ordinal,
            "EnrollmentType": classification["EnrollmentType"],
            "TrackID": track_id,
        })

        exam_enrollment_id += 1

    return exam_enrollments, sitting_allocations


# ============================================================
# ROOM GENERATION
# ============================================================

def generate_rooms(count):
    rooms = []
    capacities = []

    capacity_options = [30, 40, 50, 60, 80, 100]

    for room_id in range(1, count + 1):
        if room_id % 10 == 0:
            room_type = "ACCESSIBLE"
        elif room_id % 5 == 0:
            room_type = "LAB"
        else:
            room_type = "STANDARD"

        rooms.append({
            "RoomID": room_id,
            "RoomCode": f"ROOM-{room_id:06d}",
            "Building": f"Building {(room_id - 1) // 20 + 1}",
            "Floor": (room_id - 1) % 4,
            "RoomType": room_type,
            "IsActive": 1,
            "CreatedAt": CREATED_AT,
        })

        capacities.append({
            "RoomCapacityID": room_id,
            "RoomID": room_id,
            "Capacity": capacity_options[
                (room_id - 1) % len(capacity_options)
            ],
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": "",
            "CapacityReason": "Initial capacity",
            "CreatedAt": CREATED_AT,
        })

    return rooms, capacities


# ============================================================
# EQUIPMENT AND ROOM EQUIPMENT
# EquipmentCode is computed in SQL and is intentionally omitted.
# ============================================================

def generate_equipment():
    rows = []

    for equipment_id, (name, category) in enumerate(
        EQUIPMENT_DEFINITIONS,
        start=1,
    ):
        rows.append({
            "EquipmentID": equipment_id,
            "EquipmentName": name,
            "EquipmentCategory": category,
            "IsActive": 1,
            "CreatedAt": CREATED_AT,
        })

    return rows


def generate_room_equipment(rooms):
    rows = []
    row_id = 1

    for room in rooms:
        room_id = room["RoomID"]

        # Common baseline equipment.
        rows.append({
            "RoomEquipmentID": row_id,
            "RoomID": room_id,
            "EquipmentID": 2,
            "Quantity": 1,
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": "",
        })
        row_id += 1

        if room["RoomType"] == "LAB":
            rows.append({
                "RoomEquipmentID": row_id,
                "RoomID": room_id,
                "EquipmentID": 3,
                "Quantity": 100,
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            })
            row_id += 1

        if room["RoomType"] == "ACCESSIBLE":
            rows.append({
                "RoomEquipmentID": row_id,
                "RoomID": room_id,
                "EquipmentID": 4,
                "Quantity": 20,
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            })
            row_id += 1

        # Computer rooms are distributed across the infrastructure.
        if room_id % 4 == 0:
            rows.append({
                "RoomEquipmentID": row_id,
                "RoomID": room_id,
                "EquipmentID": 1,
                "Quantity": 100,
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            })
            row_id += 1

        # Audio equipment in a subset of rooms.
        if room_id % 7 == 0:
            rows.append({
                "RoomEquipmentID": row_id,
                "RoomID": room_id,
                "EquipmentID": 5,
                "Quantity": 1,
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": "",
            })
            row_id += 1

    return rows


# ============================================================
# INVIGILATORS AND AVAILABILITY
# ============================================================

def generate_invigilators(count):
    rows = []

    for invigilator_id in range(1, count + 1):
        rows.append({
            "InvigilatorID": invigilator_id,
            "InvigilatorCode": f"INV-{invigilator_id:06d}",
            "FullName": f"Invigilator {invigilator_id:03d}",
            "Department": DEPARTMENTS[
                (invigilator_id - 1) % len(DEPARTMENTS)
            ],
            "MaxDailyHours": 6,
            "Status": "ACTIVE",
            "CreatedAt": CREATED_AT,
        })

    return rows


def generate_availability(invigilators, count, config):
    rows = []

    dates = [
        date.fromisoformat(x)
        for x in config["calendar"]["days"]
    ]

    # Build five availability days per invigilator, skipping one
    # deterministic day per person. This creates exactly 1000 rows
    # for 200 invigilators.
    for invigilator in invigilators:
        invigilator_id = invigilator["InvigilatorID"]
        unavailable_day = (invigilator_id - 1) % len(dates)

        for day_index, exam_date in enumerate(dates):
            if day_index == unavailable_day:
                continue

            if len(rows) >= count:
                break

            start = datetime.combine(
                exam_date,
                datetime.strptime("08:00", "%H:%M").time(),
            )

            end = datetime.combine(
                exam_date,
                datetime.strptime("18:00", "%H:%M").time(),
            )

            rows.append({
                "AvailabilityID": len(rows) + 1,
                "InvigilatorID": invigilator_id,
                "AvailableFrom": iso_datetime(start),
                "AvailableTo": iso_datetime(end),
                "AvailabilityStatus": "AVAILABLE",
                "AvailabilityReason": "Baseline availability",
                "CreatedAt": CREATED_AT,
            })

    if len(rows) != count:
        raise ValueError(
            f"Expected {count} availability rows, generated {len(rows)}."
        )

    return rows


# ============================================================
# STUDENT ACCOMMODATIONS
# ============================================================

def generate_accommodations(students, count):
    accommodation_types = [
        "EXTENDED_TIME",
        "SPECIAL_EQUIPMENT",
        "SEPARATE_ROOM",
        "ACCESSIBLE_ROOM",
    ]

    rows = []

    for accommodation_id in range(1, count + 1):
        student = students[(accommodation_id - 1) % len(students)]

        accommodation_type = accommodation_types[
            (accommodation_id - 1) % len(accommodation_types)
        ]

        extension = (
            33.33
            if accommodation_type == "EXTENDED_TIME"
            else ""
        )

        rows.append({
            "AccommodationID": accommodation_id,
            "StudentID": student["StudentID"],
            "AccommodationType": accommodation_type,
            "ExtensionPercentage": extension,
            "RequiresSeparateRoom": (
                1 if accommodation_type == "SEPARATE_ROOM" else 0
            ),
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": "",
            "AccommodationStatus": "ACTIVE",
            "CreatedAt": CREATED_AT,
        })

    return rows


# ============================================================
# ROOM CLOSURES
# ============================================================

def generate_closures(rooms, count, config):
    rows = []

    first_date = date.fromisoformat(config["calendar"]["start_date"])

    for closure_id in range(1, count + 1):
        room = rooms[(closure_id - 1) % len(rooms)]

        closure_date = first_date + timedelta(
            days=(closure_id - 1) % config["calendar"]["number_of_days"]
        )

        start = datetime.combine(
            closure_date,
            datetime.strptime("12:30", "%H:%M").time(),
        )

        end = start + timedelta(hours=2)

        rows.append({
            "RoomClosureID": closure_id,
            "RoomID": room["RoomID"],
            "ClosureStart": iso_datetime(start),
            "ClosureEnd": iso_datetime(end),
            "ClosureReason": "Planned maintenance",
            "ClosureStatus": "ACTIVE",
            "CreatedAt": CREATED_AT,
        })

    return rows


# ============================================================
# GROUND TRUTH LABELS
# These are evaluation labels, not executable fixtures.
# Executable fixtures will be implemented in the test milestone.
# ============================================================

def generate_ground_truth(config, students, rooms, invigilators, exams):
    distribution = config["edge_case_fixtures"]["distribution"]

    categories = [
        (
            "student_overlap",
            "STUDENT",
            students,
            "STUDENT_CONFLICT",
            "REJECT",
            "HIGH",
            "Student overlap benchmark scenario.",
        ),
        (
            "room_capacity_boundary",
            "ROOM",
            rooms,
            "NO_ROOM_CAPACITY",
            "REJECT",
            "HIGH",
            "Room capacity boundary benchmark scenario.",
        ),
        (
            "invigilator_conflicts",
            "INVIGILATOR",
            invigilators,
            "NO_INVIGILATOR",
            "REJECT",
            "HIGH",
            "Invigilator conflict benchmark scenario.",
        ),
        (
            "extended_time",
            "STUDENT",
            students,
            "ACCOMMODATION_CONFLICT",
            "FLAG",
            "MEDIUM",
            "Extended-time accommodation benchmark scenario.",
        ),
        (
            "room_closure",
            "ROOM",
            rooms,
            "ROOM_CLOSED",
            "REJECT",
            "HIGH",
            "Room closure benchmark scenario.",
        ),
        (
            "equipment_changeover",
            "EXAM",
            exams,
            "NO_EQUIPMENT",
            "REJECT",
            "HIGH",
            "Equipment reservation and changeover benchmark scenario.",
        ),
    ]

    rows = []
    scenario_number = 1

    for category, entity_type, entities, reason, outcome, severity, description in categories:
        number_to_create = distribution[category]

        for index in range(number_to_create):
            entity = entities[index % len(entities)]

            if entity_type == "STUDENT":
                entity_code = entity["StudentCode"]
            elif entity_type == "ROOM":
                entity_code = entity["RoomCode"]
            elif entity_type == "INVIGILATOR":
                entity_code = entity["InvigilatorCode"]
            else:
                entity_code = entity["ExamCode"]

            rows.append({
                "DatasetVersion": "2.2.0",
                "ScenarioCode": f"V220-{scenario_number:03d}",
                "EntityType": entity_type,
                "EntityCode": entity_code,
                "IssueType": reason,
                "ExpectedOutcome": outcome,
                "ExpectedReasonCode": reason,
                "Severity": severity,
                "Description": description,
            })

            scenario_number += 1

    if len(rows) != config["edge_case_fixtures"]["total"]:
        raise ValueError("GroundTruth count is not exactly 150.")

    return rows


# ============================================================
# DATASET VALIDATION
# ============================================================

def validate_generated_data(data, metadata, config):
    errors = []

    students = data["Student"]
    courses = data["Course"]
    enrollments = data["Enrollment"]
    exams = data["Exam"]
    exam_enrollments = data["ExamEnrollment"]
    tracks = metadata["Track"]
    track_courses = metadata["TrackCourse"]
    student_tracks = metadata["StudentTrack"]
    classifications = metadata["EnrollmentClassification"]
    sitting_allocations = metadata["SittingAllocation"]

    expected_counts = {
        "Student": 5000,
        "Course": 300,
        "Enrollment": 20000,
        "Exam": 900,
        "ExamEnrollment": 20000,
        "Track": 75,
        "TrackCourse": 225,
        "StudentTrack": 5000,
        "EnrollmentClassification": 20000,
        "SittingAllocation": 20000,
        "GroundTruth": 150,
    }

    for table_name, expected in expected_counts.items():
        actual = len(
            data[table_name]
            if table_name in data
            else metadata[table_name]
        )

        if actual != expected:
            errors.append(
                f"{table_name}: expected {expected}, found {actual}."
            )

    if len({x["StudentID"] for x in students}) != 5000:
        errors.append("Student IDs are not unique.")

    if len({x["CourseID"] for x in courses}) != 300:
        errors.append("Course IDs are not unique.")

    if len({x["EnrollmentID"] for x in enrollments}) != 20000:
        errors.append("Enrollment IDs are not unique.")

    if len({x["ExamID"] for x in exams}) != 900:
        errors.append("Exam IDs are not unique.")

    # Validate track sizes.
    track_sizes = Counter(
        x["TrackID"] for x in student_tracks
    )

    expected_track_sizes = Counter(
        {x["TrackID"]: x["ExpectedStudentCount"] for x in tracks}
    )

    if track_sizes != expected_track_sizes:
        errors.append("Student track distribution is incorrect.")

    # Every track must have three unique compulsory courses.
    courses_by_track = defaultdict(list)

    for row in track_courses:
        courses_by_track[row["TrackID"]].append(row["CourseID"])

    for track in tracks:
        assigned = courses_by_track[track["TrackID"]]

        if len(assigned) != 3 or len(set(assigned)) != 3:
            errors.append(
                f"Track {track['TrackID']} does not have 3 unique courses."
            )

    # Compulsory courses must be unique across all tracks.
    compulsory_course_ids = [
        row["CourseID"] for row in track_courses
    ]

    if len(compulsory_course_ids) != len(set(compulsory_course_ids)):
        errors.append("A compulsory course is assigned to multiple tracks.")

    if set(compulsory_course_ids) != set(range(1, 226)):
        errors.append("Compulsory course IDs must be 1 through 225.")

    optional_course_ids = {
        row["CourseID"] for row in metadata["OptionalCoursePool"]
    }

    if optional_course_ids != set(range(226, 301)):
        errors.append("Optional course IDs must be 226 through 300.")

    # Exactly four enrollments per student:
    # three compulsory and one optional.
    enrollment_counts = Counter(
        row["StudentID"] for row in enrollments
    )

    classification_by_enrollment = {
        row["EnrollmentID"]: row
        for row in classifications
    }

    for student in students:
        student_id = student["StudentID"]

        if enrollment_counts[student_id] != 4:
            errors.append(
                f"Student {student_id} does not have exactly 4 enrollments."
            )

        student_rows = [
            row for row in enrollments
            if row["StudentID"] == student_id
        ]

        types = [
            classification_by_enrollment[row["EnrollmentID"]]["EnrollmentType"]
            for row in student_rows
        ]

        if types.count("COMPULSORY") != 3:
            errors.append(
                f"Student {student_id} does not have 3 compulsory courses."
            )

        if types.count("OPTIONAL") != 1:
            errors.append(
                f"Student {student_id} does not have 1 optional course."
            )

    # Exactly three exams per course.
    exam_counts = Counter(
        row["CourseID"] for row in exams
    )

    for course_id in range(1, 301):
        if exam_counts[course_id] != 3:
            errors.append(
                f"Course {course_id} does not have exactly 3 exams."
            )

    # Each enrollment must map to exactly one exam sitting.
    exam_enrollment_counts = Counter(
        row["EnrollmentID"] for row in exam_enrollments
    )

    for enrollment in enrollments:
        if exam_enrollment_counts[enrollment["EnrollmentID"]] != 1:
            errors.append(
                f"Enrollment {enrollment['EnrollmentID']} "
                "does not map to exactly one exam."
            )

    exam_by_id = {
        row["ExamID"]: row for row in exams
    }

    for row in exam_enrollments:
        exam = exam_by_id.get(row["ExamID"])

        if exam is None:
            errors.append(
                f"ExamEnrollment {row['ExamEnrollmentID']} "
                "references an unknown exam."
            )
        elif exam["CourseID"] != row["CourseID"]:
            errors.append(
                f"ExamEnrollment {row['ExamEnrollmentID']} "
                "has a course mismatch."
            )

    # Every course's three sittings must have distinct exam IDs.
    sitting_by_course = defaultdict(set)

    for row in sitting_allocations:
        sitting_by_course[row["CourseID"]].add(row["ExamID"])

    for course_id in range(1, 301):
        if len(sitting_by_course[course_id]) != 3:
            errors.append(
                f"Course {course_id} does not have 3 distinct exam sittings."
            )

    # Validate compulsory sitting ordinal rotation:
    # each student's three compulsory courses receive three distinct ordinals.
    allocations_by_student = defaultdict(list)

    for row in sitting_allocations:
        if row["EnrollmentType"] == "COMPULSORY":
            allocations_by_student[row["StudentID"]].append(
                row["SittingOrdinal"]
            )

    for student_id, ordinals in allocations_by_student.items():
        if len(ordinals) != 3 or len(set(ordinals)) != 3:
            errors.append(
                f"Student {student_id} compulsory sitting ordinals "
                "are not distinct."
            )

    # Validate normalized equipment and JSON synchronization.
    requirement_by_exam = {
        row["ExamID"]: row
        for row in data["ExamRequirement"]
    }

    normalized_by_exam = defaultdict(list)

    for row in data["ExamRequiredEquipment"]:
        normalized_by_exam[row["ExamID"]].append({
            "EquipmentID": row["EquipmentID"],
            "QuantityRequired": row["QuantityRequired"],
            "IsMandatory": bool(row["IsMandatory"]),
        })

    for exam_id, requirement in requirement_by_exam.items():
        json_value = requirement["RequiredEquipment"]

        if not json_value:
            if normalized_by_exam[exam_id]:
                errors.append(
                    f"Exam {exam_id}: normalized equipment exists "
                    "but JSON is empty."
                )
            continue

        try:
            parsed = json.loads(json_value)
        except json.JSONDecodeError:
            errors.append(
                f"Exam {exam_id}: RequiredEquipment is invalid JSON."
            )
            continue

        if parsed != normalized_by_exam[exam_id]:
            errors.append(
                f"Exam {exam_id}: JSON and normalized equipment differ."
            )

    # Validate room-slot grid dimensions.
    physical = config["physical_infrastructure"]

    expected_units = (
        physical["rooms"]
        * physical["days"]
        * physical["slots_per_day"]
    )

    if expected_units != 3600:
        errors.append("Physical grid is not 3600 units.")

    return errors


# ============================================================
# OUTPUT SCHEMAS
# Only actual SQL columns are used for operational tables.
# Computed/identity columns are omitted.
# ============================================================

SQL_SCHEMAS = {
    "Student": [
        "StudentID", "StudentCode", "FirstName", "LastName",
        "Email", "Department", "Status", "CreatedAt",
    ],
    "Course": [
        "CourseID", "CourseCode", "CourseName", "Department",
        "Credits", "Status", "CreatedAt",
    ],
    "Enrollment": [
        "EnrollmentID", "StudentID", "CourseID", "EnrollmentDate",
        "EnrollmentStatus", "EffectiveFrom", "EffectiveTo", "CreatedAt",
    ],
    "Exam": [
        "ExamID", "ExamCode", "CourseID", "ExamName",
        "ExamWindowStart", "ExamWindowEnd", "ExamStatus", "CreatedAt",
    ],
    "ExamEnrollment": [
        "ExamEnrollmentID", "ExamID", "EnrollmentID", "CourseID",
        "ParticipationStatus", "RegisteredAt",
    ],
    "ExamRequirement": [
        "RequirementID", "ExamID", "DurationMinutes",
        "RequiredEquipment", "AccessibilityRequired",
        "SpecialInstructions", "CreatedAt",
    ],
    "ExamRequiredEquipment": [
        "ExamRequiredEquipmentID", "ExamID", "EquipmentID",
        "QuantityRequired", "IsMandatory",
    ],
    "Room": [
        "RoomID", "RoomCode", "Building", "Floor",
        "RoomType", "IsActive", "CreatedAt",
    ],
    "RoomCapacity": [
        "RoomCapacityID", "RoomID", "Capacity", "EffectiveFrom",
        "EffectiveTo", "CapacityReason", "CreatedAt",
    ],
    "RoomClosure": [
        "RoomClosureID", "RoomID", "ClosureStart", "ClosureEnd",
        "ClosureReason", "ClosureStatus", "CreatedAt",
    ],
    "Equipment": [
        "EquipmentID", "EquipmentName", "EquipmentCategory",
        "IsActive", "CreatedAt",
    ],
    "RoomEquipment": [
        "RoomEquipmentID", "RoomID", "EquipmentID",
        "Quantity", "EffectiveFrom", "EffectiveTo",
    ],
    "Invigilator": [
        "InvigilatorID", "InvigilatorCode", "FullName",
        "Department", "MaxDailyHours", "Status", "CreatedAt",
    ],
    "Availability": [
        "AvailabilityID", "InvigilatorID", "AvailableFrom",
        "AvailableTo", "AvailabilityStatus",
        "AvailabilityReason", "CreatedAt",
    ],
    "Accommodation": [
        "AccommodationID", "StudentID", "AccommodationType",
        "ExtensionPercentage", "RequiresSeparateRoom",
        "EffectiveFrom", "EffectiveTo", "AccommodationStatus",
        "CreatedAt",
    ],
    "GroundTruth": [
        "DatasetVersion", "ScenarioCode", "EntityType", "EntityCode",
        "IssueType", "ExpectedOutcome", "ExpectedReasonCode",
        "Severity", "Description",
    ],
}

METADATA_SCHEMAS = {
    "Track": [
        "TrackID", "TrackCode", "TrackName",
        "ExpectedStudentCount", "CompulsoryCourseCount",
    ],
    "TrackCourse": [
        "TrackID", "CourseID", "CourseRole", "CourseSequence",
    ],
    "StudentTrack": [
        "StudentID", "TrackID", "PrimaryCourseID",
    ],
    "OptionalCoursePool": [
        "CourseID", "CourseRole",
    ],
    "EnrollmentClassification": [
        "EnrollmentID", "StudentID", "CourseID",
        "EnrollmentType", "TrackID", "CourseSequence",
    ],
    "SittingAllocation": [
        "EnrollmentID", "StudentID", "CourseID", "ExamID",
        "SittingOrdinal", "EnrollmentType", "TrackID",
    ],
}


# ============================================================
# MAIN
# ============================================================

def main():
    config = load_config()
    rng = random.Random(config["project"]["random_seed"])

    target = output_path(config)
    target.mkdir(parents=True, exist_ok=True)

    dataset_config = config["dataset"]

    print("=" * 72)
    print("EXAM SCHEDULING SYSTEM — DATA GENERATOR V2.2.0")
    print("=" * 72)

    print("\n[1/12] Generating tracks...")
    tracks, track_courses, optional_pool, course_roles = generate_tracks(config)

    print("[2/12] Generating students...")
    students = generate_students(dataset_config["students"], rng)

    print("[3/12] Assigning students to tracks...")
    student_tracks, student_track_lookup = assign_students_to_tracks(
        students,
        tracks,
    )

    print("[4/12] Generating courses...")
    courses = generate_courses(
        dataset_config["courses"],
        course_roles,
    )

    print("[5/12] Generating enrollments...")
    enrollments, classifications = generate_enrollments(
        students,
        student_track_lookup,
        track_courses,
        optional_pool,
    )

    print("[6/12] Generating exams and requirements...")
    exams, requirements, normalized_equipment = generate_exams(
        courses,
        config,
    )

    print("[7/12] Generating exam enrollment and sitting allocation...")
    exam_enrollments, sitting_allocations = generate_exam_enrollments(
        enrollments,
        classifications,
        student_track_lookup,
    )

    print("[8/12] Generating rooms and equipment...")
    rooms, capacities = generate_rooms(
        config["physical_infrastructure"]["rooms"]
    )
    equipment = generate_equipment()
    room_equipment = generate_room_equipment(rooms)

    print("[9/12] Generating invigilators and availability...")
    invigilators = generate_invigilators(
        config["resources"]["invigilators"]
        if "invigilators" in config["resources"]
        else config["physical_infrastructure"].get("invigilators", 200)
    )

    # The configured project currently specifies 200 invigilators.
    if len(invigilators) != 200:
        invigilators = generate_invigilators(200)

    availability = generate_availability(
        invigilators,
        config["resources"]["invigilator_availability_records"],
        config,
    )

    print("[10/12] Generating accommodations and closures...")
    accommodations = generate_accommodations(
        students,
        config["resources"]["accommodations"],
    )

    closures = generate_closures(
        rooms,
        config["resources"]["room_closures"],
        config,
    )

    print("[11/12] Generating GroundTruth labels...")
    ground_truth = generate_ground_truth(
        config,
        students,
        rooms,
        invigilators,
        exams,
    )

    data = {
        "Student": students,
        "Course": courses,
        "Enrollment": enrollments,
        "Exam": exams,
        "ExamEnrollment": exam_enrollments,
        "ExamRequirement": requirements,
        "ExamRequiredEquipment": normalized_equipment,
        "Room": rooms,
        "RoomCapacity": capacities,
        "RoomClosure": closures,
        "Equipment": equipment,
        "RoomEquipment": room_equipment,
        "Invigilator": invigilators,
        "Availability": availability,
        "Accommodation": accommodations,
        "GroundTruth": ground_truth,
    }

    metadata = {
        "Track": tracks,
        "TrackCourse": track_courses,
        "StudentTrack": student_tracks,
        "OptionalCoursePool": optional_pool,
        "EnrollmentClassification": classifications,
        "SittingAllocation": sitting_allocations,
    }

    print("[12/12] Validating generated dataset...")
    errors = validate_generated_data(data, metadata, config)

    if errors:
        print("\nDATASET VALIDATION FAILED")
        for error in errors[:100]:
            print(" -", error)

        print(f"\nTotal validation errors: {len(errors)}")
        return 1

    # All data is validated before CSV output begins.
    for table_name, rows in data.items():
        write_csv(
            target / f"{table_name}.csv",
            rows,
            SQL_SCHEMAS[table_name],
        )

    metadata_dir = target / "metadata"

    for table_name, rows in metadata.items():
        write_csv(
            metadata_dir / f"{table_name}.csv",
            rows,
            METADATA_SCHEMAS[table_name],
        )

    # The physical grid is metadata for the next implementation stage.
    # It is not a timetable or a room allocation.
    grid_rows = []

    for room_id in range(1, len(rooms) + 1):
        for day_index, exam_date in enumerate(
            config["calendar"]["days"],
            start=1,
        ):
            for slot_number, start_time in enumerate(
                config["calendar"]["slot_start_times"],
                start=1,
            ):
                grid_rows.append({
                    "RoomID": room_id,
                    "DayIndex": day_index,
                    "ExamDate": exam_date,
                    "SlotNumber": slot_number,
                    "SlotStartTime": start_time,
                    "GridUnitID": (
                        (room_id - 1) * 36
                        + (day_index - 1) * 6
                        + slot_number
                    ),
                })

    write_csv(
        metadata_dir / "PhysicalRoomGrid.csv",
        grid_rows,
        [
            "RoomID", "DayIndex", "ExamDate",
            "SlotNumber", "SlotStartTime", "GridUnitID",
        ],
    )

    # Build manifest with file hashes and record counts.
    manifest = {
        "project": "ExamSchedulingSystem",
        "version": "2.2.0",
        "seed": config["project"]["random_seed"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database_modified": False,
        "tables": {},
        "metadata": {},
        "validation": {
            "status": "PASSED",
            "errors": 0,
        },
    }

    for table_name, rows in data.items():
        path = target / f"{table_name}.csv"

        manifest["tables"][table_name] = {
            "file": path.name,
            "rows": len(rows),
            "sha256": sha256_file(path),
        }

    for table_name, rows in metadata.items():
        path = metadata_dir / f"{table_name}.csv"

        manifest["metadata"][table_name] = {
            "file": f"metadata/{path.name}",
            "rows": len(rows),
            "sha256": sha256_file(path),
        }

    grid_path = metadata_dir / "PhysicalRoomGrid.csv"

    manifest["metadata"]["PhysicalRoomGrid"] = {
        "file": "metadata/PhysicalRoomGrid.csv",
        "rows": len(grid_rows),
        "sha256": sha256_file(grid_path),
    }

    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )

    report = {
        "version": "2.2.0",
        "status": "PASSED",
        "database_modified": False,
        "counts": {
            "students": len(students),
            "tracks": len(tracks),
            "courses": len(courses),
            "compulsory_courses": len(track_courses),
            "optional_courses": len(optional_pool),
            "enrollments": len(enrollments),
            "exams": len(exams),
            "exam_enrollments": len(exam_enrollments),
            "sitting_allocations": len(sitting_allocations),
            "rooms": len(rooms),
            "physical_grid_units": len(grid_rows),
            "invigilators": len(invigilators),
            "availability_records": len(availability),
            "accommodations": len(accommodations),
            "room_closures": len(closures),
            "ground_truth_labels": len(ground_truth),
        },
        "enrollment_classifications": dict(
            Counter(x["EnrollmentType"] for x in classifications)
        ),
        "track_distribution": dict(
            sorted(Counter(
                x["ExpectedStudentCount"] for x in tracks
            ).items())
        ),
        "optional_course_distribution": dict(
            sorted(Counter(
                x["CourseID"] for x in enrollments
                if x["CourseID"] >= 226
            ).items())
        ),
        "validation_errors": [],
        "notes": [
            "SittingAllocation maps each enrollment to one of three course sittings.",
            "SittingAllocation is not a final conflict-free timetable.",
            "PhysicalRoomGrid contains 3600 infrastructure units.",
            "Room assignment and invigilator assignment are not yet performed.",
            "GroundTruth contains labels, not executable edge-case fixtures.",
            "SQL Server was not accessed or modified.",
        ],
    }

    (target / "validation_report.json").write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("V2.2.0 DATASET GENERATION SUCCESSFUL")
    print("=" * 72)

    for key, value in report["counts"].items():
        print(f"{key:30} {value:>8,}")

    print("\nEnrollment classification:")
    for key, value in report["enrollment_classifications"].items():
        print(f"{key:30} {value:>8,}")

    print("\nOutput directory:")
    print(target)

    print("\nValidation: PASSED")
    print("SQL Server: NOT MODIFIED")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("\nGENERATOR FAILED")
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)
