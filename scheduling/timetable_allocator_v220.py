from __future__ import annotations

import csv
import json
import sys
import math

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

CONFIG_PATH = ROOT / "config" / "dataset_config_v220.json"
DATA_DIR = ROOT / "output_v2" / "full" / "v2.2.0"
METADATA_DIR = DATA_DIR / "metadata"
SCHEDULING_DIR = DATA_DIR / "scheduling"

EXPECTED_STUDENTS = 5000
EXPECTED_TRACKS = 75
EXPECTED_COURSES = 300
EXPECTED_COMPULSORY_COURSES = 225
EXPECTED_OPTIONAL_COURSES = 75
EXPECTED_EXAMS = 900
EXPECTED_ALLOCATIONS = 20000
EXPECTED_ROOMS = 100

COMPULSORY_BLOCK_IDS = list(range(1, 11))
OPTIONAL_BLOCK_ID = 11


# ============================================================
# CSV / JSON HELPERS
# ============================================================

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=4), encoding="utf-8")
    temporary.replace(path)


def to_int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field}: {value!r}")


# ============================================================
# LOAD INPUTS
# ============================================================

def load_inputs():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(CONFIG_PATH)

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    data = {
        "students": read_csv(DATA_DIR / "Student.csv"),
        "courses": read_csv(DATA_DIR / "Course.csv"),
        "enrollments": read_csv(DATA_DIR / "Enrollment.csv"),
        "exams": read_csv(DATA_DIR / "Exam.csv"),
        "exam_enrollments": read_csv(DATA_DIR / "ExamEnrollment.csv"),
        "tracks": read_csv(METADATA_DIR / "Track.csv"),
        "track_courses": read_csv(METADATA_DIR / "TrackCourse.csv"),
        "student_tracks": read_csv(METADATA_DIR / "StudentTrack.csv"),
        "classifications": read_csv(
            METADATA_DIR / "EnrollmentClassification.csv"
        ),
        "sitting_allocations": read_csv(
            METADATA_DIR / "SittingAllocation.csv"
        ),
        "accommodations": read_csv(DATA_DIR / "Accommodation.csv"),
    }

    return config, data


# ============================================================
# TIME BLOCK MODEL
#
# Blocks 1-10:
#   Days 1-5, morning and afternoon.
#   Compulsory courses.
#
# Block 11:
#   Day 6, slots 1-3.
#   Optional courses.
#
# Block 12:
#   Day 6, slots 4-6.
#   Reserved / unused.
# ============================================================

def create_blocks(config):
    calendar = config["calendar"]
    dates = calendar["days"]
    start_times = calendar["slot_start_times"]

    if len(dates) != 6 or len(start_times) != 6:
        raise ValueError(
            "v2.2.0 requires exactly 6 days and 6 slots per day."
        )

    blocks = {}
    block_id = 1

    for day_index, exam_date in enumerate(dates, start=1):
        for start_slot in (1, 4):
            blocks[block_id] = {
                "BlockID": block_id,
                "DayIndex": day_index,
                "ExamDate": exam_date,
                "StartSlot": start_slot,
                "EndSlot": start_slot + 2,
                "Period": (
                    "MORNING" if start_slot == 1 else "AFTERNOON"
                ),
            }
            block_id += 1

    if len(blocks) != 12:
        raise ValueError("Expected exactly 12 timetable blocks.")

    return blocks


# ============================================================
# TRACK-COURSE BLOCK ALLOCATION
#
# Each track has 3 compulsory courses.
# Its courses are placed on 3 distinct days among Days 1-5.
# Each day has 2 blocks: morning and afternoon.
# Each of the 10 blocks receives 22 or 23 courses.
# ============================================================

