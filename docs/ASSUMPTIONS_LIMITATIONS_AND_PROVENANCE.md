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
