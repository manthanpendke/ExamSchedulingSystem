import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"
METADATA = DATA / "metadata"

ACCOMMODATION_FILE = DATA / "Accommodation.csv"
EQUIPMENT_FILE = DATA / "Equipment.csv"
OUTPUT_FILE = METADATA / "StudentSpecialEquipmentRequirement.csv"

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv_atomic(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp, path)

def main():
    accommodations = read_csv(ACCOMMODATION_FILE)
    equipment = read_csv(EQUIPMENT_FILE)

    special = [
        row for row in accommodations
        if row["AccommodationType"].strip() == "SPECIAL_EQUIPMENT"
        and row["AccommodationStatus"].strip().upper() == "ACTIVE"
    ]

    special.sort(key=lambda r: int(r["StudentID"]))

    if len(special) != 126:
        raise ValueError(
            f"Expected 126 active special-equipment records; found {len(special)}"
        )

    equipment_by_id = {
        int(row["EquipmentID"]): row
        for row in equipment
    }

    for equipment_id in (1, 4):
        item = equipment_by_id.get(equipment_id)
        if not item or str(item["IsActive"]).strip() not in ("1", "True", "true"):
            raise ValueError(
                f"Required equipment ID {equipment_id} is missing or inactive"
            )

    rows = []

    # Deterministic mapping: first 76 students receive computers.
    for index, accommodation in enumerate(special):
        equipment_id = 1 if index < 76 else 4
        item = equipment_by_id[equipment_id]

        rows.append({
            "AccommodationID": accommodation["AccommodationID"],
            "StudentID": accommodation["StudentID"],
            "EquipmentID": equipment_id,
            "EquipmentName": item["EquipmentName"],
            "QuantityRequired": 1,
            "RequirementSource": "SYNTHETIC_TEST_DATA"
        })

    student_ids = [r["StudentID"] for r in rows]

    if len(student_ids) != len(set(student_ids)):
        raise ValueError("Duplicate student equipment mappings detected")

    if sum(r["EquipmentID"] == 1 for r in rows) != 76:
        raise ValueError("Computer allocation count validation failed")

    if sum(r["EquipmentID"] == 4 for r in rows) != 50:
        raise ValueError("Accessible desk allocation count validation failed")

    fields = [
        "AccommodationID",
        "StudentID",
        "EquipmentID",
        "EquipmentName",
        "QuantityRequired",
        "RequirementSource"
    ]

    write_csv_atomic(OUTPUT_FILE, rows, fields)

    print("=" * 65)
    print("SPECIAL EQUIPMENT MAPPING GENERATED")
    print("=" * 65)
    print(f"Total students       : {len(rows)}")
    print(f"Desktop Computers    : {sum(r['EquipmentID'] == 1 for r in rows)}")
    print(f"Accessible Desks     : {sum(r['EquipmentID'] == 4 for r in rows)}")
    print(f"Output               : {OUTPUT_FILE}")
    print("Validation           : PASSED")
    print("SQL Server           : NOT ACCESSED")

if __name__ == "__main__":
    main()