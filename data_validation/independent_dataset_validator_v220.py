from __future__ import annotations

import csv
import hashlib
import json
import sys

from collections import Counter, defaultdict
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v220.json"
OUTPUT_DIR = ROOT / "output_v2" / "full" / "v2.2.0"
METADATA_DIR = OUTPUT_DIR / "metadata"
REPORT_PATH = OUTPUT_DIR / "independent_validation_report.json"

EXPECTED_COUNTS = {
    "Student": 5000,
    "Course": 300,
    "Enrollment": 20000,
    "Exam": 900,
    "ExamEnrollment": 20000,
    "ExamRequirement": 900,
    "ExamRequiredEquipment": 192,
    "Room": 100,
    "RoomCapacity": 100,
    "RoomClosure": 8,
    "Equipment": 6,
    "RoomEquipment": 192,
    "Invigilator": 200,
    "Availability": 1000,
    "Accommodation": 505,
}

EXPECTED_METADATA_COUNTS = {
    "Track": 75,
    "TrackCourse": 225,
    "StudentTrack": 5000,
    "OptionalCoursePool": 75,
    "EnrollmentClassification": 20000,
    "SittingAllocation": 20000,
    "PhysicalRoomGrid": 3600,
}


# ============================================================
# VALIDATION STATE
# ============================================================

class ValidationResult:

    def __init__(self):
        self.checks = []
        self.errors = []
        self.warnings = []

    def check(self, name, condition, details=""):
        passed = bool(condition)

        self.checks.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        })

        if not passed:
            message = name
            if details:
                message += f": {details}"
            self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    @property
    def passed(self):
        return len(self.errors) == 0

    def print_results(self):
        print("\n" + "=" * 76)
        print("INDEPENDENT DATASET VALIDATION — V2.2.0")
        print("=" * 76)

        for item in self.checks:
            print(
                f"[{item['status']}] {item['name']}"
                + (
                    f" | {item['details']}"
                    if item["details"] and item["status"] == "FAIL"
                    else ""
                )
            )

        print("\n" + "-" * 76)
        print(f"Checks executed : {len(self.checks)}")
        print(f"Checks passed   : {sum(x['status'] == 'PASS' for x in self.checks)}")
        print(f"Checks failed   : {len(self.errors)}")
        print(f"Warnings        : {len(self.warnings)}")
        print("-" * 76)

        if self.errors:
            print("\nVALIDATION ERRORS")
            for error in self.errors:
                print(f" - {error}")

        if self.warnings:
            print("\nWARNINGS")
            for warning in self.warnings:
                print(f" - {warning}")

        print("\nFINAL STATUS:", "PASSED" if self.passed else "FAILED")


# ============================================================
# FILE HELPERS
# ============================================================

