#requires -Version 5.1
<#
YottaFlex Exam Scheduling System - Documentation Generator
Run from: E:\ExamSchedulingSystem_Submission
Writes only:
  README.md
  docs\ARCHITECTURE_AND_DECISIONS.md
  docs\VALIDATION_AND_METRICS.md
  docs\ASSUMPTIONS_LIMITATIONS_AND_PROVENANCE.md
  docs\AI_USAGE_AND_PROMPT_HISTORY.md

Does NOT:
  - run the scheduler or legacy engine
  - regenerate or modify datasets / GroundTruth
  - connect to or modify SQL Server
  - modify API code or API run folders
  - modify schema/data dictionary or business_rules.md
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = (Get-Location).Path
$DocsPath = Join-Path $ProjectRoot "docs"

if (-not (Test-Path (Join-Path $ProjectRoot "api\app.py"))) {
    throw "api\app.py was not found. Run this script from the project root."
}
if (-not (Test-Path (Join-Path $ProjectRoot "scheduling\timetable_allocator_v220.py"))) {
    throw "scheduling\timetable_allocator_v220.py was not found. The v2.2.0 pipeline entry module is missing."
}
if (-not (Test-Path (Join-Path $ProjectRoot "output_v2\full\v2.2.0"))) {
    throw "Validated v2.2.0 dataset folder was not found. No files were changed."
}
New-Item -ItemType Directory -Force -Path $DocsPath | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"

$readme = @'
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
'@

$architecture = @'
# Architecture, Workflow and Design Decisions

## 1. Authoritative version and execution path

**v2.2.0 is the authoritative implementation for execution and demonstration.** The v2.2.0 modules are the active scheduling pipeline. Older scheduler engines, earlier version modules, and legacy/model-based implementations are historical or compatibility material only; they are not the execution path for the submitted solution.

The API invokes the v2.2.0 workflow. It must not be described as invoking the legacy scheduler engine or an older model.

| Responsibility | Authoritative v2.2.0 module |
|---|---|
| Timetable allocation | `scheduling/timetable_allocator_v220.py` |
| Optional exam waves | `scheduling/apply_optional_waves_v220.py` |
| Room allocation | `scheduling/room_allocator_v220.py` |
| Invigilator allocation | `scheduling/allocate_invigilators_v220.py` |
| HTTP/API interface | `api/app.py` |

## 2. Logical architecture

1. **Configuration and synthetic data** — versioned configuration and a fixed seed define the dataset profile.
2. **Relational model and SQL Server integration** — normalized entities, keys, constraints, and persistence scripts support relational integrity.
3. **Scheduling domain (v2.2.0)** — the active timetable allocator evaluates enrollment conflicts and effective exam durations.
4. **Allocation and traceability (v2.2.0)** — optional waves, rooms, students, equipment, invigilators, and exception outputs are produced.
5. **Flask API** — exposes health, run creation, run discovery, assignments, exceptions, metrics, and validation status.
6. **Independent validation** — validators inspect data and scheduling outputs; API smoke tests establish endpoint responsiveness but are not substitutes for independent schedule validation.

## 3. End-to-end workflow

```text
Master data and dependent records
        |
        v
Dataset and relationship validation
        |
        v
v2.2.0 timetable allocation
        |
        v
Optional exam wave allocation
        |
        v
v2.2.0 room and student allocation
        |
        v
v2.2.0 invigilator allocation
        |
        v
Run outputs, exceptions and metrics
        |
        v
Independent validators
        |
        v
Flask API read-only access to run results
```

The exact execution order and optional stages are governed by the v2.2.0 implementation. The diagram describes the implemented solution at a component level, not a claim that every stage is executed in every configuration.

## 4. API integration and run isolation

The Flask application is `api/app.py` and is started from the repository root with:

```powershell
python -m api.app
```

The API exposes:
- health information;
- v2.2.0 run creation;
- run listing and run details;
- timetable, room, and invigilator assignments;
- room and invigilator exceptions;
- aggregate unassigned counts;
- metrics and validation status.

