import csv
from pathlib import Path

ROOT = Path("output_v2/full/v2.2.0")
EXAM_FILE = ROOT / "Exam.csv"
TIMETABLE_FILE = ROOT / "scheduling" / "ExamTimetable.csv"

AFFECTED = {
    "EXAM-2026-000678", "EXAM-2026-000687", "EXAM-2026-000696",
    "EXAM-2026-000723", "EXAM-2026-000729", "EXAM-2026-000732",
    "EXAM-2026-000765", "EXAM-2026-000774", "EXAM-2026-000777",
    "EXAM-2026-000780", "EXAM-2026-000801", "EXAM-2026-000813",
    "EXAM-2026-000819", "EXAM-2026-000822", "EXAM-2026-000834",
    "EXAM-2026-000849", "EXAM-2026-000855", "EXAM-2026-000858",
    "EXAM-2026-000861", "EXAM-2026-000876", "EXAM-2026-000891",
}

def read_csv(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

exams = read_csv(EXAM_FILE)
timetable = read_csv(TIMETABLE_FILE)

def find_code(row):
    for key in ("ExamCode", "exam_code", "EXAMCODE"):
        if key in row:
            return row[key]
    return None

exam_map = {find_code(r): r for r in exams if find_code(r)}
tt_map = {}
for row in timetable:
    code = find_code(row)
    if code in AFFECTED:
        tt_map.setdefault(code, []).append(row)

print("READ-ONLY SOURCE AUDIT — no SQL access; GroundTruth excluded")
print(f"Exam.csv rows: {len(exams)}; ExamTimetable.csv rows: {len(timetable)}")
print("Exam.csv columns:", list(exams[0]) if exams else [])
print("ExamTimetable.csv columns:", list(timetable[0]) if timetable else [])

for code in sorted(AFFECTED):
    erow = exam_map.get(code)
    print(f"\n{code}")
    if erow is None:
        print("  NOT FOUND in Exam.csv")
    else:
        for k, v in erow.items():
            if any(term in k.lower() for term in ("window", "start", "end", "date", "duration")):
                print(f"  Exam.csv {k} = {v}")
    rows = tt_map.get(code, [])
    if not rows:
        print("  NOT FOUND in ExamTimetable.csv")
    for row in rows:
        for k, v in row.items():
            if any(term in k.lower() for term in ("start", "end", "date", "slot", "sitting")):
                print(f"  Timetable {k} = {v}")