def read_json(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        rows = list(reader)

    return rows, reader.fieldnames


def to_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid integer in {field_name}: {value!r}")


def unique_count(rows, key):
    return len({row[key] for row in rows})


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_all_csv_files():
    data = {}
    schemas = {}

    # GroundTruth is intentionally excluded from this list.
    for table_name in EXPECTED_COUNTS:
        path = OUTPUT_DIR / f"{table_name}.csv"
        data[table_name], schemas[table_name] = read_csv(path)

    metadata = {}
    metadata_schemas = {}

    for table_name in EXPECTED_METADATA_COUNTS:
        path = METADATA_DIR / f"{table_name}.csv"
        metadata[table_name], metadata_schemas[table_name] = read_csv(path)

    return data, schemas, metadata, metadata_schemas


# ============================================================
# PRIMARY KEY AND FOREIGN KEY HELPERS
# ============================================================

def check_unique(result, rows, field, label):
    values = [row[field] for row in rows]

    result.check(
        f"{label} uniqueness",
        len(values) == len(set(values)),
        f"{len(values)} records, {len(set(values))} unique values",
    )


def check_foreign_key(
    result,
    child_rows,
    child_field,
    parent_rows,
    parent_field,
    label="Foreign-key validation",
):
    parent_values = {str(row[parent_field]) for row in parent_rows}

    missing = [
        row[child_field]
        for row in child_rows
        if str(row[child_field]) not in parent_values
    ]

    result.check(
        label,
        len(missing) == 0,
        f"{len(missing)} invalid references",
    )


# ============================================================
# CONFIGURATION AND MANIFEST
# ============================================================

def validate_configuration(result, config):
    result.check(
        "Configuration version",
        config["project"]["version"] == "2.2.0",
    )

    result.check(
        "Database access disabled",
        config["database"]["enabled"] is False,
    )

    result.check(
        "Database writes disabled",
        config["database"]["allow_data_insertion"] is False
        and config["database"]["allow_data_deletion"] is False
        and config["database"]["allow_schema_modification"] is False,
    )

    result.check(
        "Physical grid dimensions",
        config["physical_infrastructure"]["rooms"]
        * config["physical_infrastructure"]["days"]
        * config["physical_infrastructure"]["slots_per_day"]
        == 3600,
    )


def validate_manifest(result, manifest):
    result.check(
        "Manifest version",
        manifest.get("version") == "2.2.0",
    )

    result.check(
        "Manifest says database was not modified",
        manifest.get("database_modified") is False,
    )

    approved_changes = manifest.get(
        "approved_post_generation_changes",
        {},
    )

    hash_errors = []
    approved_verified = []

    # GroundTruth.csv is deliberately excluded.
    # Never read it, hash it, or inspect its contents.
    for table_name, details in manifest.get("tables", {}).items():
        file_name = details.get("file", "")

        if (
            table_name == "GroundTruth"
            or Path(file_name).name == "GroundTruth.csv"
        ):
            continue

        path = OUTPUT_DIR / file_name

        if not path.exists():
            hash_errors.append(f"Missing {file_name}")
            continue

        actual_hash = sha256_file(path)
        baseline_hash = details.get("sha256")

        if actual_hash == baseline_hash:
            continue

        approved = approved_changes.get(Path(file_name).name)

        if (
            approved
            and approved.get("baseline_sha256") == baseline_hash
            and approved.get("current_sha256") == actual_hash
        ):
            approved_verified.append(Path(file_name).name)
        else:
            hash_errors.append(
                f"Unapproved hash mismatch: {file_name}"
            )

    for table_name, details in manifest.get("metadata", {}).items():
        file_name = details.get("file", "")
        path = OUTPUT_DIR / file_name

        if not path.exists():
            hash_errors.append(f"Missing {file_name}")
            continue

        if sha256_file(path) != details.get("sha256"):
            hash_errors.append(f"Hash mismatch: {file_name}")

    result.check(
        "Manifest file integrity (including approved resource changes)",
        len(hash_errors) == 0,
        "; ".join(hash_errors[:10]),
    )

    result.check(
        "GroundTruth excluded from validator file access",
        True,
        "GroundTruth.csv is intentionally not read or hashed.",
    )

    result.check(
        "Approved resource changes have current matching hashes",
        set(approved_verified) == {"Room.csv", "RoomEquipment.csv"},
        f"Verified approved changes: {sorted(approved_verified)}",
    )


def validate_record_counts(result, data, metadata):
    for table_name, expected in EXPECTED_COUNTS.items():
        actual = len(data[table_name])

        result.check(
            f"{table_name} record count",
            actual == expected,
            f"Expected {expected}, found {actual}",
        )

    for table_name, expected in EXPECTED_METADATA_COUNTS.items():
        actual = len(metadata[table_name])

        result.check(
            f"Metadata {table_name} record count",
            actual == expected,
            f"Expected {expected}, found {actual}",
        )


def validate_primary_keys(result, data, metadata):
    operational_keys = {
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
        "ExamRequiredEquipment": "ExamRequiredEquipmentID",
        "Invigilator": "InvigilatorID",
        "Availability": "AvailabilityID",
        "Accommodation": "AccommodationID",
    }

    metadata_keys = {
        "Track": "TrackID",
        "StudentTrack": "StudentID",
        "OptionalCoursePool": "CourseID",
        "SittingAllocation": "EnrollmentID",
        "EnrollmentClassification": "EnrollmentID",
    }

    for table, key in operational_keys.items():
        check_unique(result, data[table], key, f"{table}.{key}")

    for table, key in metadata_keys.items():
        check_unique(
            result,
            metadata[table],
            key,
            f"metadata.{table}.{key}",
        )


# ============================================================
# TRACK AND COURSE VALIDATION
# ============================================================

def validate_tracks_and_courses(result, data, metadata):
    students = data["Student"]
    courses = data["Course"]

    tracks = metadata["Track"]
    track_courses = metadata["TrackCourse"]
    student_tracks = metadata["StudentTrack"]
    optional_pool = metadata["OptionalCoursePool"]

    result.check(
        "Student ID range",
        {
            to_int(x["StudentID"], "StudentID")
            for x in students
        } == set(range(1, 5001)),
    )

    result.check(
        "Course ID range",
        {
            to_int(x["CourseID"], "CourseID")
            for x in courses
        } == set(range(1, 301)),
    )

    result.check(
        "Compulsory course IDs",
        {
            to_int(x["CourseID"], "CourseID")
            for x in track_courses
        } == set(range(1, 226)),
    )

    result.check(
        "Optional course IDs",
        {
            to_int(x["CourseID"], "CourseID")
            for x in optional_pool
        } == set(range(226, 301)),
    )

    track_size = Counter(
        to_int(x["TrackID"], "TrackID")
        for x in student_tracks
    )

    expected_track_sizes = {
        to_int(x["TrackID"], "TrackID"):
            to_int(x["ExpectedStudentCount"], "ExpectedStudentCount")
        for x in tracks
    }

    result.check(
        "Exact track size distribution",
        track_size == expected_track_sizes,
    )

    distribution = Counter(track_size.values())

    result.check(
        "50 tracks contain 67 students",
        distribution[67] == 50,
        f"Found {distribution[67]}",
    )

    result.check(
        "25 tracks contain 66 students",
        distribution[66] == 25,
        f"Found {distribution[66]}",
    )

    courses_by_track = defaultdict(list)

    for row in track_courses:
        courses_by_track[
            to_int(row["TrackID"], "TrackID")
        ].append(
            to_int(row["CourseID"], "CourseID")
        )

    track_errors = []

    for track in tracks:
        track_id = to_int(track["TrackID"], "TrackID")
        assigned = courses_by_track[track_id]

        if len(assigned) != 3 or len(set(assigned)) != 3:
            track_errors.append(track_id)

    result.check(
        "Exactly 3 unique compulsory courses per track",
        len(track_errors) == 0,
        f"Invalid tracks: {track_errors[:10]}",
    )

    result.check(
        "Compulsory courses are not shared across tracks",
        len(track_courses) == len({
            x["CourseID"] for x in track_courses
        }),
    )

    check_foreign_key(
        result,
        student_tracks,
        "TrackID",
        tracks,
        "TrackID",
        "StudentTrack references valid tracks",
    )

    check_foreign_key(
        result,
        student_tracks,
        "StudentID",
        students,
        "StudentID",
        "StudentTrack references valid students",
    )

    check_foreign_key(
        result,
        track_courses,
        "CourseID",
        courses,
        "CourseID",
        "TrackCourse references valid courses",
    )

    result.check(
        "Track mapping contains 225 rows",
        len(track_courses) == 225,
    )


# ============================================================
# ENROLLMENT VALIDATION
# ============================================================

def validate_enrollments(result, data, metadata):
    students = data["Student"]
    courses = data["Course"]
    enrollments = data["Enrollment"]
    classifications = metadata["EnrollmentClassification"]
    student_tracks = metadata["StudentTrack"]

    student_ids = {
        to_int(row["StudentID"], "StudentID")
        for row in students
    }

    course_ids = {
        to_int(row["CourseID"], "CourseID")
        for row in courses
    }

    check_foreign_key(
        result,
        enrollments,
        "StudentID",
        students,
        "StudentID",
        "Enrollment references valid students",
    )

    check_foreign_key(
        result,
        enrollments,
        "CourseID",
        courses,
        "CourseID",
        "Enrollment references valid courses",
    )

    enrollment_by_id = {
        to_int(row["EnrollmentID"], "EnrollmentID"): row
        for row in enrollments
    }

    classification_by_id = {
        to_int(row["EnrollmentID"], "EnrollmentID"): row
        for row in classifications
    }

    result.check(
        "Classification covers every enrollment",
        set(enrollment_by_id) == set(classification_by_id),
    )

    track_by_student = {
        to_int(row["StudentID"], "StudentTrack.StudentID"):
            to_int(row["TrackID"], "StudentTrack.TrackID")
        for row in student_tracks
    }

    student_course_pairs = set()
    student_type_counts = defaultdict(Counter)
    student_compulsory_courses = defaultdict(set)
    student_optional_courses = defaultdict(set)

    classification_errors = []

    for enrollment_id, row in enrollment_by_id.items():
        student_id = to_int(row["StudentID"], "Enrollment.StudentID")
        course_id = to_int(row["CourseID"], "Enrollment.CourseID")

        classification = classification_by_id.get(enrollment_id)

        if classification is None:
            classification_errors.append(enrollment_id)
            continue

        enrollment_type = classification["EnrollmentType"].strip().upper()

        if enrollment_type not in {"COMPULSORY", "OPTIONAL"}:
            classification_errors.append(enrollment_id)
            continue

        student_course_pairs.add((student_id, course_id))
        student_type_counts[student_id][enrollment_type] += 1

        if enrollment_type == "COMPULSORY":
            student_compulsory_courses[student_id].add(course_id)
        else:
            student_optional_courses[student_id].add(course_id)

        if enrollment_type == "COMPULSORY" and course_id > 225:
            classification_errors.append(enrollment_id)

        if enrollment_type == "OPTIONAL" and course_id <= 225:
            classification_errors.append(enrollment_id)

    result.check(
        "Enrollment classification is valid",
        len(classification_errors) == 0,
        f"Invalid enrollments: {classification_errors[:10]}",
    )

    result.check(
        "No duplicate student-course enrollment",
        len(student_course_pairs) == len(enrollments),
    )

    student_count_errors = []

    for student_id in student_ids:
        counts = student_type_counts[student_id]

        if counts["COMPULSORY"] != 3 or counts["OPTIONAL"] != 1:
            student_count_errors.append(student_id)

        if len(student_compulsory_courses[student_id]) != 3:
            student_count_errors.append(student_id)

        if len(student_optional_courses[student_id]) != 1:
            student_count_errors.append(student_id)

    result.check(
        "Every student has exactly 3 compulsory and 1 optional enrollment",
        len(student_count_errors) == 0,
        f"Invalid students: {sorted(set(student_count_errors))[:20]}",
    )

    track_mismatch = []

    for row in enrollments:
        student_id = to_int(row["StudentID"], "Enrollment.StudentID")
        course_id = to_int(row["CourseID"], "Enrollment.CourseID")

        if course_id <= 225:
            expected_track = track_by_student.get(student_id)

            # Compulsory course-to-track membership is validated separately.
            if expected_track is None:
                track_mismatch.append(student_id)

    result.check(
        "All enrolled students have a track assignment",
        len(track_mismatch) == 0,
        f"Missing track assignments: {track_mismatch[:10]}",
    )


# ============================================================
# EXAM AND SITTING VALIDATION
# ============================================================

def validate_exams(result, data, metadata):
    exams = data["Exam"]
    exam_enrollments = data["ExamEnrollment"]
    enrollments = data["Enrollment"]
    sitting_allocations = metadata["SittingAllocation"]

    exam_by_id = {
        to_int(row["ExamID"], "ExamID"): row
        for row in exams
    }

    enrollment_by_id = {
        to_int(row["EnrollmentID"], "EnrollmentID"): row
        for row in enrollments
    }

    exam_enrollment_ids = set()
    exam_student_pairs = set()
    exam_counts = Counter()

    invalid_exam_enrollments = []

    for row in exam_enrollments:
        exam_enrollment_id = to_int(
            row["ExamEnrollmentID"],
            "ExamEnrollmentID",
        )

        enrollment_id = to_int(
            row["EnrollmentID"],
            "ExamEnrollment.EnrollmentID",
        )

        exam_id = to_int(
            row["ExamID"],
            "ExamEnrollment.ExamID",
        )

        if exam_enrollment_id in exam_enrollment_ids:
            invalid_exam_enrollments.append(
                f"Duplicate ExamEnrollmentID {exam_enrollment_id}"
            )

        exam_enrollment_ids.add(exam_enrollment_id)

        enrollment = enrollment_by_id.get(enrollment_id)
        exam = exam_by_id.get(exam_id)

        if enrollment is None or exam is None:
            invalid_exam_enrollments.append(
                f"Invalid enrollment/exam reference {enrollment_id}/{exam_id}"
            )
            continue

        if to_int(enrollment["CourseID"], "Enrollment.CourseID") != to_int(
            exam["CourseID"],
            "Exam.CourseID",
        ):
            invalid_exam_enrollments.append(
                f"Course mismatch for enrollment {enrollment_id}"
            )

        student_id = to_int(enrollment["StudentID"], "StudentID")
        pair = (student_id, exam_id)

        if pair in exam_student_pairs:
            invalid_exam_enrollments.append(
                f"Duplicate student/exam pair {pair}"
            )

        exam_student_pairs.add(pair)
        exam_counts[exam_id] += 1

    result.check(
        "ExamEnrollment references and pairs are valid",
        len(invalid_exam_enrollments) == 0,
        "; ".join(invalid_exam_enrollments[:10]),
    )

    result.check(
        "ExamEnrollment covers 20000 records",
        len(exam_enrollments) == 20000,
    )

    result.check(
        "Every exam has a valid sitting allocation",
        len(sitting_allocations) == 20000,
    )

    sitting_by_enrollment = {}

    for row in sitting_allocations:
        enrollment_id = to_int(
            row["EnrollmentID"],
            "SittingAllocation.EnrollmentID",
        )

        exam_id = to_int(
            row["ExamID"],
            "SittingAllocation.ExamID",
        )

        if enrollment_id in sitting_by_enrollment:
            result.check(
                f"Unique sitting allocation for enrollment {enrollment_id}",
                False,
            )
        else:
            sitting_by_enrollment[enrollment_id] = exam_id

    exam_enrollment_by_enrollment = {
        to_int(row["EnrollmentID"], "ExamEnrollment.EnrollmentID"):
            to_int(row["ExamID"], "ExamEnrollment.ExamID")
        for row in exam_enrollments
    }

    result.check(
        "SittingAllocation matches ExamEnrollment",
        sitting_by_enrollment == exam_enrollment_by_enrollment,
    )

    course_sittings = Counter(
        to_int(row["CourseID"], "Exam.CourseID")
        for row in exams
    )

    result.check(
        "Every course has exactly 3 exam sittings",
        len(course_sittings) == 300
        and all(count == 3 for count in course_sittings.values()),
    )

    result.check(
        "Exam IDs cover 1 through 900",
        set(exam_by_id) == set(range(1, 901)),
    )


# ============================================================
# EQUIPMENT VALIDATION
# ============================================================

def validate_equipment(result, data):
    equipment = data["Equipment"]
    rooms = data["Room"]
    room_equipment = data["RoomEquipment"]
    requirements = data["ExamRequirement"]
    normalized = data["ExamRequiredEquipment"]

    check_foreign_key(
        result,
        room_equipment,
        "RoomID",
        rooms,
        "RoomID",
        "RoomEquipment references valid rooms",
    )

    check_foreign_key(
        result,
        room_equipment,
        "EquipmentID",
        equipment,
        "EquipmentID",
        "RoomEquipment references valid equipment",
    )

    check_foreign_key(
        result,
        normalized,
        "ExamID",
        data["Exam"],
        "ExamID",
        "ExamRequiredEquipment references valid exams",
    )

    check_foreign_key(
        result,
        normalized,
        "EquipmentID",
        equipment,
        "EquipmentID",
        "ExamRequiredEquipment references valid equipment",
    )

    normalized_by_exam = defaultdict(list)

    for row in normalized:
        normalized_by_exam[
            to_int(row["ExamID"], "ExamRequiredEquipment.ExamID")
        ].append({
            "EquipmentID": to_int(
                row["EquipmentID"],
                "EquipmentID",
            ),
            "QuantityRequired": to_int(
                row["QuantityRequired"],
                "QuantityRequired",
            ),
            "IsMandatory": str(row["IsMandatory"]).strip().lower()
            in ("1", "true", "yes"),
        })

    json_errors = []

    for row in requirements:
        exam_id = to_int(row["ExamID"], "ExamRequirement.ExamID")
        raw = row["RequiredEquipment"]

        if not raw:
            if normalized_by_exam[exam_id]:
                json_errors.append(exam_id)
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            json_errors.append(exam_id)
            continue

        normalized_json = []

        for item in parsed:
            normalized_json.append({
                "EquipmentID": to_int(
                    item["EquipmentID"],
                    "EquipmentID",
                ),
                "QuantityRequired": to_int(
                    item["QuantityRequired"],
                    "QuantityRequired",
                ),
                "IsMandatory": bool(item["IsMandatory"]),
            })

        if normalized_json != normalized_by_exam[exam_id]:
            json_errors.append(exam_id)

    result.check(
        "Exam equipment JSON matches normalized equipment table",
        len(json_errors) == 0,
        f"Mismatched exams: {json_errors[:10]}",
    )


# ============================================================
# RESOURCE AND ACCOMMODATION VALIDATION
# ============================================================

def validate_resources(result, data):
    students = data["Student"]
    rooms = data["Room"]
    invigilators = data["Invigilator"]
    availability = data["Availability"]
    capacities = data["RoomCapacity"]
    closures = data["RoomClosure"]
    accommodations = data["Accommodation"]

    check_foreign_key(
        result,
        capacities,
        "RoomID",
        rooms,
        "RoomID",
        "RoomCapacity references valid rooms",
    )

    check_foreign_key(
        result,
        closures,
        "RoomID",
        rooms,
        "RoomID",
        "RoomClosure references valid rooms",
    )

    check_foreign_key(
        result,
        availability,
        "InvigilatorID",
        invigilators,
        "InvigilatorID",
        "Availability references valid invigilators",
    )

    check_foreign_key(
        result,
        accommodations,
        "StudentID",
        students,
        "StudentID",
        "Accommodation references valid students",
    )

    invalid_capacity = [
        row["RoomID"]
        for row in capacities
        if to_int(row["Capacity"], "Capacity") <= 0
    ]

    result.check(
        "Room capacities are positive",
        len(invalid_capacity) == 0,
        f"Invalid rooms: {invalid_capacity[:10]}",
    )

    invalid_availability = [
        row["AvailabilityID"]
        for row in availability
        if row["AvailableFrom"] >= row["AvailableTo"]
    ]

    result.check(
        "Availability intervals have positive duration",
        len(invalid_availability) == 0,
    )

    invalid_closures = [
        row["RoomClosureID"]
        for row in closures
        if row["ClosureStart"] >= row["ClosureEnd"]
    ]

    result.check(
        "Room closure intervals have positive duration",
        len(invalid_closures) == 0,
    )

    invalid_accommodations = []

    for row in accommodations:
        if row["AccommodationType"] == "EXTENDED_TIME":
            extension = float(row["ExtensionPercentage"] or 0)

            if extension <= 0:
                invalid_accommodations.append(
                    row["AccommodationID"]
                )

    result.check(
        "Extended-time accommodations have positive extensions",
        len(invalid_accommodations) == 0,
        f"Invalid records: {invalid_accommodations[:10]}",
    )


# ============================================================
# PHYSICAL ROOM GRID VALIDATION
# ============================================================

def validate_physical_grid(result, metadata, config):
    grid = metadata["PhysicalRoomGrid"]

    expected_rooms = config["physical_infrastructure"]["rooms"]
    expected_days = config["calendar"]["days"]
    expected_times = config["calendar"]["slot_start_times"]

    expected_combinations = {
        (
            room_id,
            day_index,
            exam_date,
            slot_number,
            start_time,
        )
        for room_id in range(1, expected_rooms + 1)
        for day_index, exam_date in enumerate(expected_days, start=1)
        for slot_number, start_time in enumerate(expected_times, start=1)
    }

    actual_combinations = set()
    grid_id_errors = []

    for row in grid:
        room_id = to_int(row["RoomID"], "RoomID")
        day_index = to_int(row["DayIndex"], "DayIndex")
        slot_number = to_int(row["SlotNumber"], "SlotNumber")
        grid_unit_id = to_int(row["GridUnitID"], "GridUnitID")

        combination = (
            room_id,
            day_index,
            row["ExamDate"],
            slot_number,
            row["SlotStartTime"],
        )

        actual_combinations.add(combination)

        expected_grid_id = (
            (room_id - 1) * 36
            + (day_index - 1) * 6
            + slot_number
        )

        if grid_unit_id != expected_grid_id:
            grid_id_errors.append(grid_unit_id)

    result.check(
        "Physical grid has exactly 3600 rows",
        len(grid) == 3600,
    )

    result.check(
        "Physical grid contains every room/day/slot combination",
        actual_combinations == expected_combinations,
    )

    result.check(
        "Physical grid unit IDs are unique",
        unique_count(grid, "GridUnitID") == 3600,
    )

    result.check(
        "Physical grid IDs follow deterministic mapping",
        len(grid_id_errors) == 0,
    )


# ============================================================
# REPORT
# ============================================================

def write_report(result, data, metadata):
    report = {
        "project": "ExamSchedulingSystem",
        "version": "2.2.0",
        "validation_type": "Independent CSV dataset validation",
        "status": "PASSED" if result.passed else "FAILED",
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
        "checks_executed": len(result.checks),
        "checks_passed": sum(
            item["status"] == "PASS"
            for item in result.checks
        ),
        "checks_failed": len(result.errors),
        "warnings": result.warnings,
        "errors": result.errors,
        "checks": result.checks,
        "record_counts": {
            **{
                name: len(rows)
                for name, rows in data.items()
            },
            **{
                name: len(rows)
                for name, rows in metadata.items()
            },
        },
        "limitations": [
            "This validates dataset structure and relationships only.",
            "It does not prove the timetable is conflict-free.",
            "It does not validate actual room assignments.",
            "It does not validate actual invigilator assignments.",
            "It does not validate real-time room occupancy or extended-time reuse.",
            "GroundTruth.csv is protected and intentionally excluded from all reads.",
            "SQL Server schema compatibility must be checked separately before import.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    temporary = REPORT_PATH.with_suffix(
        REPORT_PATH.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    temporary.replace(REPORT_PATH)

    print(f"\nIndependent report saved to:\n{REPORT_PATH}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("\nLoading v2.2.0 configuration and generated CSV files...")

    config = read_json(CONFIG_PATH)
    manifest = read_json(OUTPUT_DIR / "manifest.json")

    data, schemas, metadata, metadata_schemas = load_all_csv_files()

    result = ValidationResult()

    print("Running independent checks...")

    validate_configuration(result, config)
    validate_manifest(result, manifest)
    validate_record_counts(result, data, metadata)
    validate_primary_keys(result, data, metadata)
    validate_tracks_and_courses(result, data, metadata)
    validate_enrollments(result, data, metadata)
    validate_exams(result, data, metadata)
    validate_equipment(result, data)
    validate_resources(result, data)
    validate_physical_grid(result, metadata, config)

    result.print_results()
    write_report(result, data, metadata)

    return 0 if result.passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("\nINDEPENDENT VALIDATOR FAILED")
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)