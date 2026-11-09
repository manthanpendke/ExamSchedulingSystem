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