Each API run uses a run-specific directory under `api_runs/<run_id>/data`. The run-list endpoint discovers available run directories from disk, so a run can remain discoverable after a Flask process restart even though the original in-memory registry is not durable. `outputs_available` means output files were found; it does not prove that all in-memory execution metadata or independent validation reports were persisted.

The API run uses an isolated copy of the validated v2.2.0 source dataset. The implemented API path is designed not to rebuild the protected source dataset, refresh SQL Server, or access GroundTruth. Do not claim SQL persistence for API run history unless a separate verified implementation supports that claim.

## 5. Core business rules

- A student must not have overlapping exams over the student's actual effective duration.
- Standard duration is 90 minutes; the validated extended duration is 120 minutes.
- Interval comparisons use half-open intervals `[start, end)`, so an exam ending exactly when another begins is not an overlap, subject to other constraints.
- Room capacity is checked against effective capacity for the exam date.
- Room closures, equipment requirements, accommodation constraints, and availability must be considered.
- Invigilator assignments must respect availability, interval conflicts, and configured workload rules.
- Optional-course sittings use two waves in the validated profile.
- Unassigned outcomes and exceptions remain visible with reason codes; they are not silently discarded.

## 6. Dataset and identifiers

The v2.2.0 profile contains 5,000 students, 75 tracks, 300 courses (225 compulsory and 75 optional), 20,000 enrollments, 900 exam sittings, 100 rooms, and 200 invigilators. There are three sittings per course in this profile. The 900 sittings must not be confused with the brief's suggested baseline of 300 exams.

SQL relational keys are integer identity keys where defined by the schema. Human-readable business codes are separate deterministic identifiers, including:
- `STU-000001`
- `CRS-000001`
- `EXAM-2026-000001`
- `ROOM-000001`
- `INV-000001`
- `ASN-<exam-id>-<room-id>`

Do not replace relational integer keys with string business codes.

## 7. Scheduling approach and trade-offs

The active v2.2.0 scheduling path uses custom Python allocation logic and explicit business constraints. The conflict graph supports prioritization, but actual interval and duration checks remain necessary. This transparent heuristic is easier to inspect than an opaque optimizer, but it does not guarantee a globally optimal timetable.

Independent validation adds confidence beyond the scheduler's own status, at the cost of additional runtime. Synthetic data avoids reliance on real student records and external dataset licensing, but may not reproduce every institution's operational distribution.

## 8. Exceptions and outcomes

The validated source room-allocation report records 53 unassigned student-room allocations and 36 accepted room exceptions (24 accommodation-related and 12 equipment-related). These are explicit outcomes and must be discussed. They are not evidence of 100% room assignment.

The source invigilator allocation records 1,493 assignments and zero unassigned invigilator duties in the reported result. API-run metrics must be obtained from the API run itself and must not be inferred from source reports.

## 9. Operational safety

- Treat `output_v2/full/v2.2.0` as the protected validated source dataset.
- Do not run `python run.py build` or older generation scripts during submission finalization.
- Do not run the legacy scheduler engine/model as the submitted execution path.
- Use API GET endpoints for inspection; POST creates a new run.
- Do not overwrite or refresh SQL Server or GroundTruth as part of API smoke testing.
- Keep credentials in local environment configuration and out of source control.
'@

$validation = @'
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
'@

$limitations = @'
# Assumptions, Limitations and Data Provenance

## 1. Authoritative implementation

The active and authoritative scheduling implementation is **v2.2.0**. It is the version to execute, validate, demonstrate, and describe in this submission.

The v2.2.0 pipeline uses:
- `scheduling/timetable_allocator_v220.py`
- `scheduling/apply_optional_waves_v220.py`
- `scheduling/room_allocator_v220.py`
- `scheduling/allocate_invigilators_v220.py`

The Flask API in `api/app.py` exposes the v2.2.0 workflow and run outputs.