def assign_track_course_blocks(tracks, track_courses, blocks):
    track_ids = {
        to_int(row["TrackID"], "TrackID")
        for row in tracks
    }

    if len(track_ids) != EXPECTED_TRACKS:
        raise ValueError("Expected exactly 75 unique tracks.")

    if track_ids != set(range(1, 76)):
        raise ValueError("Track IDs must be exactly 1 through 75.")

    by_track = defaultdict(list)
    course_to_track = {}

    for row in track_courses:
        track_id = to_int(row["TrackID"], "TrackID")
        course_id = to_int(row["CourseID"], "CourseID")

        if track_id not in track_ids:
            raise ValueError(
                f"Unknown TrackID {track_id} in TrackCourse."
            )

        if course_id in course_to_track:
            raise ValueError(
                f"Compulsory course {course_id} maps to multiple tracks."
            )

        course_to_track[course_id] = track_id
        by_track[track_id].append(course_id)

    expected_courses = set(
        range(1, EXPECTED_COMPULSORY_COURSES + 1)
    )

    if set(course_to_track) != expected_courses:
        raise ValueError(
            "TrackCourse must map exactly compulsory courses 1-225."
        )

    for track_id in sorted(track_ids):
        if len(by_track[track_id]) != 3:
            raise ValueError(
                f"Track {track_id} must have exactly 3 compulsory courses."
            )

    day_blocks = {
        day: [2 * day - 1, 2 * day]
        for day in range(1, 6)
    }

    block_load = Counter()
    rows = []
    course_block = {}

    for track_id in sorted(track_ids):
        course_ids = sorted(by_track[track_id])
        assigned_days = set()

        for ordinal, course_id in enumerate(course_ids, start=1):
            day_index = (
                (track_id - 1 + ordinal - 1) % 5
            ) + 1

            if day_index in assigned_days:
                raise AssertionError(
                    "Track-day allocation unexpectedly repeated a day."
                )

            assigned_days.add(day_index)

            block_id = min(
                day_blocks[day_index],
                key=lambda bid: (block_load[bid], bid),
            )

            block_load[block_id] += 1
            course_block[course_id] = block_id

            block = blocks[block_id]

            rows.append({
                "TrackID": track_id,
                "CourseID": course_id,
                "CourseOrdinal": ordinal,
                "BlockID": block_id,
                "DayIndex": day_index,
                "ExamDate": block["ExamDate"],
                "Period": block["Period"],
            })

        if len(assigned_days) != 3:
            raise ValueError(
                f"Track {track_id} does not have 3 distinct exam days."
            )

    if len(rows) != EXPECTED_COMPULSORY_COURSES:
        raise ValueError(
            f"Expected 225 track-course placements; found {len(rows)}."
        )

    if any(
        block_load[bid] not in (22, 23)
        for bid in COMPULSORY_BLOCK_IDS
    ):
        raise ValueError(
            f"Compulsory block loads are not balanced: {dict(block_load)}"
        )

    return course_block, rows, block_load


# ============================================================
# OPTIONAL COURSE BLOCK ALLOCATION
# ============================================================

def assign_optional_course_blocks(
    classifications,
    student_tracks,
    blocks,
):
    student_track = {
        to_int(row["StudentID"], "StudentID"):
        to_int(row["TrackID"], "TrackID")
        for row in student_tracks
    }

    optional_course_tracks = defaultdict(set)
    optional_course_students = defaultdict(set)

    for row in classifications:
        if row["EnrollmentType"].strip().upper() != "OPTIONAL":
            continue

        course_id = to_int(row["CourseID"], "CourseID")
        student_id = to_int(row["StudentID"], "StudentID")

        if student_id not in student_track:
            raise ValueError(
                f"Optional enrollment references unknown student {student_id}."
            )

        optional_course_tracks[course_id].add(
            student_track[student_id]
        )
        optional_course_students[course_id].add(student_id)

    expected_ids = set(
        range(
            EXPECTED_COMPULSORY_COURSES + 1,
            EXPECTED_COURSES + 1,
        )
    )

    if set(optional_course_tracks) != expected_ids:
        raise ValueError(
            "Optional course mapping must contain courses 226 through 300."
        )

    if blocks[OPTIONAL_BLOCK_ID]["DayIndex"] != 6:
        raise ValueError("Optional block 11 must be on Day 6.")

    optional_block = {
        course_id: OPTIONAL_BLOCK_ID
        for course_id in expected_ids
    }

    for course_id, students in optional_course_students.items():
        if len(students) not in (66, 67):
            raise ValueError(
                f"Optional course {course_id} has {len(students)} students; "
                "expected 66 or 67."
            )

    return optional_block, optional_course_tracks


# ============================================================
# COURSE-TO-TRACK MAPPING
# ============================================================

