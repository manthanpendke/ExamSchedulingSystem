
#!/usr/bin/env python3
"""Safe Laboratory Kit redistribution for Exam Scheduling System v2.2.0.

Default: dry run. Apply changes only with --apply.
Only RoomEquipment.csv may be changed. Total Laboratory Kit quantity is conserved.
"""

import argparse
import csv
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = DATA / "scheduling"

FILES = {
    "rooms": DATA / "Room.csv",
    "capacities": DATA / "RoomCapacity.csv",
    "room_equipment": DATA / "RoomEquipment.csv",
    "equipment": DATA / "Equipment.csv",
    "closures": DATA / "RoomClosure.csv",
    "timetable": SCHED / "ExamTimetable.csv",
    "exam_equipment": DATA / "ExamRequiredEquipment.csv",
}
ROOM_EQUIPMENT = FILES["room_equipment"]
LAB_NAME = "Laboratory Kit"
EXPECTED_TOTAL = 1000
ORIGINAL_LAB_ROOMS = 10
TARGET_LAB_ROOMS = 15
CSV_COLUMNS = [
    "RoomEquipmentID", "RoomID", "EquipmentID", "Quantity",
    "EffectiveFrom", "EffectiveTo",
]


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader)


def write_csv_atomic(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", delete=False,
        dir=str(path.parent), suffix=".tmp"
    ) as f:
        temp = Path(f.name)
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def write_json_atomic(path, value):
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp"
    ) as f:
        temp = Path(f.name)
        json.dump(value, f, indent=2)
        f.write("\n")
    temp.replace(path)


def integer(value, field):
    try:
        return int(str(value).strip())
    except Exception as exc:
        raise ValueError(f"{field} must be an integer: {value!r}") from exc


def truth(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def date_value(value, field):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value!r}") from exc


def datetime_value(value, field):
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid {field}: {value!r}")


def active_on(row, day):
    start = date_value(row.get("EffectiveFrom"), "EffectiveFrom")
    end = date_value(row.get("EffectiveTo"), "EffectiveTo")
    return not ((start and day < start) or (end and day > end))


def overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def load_data():
    return {key: read_csv(path) for key, path in FILES.items()}


def validate_sources(d):
    for label, rows, key in (
        ("Room", d["rooms"], "RoomID"),
        ("Equipment", d["equipment"], "EquipmentID"),
        ("RoomEquipment", d["room_equipment"], "RoomEquipmentID"),
    ):
        values = [integer(r[key], f"{label}.{key}") for r in rows]
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate {label}.{key} values.")

    room_ids = {integer(r["RoomID"], "RoomID") for r in d["rooms"]}
    equip_ids = {integer(r["EquipmentID"], "EquipmentID") for r in d["equipment"]}
    pairs = set()

    for row in d["room_equipment"]:
        rid = integer(row["RoomID"], "RoomEquipment.RoomID")
        eid = integer(row["EquipmentID"], "RoomEquipment.EquipmentID")
        qty = integer(row["Quantity"], "RoomEquipment.Quantity")
        if rid not in room_ids or eid not in equip_ids:
            raise ValueError(f"RoomEquipment has an invalid reference: {row}")
        if qty < 0:
            raise ValueError(f"Negative equipment quantity: {row}")
        if (rid, eid) in pairs:
            raise ValueError(f"Duplicate RoomID/EquipmentID pair: {(rid, eid)}")
        pairs.add((rid, eid))

    matches = [
        r for r in d["equipment"]
        if r.get("EquipmentName", "").strip().lower() == LAB_NAME.lower()
    ]
    if len(matches) != 1 or not truth(matches[0].get("IsActive")):
        raise ValueError("Expected exactly one active Laboratory Kit record.")
    return integer(matches[0]["EquipmentID"], "Equipment.EquipmentID")


