import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path("output_v2/full/v2.2.0")

def read_csv(name):
    path = ROOT / name
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        print(f"\n{name}: {len(rows)} rows")
        print("Columns:", reader.fieldnames)
        return rows

student_tracks = read_csv("metadata/StudentTrack.csv")
classifications = read_csv("metadata/EnrollmentClassification.csv")

def find_value(row, candidates):
    for key in candidates:
        if key in row:
            return row[key]
    raise KeyError(
        f"Expected one of {candidates}; available columns: {list(row)}"
    )

student_to_track = {
    find_value(r, ["StudentID"]):
    int(find_value(r, ["TrackID"]))
    for r in student_tracks
}

optional_students = defaultdict(set)

for row in classifications:
    enrollment_type = str(
        find_value(row, ["EnrollmentType"])
    ).strip().upper()

    if enrollment_type == "OPTIONAL":
        course_id = int(find_value(row, ["CourseID"]))
        student_id = find_value(row, ["StudentID"])
        optional_students[course_id].add(student_id)

def track_block(track_id):
    return ((track_id - 1) % 12) + 1

print("\nOPTIONAL COURSE BLOCK DIAGNOSTICS")
print("=" * 65)

for course_id in sorted(optional_students):
    tracks = sorted({
        student_to_track[s]
        for s in optional_students[course_id]
    })
    blocks = sorted({track_block(t) for t in tracks})
    free_blocks = sorted(set(range(1, 13)) - set(blocks))

    print(
        f"Course {course_id}: "
        f"{len(optional_students[course_id])} students | "
        f"{len(tracks)} tracks | "
        f"occupied blocks={blocks} | "
        f"free blocks={free_blocks}"
    )