def build_course_mappings(track_courses):
    compulsory_course_track = {}

    for row in track_courses:
        course_id = to_int(row["CourseID"], "CourseID")
        track_id = to_int(row["TrackID"], "TrackID")

        if course_id in compulsory_course_track:
            raise ValueError(
                f"Compulsory course {course_id} maps to multiple tracks."
            )

        compulsory_course_track[course_id] = track_id

    expected = set(
        range(1, EXPECTED_COMPULSORY_COURSES + 1)
    )

    if set(compulsory_course_track) != expected:
        raise ValueError("Invalid compulsory course mapping.")

    return compulsory_course_track


# ============================================================
# BUILD EXAM TIMETABLE
# ============================================================

def build_timetable(
    config,
    exams,
    blocks,
    course_block,
    optional_block,
    compulsory_course_track,
    exam_enrollments,
):
    exam_count = Counter(
        to_int(row["ExamID"], "ExamID")
        for row in exam_enrollments
    )

    exam_by_id = {}

    for exam in exams:
        exam_id = to_int(exam["ExamID"], "ExamID")

        if exam_id in exam_by_id:
            raise ValueError(f"Duplicate ExamID: {exam_id}")

        exam_by_id[exam_id] = exam

    if len(exam_by_id) != EXPECTED_EXAMS:
        raise ValueError(
            f"Expected {EXPECTED_EXAMS} exams; found {len(exam_by_id)}."
        )

    if set(exam_count) != set(exam_by_id):
        raise ValueError(
            "Exam and ExamEnrollment source coverage is invalid."
        )

    standard_duration = to_int(
        config["duration_rules"]["standard_duration_minutes"],
        "standard_duration_minutes",
    )

    if standard_duration != 90:
        raise ValueError(
            f"Expected standard duration 90 minutes; got {standard_duration}."
        )

    timetable = []
    slot_counts = Counter()
    slot_students = Counter()

    for exam_id in sorted(exam_by_id):
        exam = exam_by_id[exam_id]
        course_id = to_int(exam["CourseID"], "CourseID")

        # Dataset convention: three consecutive ExamIDs per course.
        sitting_ordinal = ((exam_id - 1) % 3) + 1

        if course_id <= EXPECTED_COMPULSORY_COURSES:
            course_role = "COMPULSORY"
            track_id = compulsory_course_track[course_id]
            block_id = course_block[course_id]
        else:
            course_role = "OPTIONAL"
            track_id = ""
            block_id = optional_block[course_id]

        block = blocks[block_id]

        slot_number = block["StartSlot"] + sitting_ordinal - 1
        exam_date = block["ExamDate"]

        slot_start = config["calendar"]["slot_start_times"][
            slot_number - 1
        ]

        start_datetime = datetime.strptime(
            f"{exam_date} {slot_start}",
            "%Y-%m-%d %H:%M",
        )

        end_datetime = start_datetime + timedelta(
            minutes=standard_duration
        )

        student_count = exam_count[exam_id]

        if student_count <= 0:
            raise ValueError(
                f"Exam {exam_id} has no registered students."
            )

        slot_key = (exam_date, slot_number)
        slot_counts[slot_key] += 1
        slot_students[slot_key] += student_count

        timetable.append({
            "ExamID": exam_id,
            "ExamCode": exam["ExamCode"],
            "CourseID": course_id,
            "SittingOrdinal": sitting_ordinal,
            "CourseRole": course_role,
            "TrackID": track_id,
            "BlockID": block_id,
            "ExamDate": exam_date,
            "DayIndex": block["DayIndex"],
            "SlotNumber": slot_number,
            "SlotStartTime": slot_start,
            "SlotEndTime": end_datetime.strftime("%H:%M"),
            "StartDateTime": start_datetime.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "EndDateTime": end_datetime.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "EnrolledStudentCount": student_count,
        })

    return timetable, slot_counts, slot_students


# ============================================================
# BUILD STUDENT TIMETABLE WITH ACCOMMODATIONS
# ============================================================