def build_lab_exam_intervals(d, lab_id):
    lab_exam_ids = {
        integer(r["ExamID"], "ExamRequiredEquipment.ExamID")
        for r in d["exam_equipment"]
        if integer(r["EquipmentID"], "ExamRequiredEquipment.EquipmentID") == lab_id
        and truth(r.get("IsMandatory"))
    }
    intervals = []
    for row in d["timetable"]:
        exam_id = integer(row["ExamID"], "ExamTimetable.ExamID")
        if exam_id not in lab_exam_ids:
            continue
        start = datetime_value(row["StartDateTime"], "StartDateTime")
        end = datetime_value(row["EndDateTime"], "EndDateTime")
        if end <= start:
            raise ValueError(f"Invalid exam interval for ExamID {exam_id}.")
        intervals.append((exam_id, start, end, start.date()))
    if not intervals:
        raise ValueError("No mandatory Laboratory Kit exams found.")
    return intervals


def capacity_on(room_id, day, capacities):
    vals = [
        integer(r["Capacity"], "RoomCapacity.Capacity")
        for r in capacities
        if integer(r["RoomID"], "RoomCapacity.RoomID") == room_id
        and active_on(r, day)
    ]
    return max(vals) if vals else 0


def equipment_on(room_id, equipment_id, day, rows):
    return sum(
        integer(r["Quantity"], "RoomEquipment.Quantity")
        for r in rows
        if integer(r["RoomID"], "RoomEquipment.RoomID") == room_id
        and integer(r["EquipmentID"], "RoomEquipment.EquipmentID") == equipment_id
        and active_on(r, day)
    )


def closed_during_lab_exam(room_id, intervals, closures):
    for closure in closures:
        if integer(closure["RoomID"], "RoomClosure.RoomID") != room_id:
            continue
        if str(closure.get("ClosureStatus", "")).upper() != "ACTIVE":
            continue
        c0 = datetime_value(closure["ClosureStart"], "ClosureStart")
        c1 = datetime_value(closure["ClosureEnd"], "ClosureEnd")
        if c1 <= c0:
            raise ValueError(f"Invalid closure interval: {closure}")
        if any(overlaps(s, e, c0, c1) for _, s, e, _ in intervals):
            return True
    return False


def choose_new_rooms(d, existing_lab_ids, intervals):
    room_by_id = {
        integer(r["RoomID"], "RoomID"): r for r in d["rooms"]
    }
    days = sorted({day for _, _, _, day in intervals})

    equipment_by_name = {
        r["EquipmentName"].strip().lower():
        integer(r["EquipmentID"], "EquipmentID")
        for r in d["equipment"]
    }
    computer_id = equipment_by_name.get("desktop computer")
    desk_id = equipment_by_name.get("accessible desk")
    if computer_id is None or desk_id is None:
        raise ValueError("Desktop Computer and Accessible Desk records are required.")

    standard, accessible = [], []

    for rid, room in room_by_id.items():
        room_type = str(room.get("RoomType", "")).strip().upper()
        if rid in existing_lab_ids or not truth(room.get("IsActive")):
            continue
        if room_type not in {"STANDARD", "ACCESSIBLE"}:
            continue
        if not all(capacity_on(rid, day, d["capacities"]) > 0 for day in days):
            continue
        if closed_during_lab_exam(rid, intervals, d["closures"]):
            continue

        computer_qty = min(
            equipment_on(rid, computer_id, day, d["room_equipment"])
            for day in days
        )
        if computer_qty <= 0:
            continue

        min_capacity = min(
            capacity_on(rid, day, d["capacities"]) for day in days
        )

        candidate = {
            "RoomID": rid,
            "RoomCode": room.get("RoomCode", ""),
            "RoomType": room_type,
            "MinimumEffectiveCapacity": min_capacity,
            "DesktopComputerQuantity": computer_qty,
        }

        if room_type == "STANDARD":
            standard.append(candidate)
        else:
            desk_qty = min(
                equipment_on(rid, desk_id, day, d["room_equipment"])
                for day in days
            )
            if desk_qty > 0:
                candidate["AccessibleDeskQuantity"] = desk_qty
                accessible.append(candidate)

    standard.sort(key=lambda x: (
        -x["MinimumEffectiveCapacity"],
        -x["DesktopComputerQuantity"],
        x["RoomID"],
    ))
    accessible.sort(key=lambda x: (
        -x["MinimumEffectiveCapacity"],
        -x["AccessibleDeskQuantity"],
        -x["DesktopComputerQuantity"],
        x["RoomID"],
    ))

    if len(standard) < 4:
        raise ValueError(
            f"Only {len(standard)} suitable STANDARD rooms found; need 4."
        )
    if not accessible:
        raise ValueError(
            "No accessible room with both Desktop Computer and Accessible Desk "
            "inventory is available."
        )
    return standard[:4], accessible[:1]


