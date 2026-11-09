# Exam Scheduling System — Business Rules Specification

**Version:** 1.0  
**Database:** ExamSchedulingDB  
**Random Seed:** 20261022  
**Status:** Initial application-rule specification

---

## 1. Purpose

Define the application-level rules governing examination eligibility, room allocation, student accommodations, invigilator assignment, conflict detection, exception reporting and evaluation.

Database constraints and application-level rules are distinguished explicitly.

## 2. Entity and Relationship Mapping

| Entity | Purpose | Main relationships |
|---|---|---|
| Student | Learner master | 1:N Enrollment; 1:N Accommodation |
| Course | Academic master | 1:N Enrollment; 1:N Exam |
| Enrollment | Student-course registration | N:1 Student; N:1 Course |
| Exam | Examination master | N:1 Course; 1:N ExamEnrollment |
| ExamRequirement | Examination requirements | Associated with Exam |
| ExamEnrollment | Exam participation | N:1 Exam; N:1 Enrollment |
| Room | Examination venue | 1:N Capacity, Closure and Equipment |
| RoomCapacity | Effective capacity history | N:1 Room |
| Equipment | Equipment master | Connected through room and exam bridge tables |
| RoomEquipment | Available room equipment | N:1 Room; N:1 Equipment |
| ExamRequiredEquipment | Required exam equipment | N:1 Exam; N:1 Equipment |
| Invigilator | Invigilator master | 1:N Availability and assignments |
| Availability | Invigilator availability | N:1 Invigilator |
| Accommodation | Student examination accommodations | N:1 Student |
| ScheduleAssignment | Exam-room-time assignment | References Exam, Room and SchedulingRun |
| AssignmentStudent | Student seat allocation | References ScheduleAssignment and ExamEnrollment |
| AssignmentInvigilator | Invigilator allocation | References ScheduleAssignment and Invigilator |
| AssignmentEvent | Assignment history | N:1 ScheduleAssignment |
| SchedulingException | Scheduling exceptions | References SchedulingRun and optionally Exam |
| SchedulingRun | Scheduling execution | Parent of scheduling outputs |
| GroundTruth | Independent evaluation labels | Evaluation schema |

Bridge tables must preserve valid parent references. Composite foreign keys must be respected.

## 3. Master Data Rules

### 3.1 Student

- StudentCode follows STU-000001 format.
- StudentCode must be unique.
- Student status must be ACTIVE, INACTIVE or GRADUATED.
- Only active students with valid enrollments are eligible for ordinary examination allocation.

### 3.2 Course

- CourseCode must be unique.
- Credits must be between 1 and 10.
- Course status must be ACTIVE or INACTIVE.
- Inactive courses must not receive new ordinary examination enrollments.

### 3.3 Enrollment

- Every enrollment references an existing student and course.
- EffectiveTo must be NULL or greater than or equal to EffectiveFrom.
- EnrollmentStatus must be ENROLLED, COMPLETED or DROPPED.
- Only eligible ENROLLED records participate in ordinary scheduling.

### 3.4 Exam

- ExamCode follows EXAM-2026-000001 format.
- Every exam references an existing course.
- ExamWindowEnd must be later than ExamWindowStart.
- ExamStatus must be DRAFT, READY, SCHEDULED or CANCELLED.
- Only READY exams are eligible for a new scheduling run.

### 3.5 ExamRequirement

- Every exam must have a valid duration requirement before scheduling.
- DurationMinutes must be between 15 and 600.
- RequiredEquipment must contain valid JSON when provided.
- Accessibility requirements must be respected.

### 3.6 ExamEnrollment

- ExamEnrollment must reference a valid Exam and Enrollment.
- The CourseID must match the course associated with both parent records.
- ParticipationStatus must be REGISTERED, WITHDRAWN or EXEMPT.
- Only REGISTERED participants are included in ordinary seat allocation.

## 4. Room and Resource Rules

### 4.1 Room eligibility

A room is eligible only when:

1. It exists.
2. IsActive is true.
3. It has an effective capacity record covering the proposed examination.
4. Its capacity is sufficient for the allocated students.
5. It is not subject to an active overlapping closure.
6. All mandatory equipment requirements are satisfied.
7. It satisfies relevant accessibility requirements.

### 4.2 Room capacity