def build_student_allocations(
    sitting_allocations,
    timetable,
    accommodations,
    standard_duration=90,
):
    timetable_by_exam = {
        to_int(row["ExamID"], "ExamID"): row
        for row in timetable
    }

    accommodation_by_student = defaultdict(list)

    for accommodation in accommodations:
        if (
            accommodation["AccommodationType"].strip().upper()
            != "EXTENDED_TIME"
        ):
            continue

        if (
            accommodation["AccommodationStatus"].strip().upper()
            != "ACTIVE"
        ):
            continue

        student_id = to_int(
            accommodation["StudentID"],
            "Accommodation.StudentID",
        )

        accommodation_by_student[student_id].append(accommodation)

    allocations = []
    seen_enrollments = set()

    for source in sitting_allocations:
        enrollment_id = to_int(
            source["EnrollmentID"],
            "EnrollmentID",
        )

        if enrollment_id in seen_enrollments:
            raise ValueError(
                f"Duplicate SittingAllocation EnrollmentID {enrollment_id}."
            )

        seen_enrollments.add(enrollment_id)

        exam_id = to_int(source["ExamID"], "ExamID")
        scheduled = timetable_by_exam.get(exam_id)

        if scheduled is None:
            raise ValueError(
                f"Missing timetable row for exam {exam_id}."
            )

        student_id = to_int(source["StudentID"], "StudentID")

        exam_date = datetime.strptime(
            scheduled["ExamDate"],
            "%Y-%m-%d",
        ).date()

        extensions = []

        for accommodation in accommodation_by_student.get(
            student_id, []
        ):
            start_date = datetime.strptime(
                accommodation["EffectiveFrom"],
                "%Y-%m-%d",
            ).date()

            end_raw = (
                accommodation.get("EffectiveTo") or ""
            ).strip()

            end_date = (
                datetime.strptime(end_raw, "%Y-%m-%d").date()
                if end_raw
                else None
            )

            if (
                start_date <= exam_date
                and (end_date is None or exam_date <= end_date)
            ):
                extensions.append(
                    float(accommodation["ExtensionPercentage"])
                )

        if len(extensions) > 1:
            raise ValueError(
                f"Student {student_id} has multiple active "
                f"extended-time records on {exam_date}."
            )

        extension = extensions[0] if extensions else 0.0

        effective_duration = int(
            math.ceil(
                standard_duration * (1.0 + extension / 100.0)
            )
        )

        start_datetime = datetime.strptime(
            scheduled["StartDateTime"],
            "%Y-%m-%d %H:%M:%S",
        )

        effective_end = start_datetime + timedelta(
            minutes=effective_duration
        )

        slot_id = (
            (int(scheduled["DayIndex"]) - 1) * 6
            + int(scheduled["SlotNumber"])
        )

        allocations.append({
            "EnrollmentID": enrollment_id,
            "StudentID": student_id,
            "CourseID": source["CourseID"],
            "ExamID": exam_id,
            "EnrollmentType": source["EnrollmentType"],
            "TrackID": source["TrackID"],
            "SittingOrdinal": source["SittingOrdinal"],
            "ExamDate": scheduled["ExamDate"],
            "SlotNumber": scheduled["SlotNumber"],
            "SlotID": slot_id,
            "StartDateTime": scheduled["StartDateTime"],
            "EndDateTime": scheduled["EndDateTime"],
            "EffectiveDurationMinutes": effective_duration,
            "EffectiveEndDateTime": effective_end.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "HasExtendedTime": 1 if extension > 0 else 0,
        })

    return allocations


# ============================================================
# VALIDATION
# ============================================================

