
import csv
import json
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
META = DATA / "metadata"
SCHED = DATA / "scheduling"
OUT = SCHED / "resource_capacity_precheck_v220.json"


def locate(filename):
    for folder in (DATA, META, SCHED):
        path = folder / filename
        if path.exists():
            return path
    raise FileNotFoundError(f"Cannot locate {filename}")


def read_csv(filename):
    with locate(filename).open(
        "r", encoding="utf-8-sig", newline=""
    ) as f:
        return list(csv.DictReader(f))


def parse_date(value):
    if not value:
        return None
    return date.fromisoformat(value.strip()[:10])


def parse_dt(value):
    if not value:
        return None
    value = value.strip()

    # Normalize values such as 2026-11-1614:30:00
    if len(value) >= 19 and value[10] != " ":
        value = value[:10] + " " + value[10:]

    return datetime.fromisoformat(value)


def active_on(row, exam_date, start_key="EffectiveFrom",
              end_key="EffectiveTo"):
    start = parse_date(row.get(start_key))
    end = parse_date(row.get(end_key))
    return (
        (start is None or start <= exam_date)
        and (end is None or exam_date <= end)
    )


def truth(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def main():
    print("=" * 76)
    print("V2.2.0 RESOURCE CAPACITY PRECHECK")
    print("=" * 76)

    timetable = read_csv("ExamTimetable.csv")
    allocations = read_csv("TimetableStudentAllocation.csv")
    accommodations = read_csv("Accommodation.csv")
    rooms = read_csv("Room.csv")
    capacities = read_csv("RoomCapacity.csv")
    closures = read_csv("RoomClosure.csv")
    equipment = read_csv("Equipment.csv")
    room_equipment = read_csv("RoomEquipment.csv")
    special_requirements = read_csv(
        "StudentSpecialEquipmentRequirement.csv"
    )
    invigilators = read_csv("Invigilator.csv")
    availability = read_csv("Availability.csv")

    # Active accommodation records by student and exam date.
    accommodation_by_student = defaultdict(list)
    for row in accommodations:
        if row.get("AccommodationStatus", "").upper() == "ACTIVE":
            accommodation_by_student[int(row["StudentID"])].append(row)

    special_by_student = {
        int(row["StudentID"]): int(row["EquipmentID"])
        for row in special_requirements
    }

    # Active room capacities, evaluated for each exam date.
    active_rooms = [
        r for r in rooms if truth(r.get("IsActive"))
    ]

    active_invigilators = {
        int(r["InvigilatorID"])
        for r in invigilators
        if r.get("Status", "").upper() == "ACTIVE"
    }

    # Index room equipment by room and equipment.
    room_equipment_index = defaultdict(list)
    for row in room_equipment:
        room_equipment_index[
            (int(row["RoomID"]), int(row["EquipmentID"]))
        ].append(row)

    equipment_by_id = {
        int(r["EquipmentID"]): r for r in equipment
    }

    # Group student allocations by sitting and timetable slot.
    exam_students = defaultdict(list)
    slot_exams = defaultdict(set)
    slot_intervals = defaultdict(list)

    for row in allocations:
        exam_id = int(row["ExamID"])
        student_id = int(row["StudentID"])
        exam_date = parse_date(row["ExamDate"])
        slot_number = int(row["SlotNumber"])
        slot_key = (exam_date.isoformat(), slot_number)

        start = parse_dt(row["StartDateTime"])
        end = parse_dt(row["EffectiveEndDateTime"])

        exam_students[exam_id].append({
            "student_id": student_id,
            "date": exam_date,
            "slot_key": slot_key,
            "start": start,
            "end": end,
        })

        slot_exams[slot_key].add(exam_id)
        slot_intervals[slot_key].append((start, end))

    # Use the timetable to verify every sitting has allocations.
    timetable_by_id = {
        int(r["ExamID"]): r for r in timetable
    }

    def get_accommodations(student_id, exam_date):
        result = []
        for row in accommodation_by_student.get(student_id, []):
            if active_on(row, exam_date):
                result.append(row)
        return result

    def capacity_for_room(room_id, exam_date):
        values = []
        for row in capacities:
            if int(row["RoomID"]) != room_id:
                continue
            if active_on(row, exam_date):
                values.append(int(row["Capacity"]))
        return max(values) if values else 0

    def room_is_closed(room_id, start, end):
        for row in closures:
            if int(row["RoomID"]) != room_id:
                continue
            if row.get("ClosureStatus", "").upper() != "ACTIVE":
                continue

            closure_start = parse_dt(row["ClosureStart"])
            closure_end = parse_dt(row["ClosureEnd"])

            if closure_start and closure_end:
                if start < closure_end and closure_start < end:
                    return True
        return False

    def equipment_quantity(room_id, equipment_id, exam_date):
        total = 0
        for row in room_equipment_index.get(
            (room_id, equipment_id), []
        ):
            if active_on(row, exam_date):
                total += int(row["Quantity"])
        return total

    def available_invigilator_count(start, end):
        found = set()

        for row in availability:
            inv_id = int(row["InvigilatorID"])

            if inv_id not in active_invigilators:
                continue

            if row.get("AvailabilityStatus", "").upper() != "AVAILABLE":
                continue

            available_from = parse_dt(row["AvailableFrom"])
            available_to = parse_dt(row["AvailableTo"])

            if (
                available_from
                and available_to
                and available_from <= start
                and available_to >= end
            ):
                found.add(inv_id)

        return len(found)

    # Equipment inventory by room.
    active_equipment_ids = {
        int(r["EquipmentID"])
        for r in equipment
        if truth(r.get("IsActive"))
    }

    results = []
    total_errors = 0
    total_warnings = 0

    for slot_key in sorted(slot_exams):
        date_text, slot_number = slot_key
        exam_date = date.fromisoformat(date_text)
        exam_ids = sorted(slot_exams[slot_key])

        slot_rows = [
            row
            for exam_id in exam_ids
            for row in exam_students[exam_id]
        ]

        slot_start = min(r["start"] for r in slot_rows)
        slot_end = max(r["end"] for r in slot_rows)

        # Room inventory effective on this date.
        room_inventory = []
        for room in active_rooms:
            room_id = int(room["RoomID"])
            cap = capacity_for_room(room_id, exam_date)

            if cap <= 0:
                continue

            if room_is_closed(room_id, slot_start, slot_end):
                continue

            room_inventory.append({
                "id": room_id,
                "type": room["RoomType"].upper(),
                "capacity": cap,
            })

        max_capacity = max(
            (r["capacity"] for r in room_inventory), default=0
        )

        accessible_rooms = [
            r for r in room_inventory
            if r["type"] == "ACCESSIBLE"
        ]

        max_accessible_capacity = max(
            (r["capacity"] for r in accessible_rooms), default=0
        )

        room_lower_bound = 0
        accessible_room_lower_bound = 0
        equipment_room_demand = defaultdict(int)
        separate_student_count = 0
        accessible_student_count = 0
        special_student_count = defaultdict(int)
        exam_details = []

        for exam_id in exam_ids:
            students = exam_students[exam_id]

            separate_ids = set()
            accessible_ids = set()
            special_counts = defaultdict(int)

            for student in students:
                student_id = student["student_id"]

                for acc in get_accommodations(
                    student_id, student["date"]
                ):
                    acc_type = acc["AccommodationType"].upper()

                    if (
                        acc_type == "SEPARATE_ROOM"
                        or truth(acc.get("RequiresSeparateRoom"))
                    ):
                        separate_ids.add(student_id)

                    if acc_type == "ACCESSIBLE_ROOM":
                        accessible_ids.add(student_id)

                    if acc_type == "SPECIAL_EQUIPMENT":
                        eq_id = special_by_student.get(student_id)
                        if eq_id is None:
                            raise ValueError(
                                f"Missing equipment mapping for student "
                                f"{student_id}"
                            )
                        special_counts[eq_id] += 1

            total_students = len(students)
            separate_count = len(separate_ids)
            non_separate_count = total_students - separate_count
            accessible_separate = len(
                accessible_ids.intersection(separate_ids)
            )
            accessible_non_separate = (
                len(accessible_ids) - accessible_separate
            )

            separate_student_count += separate_count
            accessible_student_count += len(accessible_ids)

            if separate_count:
                exam_rooms = separate_count
            else:
                exam_rooms = 0

            if non_separate_count:
                if max_capacity <= 0:
                    shared_rooms = non_separate_count
                else:
                    shared_rooms = math.ceil(
                        non_separate_count / max_capacity
                    )
                exam_rooms += shared_rooms
            else:
                shared_rooms = 0

            room_lower_bound += exam_rooms

            # Accessible rooms are needed for accessible students.
            accessible_needed = accessible_separate

            if accessible_non_separate:
                if max_accessible_capacity <= 0:
                    accessible_needed += accessible_non_separate
                else:
                    accessible_needed += math.ceil(
                        accessible_non_separate
                        / max_accessible_capacity
                    )

            accessible_room_lower_bound += accessible_needed

            for eq_id, count in special_counts.items():
                special_student_count[eq_id] += count

                # Separate-room students each need their own
                # equipment-capable room. Non-separate students
                # need at least one equipped room for this sitting.
                separate_special = len(
                    set(
                        student["student_id"]
                        for student in students
                        if student["student_id"] in separate_ids
                        and any(
                            a["AccommodationType"].upper()
                            == "SPECIAL_EQUIPMENT"
                            for a in get_accommodations(
                                student["student_id"],
                                student["date"]
                            )
                        )
                        and special_by_student.get(
                            student["student_id"]
                        ) == eq_id
                    )
                )
                non_separate_special = count - separate_special

                equipment_room_demand[eq_id] += (
                    separate_special
                    + (1 if non_separate_special > 0 else 0)
                )

            exam_details.append({
                "ExamID": exam_id,
                "Students": total_students,
                "SeparateRoomStudents": separate_count,
                "AccessibleStudents": len(accessible_ids),
                "MinimumRooms": exam_rooms,
            })

        # Accessible rooms are a subset of shared room demand,
        # except for separate-room requirements already counted.
        # This is a lower-bound comparison, not an assignment.
        room_count = len(room_inventory)
        accessible_count = len(accessible_rooms)

        inv_available = available_invigilator_count(
            slot_start, slot_end
        )

        slot_errors = []
        slot_warnings = []

        if room_lower_bound > room_count:
            slot_errors.append(
                f"Room lower bound {room_lower_bound} exceeds "
                f"available rooms {room_count}"
            )

        if accessible_room_lower_bound > accessible_count:
            slot_errors.append(
                f"Accessible-room demand lower bound "
                f"{accessible_room_lower_bound} exceeds "
                f"available accessible rooms {accessible_count}"
            )

        if room_lower_bound > inv_available:
            slot_errors.append(
                f"Invigilator lower bound {room_lower_bound} exceeds "
                f"available invigilators {inv_available}"
            )

        for eq_id, demand in equipment_room_demand.items():
            equipped_rooms = sum(
                1 for room in room_inventory
                if equipment_quantity(
                    room["id"], eq_id, exam_date
                ) >= 1
            )

            if demand > equipped_rooms:
                slot_errors.append(
                    f"Equipment {eq_id}: room demand lower bound "
                    f"{demand}, equipped rooms available {equipped_rooms}"
                )

        if not room_inventory:
            slot_errors.append("No active, capacity-valid rooms available")

        total_errors += len(slot_errors)
        total_warnings += len(slot_warnings)

        results.append({
            "ExamDate": date_text,
            "SlotNumber": slot_number,
            "ExamSittings": len(exam_ids),
            "StudentAllocations": len(slot_rows),
            "MinimumRoomDemand": room_lower_bound,
            "AvailableRooms": room_count,
            "AccessibleRoomDemandLowerBound":
                accessible_room_lower_bound,
            "AvailableAccessibleRooms": accessible_count,
            "SeparateRoomStudents": separate_student_count,
            "AccessibleStudents": accessible_student_count,
            "AvailableInvigilators": inv_available,
            "EquipmentRoomDemandLowerBound": dict(
                equipment_room_demand
            ),
            "SpecialEquipmentStudentDemand": dict(
                special_student_count
            ),
            "Errors": slot_errors,
            "Warnings": slot_warnings,
            "ExamDetails": exam_details,
        })

    report = {
        "Version": "2.2.0",
        "Check": "Resource capacity lower-bound precheck",
        "TimetableSittings": len(timetable),
        "StudentAllocations": len(allocations),
        "ActiveRooms": len(active_rooms),
        "ActiveInvigilators": len(active_invigilators),
        "ActiveEquipment": len(active_equipment_ids),
        "SlotsChecked": len(results),
        "TotalErrors": total_errors,
        "TotalWarnings": total_warnings,
        "Status": "PASSED" if total_errors == 0 else "FAILED",
        "SlotResults": results,
        "Important": (
            "This is a lower-bound feasibility check. It does not "
            "prove a complete room or invigilator allocation."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    print("\nDATE       SLOT  EXAMS  MIN ROOMS  ROOMS  ACCESS DEMAND  ACCESS ROOMS  INVIG")
    print("-" * 85)

    for row in results:
        print(
            f"{row['ExamDate']}  "
            f"{row['SlotNumber']:>2}  "
            f"{row['ExamSittings']:>5}  "
            f"{row['MinimumRoomDemand']:>9}  "
            f"{row['AvailableRooms']:>5}  "
            f"{row['AccessibleRoomDemandLowerBound']:>13}  "
            f"{row['AvailableAccessibleRooms']:>12}  "
            f"{row['AvailableInvigilators']:>5}"
        )

        for error in row["Errors"]:
            print(f"    ERROR: {error}")

    print("\n" + "=" * 76)
    print(f"Slots checked : {len(results)}")
    print(f"Errors        : {total_errors}")
    print(f"Warnings      : {total_warnings}")
    print(f"Status        : {report['Status']}")
    print(f"Report        : {OUT}")
    print("SQL Server    : NOT ACCESSED OR MODIFIED")
    print("=" * 76)


if __name__ == "__main__":
    main()
