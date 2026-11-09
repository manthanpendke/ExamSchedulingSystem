# Validation Strategy, Evidence and Metrics

## 1. Interpretation policy

This document distinguishes three evidence categories:

1. **Original v2.2.0 pipeline validation** — previously recorded independent validation of the protected source dataset and its allocation outputs.
2. **API smoke tests and output inspection** — verifies that the Flask service responds and exposes the API run outputs.
3. **Independent validation of an API-generated run** — must use run-specific outputs and run-specific reports. It is not complete merely because source v2.2.0 reports exist.

The active scheduling implementation is v2.2.0. Do not use the legacy scheduler engine or earlier models as the authoritative execution path.

## 2. Previously recorded source v2.2.0 validation evidence

The following results were previously recorded for the validated source v2.2.0 pipeline:

| Validation area | Recorded checks | Recorded result |
|---|---:|---|
| Dataset validation | 94 | Zero errors and warnings |
| Optional-wave validation | 202,637 | Zero errors |
| Timetable validation | 395,776 | Zero errors |
| Room allocation validation | 89,363 | Zero errors; `PASSED_WITH_EXCEPTIONS` |
| Invigilator validation | 17,423 | Zero errors |
| Final integration validation | 355,116 | Zero errors; `PASSED_WITH_ACCEPTED_EXCEPTIONS` |
| Edge-case suite | 6 | 6/6 passed |

These are recorded source-pipeline results. Re-run the appropriate safe validators before describing them as freshly reproduced in a new environment.

## 3. Source allocation metrics and accepted exceptions

Previously recorded v2.2.0 source outputs:

| Metric | Recorded value |
|---|---:|
| Exam timetable rows | 900 |
| Student-exam allocations | 20,000 |
| Room allocations | 1,493 |
| Student-room assignments | 19,947 |
| Equipment reservations | 210 |
| Room exceptions | 36 |
| Invigilator assignments | 1,493 |
| Invigilator exception rows | 0 |
| Unassigned student-room allocations | 53 |

The 36 room exceptions were recorded as 24 accommodation-related and 12 equipment-related. The 53 unassigned student-room allocations are an accepted reported outcome. `PASSED_WITH_EXCEPTIONS` and `PASSED_WITH_ACCEPTED_EXCEPTIONS` do not mean there were no exceptions or that every student received a room.

## 4. SQL Server evidence

Previously reported SQL integration evidence:
- 21 `dbo` tables and 72,373 rows were imported/checked.
- Database integrity checks reported no DBCC violations.
- 24 foreign keys, 47 check constraints, 46 unique/primary-key indexes, and 3 expected triggers were reported enabled.
- 8/8 SQL business rules passed.

This SQL evidence was previously reported for the database integration workflow. Do not imply that the Flask API run-creation endpoint refreshes or writes to SQL Server. The latest dataset validation command did not itself access SQL Server.

## 5. API smoke-test evidence

The Flask API was started locally using:

```powershell
python -m api.app
```

Previously verified API behavior:
- `GET /api/health` returned a healthy response and indicated the v2.2.0 source dataset was present.
- `POST /api/v2.2.0/runs` completed for the recorded run.
- The run generated timetable, room, student-room, equipment, and invigilator output files in its isolated run directory.
- The following read-only endpoint checks returned HTTP 200: metrics, room assignments, invigilator assignments, room exceptions, unassigned counts, and validation status.
- The persistent run-list endpoint returned the existing run after Flask restart by discovering its run directory on disk.

Previously recorded API run ID:

`4b28a61f-e35e-4aab-8dd5-438fff459669`

Previously inspected run output row counts:
- `ExamTimetable.csv`: 900
- `TimetableStudentAllocation.csv`: 20,000
- `RoomAllocation.csv`: 1,493
- `RoomStudentAllocation.csv`: 19,947
- `RoomAllocationExceptions.csv`: 36
- `InvigilatorAssignment.csv`: 1,493
- `InvigilatorAllocationExceptions.csv`: 0
- `RoomEquipmentReservation.csv`: 210

These counts are previously observed for that API run. Reinspect the run directory if current filesystem state must be confirmed.

## 6. API-run independent validation status

**Status: PENDING unless fresh API-run-specific independent reports have been generated and verified.**

The API validation endpoint reports `PENDING` when the required API-run-specific report files are absent. Copied source reports inside a run directory are not proof that those reports were freshly generated against the API run outputs.

Do not:
- relabel source-dataset validation reports as API-run validation;
- claim API independent validation is complete based only on HTTP 200;
- claim every API output is constraint-clean without independent checks;
- alter the protected source dataset to make the API validation pass.

The next validation task is to inspect the validator interfaces and run them against the isolated API run copy, writing reports only into that run's report/output area. Confirm script arguments and write behavior before executing any validator.

## 7. Test-suite status

The available historical records conflict:
- one earlier recorded full-suite result was 29 passed and 1 failed, with failure in `tests/test_scheduler_engine.py::test_shared_student_exams_do_not_overlap` in the legacy scheduler path;
- a later documentation-generation draft says 30 passed.

This conflict must be resolved using actual latest terminal output before publishing a definitive full-suite result. Until then, do not claim that the full test suite passes. Clearly identify the failing test as belonging to the legacy scheduler test path if that is confirmed by the test output.

## 8. Reproducibility

The project records fixed seed `20261022` and has manifest/checksum design. A second independent generation with matching checksums has not been demonstrated in the evidence summarized here. Do not claim the same-seed reproducibility acceptance criterion is complete until the second run and checksum comparison are actually performed.

Do not rebuild or overwrite the protected v2.2.0 dataset to perform this check. Use a separate temporary destination and verify the generator supports an isolated output path before attempting it.

## 9. Safe verification commands

API syntax check:

```powershell
python -m py_compile api\app.py
```

Start the API:

```powershell
python -m api.app
```

In a second terminal, run read-only checks:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:5000/api/v2.2.0/runs
```

Use the returned run ID for GET checks of metrics, assignments, exceptions, unassigned counts, and validation. Do not submit another POST merely to inspect an existing run.

For project validation, inspect the runner's supported commands first:

```powershell
python run.py --help
python run.py status
```

If supported and confirmed safe, `python run.py validate` is the non-build validation command. Do not run `python run.py build` or older data-generation scripts during finalization.
