import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output_v2" / "full" / "v2.2.0"
SCHED = BASE / "scheduling"

FILES = [
    SCHED / "RoomAllocation.csv",
    SCHED / "RoomStudentAllocation.csv",
    SCHED / "InvigilatorAssignment.csv",
    SCHED / "RoomAllocationExceptions.csv",
    SCHED / "ExamTimetable.csv",
]

print("=" * 76)
print("V2.2.0 SQL IMPORT MAPPING AUDIT - READ ONLY")
print("Only approved scheduling CSVs are inspected; GroundTruth is excluded.")
print("=" * 76)

for path in FILES:
    print(f"\n[{path.name}]")
    if not path.is_file():
        print("MISSING")
        continue
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        print("COLUMNS:", json.dumps(reader.fieldnames or []))
        samples = []
        for i, row in enumerate(reader):
            if i < 2:
                samples.append(row)
            if i >= 2:
                break
        print("SAMPLE_ROWS:", json.dumps(samples, ensure_ascii=False, default=str))

# Summarize exception codes only (not student identities).
p = SCHED / "RoomAllocationExceptions.csv"
if p.is_file():
    from collections import Counter
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = Counter((r.get("ReasonCode") or r.get("Reason") or "UNKNOWN") for r in rows)
    print("\nEXCEPTION_REASON_COUNTS:", json.dumps(dict(counts), sort_keys=True))

# Read only the run/dataset configuration metadata, not any evaluation data.
for name in ("dataset_config_v220.json", "dataset_manifest_v220.json"):
    p = ROOT / "config" / name if name.startswith("dataset_config") else BASE / "metadata" / name
    if p.is_file():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            print(f"\n[{name}] TOP_LEVEL_KEYS:", json.dumps(list(obj.keys()) if isinstance(obj, dict) else type(obj).__name__))
        except Exception as exc:
            print(f"\n[{name}] READ_ERROR:", str(exc))

print("\nSQL MODIFIED: NO | SOURCE FILES MODIFIED: NO | GROUNDTRUTH ACCESSED: NO")
