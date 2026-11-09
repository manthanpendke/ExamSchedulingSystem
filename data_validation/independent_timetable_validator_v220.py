from __future__ import annotations

import csv
import json
import math
import sys

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


# ============================================================
# PATHS AND CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

REPORT_PATH = (
    SCHED / "independent_timetable_validation_report_v220.json"
)

EXPECTED_STUDENTS = 5000
EXPECTED_TRACKS = 75
EXPECTED_COURSES = 300
EXPECTED_EXAMS = 900
EXPECTED_ALLOCATIONS = 20000

EXPECTED_OPTIONAL_BLOCKS = {
    11: 38,
    12: 37,
}

EXPECTED_OPTIONAL_SLOT_LOADS = {
    1: 38,
    2: 38,
    3: 38,
    4: 37,
    5: 37,
    6: 37,
}


# ============================================================
# FILE HELPERS
# ============================================================

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                f"CSV has no header: {path}"
            )

        return list(reader)


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required JSON file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def integer(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid integer in {field}: {value!r}"
        )


def parse_datetime(value, field):
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S",
        )
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid datetime in {field}: {value!r}"
        )


def parse_date(value, field):
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid date in {field}: {value!r}"
        )


def normalized(value):
    return str(value or "").strip().upper()


# ============================================================
# VALIDATION ENTRY POINT
# ============================================================

