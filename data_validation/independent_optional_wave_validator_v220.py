
import csv
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date, timedelta

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

REPORT_FILE = SCHED / "optional_wave_independent_validation_v220.json"
APPLICATION_REPORT = SCHED / "optional_wave_application_report_v220.json"
PLAN_FILE = SCHED / "optional_wave_plan_preview.csv"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_date(value):
    return date.fromisoformat(value[:10])


def parse_datetime(value):
    value = value.strip()
    if len(value) >= 19 and value[10] != " ":
        value = value[:10] + " " + value[10:]
    return datetime.fromisoformat(value)


def parse_time(value):
    return datetime.strptime(value.strip(), "%H:%M").time()


def main():
    print("=" * 78)
    print("INDEPENDENT OPTIONAL TWO-WAVE VALIDATOR V2.2.0")
    print("=" * 78)

    errors = []
    checks = 0

    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(message)

    if not APPLICATION_REPORT.exists():
        raise FileNotFoundError(
            "Application report missing. Run apply_optional_waves_v220.py first."
        )

    application = json.loads(
        APPLICATION_REPORT.read_text(encoding="utf-8")
    )

    timetable = read_csv(SCHED / "ExamTimetable.csv")
    allocations = read_csv(SCHED / "TimetableStudentAllocation.csv")
    optional_blocks = read_csv(SCHED / "OptionalCourseBlockAllocation.csv")
    slot_load = read_csv(SCHED / "SlotLoad.csv")
    plan = read_csv(PLAN_FILE)
    grid = read_csv(META / "PhysicalRoomGrid.csv")

    # ---------------------------------------------------------
    # 1. Counts and source coverage.
    # ---------------------------------------------------------
    check(len(timetable) == 900, "Timetable must contain 900 rows")
    check(
        len(allocations) == 20000,
        "Student allocations must contain 20,000 rows"
    )
    check(len(optional_blocks) == 75, "Expected 75 optional block rows")
    check(len(slot_load) == 36, "Expected 36 occupied timetable slots")

    timetable_by_exam = {
        int(r["ExamID"]): r for r in timetable
    }

    check(
        len(timetable_by_exam) == len(timetable),
        "Duplicate ExamID found"
    )

    # ---------------------------------------------------------
    # 2. Reconstruct course-to-wave mapping.
    # ---------------------------------------------------------
    course_wave = {}

    for row in plan:
        cid = int(row["CourseID"])
        wave = row["Period"].strip().upper()

        if cid in course_wave:
            errors.append(f"Duplicate plan row for course {cid}")
        course_wave[cid] = wave

    check(len(course_wave) == 75, "Wave plan must contain 75 courses")

    check(
        sum(v == "MORNING" for v in course_wave.values()) == 38,
        "Morning wave must contain 38 courses"
    )
    check(
        sum(v == "AFTERNOON" for v in course_wave.values()) == 37,
        "Afternoon wave must contain 37 courses"
    )

    # ---------------------------------------------------------
    # 3. Build physical grid mappings.
    # ---------------------------------------------------------
    date_to_day = {}
    grid_times = {}

    for row in grid:
        exam_date = parse_date(row["ExamDate"])
        day_index = int(row["DayIndex"])
        slot = int(row["SlotNumber"])

        date_to_day[exam_date] = day_index

        if day_index == 6:
            start = parse_time(row["SlotStartTime"])

            if slot in grid_times:
                check(
                    grid_times[slot] == start,
                    f"Inconsistent physical grid start time for slot {slot}"
                )
            else:
                grid_times[slot] = start

    check(
        set(grid_times) == {1, 2, 3, 4, 5, 6},
        "Day 6 must contain six physical slots"
    )

    # ---------------------------------------------------------
    # 4. Check course sittings and two-wave assignment.
    # ---------------------------------------------------------
    exams_by_course = defaultdict(dict)

    for row in timetable:
        if row["CourseRole"].strip().upper() != "OPTIONAL":
            continue

        cid = int(row["CourseID"])
        ordinal = int(row["SittingOrdinal"])
        exams_by_course[cid][ordinal] = row

    check(len(exams_by_course) == 75, "Expected 75 optional courses")

    for cid, wave in course_wave.items():
        sittings = exams_by_course.get(cid, {})

        check(
            set(sittings) == {1, 2, 3},
            f"Course {cid} must have exactly three sittings"
        )

        if set(sittings) != {1, 2, 3}:
            continue

        offset = 0 if wave == "MORNING" else 3
        block = 11 if wave == "MORNING" else 12

        actual_slots = []

        for ordinal in (1, 2, 3):
            row = sittings[ordinal]
            slot = int(row["SlotNumber"])
            actual_slots.append(slot)

            check(
                row["ExamDate"] == "2026-11-21",
                f"Course {cid} sitting {ordinal} is not on Day 6"
            )
            check(
                int(row["DayIndex"]) == 6,
                f"Course {cid} sitting {ordinal} has wrong DayIndex"
            )
            check(
                slot == ordinal + offset,
                f"Course {cid} sitting {ordinal} has wrong slot"
            )
            check(
                int(row["BlockID"]) == block,
                f"Course {cid} sitting {ordinal} has wrong block"
            )

            expected_start = datetime.combine(
                date(2026, 11, 21),
                grid_times[slot]
            )

            actual_start = parse_datetime(row["StartDateTime"])
            actual_end = parse_datetime(row["EndDateTime"])

            check(
                actual_start == expected_start,
                f"Course {cid} sitting {ordinal} start does not match grid"
            )

            check(
                actual_end > actual_start,
                f"Course {cid} sitting {ordinal} has invalid interval"
            )

            check(
                parse_time(row["SlotStartTime"]) == grid_times[slot],
                f"Course {cid} sitting {ordinal} slot time mismatch"
            )

        check(
            actual_slots == (
                [1, 2, 3] if wave == "MORNING" else [4, 5, 6]
            ),
            f"Course {cid} sittings are not consecutive"
        )

    # ---------------------------------------------------------
    # 5. Validate optional block allocation.
    # ---------------------------------------------------------
    block_by_course = {
        int(r["CourseID"]): r for r in optional_blocks
    }

    check(
        len(block_by_course) == 75,
        "Optional block allocation has duplicate/missing courses"
    )

    for cid, wave in course_wave.items():
        row = block_by_course.get(cid)

        if not row:
            errors.append(f"Missing optional block allocation for course {cid}")
            continue

        expected_block = 11 if wave == "MORNING" else 12

        check(
            int(row["BlockID"]) == expected_block,
            f"Optional block mismatch for course {cid}"
        )
        check(
            row["Period"].upper() == wave,
            f"Optional period mismatch for course {cid}"
        )

    # ---------------------------------------------------------
    # 6. Validate SlotID and student allocation relationships.
    # ---------------------------------------------------------
    allocation_exam_counts = defaultdict(int)
    student_intervals = defaultdict(list)
    student_course_counts = defaultdict(int)
    enrollment_ids = set()

    optional_allocation_count = 0

    for row in allocations:
        exam_id = int(row["ExamID"])
        sid = int(row["StudentID"])
        enrollment_id = int(row["EnrollmentID"])

        check(
            enrollment_id not in enrollment_ids,
            f"Duplicate EnrollmentID {enrollment_id}"
        )
        enrollment_ids.add(enrollment_id)

        exam = timetable_by_exam.get(exam_id)

        if exam is None:
            errors.append(f"Allocation references missing ExamID {exam_id}")
            continue

        allocation_exam_counts[exam_id] += 1

        exam_date = parse_date(row["ExamDate"])
        day_index = date_to_day.get(exam_date)

        check(day_index is not None, f"Missing physical grid date {exam_date}")

        if day_index is not None:
            expected_slot_id = (day_index - 1) * 6 + int(row["SlotNumber"])

            check(
                int(row["SlotID"]) == expected_slot_id,
                f"Incorrect SlotID for EnrollmentID {enrollment_id}"
            )

        check(
            int(row["SlotNumber"]) == int(exam["SlotNumber"]),
            f"Slot mismatch for EnrollmentID {enrollment_id}"
        )
        check(
            row["ExamDate"] == exam["ExamDate"],
            f"Date mismatch for EnrollmentID {enrollment_id}"
        )
        check(
            row["StartDateTime"] == exam["StartDateTime"],
            f"Start mismatch for EnrollmentID {enrollment_id}"
        )

        base_start = parse_datetime(row["StartDateTime"])
        base_end = parse_datetime(row["EndDateTime"])
        effective_end = parse_datetime(row["EffectiveEndDateTime"])

        duration = int(row["EffectiveDurationMinutes"])

        check(
            effective_end == base_start + timedelta(minutes=duration),
            f"Effective duration mismatch for EnrollmentID {enrollment_id}"
        )
        check(
            base_end > base_start,
            f"Invalid base interval for EnrollmentID {enrollment_id}"
        )
        check(
            effective_end > base_start,
            f"Invalid effective interval for EnrollmentID {enrollment_id}"
        )

        student_intervals[sid].append(
            (base_start, effective_end, exam_id)
        )

        if exam["CourseRole"].strip().upper() == "OPTIONAL":
            optional_allocation_count += 1

            cid = int(exam["CourseID"])
            check(
                cid in course_wave,
                f"Optional allocation has unplanned course {cid}"
            )

    check(
        len(enrollment_ids) == 20000,
        "Expected 20,000 unique EnrollmentIDs"
    )
    check(
        len(student_intervals) == 5000,
        "Expected 5,000 students"
    )
    check(
        optional_allocation_count == 5000,
        "Expected 5,000 optional student allocations"
    )

    # ---------------------------------------------------------
    # 7. Validate student conflict-free effective intervals.
    # ---------------------------------------------------------
    overlap_count = 0

    for sid, intervals in student_intervals.items():
        intervals.sort(key=lambda x: (x[0], x[1]))

        for previous, current in zip(intervals, intervals[1:]):
            checks += 1

            if current[0] < previous[1]:
                overlap_count += 1
                errors.append(
                    f"Student {sid}: effective interval overlap "
                    f"between ExamID {previous[2]} and {current[2]}"
                )

    check(
        overlap_count == 0,
        "Effective-time student conflicts must be zero"
    )

    # ---------------------------------------------------------
    # 8. Rebuild and independently compare SlotLoad.
    # ---------------------------------------------------------
    groups = defaultdict(list)

    for row in timetable:
        key = (
            row["ExamDate"],
            int(row["DayIndex"]),
            int(row["SlotNumber"])
        )
        groups[key].append(row)

    rebuilt = {}

    for key, rows in groups.items():
        start = min(parse_time(r["SlotStartTime"]) for r in rows)
        end = max(parse_time(r["SlotEndTime"]) for r in rows)

        rebuilt[key] = {
            "StartTime": start.strftime("%H:%M"),
            "EndTime": end.strftime("%H:%M"),
            "ExamSittingCount": len(rows),
            "TotalStudentCount": sum(
                int(r["EnrolledStudentCount"]) for r in rows
            ),
        }

    actual_load = {}

    for row in slot_load:
        key = (
            row["ExamDate"],
            int(row["DayIndex"]),
            int(row["SlotNumber"])
        )

        if key in actual_load:
            errors.append(f"Duplicate SlotLoad row {key}")

        actual_load[key] = row

    check(
        set(rebuilt) == set(actual_load),
        "SlotLoad keys do not match timetable"
    )

    for key, expected in rebuilt.items():
        actual = actual_load.get(key)

        if not actual:
            errors.append(f"Missing SlotLoad row {key}")
            continue

        check(
            actual["StartTime"] == expected["StartTime"],
            f"SlotLoad start mismatch {key}"
        )
        check(
            actual["EndTime"] == expected["EndTime"],
            f"SlotLoad end mismatch {key}"
        )
        check(
            int(actual["ExamSittingCount"])
            == expected["ExamSittingCount"],
            f"SlotLoad exam count mismatch {key}"
        )
        check(
            int(actual["TotalStudentCount"])
            == expected["TotalStudentCount"],
            f"SlotLoad student count mismatch {key}"
        )

    # ---------------------------------------------------------
    # 9. Check exact Day 6 optional wave pattern.
    # ---------------------------------------------------------
    expected_counts = {
        1: 38,
        2: 38,
        3: 38,
        4: 37,
        5: 37,
        6: 37,
    }

    actual_counts = defaultdict(int)

    for row in timetable:
        if (
            row["CourseRole"].strip().upper() == "OPTIONAL"
            and row["ExamDate"] == "2026-11-21"
        ):
            actual_counts[int(row["SlotNumber"])] += 1

    for slot, expected in expected_counts.items():
        check(
            actual_counts[slot] == expected,
            f"Day 6 optional count mismatch for slot {slot}"
        )

    # ---------------------------------------------------------
    # 10. Verify compulsory timetable unchanged using backups.
    # ---------------------------------------------------------
    backups = application.get("Backups", {})

    timetable_backup = backups.get("timetable")
    allocation_backup = backups.get("allocations")

    if not timetable_backup or not Path(timetable_backup).exists():
        errors.append("Original timetable backup missing")
    else:
        original_timetable = read_csv(Path(timetable_backup))

        original_compulsory = {
            int(r["ExamID"]): r
            for r in original_timetable
            if r["CourseRole"].strip().upper() == "COMPULSORY"
        }

        current_compulsory = {
            int(r["ExamID"]): r
            for r in timetable
            if r["CourseRole"].strip().upper() == "COMPULSORY"
        }

        check(
            original_compulsory == current_compulsory,
            "Compulsory timetable rows were modified"
        )

    if not allocation_backup or not Path(allocation_backup).exists():
        errors.append("Original student allocation backup missing")
    else:
        original_allocations = read_csv(Path(allocation_backup))

        original_exam_roles = {
            int(r["ExamID"]): r["CourseRole"].strip().upper()
            for r in read_csv(Path(timetable_backup))
        }

        original_compulsory_allocations = {
            int(r["EnrollmentID"]): r
            for r in original_allocations
            if original_exam_roles.get(int(r["ExamID"])) == "COMPULSORY"
        }

        current_compulsory_allocations = {
            int(r["EnrollmentID"]): r
            for r in allocations
            if timetable_by_exam[int(r["ExamID"])]["CourseRole"]
            .strip().upper() == "COMPULSORY"
        }

        check(
            original_compulsory_allocations
            == current_compulsory_allocations,
            "Compulsory student allocations were modified"
        )

    # ---------------------------------------------------------
    # 11. Write independent validation report.
    # ---------------------------------------------------------
    report = {
        "Version": "2.2.0",
        "Validation": "Independent optional two-wave timetable validation",
        "ChecksExecuted": checks,
        "Errors": errors,
        "ErrorCount": len(errors),
        "EffectiveStudentIntervalOverlaps": overlap_count,
        "TimetableRows": len(timetable),
        "StudentAllocationRows": len(allocations),
        "UniqueStudents": len(student_intervals),
        "OptionalCourses": len(exams_by_course),
        "OptionalExamSittings": sum(
            1 for r in timetable
            if r["CourseRole"].strip().upper() == "OPTIONAL"
        ),
        "OptionalStudentAllocations": optional_allocation_count,
        "OccupiedSlots": len(slot_load),
        "Day6OptionalCounts": dict(actual_counts),
        "CompulsoryTimetableUnchanged": not any(
            "Compulsory timetable rows" in e
            for e in errors
        ),
        "Status": "PASSED" if not errors else "FAILED",
        "SQLServer": "NOT ACCESSED OR MODIFIED",
    }

    REPORT_FILE.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("\n" + "=" * 78)
    print("INDEPENDENT OPTIONAL TWO-WAVE VALIDATION RESULT")
    print("=" * 78)
    print(f"Checks executed                 : {checks:,}")
    print(f"Errors                          : {len(errors)}")
    print(f"Effective interval overlaps     : {overlap_count}")
    print(f"Timetable rows                  : {len(timetable)}")
    print(f"Student allocations             : {len(allocations)}")
    print(f"Unique students                 : {len(student_intervals)}")
    print(f"Optional courses                : {len(exams_by_course)}")
    print(f"Optional exam sittings          : {report['OptionalExamSittings']}")
    print(f"Optional student allocations    : {optional_allocation_count}")
    print(f"Occupied slots                  : {len(slot_load)}")
    print(f"Compulsory timetable unchanged  : {report['CompulsoryTimetableUnchanged']}")
    print(f"Status                          : {report['Status']}")

    if errors:
        print("\nVALIDATION ERRORS:")
        for error in errors[:100]:
            print("  -", error)

    print(f"\nReport: {REPORT_FILE}")
    print("SQL Server: NOT ACCESSED OR MODIFIED")


if __name__ == "__main__":
    main()
