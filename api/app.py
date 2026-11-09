from __future__ import annotations

import importlib
import json
import shutil
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATA = ROOT / "output_v2" / "full" / "v2.2.0"
RUNS_DIR = ROOT / "api_runs"
SCHED_SOURCE = SOURCE_DATA / "scheduling"

# Make project packages importable when launched with:
# python -m api.app
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

app = Flask(__name__)
RUNS: dict[str, dict] = {}


def _json_file(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_dataset(run_data: Path) -> None:
    if not SOURCE_DATA.is_dir():
        raise FileNotFoundError(f"Validated v2.2.0 dataset not found: {SOURCE_DATA}")
    shutil.copytree(SOURCE_DATA, run_data)


def _run_v220_pipeline(run_id: str) -> dict:
    """Execute the real v2.2.0 modules in an isolated run copy.

    The validated source dataset, SQL Server and GroundTruth are never written.
    """
    run_root = RUNS_DIR / run_id
    run_data = run_root / "data"
    run_sched = run_data / "scheduling"
    run_meta = run_data / "metadata"

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _copy_dataset(run_data)
    run_sched.mkdir(parents=True, exist_ok=True)

    # 1) v2.2.0 timetable allocator: call its in-memory functions, not main().
    tt = importlib.import_module("scheduling.timetable_allocator_v220")
    tt.CONFIG_PATH = ROOT / "config" / "dataset_config_v220.json"
    tt.DATA_DIR = run_data
    tt.METADATA_DIR = run_meta
    tt.SCHEDULING_DIR = run_sched

    config, data = tt.load_inputs()
    blocks = tt.create_blocks(config)
    course_block, track_course_rows, block_load = tt.assign_track_course_blocks(
        data["tracks"], data["track_courses"], blocks
    )
    optional_block, optional_course_tracks = tt.assign_optional_course_blocks(
        data["classifications"], data["student_tracks"], blocks
    )
    compulsory_course_track = tt.build_course_mappings(data["track_courses"])
    timetable, slot_counts, slot_students = tt.build_timetable(
        config, data["exams"], blocks, course_block, optional_block,
        compulsory_course_track, data["exam_enrollments"]
    )
    student_allocations = tt.build_student_allocations(
        data["sitting_allocations"], timetable, data["accommodations"],
        int(config["duration_rules"]["standard_duration_minutes"])
    )
    errors, timetable_metrics = tt.validate_timetable(
        config, data, blocks, course_block, optional_block,
        track_course_rows, timetable, student_allocations, slot_counts
    )
    if errors:
        raise RuntimeError(
            "v2.2.0 timetable validation failed: " + "; ".join(map(str, errors[:20]))
        )

    tt.write_csv(run_sched / "ExamTimetable.csv", timetable, [
        "ExamID", "ExamCode", "CourseID", "SittingOrdinal", "CourseRole",
        "TrackID", "BlockID", "ExamDate", "DayIndex", "SlotNumber",
        "SlotStartTime", "SlotEndTime", "StartDateTime", "EndDateTime",
        "EnrolledStudentCount"
    ])
    tt.write_csv(run_sched / "TimetableStudentAllocation.csv", student_allocations, [
        "EnrollmentID", "StudentID", "CourseID", "ExamID", "EnrollmentType",
        "TrackID", "SittingOrdinal", "ExamDate", "SlotNumber", "SlotID",
        "StartDateTime", "EndDateTime", "EffectiveDurationMinutes",
        "EffectiveEndDateTime", "HasExtendedTime"
    ])
    slot_report = tt.create_slot_report(timetable, slot_counts, slot_students, config)
    tt.write_csv(run_sched / "SlotLoad.csv", slot_report, [
        "ExamDate", "DayIndex", "SlotNumber", "StartTime", "EndTime",
        "ExamSittingCount", "TotalStudentCount"
    ])
    tt.write_csv(run_sched / "TrackBlockAllocation.csv", track_course_rows, [
        "TrackID", "CourseID", "CourseOrdinal", "BlockID", "DayIndex",
        "ExamDate", "Period"
    ])
    optional_rows = [
        {
            "CourseID": cid, "BlockID": bid, "ExamDate": blocks[bid]["ExamDate"],
            "Period": blocks[bid]["Period"],
            "AffectedTrackCount": len(optional_course_tracks[cid])
        }
        for cid, bid in sorted(optional_block.items())
    ]
    tt.write_csv(run_sched / "OptionalCourseBlockAllocation.csv", optional_rows, [
        "CourseID", "BlockID", "ExamDate", "Period", "AffectedTrackCount"
    ])
    timetable_report = {
        "version": "2.2.0", "status": "PASSED",
        "counts": {
            "students": len(data["students"]), "tracks": len(data["tracks"]),
            "courses": len(data["courses"]), "exams_scheduled": len(timetable),
            "student_exam_allocations": len(student_allocations)
        },
        "validation": timetable_metrics,
        "database_accessed": False, "database_modified": False
    }
    tt.write_json(run_sched / "timetable_report.json", timetable_report)

    # 2) Optional two-wave application, pointed only at this run's copy.
    wave = importlib.import_module("scheduling.apply_optional_waves_v220")
    wave.FILES = {
        "timetable": run_sched / "ExamTimetable.csv",
        "allocations": run_sched / "TimetableStudentAllocation.csv",
        "optional_blocks": run_sched / "OptionalCourseBlockAllocation.csv",
        "slot_load": run_sched / "SlotLoad.csv",
    }
    wave.PLAN_FILE = run_sched / "optional_wave_plan_preview.csv"
    wave.GRID_FILE = run_meta / "PhysicalRoomGrid.csv"
    wave.REPORT_FILE = run_sched / "optional_wave_application_report_v220.json"
    wave.main()

    # 3) Physical room allocation: use its actual v2.2.0 allocate(data) function.
    room = importlib.import_module("scheduling.room_allocator_v220")
    room.DATA = run_data
    room.SCHED = run_sched
    room.META = run_meta
    room.OUT_ROOM = run_sched / "RoomAllocation.csv"
    room.OUT_STUDENT = run_sched / "RoomStudentAllocation.csv"
    room.OUT_EQUIP = run_sched / "RoomEquipmentReservation.csv"
    room.OUT_EXCEPT = run_sched / "RoomAllocationExceptions.csv"
    room.OUT_REPORT = run_sched / "room_allocation_report_v220.json"
    room_data = room.load_inputs()
    room.validate_inputs(room_data)
    room_rows, student_rows, equipment_rows, exceptions, room_report = room.allocate(room_data)

    room.write_csv(room.OUT_ROOM, room_rows, [
        "RoomAllocationID", "ExamID", "CourseID", "RoomID", "RoomCode",
        "GroupType", "StartDateTime", "EndDateTime", "AssignedCapacity",
        "AllocatedStudentCount", "EquipmentRequirementsJSON", "StudentIDsJSON"
    ])
    room.write_csv(room.OUT_STUDENT, student_rows, [
        "EnrollmentID", "StudentID", "CourseID", "ExamID", "RoomID",
        "StartDateTime", "StudentEffectiveEndDateTime", "EffectiveDurationMinutes",
        "HasExtendedTime", "RequiresSeparateRoom", "RequiresAccessibleRoom",
        "SpecialEquipmentJSON"
    ])
    room.write_csv(room.OUT_EQUIP, equipment_rows, [
        "CourseID", "EquipmentID", "EquipmentName", "ReservedQuantity",
        "ReservationStart", "ReservationEnd", "ExamIDs", "ReservationPolicy",
        "InventoryRoomIDs", "ReservationStatus"
    ])
    room.write_csv(room.OUT_EXCEPT, exceptions, [
        "ExamID", "ExamCode", "CourseID", "ReasonCode",
        "UnassignedStudentCount", "Details"
    ])
    room.write_json(room.OUT_REPORT, room_report)

    # 4) Invigilator allocator is file-oriented. Redirect every path to run copy.
    inv = importlib.import_module("scheduling.allocate_invigilators_v220")
    inv.DATA = run_data
    inv.SCHED = run_sched
    inv.INV_FILE = run_data / "Invigilator.csv"
    inv.AVAIL_FILE = run_data / "Availability.csv"
    inv.ROOM_FILE = run_sched / "RoomAllocation.csv"
    inv.OUT_ASSIGN = run_sched / "InvigilatorAssignment.csv"
    inv.OUT_EXCEPT = run_sched / "InvigilatorAllocationExceptions.csv"
    inv.OUT_REPORT = run_sched / "invigilator_allocation_report_v220.json"
    inv.main()

    inv_report = _json_file(inv.OUT_REPORT) or {}
    optional_report = _json_file(wave.REPORT_FILE) or {}

    return {
        "run_id": run_id,
        "status": "completed",
        "version": "2.2.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "storage": str(run_root),
        "source_dataset_modified": False,
        "sql_server_accessed": False,
        "groundtruth_accessed": False,
        "summary": {
            "timetable": timetable_report["counts"],
            "room_allocation": room_report.get("counts", {}),
            "invigilator_allocation": {
                "room_allocations": inv_report.get("room_allocations"),
                "assigned_room_allocations": inv_report.get("assigned_room_allocations"),
                "unassigned_room_allocations": inv_report.get("unassigned_room_allocations"),
                "assignment_percentage": inv_report.get("assignment_percentage")
            },
            "optional_waves": optional_report
        },
        "outputs": sorted(p.name for p in run_sched.iterdir() if p.is_file())
    }


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "exam-scheduling-api",
        "pipeline": "v2.2.0",
        "source_dataset_exists": SOURCE_DATA.is_dir(),
        "run_storage": str(RUNS_DIR)
    })


