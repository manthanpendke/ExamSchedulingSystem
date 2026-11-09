# YottaFlex Exam Scheduling System

## Project objective

Build an end-to-end exam scheduling workflow that assigns exam sittings to time intervals and rooms while respecting student enrollment, effective exam duration, room capacity and closures, equipment requirements, student accommodations, and invigilator availability. The solution exposes decisions and exceptions, preserves traceability, and produces measurable validation outputs.

## Authoritative implementation and version policy

**The active scheduling implementation is v2.2.0.** The v2.2.0 pipeline is the implementation to run, test, demonstrate, and explain.

- Timetable scheduling: `scheduling/timetable_allocator_v220.py`
- Optional exam waves: `scheduling/apply_optional_waves_v220.py`
- Room allocation: `scheduling/room_allocator_v220.py`
- Invigilator allocation: `scheduling/allocate_invigilators_v220.py`
- API entry point: `api/app.py`

Older scheduler engines, earlier version modules, and model-based/legacy scheduling paths are retained only for historical compatibility or reference where present. They are **not** the authoritative execution path for the submitted v2.2.0 solution. Do not run an older engine or model in place of the v2.2.0 pipeline.

The Flask API exposes the v2.2.0 workflow. It is not a separate scheduling algorithm and must not be described as using the legacy engine.

## Implemented v2.2.0 dataset profile

- 5,000 students
- 75 tracks
- 300 courses: 225 compulsory and 75 optional
- 20,000 enrollments
- 900 exam sittings and 20,000 student-exam allocations
- 100 rooms
- 200 invigilators
- 127 students with extended-time accommodation in the validated profile
- Standard duration: 90 minutes; extended duration: 120 minutes
- Five compulsory exam days; optional exams on Day 6 in two waves
- Fixed seed recorded for the dataset: `20261022`

**Volume clarification:** the brief suggests 300 exams. The implemented profile contains 300 courses and three exam sittings per course, resulting in 900 sittings. This distinction must be stated clearly during review rather than describing the profile as exactly 300 exam sittings.

## High-level workflow

1. Generate/reference master data and dependent records using valid parent identifiers.
2. Validate enrollments, exam registrations, exam requirements, rooms, capacity, equipment, closures, availability, and accommodations.
3. Build student-conflict relationships and schedule exam sittings using the v2.2.0 timetable allocator.
4. Apply optional-course waves where required.
5. Allocate rooms and students, retaining exceptions and reason codes.
6. Allocate invigilators and reconcile assignments.
7. Expose run outputs and metrics through the Flask API.
8. Run independent validators and retain machine-readable reports.

## Architecture at a glance

```text
API client
   |
   v
Flask API (api/app.py)
   |
   v
v2.2.0 scheduling pipeline
   |-- timetable allocation
   |-- optional-wave allocation
   |-- room allocation
   |-- invigilator allocation
   |
   v
Isolated API run directory (api_runs/<run_id>/data)
   |
   v
Read-only result endpoints
   |-- timetable / room / invigilator assignments
   |-- exceptions / unassigned counts
   |-- metrics / validation status
```

Each API scheduling run uses a run-specific directory. The API's run listing can discover run folders from disk after a service restart. Do not imply that the full in-memory run state or validation results are persisted unless a specific persisted artifact demonstrates that.

The API run path is isolated from the protected source dataset. The API implementation described here does not refresh SQL Server and does not read or modify GroundTruth.

## Requirements

- Windows PowerShell
- Python compatible with the versions pinned/supported by `requirements.txt`
- Dependencies from `requirements.txt`
- SQL Server and the configured ODBC driver only for the separate SQL integration/check commands

## Installation

Run from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If activation is blocked by PowerShell policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create local `.env` from `.env.example` and configure local SQL connection settings only if SQL integration is required. Never commit `.env`, passwords, tokens, or connection strings containing secrets.

## Run the Flask API

From the repository root:

```powershell
python -m api.app
```