Older scheduler engines, earlier version modules, and legacy/model-based scheduling implementations may remain in the repository for historical compatibility, comparison, or earlier development. They are not the active execution path and must not be used in place of v2.2.0 when running or demonstrating the submitted solution.

## 2. Dataset assumptions

- Synthetic records represent students, courses, enrollments, exams, rooms, equipment, invigilators, availability, and accommodations.
- The fixed seed recorded for the project is `20261022`.
- SQL Server identity keys are relational keys; business identifiers are separate deterministic codes.
- The v2.2.0 profile contains 300 courses and three exam sittings per course, giving 900 sittings.
- Standard exam duration is 90 minutes and extended duration is 120 minutes in the validated profile.
- Effective intervals use half-open interval comparisons `[start, end)`.

## 3. Scope clarification

The project brief suggests a baseline of 300 exams. The implemented v2.2.0 profile contains 300 courses and 900 exam sittings (three sittings per course). This is a documented modeling/profile choice and must be disclosed explicitly during the reviewer walkthrough.

## 4. API integration assumptions and limitations

- Flask is the HTTP interface; the v2.2.0 scheduling modules remain the scheduling implementation.
- Each API run writes to an isolated run-specific directory under `api_runs/<run_id>/data`.
- The run-list endpoint discovers available run folders from disk after a service restart.
- Disk discovery means output files are available; it does not mean the full in-memory run registry, every execution detail, or independent validation state has been durably persisted.
- The API validation endpoint reports `PENDING` when API-run-specific independent reports are missing.
- API smoke tests establish endpoint responsiveness and the ability to retrieve available output files. They do not prove independent constraint validation.
- The API run path is designed to leave the protected source dataset, GroundTruth, and SQL Server database untouched. Do not claim API run history is SQL-persisted unless a separately verified feature implements it.
- The current API is a local Flask service unless deployment, authentication, authorization, and production hosting are separately implemented and verified.
- No analytics dashboard should be claimed unless one is present and demonstrated.

## 5. Accepted room-allocation outcomes

The validated source v2.2.0 room-allocation output records:
- 53 accepted unassigned student-room allocations;
- 36 accepted room exceptions, recorded as 24 accommodation-related and 12 equipment-related.

These are visible exceptions/outcomes, not zero-exception allocation. Do not claim 100% room assignment. The source invigilator result recorded 1,493 assignments and zero unassigned invigilator duties; API-run figures must be read from the API run itself.

## 6. Algorithmic limitations

- The solution uses custom rule-based/heuristic scheduling logic.
- A valid schedule is not necessarily globally optimal.
- Results depend on the generated profile, constraints, configuration, and allocation order.
- Independent validators are necessary; a scheduler success status alone is insufficient.
- The generic legacy scheduler tests are not evidence that the v2.2.0 pipeline uses that legacy engine.

## 7. Validation and reproducibility limitations

- Previously recorded source v2.2.0 validator reports do not automatically validate a later API-generated run.
- API-run independent validation remains pending until fresh reports are produced from that run's own outputs.
- The fixed seed and manifest/checksum design do not by themselves prove reproducibility. A second isolated same-seed run and checksum equality must be demonstrated.
- Historical test records conflict (29 passed/1 failed versus a later draft saying 30 passed). Use actual terminal output to resolve the result before publication.

## 8. Data provenance and lawful use

- The project is documented as synthetic-data based.
- No external public dataset is relied on in this documentation.
- Synthetic variation is generated using project code and configured seed.
- Do not commit real student records, confidential institutional data, credentials, or private information.
- If external data is introduced, document source URL, dataset/version, retrieval date, license/terms, attribution, transformations, and fields discarded before using or redistributing it.

## 9. Security and repository hygiene

- Keep `.env`, passwords, tokens, connection strings, personal data, and local machine-specific configuration out of Git.
- Commit `.env.example` only with safe placeholders.
- Exclude `.venv`, Python caches, temporary files, and protected evaluation/GroundTruth material from public Git unless the project owner explicitly authorizes a safe, separate evaluation artifact.
- Review `git status` and staged file lists before each commit.
'@

