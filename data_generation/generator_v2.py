
from __future__ import annotations

import csv
import hashlib
import json
import random
import sys

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v2.json"

PROGRAMMES = [
    ("Computer Science", "Computer Science"),
    ("Electronics", "Electronics"),
    ("Mechanical Engineering", "Mechanical"),
    ("Information Technology", "Information Technology"),
    ("Civil Engineering", "Civil"),
]

YEARS = [1, 2, 3, 4]
LANES = [1, 2, 3]

FIRST_NAMES = [
    "Aarav", "Vihaan", "Aditya", "Arjun", "Ishaan",
    "Ananya", "Aadhya", "Diya", "Myra", "Sara",
    "Rohan", "Karan", "Neha", "Priya", "Rahul",
]

LAST_NAMES = [
    "Sharma", "Patil", "Kulkarni", "Deshmukh", "Joshi",
    "Mehta", "Shah", "Pawar", "Gupta", "Verma",
]


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(CONFIG_PATH)

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    validate_config(config)
    return config


def validate_config(config):
    scale = config["scale"]
    enrollment = config["enrollment"]
    edge = config["edge_cases"]

    if scale["students"] <= 0:
        raise ValueError("Student count must be positive.")

    if scale["courses"] < 100 or scale["courses"] % 20 != 0:
        raise ValueError(
            "Cohort model requires at least 100 courses "
            "and a course count divisible by 20."
        )

    if scale["exams_per_course"] != 3:
        raise ValueError("Exactly three sittings per course are required.")

    if enrollment["minimum_compulsory_courses"] != 2:
        raise ValueError("This version requires 2 compulsory courses minimum.")

    if enrollment["maximum_compulsory_courses"] != 3:
        raise ValueError("This version requires 3 compulsory courses maximum.")

    if edge["total"] != 150:
        raise ValueError("Exactly 150 GroundTruth scenarios are required.")

    if sum(edge["distribution"].values()) != 150:
        raise ValueError("GroundTruth distribution must total 150.")


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def iso_datetime(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def cohort_definitions():
    return [
        (programme, year, department)
        for programme, department in PROGRAMMES
        for year in YEARS
    ]


# ------------------------------------------------------------
# STUDENTS
# ------------------------------------------------------------

def generate_students(count, rng):
    cohorts = cohort_definitions()
    rows = []

    for student_id in range(1, count + 1):
        programme, year, _ = cohorts[(student_id - 1) % len(cohorts)]

        rows.append({
            "StudentID": student_id,
            "StudentCode": f"STU-{student_id:06d}",
            "FullName": (
                f"{rng.choice(FIRST_NAMES)} "
                f"{rng.choice(LAST_NAMES)}"
            ),
            "Email": f"student{student_id:06d}@university.edu",
            "Programme": programme,
            "YearOfStudy": year,
            "Status": "ACTIVE",
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rows


# ------------------------------------------------------------
# COURSES AND COURSE OFFERINGS
# ------------------------------------------------------------

def generate_courses(count):
    cohorts = cohort_definitions()
    courses_per_cohort = count // len(cohorts)

    if courses_per_cohort < 5:
        raise ValueError("Each programme/year cohort needs at least 5 courses.")

    courses = []
    offerings = []
    course_id = 1

    for programme, year, department in cohorts:
        for local_index in range(courses_per_cohort):

            lane = (local_index % 3) + 1

            course = {
                "CourseID": course_id,
                "CourseCode": f"CRS-{course_id:04d}",
                "CourseName": f"{department} Course {course_id:03d}",
                "Department": department,
                "Credits": 3 + (course_id % 3),
                "Status": "ACTIVE",
                "CreatedAt": "2026-01-01 09:00:00",
            }

            courses.append(course)

            offerings.append({
                "CourseID": course_id,
                "Programme": programme,
                "YearOfStudy": year,
                "CourseLane": lane,
            })

            course_id += 1

    return courses, offerings


# ------------------------------------------------------------
# ENROLLMENTS
# ------------------------------------------------------------

def generate_enrollments(students, offerings, rng):
    offerings_by_cohort = defaultdict(lambda: defaultdict(list))

    for offering in offerings:
        key = (
            offering["Programme"],
            int(offering["YearOfStudy"]),
        )

        offerings_by_cohort[key][
            int(offering["CourseLane"])
        ].append(int(offering["CourseID"]))

    students_by_cohort = defaultdict(list)

    for student in students:
        key = (
            student["Programme"],
            int(student["YearOfStudy"]),
        )
        students_by_cohort[key].append(student)

    enrollments = []
    classifications = []
    enrollment_id = 1

    for cohort_key in sorted(students_by_cohort):
        cohort_students = sorted(
            students_by_cohort[cohort_key],
            key=lambda x: int(x["StudentID"]),
        )

        course_lanes = offerings_by_cohort[cohort_key]

        for lane in LANES:
            if not course_lanes[lane]:
                raise ValueError(
                    f"Cohort {cohort_key} has no courses in lane {lane}."
                )

        if len(course_lanes[1]) < 2:
            raise ValueError(
                f"Cohort {cohort_key} needs two lane-1 courses "
                "to support optional enrollment."
            )

        for student in cohort_students:

            compulsory_count = (
                3 if rng.random() < 0.65 else 2
            )

            if compulsory_count == 3:
                compulsory_lanes = [1, 2, 3]
            else:
                compulsory_lanes = sorted(
                    rng.sample(LANES, 2)
                )

            selected = []

            for lane in compulsory_lanes:
                course_id = rng.choice(course_lanes[lane])

                selected.append({
                    "CourseID": course_id,
                    "CourseLane": lane,
                    "EnrollmentType": "COMPULSORY",
                })

            # Optional course for a student with two compulsory courses:
            # select from the unused lane.
            if compulsory_count == 2 and rng.random() < 0.75:
                missing_lane = next(
                    lane for lane in LANES
                    if lane not in compulsory_lanes
                )

                optional_course = rng.choice(
                    course_lanes[missing_lane]
                )

                selected.append({
                    "CourseID": optional_course,
                    "CourseLane": missing_lane,
                    "EnrollmentType": "OPTIONAL",
                })

            # Optional course for a student with three compulsory courses:
            # choose the alternative lane-1 course.
            elif compulsory_count == 3 and rng.random() < 0.20:
                existing_lane1 = next(
                    x["CourseID"]
                    for x in selected
                    if x["CourseLane"] == 1
                )

                alternatives = [
                    course_id
                    for course_id in course_lanes[1]
                    if course_id != existing_lane1
                ]

                optional_course = rng.choice(alternatives)

                selected.append({
                    "CourseID": optional_course,
                    "CourseLane": 1,
                    "EnrollmentType": "OPTIONAL",
                })

            for item in selected:
                course_id = item["CourseID"]
                lane = item["CourseLane"]

                enrollments.append({
                    "EnrollmentID": enrollment_id,
                    "StudentID": student["StudentID"],
                    "CourseID": course_id,
                    "EnrollmentDate": "2026-01-10",
                    "EnrollmentStatus": "ENROLLED",
                    "EffectiveFrom": "2026-01-01",
                    "EffectiveTo": None,
                    "CreatedAt": "2026-01-10 09:00:00",
                })

                classifications.append({
                    "EnrollmentID": enrollment_id,
                    "StudentID": student["StudentID"],
                    "CourseID": course_id,
                    "EnrollmentType": item["EnrollmentType"],
                    "CourseLane": lane,
                })

                enrollment_id += 1

    return enrollments, classifications


# ------------------------------------------------------------
# EXAMS AND REQUIREMENTS
# ------------------------------------------------------------

def generate_exams(courses, exams_per_course):
    exams = []
    requirements = []

    exam_id = 1
    requirement_id = 1

    for course in courses:
        for sitting in range(1, exams_per_course + 1):

            exams.append({
                "ExamID": exam_id,
                "ExamCode": f"EXAM-2026-{exam_id:06d}",
                "CourseID": course["CourseID"],
                "ExamName": f"{course['CourseName']} - Sitting {sitting}",
                "ExamWindowStart": "2026-11-16 08:00:00",
                "ExamWindowEnd": "2026-11-18 18:00:00",
                "ExamStatus": "READY",
                "CreatedAt": "2026-01-15 09:00:00",
            })

            requirements.append({
                "RequirementID": requirement_id,
                "ExamID": exam_id,
                "DurationMinutes": 90,
                "RequiredEquipment": None,
                "AccessibilityRequired": 0,
                "SpecialInstructions": None,
                "CreatedAt": "2026-01-15 09:00:00",
            })

            exam_id += 1
            requirement_id += 1

    return exams, requirements


# ------------------------------------------------------------
# DETERMINISTIC SITTING ASSIGNMENT
# ------------------------------------------------------------

def build_cohort_ranks(students):
    groups = defaultdict(list)

    for student in students:
        key = (
            student["Programme"],
            int(student["YearOfStudy"]),
        )
        groups[key].append(int(student["StudentID"]))

    ranks = {}

    for key, student_ids in groups.items():
        for rank, student_id in enumerate(sorted(student_ids)):
            ranks[student_id] = rank

    return ranks


def generate_exam_enrollments(
    enrollments,
    exams,
    offerings,
    students,
):
    exams_by_course = defaultdict(list)

    for exam in exams:
        exams_by_course[int(exam["CourseID"])].append(exam)

    for course_id in exams_by_course:
        exams_by_course[course_id].sort(
            key=lambda x: int(x["ExamID"])
        )

        if len(exams_by_course[course_id]) != 3:
            raise ValueError(
                f"Course {course_id} must have exactly 3 sittings."
            )

    lane_by_course = {
        int(x["CourseID"]): int(x["CourseLane"])
        for x in offerings
    }

    ranks = build_cohort_ranks(students)

    rows = []

    for exam_enrollment_id, enrollment in enumerate(enrollments, start=1):

        student_id = int(enrollment["StudentID"])
        course_id = int(enrollment["CourseID"])

        lane = lane_by_course[course_id]
        rank = ranks[student_id]

        ordinal = ((rank + lane - 1) % 3) + 1

        exam = exams_by_course[course_id][ordinal - 1]

        rows.append({
            "ExamEnrollmentID": exam_enrollment_id,
            "ExamID": exam["ExamID"],
            "EnrollmentID": enrollment["EnrollmentID"],
            "CourseID": course_id,
            "ParticipationStatus": "REGISTERED",
            "RegisteredAt": "2026-01-20 09:00:00",
        })

    return rows


# ------------------------------------------------------------
# ROOMS
# ------------------------------------------------------------

def generate_rooms(count):
    rooms = []
    capacities = []

    capacity_options = [30, 40, 50, 60, 80, 100]

    for room_id in range(1, count + 1):

        room_type = (
            "ACCESSIBLE" if room_id % 10 == 0
            else "LAB" if room_id % 5 == 0
            else "STANDARD"
        )

        rooms.append({
            "RoomID": room_id,
            "RoomCode": f"ROOM-{room_id:06d}",
            "Building": f"Building {(room_id - 1) // 20 + 1}",
            "Floor": (room_id - 1) % 4,
            "RoomType": room_type,
            "IsActive": 1,
            "CreatedAt": "2026-01-01 09:00:00",
        })

        capacities.append({
            "RoomCapacityID": room_id,
            "RoomID": room_id,
            "Capacity": capacity_options[
                (room_id - 1) % len(capacity_options)
            ],
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": None,
            "CapacityReason": "Initial capacity",
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rooms, capacities


# ------------------------------------------------------------
# EQUIPMENT
# ------------------------------------------------------------

def generate_equipment(count):
    names = [
        ("COMPUTER", "Desktop Computer"),
        ("PROJECTOR", "Projector"),
        ("LAB_KIT", "Laboratory Kit"),
        ("ACCESSIBLE_DESK", "Accessible Desk"),
        ("AUDIO", "Audio Equipment"),
        ("NETWORK", "Network Equipment"),
    ]

    rows = []

    for equipment_id in range(1, count + 1):
        code, name = names[(equipment_id - 1) % len(names)]

        rows.append({
            "EquipmentID": equipment_id,
            "EquipmentCode": code,
            "EquipmentName": name,
            "IsActive": 1,
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rows


def generate_room_equipment(rooms, equipment):
    rows = []
    row_id = 1

    for room in rooms:
        equipment_id = (
            (room["RoomID"] - 1) % len(equipment)
        ) + 1

        rows.append({
            "RoomEquipmentID": row_id,
            "RoomID": room["RoomID"],
            "EquipmentID": equipment_id,
            "Quantity": 10,
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": None,
        })

        row_id += 1

        if room["RoomType"] == "LAB":
            extra_id = (equipment_id % len(equipment)) + 1

            rows.append({
                "RoomEquipmentID": row_id,
                "RoomID": room["RoomID"],
                "EquipmentID": extra_id,
                "Quantity": 20,
                "EffectiveFrom": "2026-01-01",
                "EffectiveTo": None,
            })

            row_id += 1

    return rows


# ------------------------------------------------------------
# INVIGILATORS AND AVAILABILITY
# ------------------------------------------------------------

def generate_invigilators(count):
    departments = [
        "Computer Science",
        "Electronics",
        "Mechanical",
        "Administration",
    ]

    return [
        {
            "InvigilatorID": i,
            "InvigilatorCode": f"INV-{i:06d}",
            "FullName": f"Invigilator {i:03d}",
            "Department": departments[(i - 1) % len(departments)],
            "MaxDailyHours": 6,
            "Status": "ACTIVE",
        }
        for i in range(1, count + 1)
    ]


def generate_availability(invigilators, count):
    rows = []

    for availability_id in range(1, count + 1):
        invigilator = invigilators[
            (availability_id - 1) % len(invigilators)
        ]

        day_offset = (
            (availability_id - 1) // len(invigilators)
        ) % 7

        start = datetime(2026, 11, 16, 8, 0) + timedelta(
            days=day_offset
        )

        rows.append({
            "AvailabilityID": availability_id,
            "InvigilatorID": invigilator["InvigilatorID"],
            "AvailableFrom": iso_datetime(start),
            "AvailableTo": iso_datetime(start + timedelta(hours=8)),
            "AvailabilityStatus": "AVAILABLE",
            "AvailabilityReason": "Baseline availability",
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rows


# ------------------------------------------------------------
# ACCOMMODATIONS AND CLOSURES
# ------------------------------------------------------------

def generate_accommodations(students, count):
    types = [
        "EXTENDED_TIME",
        "SPECIAL_EQUIPMENT",
        "SEPARATE_ROOM",
        "ACCESSIBLE_ROOM",
    ]

    rows = []

    for accommodation_id in range(1, count + 1):
        student = students[(accommodation_id - 1) % len(students)]
        accommodation_type = types[
            (accommodation_id - 1) % len(types)
        ]

        rows.append({
            "AccommodationID": accommodation_id,
            "StudentID": student["StudentID"],
            "AccommodationType": accommodation_type,
            "ExtensionPercentage": (
                33.333 if accommodation_type == "EXTENDED_TIME" else None
            ),
            "RequiresSeparateRoom": (
                1 if accommodation_type == "SEPARATE_ROOM" else 0
            ),
            "EffectiveFrom": "2026-01-01",
            "EffectiveTo": None,
            "AccommodationStatus": "ACTIVE",
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rows


def generate_closures(rooms, count):
    rows = []

    for closure_id in range(1, count + 1):
        room = rooms[(closure_id - 1) % len(rooms)]

        rows.append({
            "RoomClosureID": closure_id,
            "RoomID": room["RoomID"],
            "ClosureStart": "2026-11-16 12:00:00",
            "ClosureEnd": "2026-11-16 18:00:00",
            "ClosureReason": "Planned maintenance",
            "ClosureStatus": "ACTIVE",
            "CreatedAt": "2026-01-01 09:00:00",
        })

    return rows


# ------------------------------------------------------------
# GROUND TRUTH LABELS
# ------------------------------------------------------------

def generate_ground_truth(config, students, rooms, invigilators, exams):
    distribution = config["edge_cases"]["distribution"]

    categories = {
        "STUDENT_OVERLAPPING_EXAMS": students,
        "ROOM_CAPACITY_BOUNDARY": rooms,
        "INVIGILATOR_CONFLICT": invigilators,
        "EXTENDED_TIME_ACCOMMODATION": students,
        "ROOM_CLOSURE": rooms,
        "EQUIPMENT_CHANGEOVER": exams,
    }

    descriptions = {
        "STUDENT_OVERLAPPING_EXAMS":
            "Benchmark scenario involving overlapping student exam commitments.",
        "ROOM_CAPACITY_BOUNDARY":
            "Benchmark scenario testing room capacity boundaries.",
        "INVIGILATOR_CONFLICT":
            "Benchmark scenario testing invigilator scheduling conflicts.",
        "EXTENDED_TIME_ACCOMMODATION":
            "Benchmark scenario testing extended-time occupancy and room sharing.",
        "ROOM_CLOSURE":
            "Benchmark scenario testing room closure availability.",
        "EQUIPMENT_CHANGEOVER":
            "Benchmark scenario testing equipment compatibility and course-block changeover.",
    }

    rows = []
    scenario_id = 1

    for issue_type, quantity in distribution.items():
        entities = categories[issue_type]

        for index in range(quantity):
            entity = entities[index % len(entities)]

            if issue_type in (
                "STUDENT_OVERLAPPING_EXAMS",
                "EXTENDED_TIME_ACCOMMODATION",
            ):
                entity_type = "STUDENT"
                entity_code = entity["StudentCode"]

            elif issue_type in (
                "ROOM_CAPACITY_BOUNDARY",
                "ROOM_CLOSURE",
            ):
                entity_type = "ROOM"
                entity_code = entity["RoomCode"]

            elif issue_type == "INVIGILATOR_CONFLICT":
                entity_type = "INVIGILATOR"
                entity_code = entity["InvigilatorCode"]

            else:
                entity_type = "EXAM"
                entity_code = entity["ExamCode"]

            rows.append({
                "ScenarioCode": f"EDGE-{scenario_id:04d}",
                "EntityType": entity_type,
                "EntityCode": entity_code,
                "IssueType": issue_type,
                "ExpectedOutcome": "DETECT_OR_HANDLE",
                "ExpectedReasonCode": issue_type,
                "Severity": "HIGH",
                "Description": descriptions[issue_type],
            })

            scenario_id += 1

    return rows


# ------------------------------------------------------------
# DATASET VALIDATION
# ------------------------------------------------------------

def validate_dataset(data, offerings, classifications):
    errors = []

    students = data["Student"]
    courses = data["Course"]
    enrollments = data["Enrollment"]
    exams = data["Exam"]
    exam_enrollments = data["ExamEnrollment"]

    student_ids = {int(x["StudentID"]) for x in students}
    course_ids = {int(x["CourseID"]) for x in courses}
    enrollment_ids = {int(x["EnrollmentID"]) for x in enrollments}
    exam_ids = {int(x["ExamID"]) for x in exams}

    offering_by_course = {
        int(x["CourseID"]): x for x in offerings
    }

    classification_by_enrollment = {
        int(x["EnrollmentID"]): x for x in classifications
    }

    if len(offering_by_course) != len(offerings):
        errors.append("Duplicate CourseID in CourseOffering metadata.")

    if len(classification_by_enrollment) != len(classifications):
        errors.append("Duplicate EnrollmentID in classification metadata.")

    for course_id in course_ids:
        if course_id not in offering_by_course:
            errors.append(f"Course {course_id} has no cohort offering.")

    for enrollment in enrollments:
        sid = int(enrollment["StudentID"])
        cid = int(enrollment["CourseID"])
        eid = int(enrollment["EnrollmentID"])

        if sid not in student_ids:
            errors.append(f"Enrollment {eid}: invalid StudentID.")

        if cid not in course_ids:
            errors.append(f"Enrollment {eid}: invalid CourseID.")

        if eid not in classification_by_enrollment:
            errors.append(f"Enrollment {eid}: missing classification.")

    for exam in exams:
        if int(exam["CourseID"]) not in course_ids:
            errors.append(f"Exam {exam['ExamID']}: invalid CourseID.")

    exam_count_by_course = Counter(
        int(x["CourseID"]) for x in exams
    )

    for course_id in course_ids:
        if exam_count_by_course[course_id] != 3:
            errors.append(
                f"Course {course_id}: expected exactly 3 sittings."
            )

    exam_by_id = {
        int(x["ExamID"]): x for x in exams
    }

    enrollment_exam_counts = Counter()
    sitting_counts = Counter()

    for row in exam_enrollments:
        eid = int(row["EnrollmentID"])
        exam_id = int(row["ExamID"])
        course_id = int(row["CourseID"])

        enrollment_exam_counts[eid] += 1

        if eid not in enrollment_ids:
            errors.append(f"ExamEnrollment: unknown EnrollmentID {eid}.")

        if exam_id not in exam_ids:
            errors.append(f"ExamEnrollment: unknown ExamID {exam_id}.")
            continue

        if int(exam_by_id[exam_id]["CourseID"]) != course_id:
            errors.append(
                f"ExamEnrollment {row['ExamEnrollmentID']}: course mismatch."
            )

        course_exams = sorted(
            [
                x for x in exams
                if int(x["CourseID"]) == course_id
            ],
            key=lambda x: int(x["ExamID"]),
        )

        ordinal = next(
            i + 1
            for i, x in enumerate(course_exams)
            if int(x["ExamID"]) == exam_id
        )

        sitting_counts[(course_id, ordinal)] += 1

    for enrollment_id in enrollment_ids:
        if enrollment_exam_counts[enrollment_id] != 1:
            errors.append(
                f"Enrollment {enrollment_id}: expected one exam sitting."
            )

    for course_id in course_ids:
        for ordinal in (1, 2, 3):
            if sitting_counts[(course_id, ordinal)] == 0:
                errors.append(
                    f"Course {course_id}: sitting {ordinal} is empty."
                )

    student_course_rows = defaultdict(list)

    for enrollment in enrollments:
        student_course_rows[int(enrollment["StudentID"])].append(
            int(enrollment["EnrollmentID"])
        )

    student_by_id = {
        int(x["StudentID"]): x for x in students
    }

    for student_id, ids in student_course_rows.items():
        if not 2 <= len(ids) <= 4:
            errors.append(
                f"Student {student_id}: invalid course count {len(ids)}."
            )

        types = [
            classification_by_enrollment[x]["EnrollmentType"]
            for x in ids
        ]

        compulsory = [
            classification_by_enrollment[x]
            for x in ids
            if classification_by_enrollment[x]["EnrollmentType"] == "COMPULSORY"
        ]

        optional = [
            classification_by_enrollment[x]
            for x in ids
            if classification_by_enrollment[x]["EnrollmentType"] == "OPTIONAL"
        ]

        if not 2 <= len(compulsory) <= 3:
            errors.append(
                f"Student {student_id}: compulsory count must be 2 or 3."
            )

        if len(optional) > 1:
            errors.append(
                f"Student {student_id}: more than one optional course."
            )

        compulsory_lanes = [
            int(x["CourseLane"]) for x in compulsory
        ]

        if len(compulsory_lanes) != len(set(compulsory_lanes)):
            errors.append(
                f"Student {student_id}: compulsory courses repeat a lane."
            )

        student = student_by_id[student_id]

        for enrollment_id in ids:
            row = next(
                x for x in enrollments
                if int(x["EnrollmentID"]) == enrollment_id
            )

            offering = offering_by_course[int(row["CourseID"])]

            if (
                offering["Programme"] != student["Programme"]
                or int(offering["YearOfStudy"]) != int(student["YearOfStudy"])
            ):
                errors.append(
                    f"Student {student_id}: course is outside their cohort."
                )

    if len(data["GroundTruth"]) != 150:
        errors.append("GroundTruth must contain exactly 150 labels.")

    return errors


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    config = load_config()
    rng = random.Random(int(config["seed"]))
    scale = config["scale"]

    output_dir = ROOT / config["output_directory"]
    metadata_dir = output_dir / "metadata"

    print("=" * 70)
    print("EXAM SCHEDULING DATASET GENERATOR V2.1.0")
    print("=" * 70)

    students = generate_students(scale["students"], rng)

    courses, offerings = generate_courses(scale["courses"])

    enrollments, classifications = generate_enrollments(
        students,
        offerings,
        rng,
    )

    exams, requirements = generate_exams(
        courses,
        scale["exams_per_course"],
    )

    exam_enrollments = generate_exam_enrollments(
        enrollments,
        exams,
        offerings,
        students,
    )

    rooms, capacities = generate_rooms(scale["rooms"])

    equipment = generate_equipment(scale["equipment_types"])

    room_equipment = generate_room_equipment(
        rooms,
        equipment,
    )

    invigilators = generate_invigilators(scale["invigilators"])

    availability = generate_availability(
        invigilators,
        scale["availability_records"],
    )

    accommodations = generate_accommodations(
        students,
        scale["accommodations"],
    )

    closures = generate_closures(
        rooms,
        scale["room_closures"],
    )

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

    errors = validate_dataset(
        data,
        offerings,
        classifications,
    )

    if errors:
        print("\nVALIDATION FAILED")
        for error in errors[:100]:
            print(" -", error)
        print(f"Total errors: {len(errors)}")
        return 1

    schemas = {
        "Student": [
            "StudentID", "StudentCode", "FullName", "Email",
            "Programme", "YearOfStudy", "Status", "CreatedAt",
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
            "EquipmentID", "EquipmentCode", "EquipmentName",
            "IsActive", "CreatedAt",
        ],
        "RoomEquipment": [
            "RoomEquipmentID", "RoomID", "EquipmentID",
            "Quantity", "EffectiveFrom", "EffectiveTo",
        ],
        "Invigilator": [
            "InvigilatorID", "InvigilatorCode", "FullName",
            "Department", "MaxDailyHours", "Status",
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
            "ScenarioCode", "EntityType", "EntityCode", "IssueType",
            "ExpectedOutcome", "ExpectedReasonCode", "Severity",
            "Description",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": config["version"],
        "seed": config["seed"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tables": {},
        "metadata": {},
        "validation": {
            "status": "PASSED",
            "errors": 0,
        },
    }

    for table_name, rows in data.items():
        path = output_dir / f"{table_name}.csv"

        write_csv(path, rows, schemas[table_name])

        manifest["tables"][table_name] = {
            "rows": len(rows),
            "file": path.name,
            "sha256": sha256_file(path),
        }

    metadata_schemas = {
        "CourseOffering": [
            "CourseID", "Programme", "YearOfStudy", "CourseLane",
        ],
        "EnrollmentClassification": [
            "EnrollmentID", "StudentID", "CourseID",
            "EnrollmentType", "CourseLane",
        ],
    }

    metadata = {
        "CourseOffering": offerings,
        "EnrollmentClassification": classifications,
    }

    for name, rows in metadata.items():
        path = metadata_dir / f"{name}.csv"

        write_csv(path, rows, metadata_schemas[name])

        manifest["metadata"][name] = {
            "rows": len(rows),
            "file": f"metadata/{path.name}",
            "sha256": sha256_file(path),
        }

    report = {
        "status": "PASSED",
        "version": config["version"],
        "seed": config["seed"],
        "total_tables": len(data),
        "total_rows": sum(len(x) for x in data.values()),
        "metadata_rows": sum(len(x) for x in metadata.values()),
        "errors": [],
        "row_counts": {
            name: len(rows) for name, rows in data.items()
        },
        "cohort_count": len(cohort_definitions()),
        "course_lane_count": 3,
        "enrollment_classification_counts": dict(
            Counter(x["EnrollmentType"] for x in classifications)
        ),
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )

    (output_dir / "validation_report.json").write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    readme = [
        "# Exam Scheduling Dataset v2.1.0",
        "",
        f"- Seed: {config['seed']}",
        f"- Students: {len(students)}",
        f"- Courses: {len(courses)}",
        f"- Exams: {len(exams)}",
        f"- Cohorts: {len(cohort_definitions())}",
        "- Three course lanes per cohort.",
        "- CourseOffering and EnrollmentClassification are metadata files.",
        "- GroundTruth contains 150 benchmark labels.",
        "- SQL Server database was not modified.",
    ]

    (output_dir / "README.md").write_text(
        "\n".join(readme),
        encoding="utf-8",
    )

    print("\nDATASET GENERATION COMPLETED")
    print(f"Output: {output_dir}")
    print(f"Students: {len(students):,}")
    print(f"Courses: {len(courses):,}")
    print(f"Enrollments: {len(enrollments):,}")
    print(f"Exams: {len(exams):,}")
    print(f"Exam enrollments: {len(exam_enrollments):,}")
    print(f"GroundTruth labels: {len(ground_truth):,}")
    print(f"Metadata files: {len(metadata)}")
    print("Validation: PASSED")
    print("SQL Server database: NOT MODIFIED")

    return 0


if __name__ == "__main__":
    sys.exit(main())