The local development service is expected at `http://127.0.0.1:5000` when using the current local configuration.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
```

## API endpoint reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Health and source-dataset status |
| POST | `/api/v2.2.0/runs` | Start a v2.2.0 scheduling run |
| GET | `/api/v2.2.0/runs` | List run folders available on disk |
| GET | `/api/v2.2.0/runs/<run_id>` | Read run details |
| GET | `/api/v2.2.0/runs/<run_id>/assignments/timetable` | Read timetable assignments |
| GET | `/api/v2.2.0/runs/<run_id>/assignments/rooms` | Read room assignments |
| GET | `/api/v2.2.0/runs/<run_id>/assignments/invigilators` | Read invigilator assignments |
| GET | `/api/v2.2.0/runs/<run_id>/exceptions/rooms` | Read room exceptions |
| GET | `/api/v2.2.0/runs/<run_id>/exceptions/invigilators` | Read invigilator exceptions |
| GET | `/api/v2.2.0/runs/<run_id>/unassigned` | Read aggregate unassigned counts |
| GET | `/api/v2.2.0/runs/<run_id>/metrics` | Read run metrics |
| GET | `/api/v2.2.0/runs/<run_id>/validation` | Read validation status |

Example read-only checks:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/v2.2.0/runs
# Replace <run_id> with an ID returned by the list endpoint.
Invoke-RestMethod "http://127.0.0.1:5000/api/v2.2.0/runs/<run_id>/metrics"
Invoke-RestMethod "http://127.0.0.1:5000/api/v2.2.0/runs/<run_id>/validation"
```

The run-creation POST endpoint executes the v2.2.0 pipeline. Do not issue another POST merely to inspect existing results; use the GET endpoints for read-only inspection.

## Output and exception interpretation

The validated source v2.2.0 allocation artifacts previously recorded include:
- 900 timetable exam rows
- 20,000 student-exam allocations
- 1,493 room allocations
- 19,947 student-room assignments
- 210 equipment reservations
- 36 room exceptions
- 1,493 invigilator assignments
- 0 invigilator exception rows

Room allocation reported 53 unassigned student-room allocations. These and the 36 room exceptions are visible accepted outcomes; they must not be hidden or described as complete room coverage. The API run's output counts should be read from that run's own files/metrics rather than assumed from source-dataset reports.

## Safe verification commands

Run only commands that are appropriate for the current repository and environment:

```powershell
python -m py_compile api\app.py
python -m api.app
```

While the API is running, use the GET health, list, metrics, assignments, exceptions, unassigned, and validation endpoints to inspect behavior.

For the broader project, inspect the supported commands before running them:

```powershell
python run.py --help
python run.py status
```

The safe validation command, if supported by the checked-in runner, is:

```powershell
python run.py validate
```

Do not run `python run.py build`, old generation scripts, or legacy scheduler engines during finalization. The validated v2.2.0 dataset is protected from accidental regeneration.

## Validation status and evidence

Validation evidence for the original v2.2.0 source pipeline is summarized in `docs/VALIDATION_AND_METRICS.md`. API smoke-test evidence is reported separately from independent API-run validation.

A successful HTTP response proves that the endpoint responded; it does not by itself prove that every scheduling constraint has been independently revalidated. If the API validation endpoint reports `PENDING`, report it as pending. Do not substitute copied source-dataset reports for API-run-specific independent validation.

## Documentation map

- `docs/ARCHITECTURE_AND_DECISIONS.md` — architecture, v2.2.0 execution path, constraints and trade-offs.
- `docs/SCHEMA_AND_DATA_DICTIONARY.md` — SQL schema metadata and data dictionary.
- `docs/business_rules.md` — business rules.
- `docs/VALIDATION_AND_METRICS.md` — validation evidence, API smoke tests and limitations.
- `docs/ASSUMPTIONS_LIMITATIONS_AND_PROVENANCE.md` — assumptions, exceptions, provenance and limitations.
- `docs/AI_USAGE_AND_PROMPT_HISTORY.md` — AI disclosure and prompt-history summary.

## Security and submission hygiene

- Keep `.env`, credentials, tokens and private connection details out of Git.
- Keep `.env.example` limited to placeholders.
- Do not publish private, confidential, or evaluation-only data.
- Review `git status` and staged files before every commit.
- The public repository should contain the code and documentation required to reproduce the permitted workflow, not local virtual environments, caches, secrets, or unapproved evaluation artifacts.