def validate_timetable(
    config,
    data,
    blocks,
    course_block,
    optional_block,
    track_course_rows,
    timetable,
    student_allocations,
    slot_counts,
):
    errors = []

    def add_error(message):
        if len(errors) < 500:
            errors.append(message)

    expected_counts = {
        "students": EXPECTED_STUDENTS,
        "tracks": EXPECTED_TRACKS,
        "courses": EXPECTED_COURSES,
        "exams": EXPECTED_EXAMS,
        "student allocations": EXPECTED_ALLOCATIONS,
    }

    actual_counts = {
        "students": len(data["students"]),
        "tracks": len(data["tracks"]),
        "courses": len(data["courses"]),
        "exams": len(timetable),
        "student allocations": len(student_allocations),
    }

    for label, expected in expected_counts.items():
        if actual_counts[label] != expected:
            add_error(
                f"Expected {expected} {label}; "
                f"found {actual_counts[label]}."
            )

    exam_ids = [
        to_int(row["ExamID"], "ExamID")
        for row in timetable
    ]

    if len(exam_ids) != len(set(exam_ids)):
        add_error("Duplicate exam assignments detected.")

    expected_exam_ids = {
        to_int(row["ExamID"], "ExamID")
        for row in data["exams"]
    }

    if set(exam_ids) != expected_exam_ids:
        add_error(
            "Exam timetable does not cover every source exam exactly once."
        )

    # --------------------------------------------------------
    # Timetable and course sitting validation
    # --------------------------------------------------------

    by_course = defaultdict(list)

    for row in timetable:
        course_id = int(row["CourseID"])
        by_course[course_id].append(row)

        if row["CourseRole"] == "COMPULSORY":
            if int(row["DayIndex"]) not in range(1, 6):
                add_error(
                    f"Compulsory exam {row['ExamID']} not on Days 1-5."
                )

            if (
                int(row["BlockID"])
                != course_block.get(course_id)
            ):
                add_error(
                    f"Wrong block for compulsory course {course_id}."
                )

        else:
            if (
                int(row["DayIndex"]) != 6
                or int(row["SlotNumber"]) not in (1, 2, 3)
            ):
                add_error(
                    f"Optional exam {row['ExamID']} "
                    "outside Day 6 slots 1-3."
                )

    if len(by_course) != EXPECTED_COURSES:
        add_error(
            f"Expected 300 courses; found {len(by_course)}."
        )

    for course_id, rows in by_course.items():
        rows.sort(
            key=lambda row: int(row["SittingOrdinal"])
        )

        if len(rows) != 3:
            add_error(
                f"Course {course_id} must have 3 sittings."
            )
            continue

        ordinals = [
            int(row["SittingOrdinal"])
            for row in rows
        ]

        if ordinals != [1, 2, 3]:
            add_error(
                f"Course {course_id} sitting ordinals invalid."
            )

        dates = {row["ExamDate"] for row in rows}
        block_ids = {
            int(row["BlockID"])
            for row in rows
        }

        if len(dates) != 1 or len(block_ids) != 1:
            add_error(
                f"Course {course_id} sittings not in one block/day."
            )

        slots = [
            int(row["SlotNumber"])
            for row in rows
        ]

        if slots != list(range(slots[0], slots[0] + 3)):
            add_error(
                f"Course {course_id} sittings are not consecutive."
            )

    # --------------------------------------------------------
    # Track-course mapping validation
    # --------------------------------------------------------

    if len(track_course_rows) != 225:
        add_error(
            f"Expected 225 track-course rows; "
            f"found {len(track_course_rows)}."
        )

    track_days = defaultdict(set)
    block_load = Counter()

    for row in track_course_rows:
        track_id = int(row["TrackID"])
        course_id = int(row["CourseID"])
        block_id = int(row["BlockID"])

        track_days[track_id].add(int(row["DayIndex"]))
        block_load[block_id] += 1

        if course_block.get(course_id) != block_id:
            add_error(
                f"TrackCourse placement mismatch for course {course_id}."
            )

    for track_id in range(1, 76):
        if len(track_days[track_id]) != 3:
            add_error(
                f"Track {track_id} compulsory courses are not "
                "on 3 distinct days."
            )

    if any(
        block_load[block_id] not in (22, 23)
        for block_id in COMPULSORY_BLOCK_IDS
    ):
        add_error(
            f"Compulsory block loads are not balanced: {dict(block_load)}"
        )

    if (
        set(optional_block) != set(range(226, 301))
        or any(
            block_id != OPTIONAL_BLOCK_ID
            for block_id in optional_block.values()
        )
    ):
        add_error(
            "Optional courses must all map to block 11."
        )

    # --------------------------------------------------------
    # Student allocation and effective-time validation
    # --------------------------------------------------------

    enrollment_by_id = {
        int(row["EnrollmentID"]): row
        for row in data["enrollments"]
    }

    source_sitting = {
        int(row["EnrollmentID"]): row
        for row in data["sitting_allocations"]
    }

    exam_students = defaultdict(set)

    for row in data["exam_enrollments"]:
        exam_id = int(row["ExamID"])
        enrollment = enrollment_by_id.get(
            int(row["EnrollmentID"])
        )

        if enrollment:
            exam_students[exam_id].add(
                int(enrollment["StudentID"])
            )

    student_rows = defaultdict(list)
    seen_enrollments = set()

    for row in student_allocations:
        exam_id = int(row["ExamID"])
        student_id = int(row["StudentID"])
        enrollment_id = int(row["EnrollmentID"])

        if enrollment_id in seen_enrollments:
            add_error(
                f"Duplicate allocation EnrollmentID {enrollment_id}."
            )

        seen_enrollments.add(enrollment_id)

        source = enrollment_by_id.get(enrollment_id)

        if source is None:
            add_error(
                f"Unknown EnrollmentID {enrollment_id}."
            )
        else:
            if int(source["StudentID"]) != student_id:
                add_error(
                    f"StudentID mismatch for EnrollmentID {enrollment_id}."
                )

            if int(source["CourseID"]) != int(row["CourseID"]):
                add_error(
                    f"CourseID mismatch for EnrollmentID {enrollment_id}."
                )

        source_row = source_sitting.get(enrollment_id)

        if (
            source_row is None
            or int(source_row["ExamID"]) != exam_id
        ):
            add_error(
                f"SittingAllocation mismatch for EnrollmentID {enrollment_id}."
            )

        start = datetime.strptime(
            row["StartDateTime"],
            "%Y-%m-%d %H:%M:%S",
        )

        effective_end = datetime.strptime(
            row["EffectiveEndDateTime"],
            "%Y-%m-%d %H:%M:%S",
        )

        base_end = datetime.strptime(
            row["EndDateTime"],
            "%Y-%m-%d %H:%M:%S",
        )

        duration = int(row["EffectiveDurationMinutes"])

        if effective_end - start != timedelta(minutes=duration):
            add_error(
                f"Effective duration mismatch for student {student_id}, "
                f"exam {exam_id}."
            )

        if effective_end < base_end:
            add_error(
                f"Effective end precedes standard end for student "
                f"{student_id}, exam {exam_id}."
            )

        if duration not in (90, 120):
            add_error(
                f"Unexpected effective duration {duration} for "
                f"student {student_id}, exam {exam_id}."
            )

        student_rows[student_id].append(row)

    if len(student_rows) != EXPECTED_STUDENTS:
        add_error(
            f"Expected 5000 students in allocations; "
            f"found {len(student_rows)}."
        )

    overlap_count = 0
    extended_count = 0
    extended_students = set()

    for student_id, rows in student_rows.items():
        if len(rows) != 4:
            add_error(
                f"Student {student_id} has {len(rows)} allocations; "
                "expected 4."
            )

        compulsory = [
            row for row in rows
            if row["EnrollmentType"].upper() == "COMPULSORY"
        ]

        optional = [
            row for row in rows
            if row["EnrollmentType"].upper() == "OPTIONAL"
        ]

        if len(compulsory) != 3 or len(optional) != 1:
            add_error(
                f"Student {student_id} must have 3 compulsory + 1 optional."
            )

        compulsory_days = {
            row["ExamDate"]
            for row in compulsory
        }

        if len(compulsory_days) != 3:
            add_error(
                f"Student {student_id} compulsory exams are not "
                "on 3 distinct days."
            )

        ordered = sorted(
            rows,
            key=lambda row: row["StartDateTime"],
        )

        for previous, current in zip(ordered, ordered[1:]):
            previous_end = datetime.strptime(
                previous["EffectiveEndDateTime"],
                "%Y-%m-%d %H:%M:%S",
            )

            current_start = datetime.strptime(
                current["StartDateTime"],
                "%Y-%m-%d %H:%M:%S",
            )

            if current_start < previous_end:
                overlap_count += 1
                add_error(
                    f"Student {student_id} has effective-time overlap: "
                    f"exams {previous['ExamID']} and {current['ExamID']}."
                )

        for row in rows:
            if int(row["HasExtendedTime"]):
                extended_count += 1
                extended_students.add(student_id)

    if len(seen_enrollments) != EXPECTED_ALLOCATIONS:
        add_error(
            "Allocation EnrollmentID count is not 20,000."
        )

    source_pairs = set()

    for row in data["exam_enrollments"]:
        enrollment = enrollment_by_id.get(
            int(row["EnrollmentID"])
        )

        if enrollment:
            source_pairs.add((
                int(enrollment["StudentID"]),
                int(row["ExamID"]),
            ))

    output_pairs = {
        (int(row["StudentID"]), int(row["ExamID"]))
        for row in student_allocations
    }

    if (
        source_pairs != output_pairs
        or len(source_pairs) != len(data["exam_enrollments"])
    ):
        add_error(
            "Output student/exam pairs differ from ExamEnrollment."
        )

    # --------------------------------------------------------
    # Physical slot screening
    # --------------------------------------------------------

    max_rooms = to_int(
        config["physical_infrastructure"]["rooms"],
        "rooms",
    )

    if max_rooms != EXPECTED_ROOMS:
        add_error(
            f"Expected 100 rooms; found {max_rooms}."
        )

    if any(count > max_rooms for count in slot_counts.values()):
        add_error(
            "A slot exceeds the number of physical rooms."
        )

    for slot in (1, 2, 3):
        day_six = config["calendar"]["days"][5]

        if slot_counts[(day_six, slot)] != 75:
            add_error(
                f"Day 6 slot {slot} must have 75 optional sittings."
            )

    metrics = {
        "block_load": dict(block_load),
        "extended_time_students": len(extended_students),
        "extended_time_allocations": extended_count,
        "effective_interval_overlaps": overlap_count,
    }

    return errors, metrics