def main():

    print("\n" + "=" * 76)
    print("INDEPENDENT TIMETABLE VALIDATOR — V2.2.0")
    print("Extended-time and optional-wave validation")
    print("=" * 76)

    config = read_json(
        ROOT / "config" / "dataset_config_v220.json"
    )

    students = read_csv(DATA / "Student.csv")
    courses = read_csv(DATA / "Course.csv")
    enrollments = read_csv(DATA / "Enrollment.csv")
    exams = read_csv(DATA / "Exam.csv")
    exam_enrollments = read_csv(DATA / "ExamEnrollment.csv")
    accommodations = read_csv(DATA / "Accommodation.csv")

    tracks = read_csv(META / "Track.csv")
    track_courses = read_csv(META / "TrackCourse.csv")
    student_tracks = read_csv(META / "StudentTrack.csv")
    classifications = read_csv(
        META / "EnrollmentClassification.csv"
    )
    sitting_allocations = read_csv(
        META / "SittingAllocation.csv"
    )

    timetable = read_csv(
        SCHED / "ExamTimetable.csv"
    )
    allocations = read_csv(
        SCHED / "TimetableStudentAllocation.csv"
    )
    slot_load = read_csv(
        SCHED / "SlotLoad.csv"
    )
    track_course_blocks = read_csv(
        SCHED / "TrackBlockAllocation.csv"
    )
    optional_blocks = read_csv(
        SCHED / "OptionalCourseBlockAllocation.csv"
    )

    errors = []
    checks = 0

    def check(condition, message):
        nonlocal checks

        checks += 1

        if not condition and len(errors) < 1000:
            errors.append(message)

    # ========================================================
    # 1. COUNTS AND UNIQUE SOURCE IDS
    # ========================================================

    print("\n[1/8] Checking source record counts...")

    check(
        len(students) == EXPECTED_STUDENTS,
        f"Expected 5000 students; found {len(students)}.",
    )

    check(
        len(tracks) == EXPECTED_TRACKS,
        f"Expected 75 tracks; found {len(tracks)}.",
    )

    check(
        len(courses) == EXPECTED_COURSES,
        f"Expected 300 courses; found {len(courses)}.",
    )

    check(
        len(exams) == EXPECTED_EXAMS,
        f"Expected 900 source exams; found {len(exams)}.",
    )

    check(
        len(timetable) == EXPECTED_EXAMS,
        f"Expected 900 timetable rows; found {len(timetable)}.",
    )

    check(
        len(allocations) == EXPECTED_ALLOCATIONS,
        f"Expected 20000 allocations; found {len(allocations)}.",
    )

    check(
        len(track_course_blocks) == 225,
        f"Expected 225 track-course block rows; found {len(track_course_blocks)}.",
    )

    check(
        len(optional_blocks) == 75,
        f"Expected 75 optional course block rows; found {len(optional_blocks)}.",
    )

    exam_by_id = {}

    for row in exams:
        exam_id = integer(
            row["ExamID"],
            "Exam.ExamID",
        )

        check(
            exam_id not in exam_by_id,
            f"Duplicate source ExamID {exam_id}.",
        )

        exam_by_id[exam_id] = row

    timetable_by_id = {}

    for row in timetable:
        exam_id = integer(
            row["ExamID"],
            "Timetable.ExamID",
        )

        check(
            exam_id not in timetable_by_id,
            f"Duplicate timetable ExamID {exam_id}.",
        )

        timetable_by_id[exam_id] = row

    check(
        set(exam_by_id) == set(timetable_by_id),
        "Timetable ExamIDs do not match source ExamIDs.",
    )

    # ========================================================
    # 2. TRACK, COURSE AND DAY MAPPINGS
    # ========================================================

    print("\n[2/8] Rebuilding track/course/day mappings...")

    dates = config["calendar"]["days"]
    slot_starts = config["calendar"]["slot_start_times"]

    check(
        len(dates) == 6,
        "Calendar must contain exactly 6 days.",
    )

    check(
        len(slot_starts) == 6,
        "Calendar must contain exactly 6 slot start times.",
    )

    student_track = {}

    for row in student_tracks:
        student_id = integer(
            row["StudentID"],
            "StudentTrack.StudentID",
        )

        track_id = integer(
            row["TrackID"],
            "StudentTrack.TrackID",
        )

        check(
            student_id not in student_track,
            f"Duplicate StudentTrack mapping for student {student_id}.",
        )

        student_track[student_id] = track_id

    check(
        len(student_track) == EXPECTED_STUDENTS,
        "StudentTrack must map all 5000 students.",
    )

    compulsory_course_track = {}
    track_courses_by_track = defaultdict(list)

    for row in track_courses:
        course_id = integer(
            row["CourseID"],
            "TrackCourse.CourseID",
        )

        track_id = integer(
            row["TrackID"],
            "TrackCourse.TrackID",
        )

        check(
            course_id not in compulsory_course_track,
            f"Course {course_id} maps to multiple tracks.",
        )

        compulsory_course_track[course_id] = track_id
        track_courses_by_track[track_id].append(course_id)

    check(
        set(compulsory_course_track) == set(range(1, 226)),
        "TrackCourse must map compulsory courses 1-225.",
    )

    for track_id in range(1, 76):
        check(
            len(track_courses_by_track[track_id]) == 3,
            f"Track {track_id} must have exactly 3 compulsory courses.",
        )

    track_course_map = {}
    block_load = Counter()
    track_days = defaultdict(set)

    for row in track_course_blocks:

        track_id = integer(
            row["TrackID"],
            "TrackBlock.TrackID",
        )

        course_id = integer(
            row["CourseID"],
            "TrackBlock.CourseID",
        )

        ordinal = integer(
            row["CourseOrdinal"],
            "TrackBlock.CourseOrdinal",
        )

        block_id = integer(
            row["BlockID"],
            "TrackBlock.BlockID",
        )

        day_index = integer(
            row["DayIndex"],
            "TrackBlock.DayIndex",
        )

        key = (track_id, course_id)

        check(
            key not in track_course_map,
            f"Duplicate track-course placement {key}.",
        )

        track_course_map[key] = row

        block_load[block_id] += 1
        track_days[track_id].add(day_index)

        check(
            compulsory_course_track.get(course_id) == track_id,
            f"Track/course mapping mismatch for {key}.",
        )

        check(
            1 <= day_index <= 5
            and 1 <= block_id <= 10,
            f"Invalid compulsory day/block for {key}.",
        )

        check(
            (block_id + 1) // 2 == day_index,
            f"Block {block_id} does not correspond to day {day_index} for {key}.",
        )

        check(
            row["ExamDate"] == dates[day_index - 1],
            f"Track-course date mismatch for {key}.",
        )

        check(
            ordinal in (1, 2, 3),
            f"Invalid course ordinal for {key}.",
        )

    check(
        len(track_course_map) == 225,
        "Track-course mapping must contain 225 unique pairs.",
    )

    for track_id in range(1, 76):
        check(
            len(track_days[track_id]) == 3,
            f"Track {track_id} must have compulsory courses on 3 distinct days.",
        )

    check(
        all(
            block_load[block_id] in (22, 23)
            for block_id in range(1, 11)
        ),
        f"Compulsory block loads must be balanced 22/23: {dict(block_load)}",
    )

    # ========================================================
    # 3. OPTIONAL COURSE BLOCK ALLOCATION
    # ========================================================

    print("\n[3/8] Checking optional-course wave allocation...")

    optional_map = {}

    for row in optional_blocks:

        course_id = integer(
            row["CourseID"],
            "OptionalCourseBlockAllocation.CourseID",
        )

        block_id = integer(
            row["BlockID"],
            "OptionalCourseBlockAllocation.BlockID",
        )

        check(
            course_id not in optional_map,
            f"Duplicate optional course {course_id}.",
        )

        optional_map[course_id] = block_id

    check(
        set(optional_map) == set(range(226, 301)),
        "Optional block allocation must cover courses 226-300.",
    )

    optional_block_distribution = Counter(
        optional_map.values()
    )

    check(
        optional_block_distribution
        == Counter(EXPECTED_OPTIONAL_BLOCKS),
        "Optional courses must be split into Block 11: 38 and "
        f"Block 12: 37. Found {dict(optional_block_distribution)}.",
    )

    # ========================================================
    # 4. TIMETABLE, CALENDAR AND SITTINGS
    # ========================================================

    print("\n[4/8] Checking timetable dates, slots and exam sittings...")

    standard_duration = integer(
        config["duration_rules"]["standard_duration_minutes"],
        "standard_duration_minutes",
    )

    check(
        standard_duration == 90,
        "Standard exam duration must be 90 minutes.",
    )

    exam_counts = Counter(
        integer(
            row["ExamID"],
            "ExamEnrollment.ExamID",
        )
        for row in exam_enrollments
    )

    course_sittings = defaultdict(list)
    slot_counts = Counter()

    for exam_id, row in timetable_by_id.items():

        course_id = integer(
            row["CourseID"],
            "Timetable.CourseID",
        )

        ordinal = integer(
            row["SittingOrdinal"],
            "Timetable.SittingOrdinal",
        )

        day_index = integer(
            row["DayIndex"],
            "Timetable.DayIndex",
        )

        slot_number = integer(
            row["SlotNumber"],
            "Timetable.SlotNumber",
        )

        block_id = integer(
            row["BlockID"],
            "Timetable.BlockID",
        )

        check(
            integer(
                exam_by_id[exam_id]["CourseID"],
                "Exam.CourseID",
            ) == course_id,
            f"Exam {exam_id} CourseID mismatch.",
        )

        check(
            ordinal == ((exam_id - 1) % 3) + 1,
            f"Exam {exam_id} sitting ordinal mismatch.",
        )

        check(
            1 <= day_index <= 6
            and 1 <= slot_number <= 6,
            f"Exam {exam_id} has invalid day/slot.",
        )

        if not (
            1 <= day_index <= 6
            and 1 <= slot_number <= 6
        ):
            continue

        check(
            row["ExamDate"] == dates[day_index - 1],
            f"Exam {exam_id} date/day mismatch.",
        )

        check(
            row["SlotStartTime"] == slot_starts[slot_number - 1],
            f"Exam {exam_id} slot start mismatch.",
        )

        start = parse_datetime(
            row["StartDateTime"],
            "Timetable.StartDateTime",
        )

        end = parse_datetime(
            row["EndDateTime"],
            "Timetable.EndDateTime",
        )

        check(
            end - start == timedelta(minutes=standard_duration),
            f"Exam {exam_id} base duration is not 90 minutes.",
        )

        check(
            row["SlotEndTime"] == end.strftime("%H:%M"),
            f"Exam {exam_id} SlotEndTime mismatch.",
        )

        check(
            integer(
                row["EnrolledStudentCount"],
                "EnrolledStudentCount",
            ) == exam_counts[exam_id],
            f"Exam {exam_id} enrolled student count mismatch.",
        )

        if course_id <= 225:

            check(
                normalized(row["CourseRole"]) == "COMPULSORY",
                f"Course {course_id} should be compulsory.",
            )

            track_id = integer(
                row["TrackID"],
                "Timetable.TrackID",
            )

            mapping = track_course_map.get(
                (track_id, course_id)
            )

            check(
                mapping is not None,
                f"Missing track-course mapping for {track_id}/{course_id}.",
            )

            if mapping:
                check(
                    block_id == integer(
                        mapping["BlockID"],
                        "TrackBlock.BlockID",
                    )
                    and day_index == integer(
                        mapping["DayIndex"],
                        "TrackBlock.DayIndex",
                    ),
                    f"Exam {exam_id} differs from track-course block mapping.",
                )

            check(
                day_index <= 5,
                f"Compulsory course {course_id} scheduled on Day 6.",
            )

        else:

            check(
                normalized(row["CourseRole"]) == "OPTIONAL",
                f"Course {course_id} should be optional.",
            )

            check(
                block_id == optional_map.get(course_id),
                f"Optional course {course_id} block mismatch.",
            )

            if optional_map.get(course_id) == 11:
                expected_slots = (1, 2, 3)

            elif optional_map.get(course_id) == 12:
                expected_slots = (4, 5, 6)

            else:
                expected_slots = ()

            check(
                day_index == 6
                and slot_number in expected_slots,
                f"Optional course {course_id} is outside its approved "
                f"Day 6 wave slots {expected_slots}.",
            )

            check(
                str(row["TrackID"]).strip() == "",
                f"Optional course {course_id} should have blank TrackID.",
            )

        course_sittings[course_id].append(row)

        slot_counts[
            (row["ExamDate"], slot_number)
        ] += 1

    check(
        set(course_sittings) == set(range(1, 301)),
        "Timetable must cover courses 1-300.",
    )

    for course_id, rows in course_sittings.items():

        rows.sort(
            key=lambda row: integer(
                row["SittingOrdinal"],
                "SittingOrdinal",
            )
        )

        check(
            len(rows) == 3,
            f"Course {course_id} must have exactly 3 sittings.",
        )

        if len(rows) != 3:
            continue

        slots = [
            integer(row["SlotNumber"], "SlotNumber")
            for row in rows
        ]

        check(
            slots == list(range(slots[0], slots[0] + 3)),
            f"Course {course_id} sittings are not consecutive.",
        )

        check(
            len({row["ExamDate"] for row in rows}) == 1,
            f"Course {course_id} sittings are not on the same date.",
        )

        check(
            len({
                integer(row["BlockID"], "BlockID")
                for row in rows
            }) == 1,
            f"Course {course_id} sittings are not in the same block.",
        )

    # ========================================================
    # 5. STUDENT ENROLLMENT AND SITTING RELATIONSHIPS
    # ========================================================

    print("\n[5/8] Validating student enrollment and sitting relationships...")

    enrollment_by_id = {
        integer(row["EnrollmentID"], "EnrollmentID"): row
        for row in enrollments
    }

    classification_by_enrollment = {
        integer(
            row["EnrollmentID"],
            "Classification.EnrollmentID",
        ): row
        for row in classifications
    }

    sitting_by_enrollment = {
        integer(
            row["EnrollmentID"],
            "SittingAllocation.EnrollmentID",
        ): row
        for row in sitting_allocations
    }

    student_rows = defaultdict(list)
    output_by_enrollment = {}
    output_pairs = set()

    for row in allocations:

        enrollment_id = integer(
            row["EnrollmentID"],
            "Allocation.EnrollmentID",
        )

        student_id = integer(
            row["StudentID"],
            "Allocation.StudentID",
        )

        course_id = integer(
            row["CourseID"],
            "Allocation.CourseID",
        )

        exam_id = integer(
            row["ExamID"],
            "Allocation.ExamID",
        )

        check(
            enrollment_id not in output_by_enrollment,
            f"Duplicate allocation EnrollmentID {enrollment_id}.",
        )

        output_by_enrollment[enrollment_id] = row
        student_rows[student_id].append(row)
        output_pairs.add((student_id, exam_id))

        source = enrollment_by_id.get(enrollment_id)

        check(
            source is not None,
            f"Unknown EnrollmentID {enrollment_id}.",
        )

        if source:

            check(
                integer(
                    source["StudentID"],
                    "Enrollment.StudentID",
                ) == student_id,
                f"Student mismatch for enrollment {enrollment_id}.",
            )

            check(
                integer(
                    source["CourseID"],
                    "Enrollment.CourseID",
                ) == course_id,
                f"Course mismatch for enrollment {enrollment_id}.",
            )

        source_sitting = sitting_by_enrollment.get(enrollment_id)

        check(
            source_sitting is not None
            and integer(
                source_sitting["ExamID"],
                "SittingAllocation.ExamID",
            ) == exam_id,
            f"Sitting allocation mismatch for enrollment {enrollment_id}.",
        )

        classification = classification_by_enrollment.get(
            enrollment_id
        )

        check(
            classification is not None,
            f"Missing classification for enrollment {enrollment_id}.",
        )

        if classification:

            check(
                normalized(classification["EnrollmentType"])
                == normalized(row["EnrollmentType"]),
                f"Enrollment type mismatch for enrollment {enrollment_id}.",
            )

        check(
            exam_id in timetable_by_id,
            f"Allocation references unknown exam {exam_id}.",
        )

        if exam_id in timetable_by_id:

            scheduled = timetable_by_id[exam_id]

            check(
                integer(
                    scheduled["CourseID"],
                    "Timetable.CourseID",
                ) == course_id,
                f"Allocation course mismatch for exam {exam_id}.",
            )

            check(
                row["ExamDate"] == scheduled["ExamDate"],
                f"Allocation date mismatch for exam {exam_id}.",
            )

            check(
                integer(
                    row["SlotNumber"],
                    "Allocation.SlotNumber",
                ) == integer(
                    scheduled["SlotNumber"],
                    "Timetable.SlotNumber",
                ),
                f"Allocation slot mismatch for exam {exam_id}.",
            )

        check(
            student_track.get(student_id)
            == integer(row["TrackID"], "Allocation.TrackID"),
            f"Student track mismatch for student {student_id}.",
        )

    check(
        len(output_by_enrollment) == EXPECTED_ALLOCATIONS,
        "Allocation EnrollmentIDs must be unique and total 20000.",
    )

    check(
        set(output_by_enrollment) == set(sitting_by_enrollment),
        "Output allocation EnrollmentIDs differ from source SittingAllocation.",
    )

    check(
        len(student_rows) == EXPECTED_STUDENTS,
        "Expected all 5000 students in allocations.",
    )

    source_pairs = set()

    for row in exam_enrollments:

        enrollment_id = integer(
            row["EnrollmentID"],
            "ExamEnrollment.EnrollmentID",
        )

        exam_id = integer(
            row["ExamID"],
            "ExamEnrollment.ExamID",
        )

        source = enrollment_by_id.get(enrollment_id)

        check(
            source is not None,
            f"ExamEnrollment references unknown enrollment {enrollment_id}.",
        )

        if source:
            source_pairs.add((
                integer(source["StudentID"], "StudentID"),
                exam_id,
            ))

    check(
        source_pairs == output_pairs
        and len(source_pairs) == len(exam_enrollments),
        "Student/exam pairs differ from ExamEnrollment.",
    )

    # ========================================================
    # 6. ACCOMMODATION AND EFFECTIVE INTERVAL VALIDATION
    # ========================================================

    print("\n[6/8] Checking extended-time effective intervals...")

    active_extensions = defaultdict(list)

    for accommodation in accommodations:

        if normalized(
            accommodation["AccommodationType"]
        ) != "EXTENDED_TIME":
            continue

        if normalized(
            accommodation["AccommodationStatus"]
        ) != "ACTIVE":
            continue

        student_id = integer(
            accommodation["StudentID"],
            "Accommodation.StudentID",
        )

        active_extensions[student_id].append(
            accommodation
        )

    extended_students = set()
    extended_allocations = 0
    overlap_pairs = 0

    for student_id in range(1, EXPECTED_STUDENTS + 1):

        rows = student_rows.get(student_id, [])

        check(
            len(rows) == 4,
            f"Student {student_id} has {len(rows)} allocations; expected 4.",
        )

        compulsory = [
            row for row in rows
            if normalized(row["EnrollmentType"]) == "COMPULSORY"
        ]

        optional = [
            row for row in rows
            if normalized(row["EnrollmentType"]) == "OPTIONAL"
        ]

        check(
            len(compulsory) == 3
            and len(optional) == 1,
            f"Student {student_id} must have 3 compulsory "
            "and 1 optional allocation.",
        )

        check(
            len({
                row["ExamDate"]
                for row in compulsory
            }) == 3,
            f"Student {student_id} compulsory exams must be on 3 distinct dates.",
        )

        intervals = []

        for row in rows:

            exam_date = parse_date(
                row["ExamDate"],
                "Allocation.ExamDate",
            )

            applicable = []

            for accommodation in active_extensions.get(
                student_id,
                [],
            ):

                effective_from = parse_date(
                    accommodation["EffectiveFrom"],
                    "Accommodation.EffectiveFrom",
                )

                end_raw = (
                    accommodation.get("EffectiveTo") or ""
                ).strip()

                effective_to = (
                    parse_date(
                        end_raw,
                        "Accommodation.EffectiveTo",
                    )
                    if end_raw else None
                )

                if (
                    effective_from <= exam_date
                    and (
                        effective_to is None
                        or exam_date <= effective_to
                    )
                ):
                    applicable.append(accommodation)

            check(
                len(applicable) <= 1,
                f"Student {student_id} has multiple effective "
                f"extended-time records on {exam_date}.",
            )

            extension = (
                float(applicable[0]["ExtensionPercentage"])
                if applicable else 0.0
            )

            expected_duration = int(
                math.ceil(
                    standard_duration
                    * (1.0 + extension / 100.0)
                )
            )

            start = parse_datetime(
                row["StartDateTime"],
                "Allocation.StartDateTime",
            )

            effective_end = parse_datetime(
                row["EffectiveEndDateTime"],
                "Allocation.EffectiveEndDateTime",
            )

            base_end = parse_datetime(
                row["EndDateTime"],
                "Allocation.EndDateTime",
            )

            duration = integer(
                row["EffectiveDurationMinutes"],
                "EffectiveDurationMinutes",
            )

            check(
                duration == expected_duration,
                f"Student {student_id} exam {row['ExamID']} "
                f"effective duration {duration}; "
                f"expected {expected_duration}.",
            )

            check(
                effective_end - start
                == timedelta(minutes=duration),
                f"Student {student_id} exam {row['ExamID']} "
                "effective end mismatch.",
            )

            check(
                effective_end >= base_end,
                f"Student {student_id} exam {row['ExamID']} "
                "effective end precedes base end.",
            )

            check(
                integer(
                    row["HasExtendedTime"],
                    "HasExtendedTime",
                ) == int(expected_duration > standard_duration),
                f"Student {student_id} exam {row['ExamID']} "
                "HasExtendedTime flag mismatch.",
            )

            if expected_duration > standard_duration:
                extended_students.add(student_id)
                extended_allocations += 1

            intervals.append((
                start,
                effective_end,
                integer(row["ExamID"], "ExamID"),
            ))

        intervals.sort(key=lambda item: item[0])

        for previous, current in zip(
            intervals,
            intervals[1:],
        ):

            if current[0] < previous[1]:

                overlap_pairs += 1

                check(
                    False,
                    f"Student {student_id} has effective interval "
                    f"conflict between exams {previous[2]} "
                    f"and {current[2]}.",
                )

    # ========================================================
    # 7. SLOT LOAD AND OPTIONAL WAVE VALIDATION
    # ========================================================

    print("\n[7/8] Checking slot loads and optional waves...")

    room_count = integer(
        config["physical_infrastructure"]["rooms"],
        "physical_infrastructure.rooms",
    )

    check(
        room_count == 100,
        f"Expected 100 rooms; found {room_count}.",
    )

    for key, count in slot_counts.items():

        check(
            count <= room_count,
            f"Slot {key} has {count} exams, exceeding 100 rooms.",
        )

    expected_optional_sittings_by_slot = {
        1: 38,
        2: 38,
        3: 38,
        4: 37,
        5: 37,
        6: 37,
    }

    day_six = dates[5]

    for slot, expected_count in (
        expected_optional_sittings_by_slot.items()
    ):

        actual_count = slot_counts[(day_six, slot)]

        check(
            actual_count == expected_count,
            f"Day 6 slot {slot} should contain "
            f"{expected_count} optional sittings; "
            f"found {actual_count}.",
        )

    check(
        len(slot_load) == 36,
        f"Expected 36 SlotLoad rows; found {len(slot_load)}.",
    )

    slot_map = {}

    for row in slot_load:

        key = (
            row["ExamDate"],
            integer(row["SlotNumber"], "SlotLoad.SlotNumber"),
        )

        check(
            key not in slot_map,
            f"Duplicate SlotLoad row {key}.",
        )

        slot_map[key] = row

    expected_keys = {
        (day, slot)
        for day in dates
        for slot in range(1, 7)
    }

    check(
        set(slot_map) == expected_keys,
        "SlotLoad must contain all 36 unique physical slots.",
    )

    for key in expected_keys:

        if key not in slot_map:
            continue

        row = slot_map[key]

        check(
            integer(
                row["ExamSittingCount"],
                "SlotLoad.ExamSittingCount",
            ) == slot_counts[key],
            f"SlotLoad exam count mismatch for {key}.",
        )

        expected_students = sum(
            integer(
                item["EnrolledStudentCount"],
                "EnrolledStudentCount",
            )
            for item in timetable
            if (
                item["ExamDate"],
                integer(
                    item["SlotNumber"],
                    "SlotNumber",
                ),
            ) == key
        )

        check(
            integer(
                row["TotalStudentCount"],
                "SlotLoad.TotalStudentCount",
            ) == expected_students,
            f"SlotLoad student count mismatch for {key}.",
        )

    # ========================================================
    # 8. REPORT
    # ========================================================

    print("\n[8/8] Writing independent validation report...")

    report = {
        "version": "2.2.0",
        "validator": (
            "Independent timetable validator - "
            "extended-time and optional-wave aware"
        ),
        "status": "PASSED" if not errors else "FAILED",
        "checks_executed": checks,
        "error_count": len(errors),
        "errors": errors,
        "counts": {
            "students": len(students),
            "tracks": len(tracks),
            "courses": len(course_sittings),
            "exams": len(timetable),
            "student_allocations": len(allocations),
            "track_course_day_assignments": len(
                track_course_blocks
            ),
            "slot_load_rows": len(slot_load),
        },
        "compulsory_block_course_load": {
            str(block_id): block_load[block_id]
            for block_id in range(1, 11)
        },
        "extended_time": {
            "students": len(extended_students),
            "allocations": extended_allocations,
            "overlap_pairs": overlap_pairs,
        },
        "optional_exam_slot_load": {
            str(slot): slot_counts[(day_six, slot)]
            for slot in range(1, 7)
        },
        "optional_wave_course_counts": {
            str(block_id): optional_block_distribution[block_id]
            for block_id in (11, 12)
        },
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
        "limitations": [
            "Validates timetable and student-level effective exam intervals.",
            "Does not validate physical room batches or capacity.",
            "Does not validate room closures or effective-dated room capacity.",
            "Does not validate equipment availability or changeovers.",
            "Does not allocate or validate invigilators.",
            "Room-level extended-time occupancy remains pending.",
            "GroundTruth.csv is not read by this validator.",
        ],
    }

    SCHED.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = REPORT_PATH.with_suffix(
        REPORT_PATH.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    temporary.replace(REPORT_PATH)

    print("\n" + "=" * 76)
    print("INDEPENDENT TIMETABLE VALIDATION RESULT")
    print("=" * 76)

    print(f"Checks executed: {checks:,}")
    print(f"Errors: {len(errors)}")
    print(f"Status: {report['status']}")

    if errors:
        print("\nFirst 100 errors:")

        for error in errors[:100]:
            print(" -", error)

    print("\nReport:", REPORT_PATH)
    print("SQL Server: NOT ACCESSED OR MODIFIED")
    print("GroundTruth.csv: NOT ACCESSED")

    return 0 if not errors else 1


if __name__ == "__main__":

    try:
        raise SystemExit(main())

    except Exception as exc:
        print("\nINDEPENDENT VALIDATOR FAILED TO EXECUTE")
        print(f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)