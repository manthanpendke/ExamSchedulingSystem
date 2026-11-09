
import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config" / "dataset_config.json"


def load_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def check(results, condition, message):
    passed = bool(condition)
    results.append(passed)
    print(f"[{'PASS' if passed else 'FAIL'}] {message}")
    return passed


def main():
    parser = argparse.ArgumentParser(
        description="Audit an Exam Scheduling synthetic dataset."
    )
    parser.add_argument(
        "--profile",
        choices=["starter", "full"],
        default="full",
        help="Dataset profile to audit (default: full).",
    )
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Missing configuration: {CONFIG_FILE}")

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    profile = config["profiles"][args.profile]

    dataset_dir = (
        PROJECT_ROOT / "output" / args.profile
        / f"v{config['dataset']['version']}"
    )
    csv_dir = dataset_dir / "csv"
    ground_truth_file = (
        dataset_dir / "ground_truth" / "csv" / "GroundTruth.csv"
    )

    print("=" * 68)
    print("EXAM SCHEDULING DATASET QUALITY AUDIT")
    print("=" * 68)
    print(f"Profile: {args.profile}")
    print(f"Seed: {config['dataset']['random_seed']}")
    print(f"Dataset: {dataset_dir}")

    results = []

    table_names = [
        "Student", "Course", "Room", "Invigilator", "Equipment",
        "Enrollment", "Accommodation", "Availability", "Exam",
        "ExamRequirement", "ExamRequiredEquipment", "ExamEnrollment",
        "RoomCapacity", "RoomEquipment", "RoomClosure",
    ]

    tables = {
        name: load_csv(csv_dir / f"{name}.csv")
        for name in table_names
    }
    ground_truth = load_csv(ground_truth_file)

    def codes(table, column):
        return {row[column] for row in tables[table]}

    student_codes = codes("Student", "StudentCode")
    course_codes = codes("Course", "CourseCode")
    room_codes = codes("Room", "RoomCode")
    invigilator_codes = codes("Invigilator", "InvigilatorCode")
    equipment_codes = codes("Equipment", "EquipmentCode")
    exam_codes = codes("Exam", "ExamCode")

    print("\n1. PROFILE VOLUME")

    expected_counts = {
        "Student": profile["students"],
        "Course": profile["courses"],
        "Exam": profile["exams"],
        "Room": profile["rooms"],
        "Invigilator": profile["invigilators"],
    }

    for table, expected in expected_counts.items():
        check(
            results,
            len(tables[table]) == expected,
            f"{table}: expected {expected:,}, found {len(tables[table]):,}",
        )

    print("\n2. BASELINE REFERENCES")

    reference_checks = [
        (
            all(r["StudentCode"] in student_codes
                for r in tables["Enrollment"]),
            "Enrollment references valid students",
        ),
        (
            all(r["CourseCode"] in course_codes
                for r in tables["Enrollment"]),
            "Enrollment references valid courses",
        ),
        (
            all(r["StudentCode"] in student_codes
                for r in tables["Accommodation"]),
            "Accommodation references valid students",
        ),
        (
            all(r["InvigilatorCode"] in invigilator_codes
                for r in tables["Availability"]),
            "Availability references valid invigilators",
        ),
        (
            all(r["ExamCode"] in exam_codes
                for r in tables["ExamRequirement"]),
            "ExamRequirement references valid exams",
        ),
        (
            all(r["ExamCode"] in exam_codes
                and r["EquipmentCode"] in equipment_codes
                for r in tables["ExamRequiredEquipment"]),
            "ExamRequiredEquipment references valid exams and equipment",
        ),
        (
            all(r["RoomCode"] in room_codes
                for r in tables["RoomCapacity"]),
            "RoomCapacity references valid rooms",
        ),
        (
            all(r["RoomCode"] in room_codes
                and r["EquipmentCode"] in equipment_codes
                for r in tables["RoomEquipment"]),
            "RoomEquipment references valid rooms and equipment",
        ),
        (
            all(r["RoomCode"] in room_codes
                for r in tables["RoomClosure"]),
            "RoomClosure references valid rooms",
        ),
    ]

    for condition, message in reference_checks:
        check(results, condition, message)

    print("\n3. GROUND-TRUTH SCENARIOS")

    expected_scenarios = {
        "NEG_STUDENT_OVERLAP",
        "NEG_ROOM_CAPACITY",
        "NEG_INVIGILATOR_DOUBLE_BOOKING",
        "NEG_ACCOMMODATION_IGNORED",
        "NEG_ROOM_CLOSED",
    }

    actual_scenarios = {
        row["ScenarioCode"] for row in ground_truth
    }

    check(
        results,
        len(ground_truth) == 5,
        f"Exactly five ground-truth records exist (found {len(ground_truth)})",
    )

    check(
        results,
        actual_scenarios == expected_scenarios,
        "All five required scenario codes exist exactly once",
    )

    accommodation_students = {
        row["StudentCode"]
        for row in tables["Accommodation"]
        if row["AccommodationStatus"] == "ACTIVE"
    }

    accommodation_scenario = next(
        (
            row for row in ground_truth
            if row["ScenarioCode"] == "NEG_ACCOMMODATION_IGNORED"
        ),
        None,
    )

    check(
        results,
        accommodation_scenario is not None
        and accommodation_scenario["EntityCode"] in accommodation_students,
        "Accommodation scenario references a student with active accommodation",
    )

    closed_rooms = {
        row["RoomCode"]
        for row in tables["RoomClosure"]
        if row["ClosureStatus"] == "ACTIVE"
    }

    closure_scenario = next(
        (
            row for row in ground_truth
            if row["ScenarioCode"] == "NEG_ROOM_CLOSED"
        ),
        None,
    )

    check(
        results,
        closure_scenario is not None
        and closure_scenario["EntityCode"] in closed_rooms,
        "Room closure scenario references a room with an active closure",
    )

    entity_maps = {
        "STUDENT": student_codes,
        "ROOM": room_codes,
        "INVIGILATOR": invigilator_codes,
        "EXAM": exam_codes,
    }

    check(
        results,
        all(
            row["EntityType"] in entity_maps
            and row["EntityCode"] in entity_maps[row["EntityType"]]
            for row in ground_truth
        ),
        "All ground-truth entities reference existing baseline entities",
    )

    print("\n4. GROUND-TRUTH SEPARATION")

    check(
        results,
        not (csv_dir / "GroundTruth.csv").exists(),
        "Ground truth is not mixed into baseline CSV files",
    )

    print("\n5. SUMMARY")

    passed = sum(results)
    failed = len(results) - passed

    print("-" * 68)
    print(f"Profile: {args.profile}")
    print(f"Checks passed: {passed}")
    print(f"Checks failed: {failed}")

    if failed:
        print("\nDATASET QUALITY AUDIT: FAILED")
        sys.exit(1)

    print("\nDATASET QUALITY AUDIT: PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nAUDIT ERROR: {exc}")
        sys.exit(2)