def validate_plan(original, planned, lab_id, total, quantities):
    original_non_lab = [
        r for r in original
        if integer(r["EquipmentID"], "EquipmentID") != lab_id
    ]
    planned_non_lab = [
        r for r in planned
        if integer(r["EquipmentID"], "EquipmentID") != lab_id
    ]
    if original_non_lab != planned_non_lab:
        raise ValueError("A non-Laboratory-Kit equipment row was changed.")

    lab_rows = [
        r for r in planned
        if integer(r["EquipmentID"], "EquipmentID") == lab_id
        and integer(r["Quantity"], "Quantity") > 0
    ]
    actual = defaultdict(int)
    for row in lab_rows:
        actual[integer(row["RoomID"], "RoomID")] += integer(
            row["Quantity"], "Quantity"
        )

    if sum(actual.values()) != total:
        raise ValueError("Total Laboratory Kit quantity changed.")
    if dict(actual) != dict(quantities):
        raise ValueError("Final room quantities do not match the plan.")

    ids = [integer(r["RoomEquipmentID"], "RoomEquipmentID") for r in planned]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate RoomEquipmentID in planned file.")

    pairs = [
        (integer(r["RoomID"], "RoomID"), integer(r["EquipmentID"], "EquipmentID"))
        for r in planned
    ]
    if len(pairs) != len(set(pairs)):
        raise ValueError("Duplicate RoomID/EquipmentID pair in planned file.")


