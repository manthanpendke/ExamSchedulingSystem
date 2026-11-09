
import csv
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, date, time, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

FILES = {
    "timetable": SCHED / "ExamTimetable.csv",
    "allocations": SCHED / "TimetableStudentAllocation.csv",
    "optional_blocks": SCHED / "OptionalCourseBlockAllocation.csv",
    "slot_load": SCHED / "SlotLoad.csv",
}

PLAN_FILE = SCHED / "optional_wave_plan_preview.csv"
GRID_FILE = META / "PhysicalRoomGrid.csv"
REPORT_FILE = SCHED / "optional_wave_application_report_v220.json"

EXPECTED_DATE = date(2026, 11, 21)
EXPECTED_MORNING = 38
EXPECTED_AFTERNOON = 37


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


def write_temp(path, rows, fields):
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    return temp


def fail(message):
    raise ValueError(message)


def main():
    print("=" * 78)
    print("APPLY OPTIONAL TWO-WAVE TIMETABLE V2.2.0")
    print("=" * 78)

    # ---------------------------------------------------------
    # 1. Read and validate all inputs.
    # ---------------------------------------------------------
    for path in list(FILES.values()) + [PLAN_FILE, GRID_FILE]:
        if not path.exists():
            fail(f"Required file missing: {path}")

    timetable = read_csv(FILES["timetable"])
    allocations = read_csv(FILES["allocations"])
    optional_blocks = read_csv(FILES["optional_blocks"])
    slot_load = read_csv(FILES["slot_load"])
    wave_plan = read_csv(PLAN_FILE)
    grid = read_csv(GRID_FILE)

    if len(timetable) != 900:
        fail(f"Expected 900 timetable rows; found {len(timetable)}")

    if len(allocations) != 20000:
        fail(
            f"Expected 20,000 student allocations; "
            f"found {len(allocations)}"
        )

    # ---------------------------------------------------------
    # 2. Validate wave plan.
    # ---------------------------------------------------------
    course_wave = {}

    for row in wave_plan:
        course_id = int(row["CourseID"])
        wave = row["Period"].strip().upper()

        if wave not in ("MORNING", "AFTERNOON"):
            fail(f"Invalid wave for CourseID {course_id}: {wave}")

        if course_id in course_wave:
            fail(f"Duplicate wave assignment for CourseID {course_id}")

        course_wave[course_id] = wave

    morning_count = sum(
        v == "MORNING" for v in course_wave.values()
    )
    afternoon_count = sum(
        v == "AFTERNOON" for v in course_wave.values()
    )

    if len(course_wave) != 75:
        fail(f"Expected 75 optional courses; found {len(course_wave)}")

    if morning_count != EXPECTED_MORNING:
        fail(f"Expected 38 morning courses; found {morning_count}")

    if afternoon_count != EXPECTED_AFTERNOON:
        fail(f"Expected 37 afternoon courses; found {afternoon_count}")

    # ---------------------------------------------------------
    # 3. Build physical grid mappings.
    # ---------------------------------------------------------
    date_to_day = {}
    day6_start = {}

    for row in grid:
        day_index = int(row["DayIndex"])
        exam_date = parse_date(row["ExamDate"])
        slot = int(row["SlotNumber"])
        start_time = parse_time(row["SlotStartTime"])

        if exam_date in date_to_day:
            if date_to_day[exam_date] != day_index:
                fail(f"Inconsistent day index for {exam_date}")
        else:
            date_to_day[exam_date] = day_index

        if day_index == 6:
            if slot in day6_start and day6_start[slot] != start_time:
                fail(f"Inconsistent physical grid time for slot {slot}")
            day6_start[slot] = start_time

    if set(day6_start) != {1, 2, 3, 4, 5, 6}:
        fail("Day 6 physical grid must contain slots 1 through 6")

    if EXPECTED_DATE not in date_to_day:
        fail("Expected Day 6 exam date is missing from physical grid")

    if date_to_day[EXPECTED_DATE] != 6:
        fail("21 November 2026 is not DayIndex 6 in the physical grid")

    # ---------------------------------------------------------
    # 4. Verify the existing SlotID convention before changing.
    # ---------------------------------------------------------
    existing_slot_ids = {}

    for row in allocations:
        exam_date = parse_date(row["ExamDate"])
        slot = int(row["SlotNumber"])
        slot_id = int(row["SlotID"])

        day_index = date_to_day.get(exam_date)

        if day_index is None:
            fail(f"Allocation date {exam_date} not found in physical grid")

        expected_slot_id = (day_index - 1) * 6 + slot

        if slot_id != expected_slot_id:
            fail(
                f"SlotID convention mismatch: {exam_date}, slot {slot}, "
                f"found {slot_id}, expected {expected_slot_id}"
            )

        existing_slot_ids[(exam_date, slot)] = slot_id

    # ---------------------------------------------------------
    # 5. Index timetable rows and validate optional sittings.
    # ---------------------------------------------------------
    timetable_by_exam = {}
    exams_by_course = defaultdict(dict)

    for row in timetable:
        exam_id = int(row["ExamID"])

        if exam_id in timetable_by_exam:
            fail(f"Duplicate ExamID {exam_id}")

        timetable_by_exam[exam_id] = row

        if row["CourseRole"].strip().upper() == "OPTIONAL":
            course_id = int(row["CourseID"])
            ordinal = int(row["SittingOrdinal"])

            if ordinal in exams_by_course[course_id]:
                fail(
                    f"Duplicate sitting ordinal {ordinal} "
                    f"for course {course_id}"
                )

            exams_by_course[course_id][ordinal] = row

    if set(exams_by_course) != set(course_wave):
        fail("Wave plan courses do not match optional timetable courses")

    for course_id, sittings in exams_by_course.items():
        if set(sittings) != {1, 2, 3}:
            fail(f"Course {course_id} must have sittings 1, 2 and 3")

    # ---------------------------------------------------------
    # 6. Calculate all optional exam changes in memory.
    # ---------------------------------------------------------
    updated_timetable = [dict(row) for row in timetable]
    updated_timetable_by_exam = {
        int(row["ExamID"]): row for row in updated_timetable
    }

    exam_changes = {}

    for course_id, wave in course_wave.items():
        block_id = 11 if wave == "MORNING" else 12
        offset = 0 if wave == "MORNING" else 3

        for ordinal in (1, 2, 3):
            old_row = exams_by_course[course_id][ordinal]
            exam_id = int(old_row["ExamID"])

            new_slot = ordinal + offset
            start_clock = day6_start[new_slot]

            original_start = parse_datetime(old_row["StartDateTime"])
            original_end = parse_datetime(old_row["EndDateTime"])
            duration = original_end - original_start

            if duration <= timedelta(0):
                fail(f"Invalid duration for ExamID {exam_id}")

            new_start = datetime.combine(EXPECTED_DATE, start_clock)
            new_end = new_start + duration

            new_row = updated_timetable_by_exam[exam_id]

            new_row["BlockID"] = str(block_id)
            new_row["ExamDate"] = EXPECTED_DATE.isoformat()
            new_row["DayIndex"] = "6"
            new_row["SlotNumber"] = str(new_slot)
            new_row["SlotStartTime"] = new_start.strftime("%H:%M")
            new_row["SlotEndTime"] = new_end.strftime("%H:%M")
            new_row["StartDateTime"] = new_start.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            new_row["EndDateTime"] = new_end.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            slot_id = (6 - 1) * 6 + new_slot

            exam_changes[exam_id] = {
                "CourseID": course_id,
                "SittingOrdinal": ordinal,
                "CourseRole": "OPTIONAL",
                "Wave": wave,
                "BlockID": block_id,
                "ExamDate": EXPECTED_DATE.isoformat(),
                "DayIndex": 6,
                "SlotNumber": new_slot,
                "SlotID": slot_id,
                "StartDateTime": new_start,
                "EndDateTime": new_end,
            }

    if len(exam_changes) != 225:
        fail(f"Expected 225 optional exams; found {len(exam_changes)}")

    # ---------------------------------------------------------
    # 7. Update optional student allocations.
    # ---------------------------------------------------------
    updated_allocations = []
    allocation_exam_counts = defaultdict(int)

    for old in allocations:
        row = dict(old)
        exam_id = int(row["ExamID"])

        if exam_id in exam_changes:
            change = exam_changes[exam_id]

            effective_duration = int(row["EffectiveDurationMinutes"])

            if effective_duration <= 0:
                fail(
                    f"Invalid effective duration for EnrollmentID "
                    f"{row['EnrollmentID']}"
                )

            effective_end = (
                change["StartDateTime"]
                + timedelta(minutes=effective_duration)
            )

            row["ExamDate"] = change["ExamDate"]
            row["SlotNumber"] = str(change["SlotNumber"])
            row["SlotID"] = str(change["SlotID"])
            row["StartDateTime"] = change["StartDateTime"].strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            row["EndDateTime"] = change["EndDateTime"].strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            row["EffectiveEndDateTime"] = effective_end.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        updated_allocations.append(row)
        allocation_exam_counts[exam_id] += 1

    # ---------------------------------------------------------
    # 8. Validate all student effective intervals.
    # ---------------------------------------------------------
    student_intervals = defaultdict(list)

    for row in updated_allocations:
        sid = int(row["StudentID"])
        start = parse_datetime(row["StartDateTime"])
        effective_end = parse_datetime(row["EffectiveEndDateTime"])

        if effective_end <= start:
            fail(
                f"Invalid effective interval for StudentID {sid}, "
                f"ExamID {row['ExamID']}"
            )

        student_intervals[sid].append(
            (start, effective_end, int(row["ExamID"]))
        )

    overlap_count = 0

    for sid, intervals in student_intervals.items():
        intervals.sort(key=lambda x: (x[0], x[1]))

        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                overlap_count += 1
                fail(
                    f"Effective exam overlap for StudentID {sid}: "
                    f"ExamID {previous[2]} and ExamID {current[2]}"
                )

    if overlap_count:
        fail(f"Found {overlap_count} student interval overlaps")

    # ---------------------------------------------------------
    # 9. Validate each optional course's three sittings.
    # ---------------------------------------------------------
    for course_id, wave in course_wave.items():
        sittings = [
            exam_changes[
                int(exams_by_course[course_id][ordinal]["ExamID"])
            ]
            for ordinal in (1, 2, 3)
        ]

        expected_slots = (
            [1, 2, 3] if wave == "MORNING" else [4, 5, 6]
        )

        actual_slots = [r["SlotNumber"] for r in sittings]

        if actual_slots != expected_slots:
            fail(
                f"Course {course_id} has incorrect slots: "
                f"{actual_slots}, expected {expected_slots}"
            )

        if any(r["ExamDate"] != EXPECTED_DATE.isoformat() for r in sittings):
            fail(f"Course {course_id} is not on Day 6")

        expected_block = 11 if wave == "MORNING" else 12

        if any(r["BlockID"] != expected_block for r in sittings):
            fail(f"Course {course_id} has incorrect block assignment")

    # ---------------------------------------------------------
    # 10. Update optional block allocation.
    # ---------------------------------------------------------
    updated_optional_blocks = []

    for old in optional_blocks:
        row = dict(old)
        course_id = int(row["CourseID"])

        if course_id not in course_wave:
            fail(
                f"Optional block allocation has unknown course {course_id}"
            )

        wave = course_wave[course_id]

        row["BlockID"] = "11" if wave == "MORNING" else "12"
        row["ExamDate"] = EXPECTED_DATE.isoformat()
        row["Period"] = wave

        updated_optional_blocks.append(row)

    if len(updated_optional_blocks) != 75:
        fail(
            f"Expected 75 optional block rows; "
            f"found {len(updated_optional_blocks)}"
        )

    # ---------------------------------------------------------
    # 11. Rebuild SlotLoad.csv from the updated timetable.
    # ---------------------------------------------------------
    slot_groups = defaultdict(list)

    for row in updated_timetable:
        key = (
            row["ExamDate"],
            int(row["DayIndex"]),
            int(row["SlotNumber"]),
        )
        slot_groups[key].append(row)

    rebuilt_slot_load = []

    for (exam_date, day_index, slot), rows in sorted(slot_groups.items()):
        start_times = [parse_time(r["SlotStartTime"]) for r in rows]
        end_times = [parse_time(r["SlotEndTime"]) for r in rows]

        total_students = sum(
            int(r["EnrolledStudentCount"]) for r in rows
        )

        rebuilt_slot_load.append({
            "ExamDate": exam_date,
            "DayIndex": str(day_index),
            "SlotNumber": str(slot),
            "StartTime": min(start_times).strftime("%H:%M"),
            "EndTime": max(end_times).strftime("%H:%M"),
            "ExamSittingCount": str(len(rows)),
            "TotalStudentCount": str(total_students),
        })

    if len(rebuilt_slot_load) != 36:
        fail(
            f"Expected 36 occupied timetable slots; "
            f"found {len(rebuilt_slot_load)}"
        )

    # ---------------------------------------------------------
    # 12. Validate total counts and unique identifiers.
    # ---------------------------------------------------------
    if len(updated_timetable) != 900:
        fail("Updated timetable row count changed")

    if len(updated_allocations) != 20000:
        fail("Updated student allocation row count changed")

    if len(student_intervals) != 5000:
        fail(
            f"Expected 5,000 students; found {len(student_intervals)}"
        )

    if len({
        int(r["EnrollmentID"]) for r in updated_allocations
    }) != 20000:
        fail("EnrollmentID uniqueness validation failed")

    # ---------------------------------------------------------
    # 13. Prepare transactional file updates and backups.
    # ---------------------------------------------------------
    output_data = {
        "timetable": updated_timetable,
        "allocations": updated_allocations,
        "optional_blocks": updated_optional_blocks,
        "slot_load": rebuilt_slot_load,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backups = {}
    temp_files = {}
    replaced = []

    for key, path in FILES.items():
        if not output_data[key]:
            fail(f"No output rows prepared for {key}")

        fields = list(read_csv(path)[0].keys())

        backup = path.with_name(
            path.stem + f".backup_{timestamp}" + path.suffix
        )

        temp = write_temp(path, output_data[key], fields)

        backups[key] = str(backup)
        temp_files[key] = temp

    for key, path in FILES.items():
        shutil.copy2(path, backups[key])

    try:
        for key, path in FILES.items():
            os.replace(temp_files[key], path)
            replaced.append(key)

    except Exception:
        for key in replaced:
            shutil.copy2(backups[key], FILES[key])

        for temp in temp_files.values():
            if temp.exists():
                temp.unlink()

        raise

    # ---------------------------------------------------------
    # 14. Write application report.
    # ---------------------------------------------------------
    report = {
        "Version": "2.2.0",
        "Operation": "Optional two-wave timetable application",
        "Status": "APPLIED",
        "ExamDate": EXPECTED_DATE.isoformat(),
        "MorningCourses": morning_count,
        "AfternoonCourses": afternoon_count,
        "OptionalExamSittingsUpdated": len(exam_changes),
        "StudentAllocationsUpdated": sum(
            1 for r in updated_allocations
            if int(r["ExamID"]) in exam_changes
        ),
        "TotalTimetableRows": len(updated_timetable),
        "TotalStudentAllocations": len(updated_allocations),
        "TotalStudents": len(student_intervals),
        "OccupiedSlots": len(rebuilt_slot_load),
        "EffectiveIntervalOverlaps": overlap_count,
        "Day6OptionalSlotCounts": {
            str(slot): sum(
                1 for row in updated_timetable
                if row["CourseRole"].upper() == "OPTIONAL"
                and int(row["DayIndex"]) == 6
                and int(row["SlotNumber"]) == slot
            )
            for slot in range(1, 7)
        },
        "ModifiedFiles": {
            key: str(path) for key, path in FILES.items()
        },
        "Backups": backups,
        "CompulsoryExamsModified": False,
        "SQLServer": "NOT ACCESSED OR MODIFIED",
        "IndependentValidation": "PENDING",
    }

    REPORT_FILE.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("\n" + "=" * 78)
    print("OPTIONAL TWO-WAVE TIMETABLE APPLIED")
    print("=" * 78)
    print(f"Morning courses             : {morning_count}")
    print(f"Afternoon courses           : {afternoon_count}")
    print(f"Optional exam sittings      : {len(exam_changes)}")
    print(f"Student allocations         : {len(updated_allocations)}")
    print(f"Effective interval overlaps : {overlap_count}")
    print(f"Occupied timetable slots    : {len(rebuilt_slot_load)}")

    print("\nDay 6 optional sitting counts:")
    for slot, count in report["Day6OptionalSlotCounts"].items():
        print(f"  Slot {slot}: {count}")

    print("\nBackups:")
    for key, path in backups.items():
        print(f"  {key}: {path}")

    print(f"\nReport: {REPORT_FILE}")
    print("Compulsory exams: NOT MODIFIED")
    print("SQL Server: NOT ACCESSED OR MODIFIED")
    print("\nIndependent validation: PENDING")


if __name__ == "__main__":
    main()
