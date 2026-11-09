
import csv
import json
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date, timedelta

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"

PLAN_CSV = SCHED / "optional_wave_plan_preview.csv"
REPORT_JSON = SCHED / "optional_wave_plan_preview.json"

def read_csv(name):
    for folder in (DATA, META, SCHED):
        path = folder / name
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
    raise FileNotFoundError(name)

def parse_date(value):
    return date.fromisoformat(value[:10])

def parse_dt(value):
    value = value.strip()
    if len(value) >= 19 and value[10] != " ":
        value = value[:10] + " " + value[10:]
    return datetime.fromisoformat(value)

def truth(value):
    return str(value).strip().lower() in ("1", "true", "yes")

def active_on(row, day):
    start = parse_date(row["EffectiveFrom"]) if row.get("EffectiveFrom") else None
    end = parse_date(row["EffectiveTo"]) if row.get("EffectiveTo") else None
    return (start is None or start <= day) and (end is None or day <= end)

def main():
    timetable = read_csv("ExamTimetable.csv")
    allocations = read_csv("TimetableStudentAllocation.csv")
    accommodations = read_csv("Accommodation.csv")
    special_map = read_csv("StudentSpecialEquipmentRequirement.csv")
    rooms = read_csv("Room.csv")
    capacities = read_csv("RoomCapacity.csv")
    closures = read_csv("RoomClosure.csv")
    equipment = read_csv("Equipment.csv")
    room_equipment = read_csv("RoomEquipment.csv")
    invigilators = read_csv("Invigilator.csv")
    availability = read_csv("Availability.csv")
    grid = read_csv("PhysicalRoomGrid.csv")

    optional_exams = [
        r for r in timetable
        if r["CourseRole"].strip().upper() == "OPTIONAL"
    ]

    exams_by_course = defaultdict(dict)
    for row in optional_exams:
        exams_by_course[int(row["CourseID"])][int(row["SittingOrdinal"])] = row

    if len(exams_by_course) != 75:
        raise ValueError(f"Expected 75 optional courses; found {len(exams_by_course)}")

    for course_id, sittings in exams_by_course.items():
        if set(sittings) != {1, 2, 3}:
            raise ValueError(f"Course {course_id} does not have exactly 3 sittings")

    day6 = date(2026, 11, 21)

    accommodation_by_student = defaultdict(list)
    for row in accommodations:
        if row["AccommodationStatus"].strip().upper() == "ACTIVE":
            accommodation_by_student[int(row["StudentID"])].append(row)

    special_by_student = {
        int(r["StudentID"]): int(r["EquipmentID"])
        for r in special_map
    }

    allocations_by_exam = defaultdict(list)
    for row in allocations:
        allocations_by_exam[int(row["ExamID"])].append(row)

    # Build a resource-demand vector for every course and sitting ordinal.
    # Vector: rooms, accessible rooms, computer rooms, accessible-desk rooms,
    # student count.
    course_vectors = {}

    for course_id, sittings in exams_by_course.items():
        vector = []

        for ordinal in (1, 2, 3):
            exam_id = int(sittings[ordinal]["ExamID"])
            students = allocations_by_exam[exam_id]

            separate = set()
            accessible = set()
            computer = set()
            desk = set()

            for allocation in students:
                sid = int(allocation["StudentID"])

                for acc in accommodation_by_student.get(sid, []):
                    if not active_on(acc, day6):
                        continue

                    kind = acc["AccommodationType"].strip().upper()

                    if kind == "SEPARATE_ROOM" or truth(
                        acc.get("RequiresSeparateRoom")
                    ):
                        separate.add(sid)

                    elif kind == "ACCESSIBLE_ROOM":
                        accessible.add(sid)

                    elif kind == "SPECIAL_EQUIPMENT":
                        eq_id = special_by_student.get(sid)
                        if eq_id == 1:
                            computer.add(sid)
                        elif eq_id == 4:
                            desk.add(sid)
                        else:
                            raise ValueError(
                                f"Missing/unsupported equipment mapping for student {sid}"
                            )

            total = len(students)
            separate_count = len(separate)
            shared_count = total - separate_count

            room_demand = separate_count + (1 if shared_count else 0)

            accessible_demand = (
                len(accessible.intersection(separate))
                + (1 if accessible - separate else 0)
            )

            computer_demand = (
                len(computer.intersection(separate))
                + (1 if computer - separate else 0)
            )

            desk_demand = (
                len(desk.intersection(separate))
                + (1 if desk - separate else 0)
            )

            vector.append([
                room_demand,
                accessible_demand,
                computer_demand,
                desk_demand,
                total
            ])

        course_vectors[course_id] = vector

    # Calculate global totals for each of the 15 resource dimensions.
    dimensions = 15
    global_totals = [0] * dimensions

    for vector in course_vectors.values():
        flat = [x for sitting in vector for x in sitting]
        for i, value in enumerate(flat):
            global_totals[i] += value

    target_sizes = {"MORNING": 38, "AFTERNOON": 37}
    wave_totals = {
        "MORNING": [0] * dimensions,
        "AFTERNOON": [0] * dimensions
    }
    wave_courses = {"MORNING": [], "AFTERNOON": []}

    # Process high-resource-demand courses first.
    def burden(course_id):
        flat = [x for sitting in course_vectors[course_id] for x in sitting]
        return (
            flat[1] * 1000
            + flat[0] * 100
            + flat[2] * 20
            + flat[3] * 20
            + flat[4]
        )

    ordered_courses = sorted(
        course_vectors,
        key=lambda cid: (-burden(cid), cid)
    )

    def score(candidate_wave, course_id):
        candidate_totals = {
            name: list(values) for name, values in wave_totals.items()
        }

        flat = [
            x for sitting in course_vectors[course_id] for x in sitting
        ]

        for i, value in enumerate(flat):
            candidate_totals[candidate_wave][i] += value

        result = 0.0

        for name in ("MORNING", "AFTERNOON"):
            target_ratio = target_sizes[name] / 75
            for i in range(dimensions):
                target = global_totals[i] * target_ratio
                scale = max(1.0, math.sqrt(global_totals[i] + 1))
                difference = candidate_totals[name][i] - target
                result += (difference / scale) ** 2

        return result

    for course_id in ordered_courses:
        candidates = [
            name for name in ("MORNING", "AFTERNOON")
            if len(wave_courses[name]) < target_sizes[name]
        ]

        chosen = min(
            candidates,
            key=lambda name: (score(name, course_id), name)
        )

        flat = [
            x for sitting in course_vectors[course_id] for x in sitting
        ]

        for i, value in enumerate(flat):
            wave_totals[chosen][i] += value

        wave_courses[chosen].append(course_id)

    # Resource inventory for Day 6.
    active_rooms = [
        r for r in rooms if truth(r["IsActive"])
    ]
    active_invigilators = {
        int(r["InvigilatorID"])
        for r in invigilators
        if r["Status"].strip().upper() == "ACTIVE"
    }

    grid_times = {}
    for row in grid:
        if int(row["DayIndex"]) == 6:
            slot = int(row["SlotNumber"])
            grid_times[slot] = row["SlotStartTime"]

    if set(grid_times) != {1, 2, 3, 4, 5, 6}:
        raise ValueError("Physical room grid does not contain all six Day 6 slots")

    room_equipment_index = defaultdict(list)
    for row in room_equipment:
        room_equipment_index[
            (int(row["RoomID"]), int(row["EquipmentID"]))
        ].append(row)

    def capacity(room_id):
        values = []
        for row in capacities:
            if int(row["RoomID"]) == room_id and active_on(row, day6):
                values.append(int(row["Capacity"]))
        return max(values) if values else 0

    def equipment_qty(room_id, equipment_id):
        total = 0
        for row in room_equipment_index.get((room_id, equipment_id), []):
            if active_on(row, day6):
                total += int(row["Quantity"])
        return total

    def available_room(room, start, end):
        rid = int(room["RoomID"])

        for closure in closures:
            if (
                int(closure["RoomID"]) == rid
                and closure["ClosureStatus"].strip().upper() == "ACTIVE"
            ):
                cstart = parse_dt(closure["ClosureStart"])
                cend = parse_dt(closure["ClosureEnd"])
                if start < cend and cstart < end:
                    return False

        return capacity(rid) > 0

    def available_staff(start, end):
        found = set()

        for row in availability:
            iid = int(row["InvigilatorID"])

            if iid not in active_invigilators:
                continue

            if row["AvailabilityStatus"].strip().upper() != "AVAILABLE":
                continue

            if parse_dt(row["AvailableFrom"]) <= start and parse_dt(
                row["AvailableTo"]
            ) >= end:
                found.add(iid)

        return len(found)

    plan_rows = []
    slot_results = []

    for wave, block_id, offset in (
        ("MORNING", 11, 0),
        ("AFTERNOON", 12, 3)
    ):
        for course_id in sorted(wave_courses[wave]):
            affected_tracks = {
                int(r["TrackID"])
                for ordinal in (1, 2, 3)
                for r in allocations_by_exam[
                    int(exams_by_course[course_id][ordinal]["ExamID"])
                ]
            }

            plan_rows.append({
                "CourseID": course_id,
                "BlockID": block_id,
                "ExamDate": day6.isoformat(),
                "Period": wave,
                "AffectedTrackCount": len(affected_tracks)
            })

        for ordinal in (1, 2, 3):
            slot_number = ordinal + offset
            start_time = datetime.combine(
                day6,
                datetime.strptime(grid_times[slot_number], "%H:%M").time()
            )

            exam_ids = [
                int(exams_by_course[cid][ordinal]["ExamID"])
                for cid in wave_courses[wave]
            ]

            exam_end_times = []
            room_demand = 0
            accessible_demand = 0
            computer_demand = 0
            desk_demand = 0
            students_total = 0

            for exam_id in exam_ids:
                rows = allocations_by_exam[exam_id]
                end = max(
                    parse_dt(r["EffectiveEndDateTime"]) for r in rows
                )
                exam_end_times.append(end)

                course_id = int(timetable_by_id[exam_id]["CourseID"]) if False else None

                # Recover the course and sitting from the exam lookup.
                exam_row = next(
                    r for r in optional_exams if int(r["ExamID"]) == exam_id
                )
                cid = int(exam_row["CourseID"])
                sit = int(exam_row["SittingOrdinal"])
                metrics = course_vectors[cid][sit - 1]

                room_demand += metrics[0]
                accessible_demand += metrics[1]
                computer_demand += metrics[2]
                desk_demand += metrics[3]
                students_total += metrics[4]

            slot_end = max(exam_end_times)

            usable_rooms = [
                r for r in active_rooms
                if available_room(r, start_time, slot_end)
            ]

            room_count = len(usable_rooms)
            accessible_count = sum(
                1 for r in usable_rooms
                if r["RoomType"].strip().upper() == "ACCESSIBLE"
            )

            computer_room_count = sum(
                1 for r in usable_rooms
                if equipment_qty(int(r["RoomID"]), 1) >= 1
            )
            desk_room_count = sum(
                1 for r in usable_rooms
                if equipment_qty(int(r["RoomID"]), 4) >= 1
            )

            staff_count = available_staff(start_time, slot_end)

            errors = []
            if room_demand > room_count:
                errors.append("ROOM_SHORTAGE")
            if accessible_demand > accessible_count:
                errors.append("ACCESSIBLE_ROOM_SHORTAGE")
            if computer_demand > computer_room_count:
                errors.append("COMPUTER_EQUIPPED_ROOM_SHORTAGE")
            if desk_demand > desk_room_count:
                errors.append("ACCESSIBLE_DESK_EQUIPPED_ROOM_SHORTAGE")
            if room_demand > staff_count:
                errors.append("INVIGILATOR_SHORTAGE")

            slot_results.append({
                "Wave": wave,
                "SlotNumber": slot_number,
                "ExamSittings": len(exam_ids),
                "StudentAllocations": students_total,
                "MinimumRoomDemand": room_demand,
                "AvailableRooms": room_count,
                "AccessibleRoomDemand": accessible_demand,
                "AvailableAccessibleRooms": accessible_count,
                "ComputerRoomDemand": computer_demand,
                "AvailableComputerRooms": computer_room_count,
                "DeskRoomDemand": desk_demand,
                "AvailableDeskRooms": desk_room_count,
                "MinimumInvigilators": room_demand,
                "AvailableInvigilators": staff_count,
                "Errors": errors
            })

    PLAN_CSV.parent.mkdir(parents=True, exist_ok=True)

    with PLAN_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "CourseID", "BlockID", "ExamDate",
                "Period", "AffectedTrackCount"
            ]
        )
        writer.writeheader()
        writer.writerows(plan_rows)

    report = {
        "Version": "2.2.0",
        "Plan": "Optional exams split into two waves",
        "MorningCourseCount": len(wave_courses["MORNING"]),
        "AfternoonCourseCount": len(wave_courses["AFTERNOON"]),
        "MorningCourses": sorted(wave_courses["MORNING"]),
        "AfternoonCourses": sorted(wave_courses["AFTERNOON"]),
        "SlotsChecked": len(slot_results),
        "TotalErrors": sum(len(r["Errors"]) for r in slot_results),
        "Status": (
            "PASSED"
            if all(not r["Errors"] for r in slot_results)
            else "FAILED"
        ),
        "SlotResults": slot_results,
        "Note": (
            "This is a lower-bound feasibility preview, not a completed "
            "room allocation. Equipment quantity per room and actual "
            "room-to-exam matching must be checked by the allocator."
        )
    }

    REPORT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("=" * 90)
    print("OPTIONAL TWO-WAVE RESOURCE PLAN")
    print("=" * 90)
    print(f"Morning courses   : {len(wave_courses['MORNING'])}")
    print(f"Afternoon courses : {len(wave_courses['AFTERNOON'])}")
    print("\nWAVE       SLOT  EXAMS  MIN ROOMS  ACCESS  ACCESS AVAIL  COMPUTER  DESK  STAFF")
    print("-" * 90)

    for row in slot_results:
        print(
            f"{row['Wave']:<10} "
            f"{row['SlotNumber']:>2} "
            f"{row['ExamSittings']:>6} "
            f"{row['MinimumRoomDemand']:>10} "
            f"{row['AccessibleRoomDemand']:>7} "
            f"{row['AvailableAccessibleRooms']:>13} "
            f"{row['ComputerRoomDemand']:>9} "
            f"{row['DeskRoomDemand']:>5} "
            f"{row['AvailableInvigilators']:>6}"
        )

        for error in row["Errors"]:
            print(f"    ERROR: {error}")

    print("\nStatus:", report["Status"])
    print("Preview CSV:", PLAN_CSV)
    print("Preview JSON:", REPORT_JSON)
    print("Existing timetable files: NOT MODIFIED")
    print("SQL Server: NOT ACCESSED OR MODIFIED")

if __name__ == "__main__":
    timetable_by_id = {
        int(r["ExamID"]): r for r in read_csv("ExamTimetable.csv")
    }
    main()
