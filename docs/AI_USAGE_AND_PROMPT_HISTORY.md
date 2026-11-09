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