$aiHistory = @'
# AI Usage Disclosure and Prompt History

## 1. Disclosure

Generative AI (ChatGPT) was used as an engineering assistant during requirements analysis, project planning, Python and SQL implementation support, scheduling design discussions, debugging, validation planning, API integration support, documentation drafting, and review of terminal outputs.

AI-generated suggestions and code were not treated as proof of correctness. The candidate is responsible for reviewing the implementation, running the project locally, checking actual command output, understanding the scheduling and data model, and explaining design decisions and limitations.

## 2. Authoritative implementation clarification

The submitted execution path is **v2.2.0**. AI-assisted work on the API was directed to integrate with the v2.2.0 scheduling pipeline. The API must not be described as running the older/legacy scheduler engine or an earlier model. Older scheduler modules remain historical/reference code where present; v2.2.0 is the version to run and demonstrate.

## 3. Main AI-assisted work areas

- Translating the business brief into entities, dependencies, constraints, and acceptance criteria.
- Planning deterministic synthetic master and transaction data.
- Reviewing identifier conventions, foreign-key relationships, bridge tables, and data dictionary structure.
- Designing student-conflict scheduling and interval checks.
- Reviewing room, equipment, accommodation, and invigilator allocation rules.
- Supporting SQL Server connectivity, schema inspection, and safe validation design.
- Supporting the v2.2.0 Flask API integration and isolated run-output design.
- Adding read-only API access for timetable, room, invigilator assignments, exceptions, metrics, and validation status.
- Debugging API startup and endpoint behavior using actual local terminal responses.
- Drafting architecture, validation, assumptions, README, and AI-disclosure documentation.

## 4. Representative prompt history

The following is a structured summary of the main engineering instructions used during development. It is not represented as a timestamped verbatim export of every original chat message.

### Prompt 1 — Analyze the business requirements

```text
Analyze the exam scheduling business requirements. Identify entities, relationships, generation dependencies, validation rules, scheduling constraints, room and invigilator allocation, exception paths, metrics, documentation, and acceptance criteria. Separate confirmed implementation from proposed work. Do not restart completed work.
```

### Prompt 2 — Preserve existing project decisions

```text
Continue from the existing project. Use Python and SQL Server with the existing project structure. Preserve validated data and existing schema. Before changing code, inspect dependencies, interfaces, configuration, and test evidence. Do not recreate the database or regenerate validated data without an explicit safe plan.
```

### Prompt 3 — Deterministic data and ground truth separation

```text
Design deterministic synthetic data using the configured fixed seed and stable business identifiers. Generate parent records before dependent records, derive values from source records, validate keys and joins, and keep evaluation labels separate from normal scheduling inputs. Do not leak GroundTruth into scheduling features.
```

### Prompt 4 — Implement and validate scheduling constraints

```text
Review the scheduling implementation against student enrollment conflicts, effective exam durations, room capacity, closures, equipment, accommodations, and invigilator availability. Use actual time intervals and explicit reason codes. Add independent validation and tests for normal, boundary, and negative scenarios.
```

### Prompt 5 — Preserve SQL Server integrity

```text
Use the existing SQL Server schema and parameterized database operations. Preserve keys, constraints, indexes, triggers, and transaction safety. Keep credentials in environment configuration. Do not recreate, truncate, or refresh the database as part of unrelated testing.
```

### Prompt 6 — Integrate the Flask API with v2.2.0

```text
Integrate the Flask API with the authoritative v2.2.0 scheduling pipeline. Do not call the legacy scheduler engine or older scheduling models. Create isolated run-specific output directories. Do not overwrite the validated source dataset, access GroundTruth, or refresh SQL Server. Expose run creation and read-only endpoints for run details and generated assignments.
```

### Prompt 7 — Add read-only result endpoints

```text
Add read-only endpoints for timetable assignments, room assignments, invigilator assignments, room exceptions, invigilator exceptions, aggregate unassigned counts, metrics, and validation status. Validate query limits and run identifiers. Return an honest PENDING status when independent API-run validation reports are not available.
```

