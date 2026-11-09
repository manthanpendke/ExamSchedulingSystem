import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VALIDATION_STEPS = [
    ("Dataset validation", "data_validation/independent_dataset_validator_v220.py"),
    ("Optional wave validation", "data_validation/independent_optional_wave_validator_v220.py"),
    ("Timetable validation", "data_validation/independent_timetable_validator_v220.py"),
    ("Room allocation validation", "data_validation/independent_room_allocation_validator_v220.py"),
    ("Invigilator validation", "data_validation/independent_invigilator_validator_v220.py"),
    ("Final integration validation", "data_validation/final_integration_validator_v220.py"),
    ("Edge-case tests", "edge_case_test_suite_v220.py"),
]

SQL_STEPS = [
    ("SQL post-import validation", "data_validation/sql_post_import_validation_v220.py"),
    ("SQL business-rule validation", "data_validation/sql_business_rule_validation_v220.py"),
]

def execute_steps(steps):
    for label, relative_path in steps:
        script = ROOT / relative_path

        if not script.is_file():
            raise FileNotFoundError(f"Required script missing: {relative_path}")

        print(f"\n{'=' * 65}\n{label}\n{'=' * 65}", flush=True)

        subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            check=True
        )

def show_status():
    print("\nEXAM SCHEDULING SYSTEM")
    print("=" * 55)
    print(f"Project directory : {ROOT}")
    print(f"Python executable : {sys.executable}")
    print("\nAvailable safe commands:")
    print("  python run.py validate   - Validate existing scheduling outputs")
    print("  python run.py sql-check  - Run read-only SQL checks")
    print("  python run.py status     - Display project execution status")
    print("\nDataset regeneration and SQL refresh are deliberately")
    print("not available through this runner.")

def main():
    parser = argparse.ArgumentParser(
        description="Exam Scheduling System - Safe execution runner"
    )
    parser.add_argument(
        "mode",
        choices=["validate", "sql-check", "status"],
        help="Select a safe execution mode"
    )
    args = parser.parse_args()

    if args.mode == "validate":
        execute_steps(VALIDATION_STEPS)
    elif args.mode == "sql-check":
        execute_steps(SQL_STEPS)
    elif args.mode == "status":
        show_status()

    print("\nALL REQUESTED STEPS COMPLETED SUCCESSFULLY.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nFAILED: {exc.cmd}", file=sys.stderr)
        print(f"Exit code: {exc.returncode}", file=sys.stderr)
        sys.exit(exc.returncode)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