- Capacity must be greater than zero.
- EffectiveTo must be NULL or greater than or equal to EffectiveFrom.
- The number of allocated students must not exceed the effective capacity.
- AssignedCapacity must be positive.
- Capacity must be evaluated at the scheduled examination date.

### 4.3 Room closures

- ClosureEnd must be later than ClosureStart.
- ClosureStatus must be ACTIVE, COMPLETED or CANCELLED.
- An ACTIVE closure overlapping an examination prevents room allocation.
- CANCELLED closures do not block allocation.

### 4.4 Equipment

- Equipment must be active.
- Equipment must be available in the room during the examination.
- Available quantity must satisfy mandatory examination requirements.
- Optional equipment must not be treated as mandatory.
- Equipment JSON and normalized equipment bridge records must be synchronized or explicitly reconciled.

## 5. Student Accommodation Rules

Supported accommodation types:

| Type | Scheduling requirement |
|---|---|
| EXTENDED_TIME | Apply additional examination duration |
| SEPARATE_ROOM | Allocate a separate examination room |
| ACCESSIBLE_ROOM | Use an accessible room |
| SPECIAL_EQUIPMENT | Provide required special equipment |

Rules:

- AccommodationStatus must be ACTIVE, EXPIRED or REVOKED.
- Effective dates must be respected.
- Extended-time percentage must be greater than zero and at most 200.
- Extended-time percentage must be NULL for other accommodation types.
- Accommodation requirements must be applied before confirming assignments.
- An accommodation violation must never be accepted as a valid assignment.

Extended duration:

EffectiveDuration = CEILING(BaseDuration × (1 + ExtensionPercentage / 100))

The calculation must be performed in minutes.

If multiple accommodations apply, all applicable requirements must be considered.

## 6. Student Conflict Rules

- A student cannot participate in overlapping examinations.
- Conflict detection must use actual examination intervals, including extended durations.
- Only registered examination participants are considered.
- Withdrawn and exempt participants are excluded.
- A student conflict must be identified before assignment confirmation.
- Student allocations must be checked across the complete scheduling run.

Two examination intervals overlap when:

StartA < EndB AND StartB < EndA

## 7. Invigilator Rules

- InvigilatorCode follows INV-000001 format.
- Invigilator must be ACTIVE.
- AvailabilityStatus must be AVAILABLE or UNAVAILABLE.
- AvailableTo must be later than AvailableFrom.
- An invigilator must be available for the entire assignment.
- An invigilator cannot supervise overlapping assignments.
- Daily assigned hours must not exceed MaxDailyHours.
- Invigilator role must be PRIMARY, ASSISTANT or RELIEF.
- Removed allocations must not count toward active workload.

## 8. Scheduling Assignment Rules

Every assignment must:

- Reference a valid examination.
- Reference a valid room.
- Reference a valid scheduling run.
- Have EndTime greater than StartTime.
- Have positive AssignedCapacity.
- Respect room capacity.
- Respect student conflict restrictions.
- Respect invigilator availability.
- Respect accommodations.
- Respect equipment and room closures.

AssignmentStatus must be PROPOSED, CONFIRMED or CANCELLED.

Only assignments satisfying all hard constraints may become CONFIRMED.

## 9. Assignment History and Lifecycle

Assignment lifecycle:

CREATED → PROPOSED → CONFIRMED

Other permitted operational transitions include:

PROPOSED → CANCELLED  
CONFIRMED → CANCELLED

Changes to confirmed assignments must create corresponding historical events.

Supported event types:

- CREATED
- CONFIRMED
- RESCHEDULED
- CANCELLED
- INVIGILATOR_CHANGED
- STUDENT_REALLOCATED

Existing event history must not be overwritten.

Assignment events must record timestamps and relevant actor information.

## 10. Scheduling Exception Reason Codes

Use the existing database-supported reason codes.

| Reason code | Meaning |
|---|---|
| INVALID_REQUIREMENT | Missing or invalid examination requirements |
| NO_ELIGIBLE_STUDENTS | No eligible examination participants |
| ACCOMMODATION_CONFLICT | No feasible allocation respecting accommodations |
| STUDENT_CONFLICT | Student examination overlap prevents allocation |
| NO_ROOM_CAPACITY | No eligible room has sufficient capacity |
| NO_EQUIPMENT | Required equipment is unavailable |
| ROOM_CLOSED | Candidate rooms are unavailable because of closures |
| NO_VALID_TIMESLOT | No feasible examination time exists |
| NO_INVIGILATOR | No suitable invigilator can be assigned |
| OTHER | Unclassified scheduling failure |

