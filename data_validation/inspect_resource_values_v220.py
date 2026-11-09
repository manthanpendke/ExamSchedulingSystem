import csv
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"

FILES = {
    "Accommodation": "Accommodation.csv",
    "Room": "Room.csv",
    "RoomCapacity": "RoomCapacity.csv",
    "RoomClosure": "RoomClosure.csv",
    "Equipment": "Equipment.csv",
    "RoomEquipment": "RoomEquipment.csv",
    "ExamRequiredEquipment": "ExamRequiredEquipment.csv",
    "ExamRequirement": "ExamRequirement.csv",
    "Invigilator": "Invigilator.csv",
    "Availability": "Availability.csv",
}

def read_csv(name):
    path = DATA / name
    if not path.exists():
        path = DATA / "metadata" / name
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def show_values(rows, column, label, limit=30):
    values = Counter(
        (r.get(column) or "").strip()
        for r in rows
    )
    print(f"\n{label} — {column}")
    for value, count in values.most_common(limit):
        print(f"  {value or '<blank>'}: {count}")

def show_samples(rows, columns, label, limit=5):
    print(f"\n{label} — sample rows")
    for row in rows[:limit]:
        print("  " + " | ".join(
            f"{c}={row.get(c, '')}" for c in columns
        ))

def main():
    data = {
        name: read_csv(filename)
        for name, filename in FILES.items()
    }

    print("=" * 75)
    print("V2.2.0 RESOURCE INPUT VALUE INSPECTION")
    print("=" * 75)

    show_values(data["Accommodation"], "AccommodationType",
                "ACCOMMODATION TYPES")
    show_values(data["Accommodation"], "AccommodationStatus",
                "ACCOMMODATION STATUSES")
    show_values(data["Accommodation"], "ExtensionPercentage",
                "EXTENSION PERCENTAGES")
    show_values(data["Room"], "RoomType", "ROOM TYPES")
    show_values(data["Room"], "IsActive", "ROOM ACTIVE VALUES")
    show_values(data["RoomCapacity"], "Capacity", "ROOM CAPACITIES")
    show_values(data["RoomClosure"], "ClosureStatus",
                "ROOM CLOSURE STATUSES")
    show_values(data["Equipment"], "EquipmentName",
                "EQUIPMENT NAMES")
    show_values(data["Equipment"], "EquipmentCategory",
                "EQUIPMENT CATEGORIES")
    show_values(data["Equipment"], "IsActive",
                "EQUIPMENT ACTIVE VALUES")
    show_values(data["Invigilator"], "Status",
                "INVIGILATOR STATUSES")
    show_values(data["Availability"], "AvailabilityStatus",
                "AVAILABILITY STATUSES")
    show_values(data["ExamRequirement"], "AccessibilityRequired",
                "EXAM ACCESSIBILITY VALUES")
    show_values(data["ExamRequirement"], "RequiredEquipment",
                "EXAM REQUIRED EQUIPMENT TEXT")
    show_values(data["ExamRequirement"], "SpecialInstructions",
                "EXAM SPECIAL INSTRUCTIONS")

    show_samples(
        data["Accommodation"],
        ["StudentID", "AccommodationType", "ExtensionPercentage",
         "RequiresSeparateRoom", "EffectiveFrom", "EffectiveTo",
         "AccommodationStatus"],
        "ACCOMMODATION"
    )

    show_samples(
        data["Room"],
        ["RoomID", "RoomCode", "Building", "Floor", "RoomType", "IsActive"],
        "ROOM"
    )

    show_samples(
        data["Equipment"],
        ["EquipmentID", "EquipmentName", "EquipmentCategory", "IsActive"],
        "EQUIPMENT"
    )

    show_samples(
        data["ExamRequirement"],
        ["ExamID", "DurationMinutes", "RequiredEquipment",
         "AccessibilityRequired", "SpecialInstructions"],
        "EXAM REQUIREMENTS"
    )

    show_samples(
        data["Availability"],
        ["InvigilatorID", "AvailableFrom", "AvailableTo",
         "AvailabilityStatus", "AvailabilityReason"],
        "INVIGILATOR AVAILABILITY"
    )

    show_samples(
        data["RoomClosure"],
        ["RoomID", "ClosureStart", "ClosureEnd",
         "ClosureReason", "ClosureStatus"],
        "ROOM CLOSURES"
    )

    print("\n" + "=" * 75)
    print("INPUT COUNTS")
    print("=" * 75)
    for name, rows in data.items():
        print(f"{name:25s}: {len(rows):,}")

    print("\nInspection completed. No source files were modified.")

if __name__ == "__main__":
    main()