@app.post("/api/v2.2.0/runs")
def create_run():
    run_id = str(uuid.uuid4())
    try:
        result = _run_v220_pipeline(run_id)
        RUNS[run_id] = result
        return jsonify(result), 201
    except Exception as exc:
        return jsonify({
            "run_id": run_id,
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc()
        }), 500


@app.get("/api/v2.2.0/runs")
def list_runs():
    """List runs from disk so they remain discoverable after an API restart."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for run_path in sorted(
        (p for p in RUNS_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        sched_path = run_path / "data" / "scheduling"
        if not sched_path.is_dir():
            continue
        try:
            run_id = str(uuid.UUID(run_path.name))
        except ValueError:
            continue

        outputs = sorted(p.name for p in sched_path.iterdir() if p.is_file())
        runs.append({
            "run_id": run_id,
            "status": "outputs_available",
            "storage": str(run_path),
            "outputs": outputs,
        })
    return jsonify({"runs": runs, "count": len(runs)})


@app.get("/api/v2.2.0/runs/<run_id>")
def get_run(run_id: str):
    if run_id in RUNS:
        return jsonify(RUNS[run_id])
    run_path = RUNS_DIR / run_id
    if run_path.is_dir():
        return jsonify({
            "run_id": run_id,
            "status": "outputs_available",
            "storage": str(run_path),
            "outputs": sorted(
                p.name for p in (run_path / "data" / "scheduling").glob("*")
                if p.is_file()
            )
        })
    return jsonify({"error": "run not found", "run_id": run_id}), 404


def _run_directory(run_id: str) -> Path:
    # UUID parsing prevents path traversal through the run_id route parameter.
    parsed = uuid.UUID(run_id)
    run_root = RUNS_DIR / str(parsed)
    if not run_root.is_dir():
        raise FileNotFoundError(f"Run not found: {parsed}")
    return run_root


def _read_csv_page(path: Path, limit: int = 100, offset: int = 0) -> dict:
    import csv

    if not path.is_file():
        raise FileNotFoundError(f"Run output not found: {path.name}")
    if limit < 1 or limit > 1000 or offset < 0:
        raise ValueError("limit must be 1..1000 and offset must be >= 0")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return {
        "file": path.name,
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "rows": rows[offset:offset + limit],
    }


def _read_run_report(sched: Path, filename: str) -> dict:
    path = sched / filename
    return _json_file(path) or {}


@app.get("/api/v2.2.0/runs/<run_id>/assignments/timetable")
def get_timetable_assignments(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return jsonify(_read_csv_page(
            sched / "TimetableStudentAllocation.csv", limit, offset
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/assignments/rooms")
def get_room_assignments(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return jsonify(_read_csv_page(
            sched / "RoomStudentAllocation.csv", limit, offset
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/assignments/invigilators")
def get_invigilator_assignments(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return jsonify(_read_csv_page(
            sched / "InvigilatorAssignment.csv", limit, offset
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/exceptions/rooms")
def get_room_exceptions(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return jsonify(_read_csv_page(
            sched / "RoomAllocationExceptions.csv", limit, offset
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/exceptions/invigilators")
def get_invigilator_exceptions(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return jsonify(_read_csv_page(
            sched / "InvigilatorAllocationExceptions.csv", limit, offset
        ))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/unassigned")
def get_unassigned_summary(run_id: str):
    """Expose allocator exception rows; these are not individual student IDs."""
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        import csv
        path = sched / "RoomAllocationExceptions.csv"
        if not path.is_file():
            return jsonify({"error": "RoomAllocationExceptions.csv missing"}), 404
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        count = sum(int(row.get("UnassignedStudentCount") or 0) for row in rows)
        return jsonify({
            "run_id": str(uuid.UUID(run_id)),
            "unassigned_student_count": count,
            "exception_count": len(rows),
            "note": "The source exception file contains aggregate exam-level counts, not a verified list of individual unassigned student IDs.",
            "exceptions": rows
        })
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/v2.2.0/runs/<run_id>/metrics")
def get_run_metrics(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        reports = {
            "timetable": _read_run_report(sched, "timetable_report.json"),
            "rooms": _read_run_report(sched, "room_allocation_report_v220.json"),
            "invigilators": _read_run_report(sched, "invigilator_allocation_report_v220.json"),
            "optional_waves": _read_run_report(sched, "optional_wave_application_report_v220.json"),
        }
        return jsonify({"run_id": str(uuid.UUID(run_id)), "reports": reports})
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@app.get("/api/v2.2.0/runs/<run_id>/validation")
def get_run_validation_status(run_id: str):
    try:
        sched = _run_directory(run_id) / "data" / "scheduling"
        # Only run-specific independent reports count. Reports copied from the
        # source dataset are deliberately not treated as fresh validation.
        expected = [
            "api_independent_validation_report.json",
            "api_final_integration_validation_report.json",
        ]
        statuses = {
            name: (
                _read_run_report(sched, name)
                if (sched / name).is_file()
                else {"status": "PENDING", "note": "Not generated for this API run."}
            )
            for name in expected
        }
        return jsonify({
            "run_id": str(uuid.UUID(run_id)),
            "validation": statuses,
            "overall_status": (
                "PENDING" if any(v.get("status") == "PENDING" for v in statuses.values())
                else "REPORTS_AVAILABLE"
            )
        })
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