Each unassigned exam must have an exception record with:

- SchedulingRunID
- ExamID where applicable
- IssueType
- ReasonCode
- Severity
- ExceptionDetails
- ExceptionStatus
- DetectedAt

An exception must not be generated merely because an unrelated diagnostic condition exists. Record the actual blocking reason and supporting evidence.

ExceptionStatus must be OPEN, RESOLVED or WAIVED.

OPEN exceptions must have NULL ResolvedAt. Resolved and waived exceptions must have a resolution timestamp.

## 11. Required Negative Scenarios

Generate valid baseline records first.

Inject deliberate anomalies into separate labelled scenarios.

| Scenario | Expected detection |
|---|---|
| Student has overlapping exams | STUDENT_CONFLICT |
| Room capacity exceeded | NO_ROOM_CAPACITY |
| Invigilator double-booked | NO_INVIGILATOR or assignment conflict rejection |
| Accommodation ignored | ACCOMMODATION_CONFLICT |
| Exam outside room availability | ROOM_CLOSED or NO_VALID_TIMESLOT, according to the actual blocking condition |

Anomaly records must be isolated from unrelated baseline records.

Deliberately invalid assignments must be rejected or flagged, never silently accepted.

## 12. Ground Truth Separation

Ground truth belongs in evaluation.GroundTruth.

Required fields include:

- DatasetVersion
- ScenarioCode
- EntityType
- EntityCode
- IssueType
- ExpectedOutcome
- ExpectedReasonCode
- Severity
- Description

Allowed ExpectedOutcome values:

- ACCEPT
- REJECT
- UNASSIGNED
- FLAG

Ground truth must never be included in scheduler input data.

The scheduling algorithm must independently evaluate each scenario.

Actual scheduler results must be compared against expected outcomes after execution.

## 13. Reasonable Scheduling Heuristics

The custom scheduling algorithm should:

1. Identify eligible examinations.
2. Calculate examination durations.
3. Construct the student conflict graph.
4. Prioritize highly constrained examinations.
5. Generate feasible candidate time slots.
6. Identify eligible rooms.
7. Check capacity and equipment.
8. Apply accommodation restrictions.
9. Check room closures.
10. Allocate invigilators.
11. Confirm valid assignments.
12. Record unassigned examinations and exceptions.

Use explainable deterministic heuristics.

Do not use OR-Tools or an external optimization solver.

## 14. Evaluation Metrics

Calculate all metrics from actual scheduling outputs.

| Metric | Calculation |
|---|---|
| Scheduling success rate | Scheduled exams / Total eligible exams × 100 |
| Unassigned rate | Unassigned exams / Total eligible exams × 100 |
| Room utilization | Occupied room time / Available room time × 100 |
| Invigilator utilization | Assigned invigilator hours / Available invigilator hours × 100 |
| Student conflict count | Number of detected overlapping student assignments |
| Accommodation compliance | Compliant accommodated allocations / Total accommodated allocations × 100 |
| Capacity violations | Number of assignments exceeding room capacity |
| Invigilator conflicts | Number of overlapping invigilator assignments |

Report exception counts by reason code.

Report evaluation results separately for normal and deliberately anomalous scenarios.

## 15. Data Integrity and Reproducibility

- Fixed seed: 20261022.
- Deterministic business identifiers.
- SQL Server identity columns remain unchanged.
- Parent records must be inserted before child records.
- All foreign-key references must be valid.
- Derived values must come from source records.
- Ground truth must remain separate.
- Data generation must be repeatable.
- Existing history must be retained.
- Dataset exports must include source manifests and checksums.

## 16. Rule Enforcement Classification

**Database-enforced rules:** Primary keys, foreign keys, unique keys/indexes, CHECK constraints and configured triggers.

**Application-enforced rules:** Enrollment eligibility, cross-table course consistency, examination conflicts, room availability, capacity evaluation at examination time, equipment matching, accommodation compliance, invigilator workload and assignment lifecycle.

The application must not assume that every business rule is enforced by SQL Server.

---

**Document status:** Initial specification based on the supplied business requirements and exported SQL Server metadata. Application-level rules must be tested against the existing database and scheduling workflow before final acceptance.