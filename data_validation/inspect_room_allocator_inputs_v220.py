
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output_v2" / "full" / "v2.2.0"

KEYWORDS = (
    "room",
    "equipment",
    "accommodation",
    "invigilator",
    "availability",
    "closure",
    "requirement",
)

def inspect(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print("\n" + "=" * 85)
    print(f"FILE: {path.relative_to(DATA)}")
    print(f"RECORD COUNT: {len(rows)}")
    print("COLUMNS:", reader.fieldnames)

    for index, row in enumerate(rows[:2], start=1):
        print(f"\nSAMPLE ROW {index}:")
        for key, value in row.items():
            print(f"  {key}: {value}")

def main():
    if not DATA.exists():
        raise FileNotFoundError(DATA)

    files = sorted(
        path for path in DATA.rglob("*.csv")
        if any(word in path.stem.lower() for word in KEYWORDS)
    )

    if not files:
        raise RuntimeError("No matching resource CSV files found.")

    print("=" * 85)
    print("V2.2.0 ROOM AND INVIGILATOR INPUT INSPECTION")
    print("=" * 85)

    for path in files:
        inspect(path)

    print("\n" + "=" * 85)
    print(f"TOTAL FILES INSPECTED: {len(files)}")
    print("READ-ONLY INSPECTION — NO DATA MODIFIED")
    print("SQL SERVER: NOT ACCESSED")
    print("=" * 85)

if __name__ == "__main__":
    main()