# ============================================================
# SLOT LOAD REPORT
# ============================================================

def create_slot_report(
    timetable,
    slot_counts,
    slot_students,
    config,
):
    rows = []

    standard_duration = to_int(
        config["duration_rules"]["standard_duration_minutes"],
        "standard_duration_minutes",
    )

    for day_index, exam_date in enumerate(
        config["calendar"]["days"],
        start=1,
    ):
        for slot_number, start_time in enumerate(
            config["calendar"]["slot_start_times"],
            start=1,
        ):
            start_datetime = datetime.strptime(
                f"{exam_date} {start_time}",
                "%Y-%m-%d %H:%M",
            )

            end_datetime = start_datetime + timedelta(
                minutes=standard_duration
            )

            key = (exam_date, slot_number)

            rows.append({
                "ExamDate": exam_date,
                "DayIndex": day_index,
                "SlotNumber": slot_number,
                "StartTime": start_time,
                "EndTime": end_datetime.strftime("%H:%M"),
                "ExamSittingCount": slot_counts[key],
                "TotalStudentCount": slot_students[key],
            })

    return rows


# ============================================================
# MAIN
# ============================================================

def main():
    config, data = load_inputs()

    print("=" * 76)
    print("EXAM SCHEDULING SYSTEM - TIMETABLE ALLOCATOR V2.2.0")
    print("=" * 76)

    blocks = create_blocks(config)

    print(
        "[1/6] Assigning each track's 3 compulsory courses "
        "to 3 different days..."
    )

    (
        course_block,
        track_course_rows,
        block_load,
    ) = assign_track_course_blocks(
        data["tracks"],
        data["track_courses"],
        blocks,
    )

    print(
        "[2/6] Reserving Day 6 slots 1-3 for optional courses..."
    )

    optional_block, optional_course_tracks = (
        assign_optional_course_blocks(
            data["classifications"],
            data["student_tracks"],
            blocks,
        )
    )

    compulsory_course_track = build_course_mappings(
        data["track_courses"]
    )

    print("[3/6] Building all 900 exam sittings...")

    timetable, slot_counts, slot_students = build_timetable(
        config,
        data["exams"],
        blocks,
        course_block,
        optional_block,
        compulsory_course_track,
        data["exam_enrollments"],
    )

    print(
        "[4/6] Building student allocations with "
        "effective accommodation durations..."
    )

    student_allocations = build_student_allocations(
        data["sitting_allocations"],
        timetable,
        data["accommodations"],
        int(config["duration_rules"]["standard_duration_minutes"]),
    )

    print(
        "[5/6] Validating standard and extended-time "
        "student intervals..."
    )

    errors, metrics = validate_timetable(
        config,
        data,
        blocks,
        course_block,
        optional_block,
        track_course_rows,
        timetable,
        student_allocations,
        slot_counts,
    )

    if errors:
        print("\nTIMETABLE VALIDATION FAILED")

        for issue in errors[:100]:
            print(" -", issue)

        print(f"Total errors reported: {len(errors)}")
        print("No timetable output files were replaced.")
        return 1

    # All validations pass before output files are replaced.
    SCHEDULING_DIR.mkdir(parents=True, exist_ok=True)

    write_csv(
        SCHEDULING_DIR / "ExamTimetable.csv",
        timetable,
        [
            "ExamID",
            "ExamCode",
            "CourseID",
            "SittingOrdinal",
            "CourseRole",
            "TrackID",
            "BlockID",
            "ExamDate",
            "DayIndex",
            "SlotNumber",
            "SlotStartTime",
            "SlotEndTime",
            "StartDateTime",
            "EndDateTime",
            "EnrolledStudentCount",
        ],
    )

    write_csv(
        SCHEDULING_DIR / "TimetableStudentAllocation.csv",
        student_allocations,
        [
            "EnrollmentID",
            "StudentID",
            "CourseID",
            "ExamID",
            "EnrollmentType",
            "TrackID",
            "SittingOrdinal",
            "ExamDate",
            "SlotNumber",
            "SlotID",
            "StartDateTime",
            "EndDateTime",
            "EffectiveDurationMinutes",
            "EffectiveEndDateTime",
            "HasExtendedTime",
        ],
    )

    slot_report = create_slot_report(
        timetable,
        slot_counts,
        slot_students,
        config,
    )

    write_csv(
        SCHEDULING_DIR / "SlotLoad.csv",
        slot_report,
        [
            "ExamDate",
            "DayIndex",
            "SlotNumber",
            "StartTime",
            "EndTime",
            "ExamSittingCount",
            "TotalStudentCount",
        ],
    )

    write_csv(
        SCHEDULING_DIR / "TrackBlockAllocation.csv",
        track_course_rows,
        [
            "TrackID",
            "CourseID",
            "CourseOrdinal",
            "BlockID",
            "DayIndex",
            "ExamDate",
            "Period",
        ],
    )

    optional_rows = [
        {
            "CourseID": course_id,
            "BlockID": block_id,
            "ExamDate": blocks[block_id]["ExamDate"],
            "Period": blocks[block_id]["Period"],
            "AffectedTrackCount": len(
                optional_course_tracks[course_id]
            ),
        }
        for course_id, block_id in sorted(optional_block.items())
    ]

    write_csv(
        SCHEDULING_DIR / "OptionalCourseBlockAllocation.csv",
        optional_rows,
        [
            "CourseID",
            "BlockID",
            "ExamDate",
            "Period",
            "AffectedTrackCount",
        ],
    )

    report = {
        "version": "2.2.0",
        "algorithm": (
            "Three distinct compulsory exam days per track; "
            "optional exams on Day 6 slots 1-3"
        ),
        "status": "PASSED",
        "database_accessed": False,
        "database_modified": False,
        "counts": {
            "students": len(data["students"]),
            "tracks": len(data["tracks"]),
            "courses": len(data["courses"]),
            "compulsory_courses": 225,
            "optional_courses": 75,
            "exams_scheduled": len(timetable),
            "student_exam_allocations": len(student_allocations),
            "track_course_day_assignments": len(track_course_rows),
            "timetable_blocks": len(blocks),
            "physical_room_slot_units": 3600,
        },
        "compulsory_block_course_load": {
            str(block_id): block_load[block_id]
            for block_id in COMPULSORY_BLOCK_IDS
        },
        "optional_exam_slot_load": {
            str(slot): slot_counts[
                (config["calendar"]["days"][5], slot)
            ]
            for slot in (1, 2, 3)
        },
        "validation": metrics,
        "limitations": [
            "This is timetable allocation, not physical room assignment.",
            "Room batch capacity, closures, effective-dated room capacity, "
            "equipment changeovers and invigilator assignments remain "
            "to be validated.",
            "Extended-time intervals are checked at student level; "
            "room-level extended-time occupancy is not yet allocated.",
            "SQL Server was not accessed or modified.",
        ],
    }

    write_json(
        SCHEDULING_DIR / "timetable_report.json",
        report,
    )

    print("\n" + "=" * 76)
    print("V2.2.0 TIMETABLE ALLOCATION SUCCESSFUL")
    print("=" * 76)

    for key, value in report["counts"].items():
        print(f"{key:38} {value:>8,}")

    print("\nCompulsory course load by block:")

    for block_id in COMPULSORY_BLOCK_IDS:
        print(
            f"Block {block_id:02}: {block_load[block_id]} courses"
        )

    print(
        f"\nExtended-time students: "
        f"{metrics['extended_time_students']}"
    )

    print(
        f"Extended-time allocations: "
        f"{metrics['extended_time_allocations']}"
    )

    print(
        f"Effective interval overlaps: "
        f"{metrics['effective_interval_overlaps']}"
    )

    print("\nOutput:", SCHEDULING_DIR)
    print("SQL Server: NOT ACCESSED OR MODIFIED")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("\nTIMETABLE ALLOCATOR FAILED")
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)