def build_plan(d):
    lab_id = validate_sources(d)
    intervals = build_lab_exam_intervals(d, lab_id)

    lab_rows = [
        r for r in d["room_equipment"]
        if integer(r["EquipmentID"], "EquipmentID") == lab_id
        and integer(r["Quantity"], "Quantity") > 0
    ]
    current = defaultdict(int)
    for row in lab_rows:
        current[integer(row["RoomID"], "RoomID")] += integer(
            row["Quantity"], "Quantity"
        )

    total = sum(current.values())
    existing_ids = set(current)

    # Idempotent: a correct 15-room distribution is accepted without rewriting.
    if len(existing_ids) == 15:
        room_types = {
            integer(r["RoomID"], "RoomID"): str(r["RoomType"]).strip().upper()
            for r in d["rooms"]
        }
        composition = defaultdict(int)
        for rid in existing_ids:
            composition[room_types.get(rid, "UNKNOWN")] += 1

        if (
            total != EXPECTED_TOTAL
            or any(q not in (66, 67) for q in current.values())
            or composition != {"LAB": 10, "STANDARD": 4, "ACCESSIBLE": 1}
        ):
            raise ValueError(
                "15 equipped rooms exist, but the inventory distribution or "
                "room-type composition is not the expected 10 LAB, 4 STANDARD, "
                "1 ACCESSIBLE with 1,000 units. Manual review required."
            )
        return {
            "already_applied": True, "lab_id": lab_id, "intervals": intervals,
            "total": total, "quantities": dict(current),
            "planned": d["room_equipment"], "existing_ids": sorted(existing_ids),
            "new_standard": [], "new_accessible": [],
        }

    if len(existing_ids) != ORIGINAL_LAB_ROOMS:
        raise ValueError(
            f"Expected {ORIGINAL_LAB_ROOMS} original LAB rooms; found "
            f"{len(existing_ids)}. This may be a partial modification. "
            "No changes made."
        )
    if total != EXPECTED_TOTAL:
        raise ValueError(
            f"Expected {EXPECTED_TOTAL} Laboratory Kit units; found {total}. "
            "No changes made."
        )

    room_types = {
        integer(r["RoomID"], "RoomID"): str(r["RoomType"]).upper()
        for r in d["rooms"]
    }
    if any(room_types.get(rid) != "LAB" for rid in existing_ids):
        raise ValueError("Existing Laboratory Kit stock is not confined to LAB rooms.")

    std, acc = choose_new_rooms(d, existing_ids, intervals)
    std_ids = [r["RoomID"] for r in std]
    acc_ids = [r["RoomID"] for r in acc]
    all_ids = sorted(existing_ids) + std_ids + acc_ids

    if len(set(all_ids)) != 15:
        raise ValueError("The planned 15 rooms are not unique.")

    # Preserve all 1,000 units: 10 rooms receive 67, 5 rooms receive 66.
    quantities = {
        rid: (67 if index < 10 else 66)
        for index, rid in enumerate(all_ids)
    }
    if sum(quantities.values()) != total:
        raise AssertionError("Internal inventory conservation check failed.")

    effective_ranges = {
        (str(r.get("EffectiveFrom", "")).strip(),
         str(r.get("EffectiveTo", "")).strip())
        for r in lab_rows
    }
    if len(effective_ranges) != 1:
        raise ValueError(
            "Existing Laboratory Kit rows have different effective date ranges; "
            "refusing to invent dates."
        )
    effective_from, effective_to = next(iter(effective_ranges))

    planned = []
    for row in d["room_equipment"]:
        updated = dict(row)
        if integer(row["EquipmentID"], "EquipmentID") == lab_id:
            rid = integer(row["RoomID"], "RoomID")
            updated["Quantity"] = str(quantities[rid])
        planned.append(updated)

    max_id = max(
        integer(r["RoomEquipmentID"], "RoomEquipmentID")
        for r in d["room_equipment"]
    )
    for rid in std_ids + acc_ids:
        max_id += 1
        planned.append({
            "RoomEquipmentID": str(max_id),
            "RoomID": str(rid),
            "EquipmentID": str(lab_id),
            "Quantity": str(quantities[rid]),
            "EffectiveFrom": effective_from,
            "EffectiveTo": effective_to,
        })

    validate_plan(
        d["room_equipment"], planned, lab_id, total, quantities
    )
    return {
        "already_applied": False, "lab_id": lab_id, "intervals": intervals,
        "total": total, "quantities": quantities, "planned": planned,
        "existing_ids": sorted(existing_ids), "new_standard": std,
        "new_accessible": acc,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply the validated change. Without this flag, only preview."
    )
    args = parser.parse_args()

    SCHED.mkdir(parents=True, exist_ok=True)
    d = load_data()
    plan = build_plan(d)

    preview_path = SCHED / "lab_kit_redistribution_preview_v220.csv"
    report_path = SCHED / "lab_kit_redistribution_report_v220.json"

    if plan["already_applied"]:
        report = {
            "version": "2.2.0",
            "status": "ALREADY_APPLIED",
            "equipment": LAB_NAME,
            "equipment_id": plan["lab_id"],
            "total_quantity": plan["total"],
            "equipped_room_count": len(plan["quantities"]),
            "quantity_by_room": {
                str(k): v for k, v in sorted(plan["quantities"].items())
            },
            "no_changes_made": True,
            "database_accessed": False,
            "ground_truth_accessed": False,
        }
        write_json_atomic(report_path, report)
        print("Redistribution already applied correctly. No changes made.")
        print(f"Report: {report_path}")
        return 0

    backup_path = None
    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = ROOM_EQUIPMENT.with_name(
            f"RoomEquipment.backup_before_lab_redistribution_{stamp}.csv"
        )
        shutil.copy2(ROOM_EQUIPMENT, backup_path)
        try:
            write_csv_atomic(ROOM_EQUIPMENT, plan["planned"], CSV_COLUMNS)
            persisted = read_csv(ROOM_EQUIPMENT)
            validate_plan(
                d["room_equipment"], persisted, plan["lab_id"],
                plan["total"], plan["quantities"]
            )
        except Exception:
            shutil.copy2(backup_path, ROOM_EQUIPMENT)
            raise

    room_by_id = {
        integer(r["RoomID"], "RoomID"): r for r in d["rooms"]
    }
    preview = []
    for rid, qty in sorted(plan["quantities"].items()):
        room = room_by_id[rid]
        preview.append({
            "RoomID": rid,
            "RoomCode": room.get("RoomCode", ""),
            "RoomType": room.get("RoomType", ""),
            "LaboratoryKitQuantity": qty,
            "NewlyEquipped": rid not in plan["existing_ids"],
        })
    write_csv_atomic(preview_path, preview, [
        "RoomID", "RoomCode", "RoomType",
        "LaboratoryKitQuantity", "NewlyEquipped",
    ])

    report = {
        "version": "2.2.0",
        "status": "APPLIED" if args.apply else "DRY_RUN_READY",
        "equipment": LAB_NAME,
        "equipment_id": plan["lab_id"],
        "original_total_quantity": plan["total"],
        "planned_total_quantity": sum(plan["quantities"].values()),
        "equipped_rooms_before": len(plan["existing_ids"]),
        "equipped_rooms_after": len(plan["quantities"]),
        "new_standard_rooms": plan["new_standard"],
        "new_accessible_rooms": plan["new_accessible"],
        "quantity_by_room": {
            str(k): v for k, v in sorted(plan["quantities"].items())
        },
        "lab_exam_sittings_checked": len(plan["intervals"]),
        "lab_exam_dates_checked": sorted({
            day.isoformat() for _, _, _, day in plan["intervals"]
        }),
        "only_room_equipment_csv_modified": bool(args.apply),
        "room_types_capacities_closures_timetable_students_unchanged": True,
        "non_lab_equipment_unchanged": True,
        "database_accessed": False,
        "database_modified": False,
        "ground_truth_accessed": False,
        "backup_file": str(backup_path) if backup_path else None,
        "notes": [
            "Only RoomEquipment.csv is changed when --apply is supplied.",
            "Total Laboratory Kit quantity remains exactly 1,000.",
            "Four STANDARD rooms and one ACCESSIBLE room are added.",
            "The accessible target already has Desktop Computer and Accessible Desk stock.",
            "Rerun room_allocator_v220.py and independent_room_allocation_validator_v220.py afterward.",
            "This redistribution does not itself guarantee 20,000 room assignments.",
        ],
    }
    write_json_atomic(report_path, report)

    print("\n" + "=" * 66)
    print("LABORATORY KIT REDISTRIBUTION — v2.2.0")
    print("=" * 66)
    print("Mode                  :", "APPLY" if args.apply else "DRY RUN")
    print("Equipment ID          :", plan["lab_id"])
    print("Total quantity        :", plan["total"], "->", sum(plan["quantities"].values()))
    print("Equipped rooms        :", len(plan["existing_ids"]), "->", len(plan["quantities"]))
    print("New STANDARD rooms    :", [r["RoomID"] for r in plan["new_standard"]])
    print("New ACCESSIBLE room   :", [r["RoomID"] for r in plan["new_accessible"]])
    print("Lab exam sittings     :", len(plan["intervals"]))
    print("Quantity distribution :", {
        q: list(plan["quantities"].values()).count(q)
        for q in sorted(set(plan["quantities"].values()))
    })
    if backup_path:
        print("Backup                :", backup_path)
    print("Preview CSV           :", preview_path)
    print("Report JSON           :", report_path)
    print("SQL Server            : NOT ACCESSED OR MODIFIED")
    print("GroundTruth           : NOT ACCESSED")
    print("Timetable             : NOT MODIFIED")
    print("Room/Capacity/Closure : NOT MODIFIED")
    print("=" * 66)
    print(
        "\nSUCCESS: change applied and read-back validated."
        if args.apply else
        "\nDRY RUN ONLY: no source inventory was changed. "
        "Review preview, then run with --apply."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"\nREDISTRIBUTION FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print("No unvalidated changes were intentionally committed.", file=sys.stderr)
        sys.exit(1)
