
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dataset_config_v220.json"


def validate():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    dataset = config["dataset"]
    tracks = config["track_rules"]
    calendar = config["calendar"]
    infrastructure = config["physical_infrastructure"]
    fixtures = config["edge_case_fixtures"]

    checks = {
        "Version is 2.2.0":
            config["project"]["version"] == "2.2.0",

        "Exactly 5000 students":
            dataset["students"] == 5000,

        "Exactly 75 tracks":
            dataset["tracks"] == 75,

        "Exactly 300 courses":
            dataset["courses"] == 300,

        "225 compulsory courses":
            dataset["compulsory_courses"] == 225,

        "75 optional courses":
            dataset["optional_courses"] == 75,

        "Exactly 3 compulsory courses per track":
            tracks["compulsory_courses_per_track"] == 3,

        "Exactly 1 optional course per student":
            tracks["optional_courses_per_student"] == 1,

        "Exactly 20000 enrollments":
            dataset["total_enrollments"] == 20000,

        "Exactly 900 exam sittings":
            dataset["total_exam_sittings"] == 900,

        "Track distribution totals 5000":
            (
                tracks["balanced_distribution"]["tracks_with_67_students"] * 67
                + tracks["balanced_distribution"]["tracks_with_66_students"] * 66
            ) == 5000,

        "Track distribution totals 75":
            (
                tracks["balanced_distribution"]["tracks_with_67_students"]
                + tracks["balanced_distribution"]["tracks_with_66_students"]
            ) == 75,

        "36 timetable slots":
            calendar["number_of_days"] * calendar["slots_per_day"] == 36,

        "3600 physical room-slot units":
            infrastructure["rooms"]
            * infrastructure["days"]
            * infrastructure["slots_per_day"] == 3600,

        "150 edge-case fixtures":
            sum(fixtures["distribution"].values()) == fixtures["total"],

        "SQL database disabled":
            config["database"]["enabled"] is False
    }

    print("\n========== V2.2.0 CONFIGURATION VALIDATION ==========\n")

    failed = []

    for description, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {description}")

        if not passed:
            failed.append(description)

    print("\n=====================================================")
    print(f"Checks passed: {len(checks) - len(failed)}/{len(checks)}")

    if failed:
        print("\nConfiguration validation failed:")
        for item in failed:
            print(f"- {item}")
        sys.exit(1)

    print("\nV2.2.0 configuration is valid.")
    return config


if __name__ == "__main__":
    validate()