### Prompt 8 — Make run listing survive API restart

```text
The in-memory run registry is empty after restarting Flask. Update the run-list endpoint to discover existing run directories from disk. Do not rerun the scheduling POST or modify existing run outputs. Distinguish outputs available on disk from fully persisted execution metadata.
```

### Prompt 9 — Verify the API using actual responses

```text
Check Python syntax, start the Flask service, and verify health, run listing, metrics, assignment, exception, unassigned, and validation GET endpoints. Use actual terminal output. Do not claim independent validation based only on HTTP 200 responses or copied source reports.
```

### Prompt 10 — Prepare documentation and submission

```text
Update README, architecture, validation, assumptions/limitations, and AI usage documentation to describe the current v2.2.0 pipeline and Flask API. Clearly distinguish source pipeline validation from API smoke tests and API-run independent validation. Preserve schema documentation unless schema changes. Do not modify datasets, GroundTruth, SQL Server, or API outputs.
```

## 5. What the candidate personally reviewed or verified

The candidate's local work and review should be described only to the extent actually performed. The project history records these activities:
- inspected local project files and command output;
- ran Python compilation and started the Flask API;
- called API endpoints and observed HTTP 200 responses;
- inspected run listing and generated CSV row counts;
- reviewed validation endpoint output, including its `PENDING` status;
- reviewed the project structure and documentation inventory.

The candidate should be prepared to explain the v2.2.0 pipeline, why the API uses isolated run folders, the difference between API smoke tests and independent validation, and the accepted room-allocation exceptions.

## 6. AI limitations and candidate responsibility

AI assistance can accelerate implementation and documentation but can produce stale assumptions, incorrect code, or claims unsupported by execution evidence. The candidate reviewed outputs against the local project and should retain only claims supported by code, files, or actual terminal results.

Do not claim that AI independently verified the project. Do not describe this structured prompt summary as a complete verbatim conversation export. If the assessment requires the full original prompt log, attach the actual exported prompt history separately.
'@

$files = [ordered]@{
    "README.md" = $readme
    "docs\ARCHITECTURE_AND_DECISIONS.md" = $architecture
    "docs\VALIDATION_AND_METRICS.md" = $validation
    "docs\ASSUMPTIONS_LIMITATIONS_AND_PROVENANCE.md" = $limitations
    "docs\AI_USAGE_AND_PROMPT_HISTORY.md" = $aiHistory
}

# Back up existing target Markdown files before replacing them.
$backupRoot = Join-Path $ProjectRoot ("docs_backup_before_api_docs_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

foreach ($relativePath in $files.Keys) {
    $target = Join-Path $ProjectRoot $relativePath
    $parent = Split-Path -Parent $target
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    if (Test-Path $target) {
        $backupTarget = Join-Path $backupRoot $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupTarget) | Out-Null
        Copy-Item -LiteralPath $target -Destination $backupTarget -Force
    }

    Set-Content -LiteralPath $target -Value $files[$relativePath] -Encoding UTF8
}

Write-Host ""
Write-Host "Documentation generation completed." -ForegroundColor Green
Write-Host "Project root: $ProjectRoot"
Write-Host "Authoritative scheduling version: v2.2.0"
Write-Host "Backup folder: $backupRoot"
Write-Host ""
Write-Host "Updated files:"
$files.Keys | ForEach-Object { Write-Host " - $_" }

Write-Host ""
Write-Host "Not modified:"
Write-Host " - docs\SCHEMA_AND_DATA_DICTIONARY.md"
Write-Host " - docs\business_rules.md"
Write-Host " - output_v2\full\v2.2.0"
Write-Host " - GroundTruth / evaluation data"
Write-Host " - SQL Server"
Write-Host " - api_runs"
Write-Host " - api\app.py"
Write-Host ""
Write-Host "IMPORTANT: This script only writes Markdown documentation."
Write-Host "It does not run v2.2.0, the legacy engine, or any scheduling model."
Write-Host "Review the generated files and verify all claims against current local outputs before committing."
