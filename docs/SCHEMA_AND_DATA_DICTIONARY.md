# SQL Server Schema and Data Dictionary

> Generated from exported SQL Server metadata. This script does not connect to the database.

## Table Inventory

| Table | Columns |
|---|---:|
| dbo.Accommodation | 9 |
| dbo.AssignmentEvent | 8 |
| dbo.AssignmentInvigilator | 8 |
| dbo.AssignmentStudent | 8 |
| dbo.Availability | 7 |
| dbo.Course | 7 |
| dbo.Enrollment | 8 |
| dbo.Equipment | 6 |
| dbo.Exam | 8 |
| dbo.ExamEnrollment | 6 |
| dbo.ExamRequiredEquipment | 5 |
| dbo.ExamRequirement | 7 |
| dbo.Invigilator | 7 |
| dbo.Room | 7 |
| dbo.RoomCapacity | 7 |
| dbo.RoomClosure | 7 |
| dbo.RoomEquipment | 6 |
| dbo.ScheduleAssignment | 10 |
| dbo.SchedulingException | 10 |
| dbo.SchedulingRun | 8 |
| dbo.Student | 8 |

## dbo.Accommodation

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AccommodationID` | `int` |  | True | False | 10 | 0 | 4 |
| `StudentID` | `int` |  | False | False | 10 | 0 | 4 |
| `AccommodationType` | `varchar` |  | False | False | 0 | 0 | 40 |
| `ExtensionPercentage` | `decimal` |  | False | False | 5 | 2 | 5 |
| `RequiresSeparateRoom` | `bit` |  | False | False | 1 | 0 | 1 |
| `EffectiveFrom` | `date` |  | False | False | 10 | 0 | 3 |
| `EffectiveTo` | `date` |  | False | False | 10 | 0 | 3 |
| `AccommodationStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.AssignmentEvent

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AssignmentEventID` | `bigint` |  | True | False | 19 | 0 | 8 |
| `AssignmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `EventType` | `varchar` |  | False | False | 0 | 0 | 40 |
| `PreviousStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `NewStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `EventTimestamp` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `Actor` | `varchar` |  | False | False | 0 | 0 | 100 |
| `EventDetails` | `nvarchar` |  | False | False | 0 | 0 | -1 |

## dbo.AssignmentInvigilator

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AssignmentInvigilatorID` | `int` |  | True | False | 10 | 0 | 4 |
| `AssignmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `InvigilatorID` | `int` |  | False | False | 10 | 0 | 4 |
| `SchedulingRunID` | `int` |  | False | False | 10 | 0 | 4 |
| `AssignedRole` | `varchar` |  | False | False | 0 | 0 | 30 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `AssignmentStatus` | `varchar` |  | False | False | 0 | 0 | 20 |

## dbo.AssignmentStudent

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AssignmentStudentID` | `int` |  | True | False | 10 | 0 | 4 |
| `AssignmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `ExamEnrollmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `SchedulingRunID` | `int` |  | False | False | 10 | 0 | 4 |
| `SeatNumber` | `varchar` |  | False | False | 0 | 0 | 20 |
| `AllocationStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Availability

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AvailabilityID` | `int` |  | True | False | 10 | 0 | 4 |
| `InvigilatorID` | `int` |  | False | False | 10 | 0 | 4 |
| `AvailableFrom` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `AvailableTo` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `AvailabilityStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `AvailabilityReason` | `varchar` |  | False | False | 0 | 0 | 200 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Course

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `CourseID` | `int` |  | True | False | 10 | 0 | 4 |
| `CourseCode` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CourseName` | `varchar` |  | False | False | 0 | 0 | 150 |
| `Department` | `varchar` |  | False | False | 0 | 0 | 100 |
| `Credits` | `tinyint` |  | False | False | 3 | 0 | 1 |
| `Status` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Enrollment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `EnrollmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `StudentID` | `int` |  | False | False | 10 | 0 | 4 |
| `CourseID` | `int` |  | False | False | 10 | 0 | 4 |
| `EnrollmentDate` | `date` |  | False | False | 10 | 0 | 3 |
| `EnrollmentStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `EffectiveFrom` | `date` |  | False | False | 10 | 0 | 3 |
| `EffectiveTo` | `date` |  | False | False | 10 | 0 | 3 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Equipment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `EquipmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `EquipmentCode` | `varchar` |  | False | True | 0 | 0 | 10 |
| `EquipmentName` | `varchar` |  | False | False | 0 | 0 | 100 |
| `EquipmentCategory` | `varchar` |  | False | False | 0 | 0 | 50 |
| `IsActive` | `bit` |  | False | False | 1 | 0 | 1 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Exam

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `ExamID` | `int` |  | True | False | 10 | 0 | 4 |
| `ExamCode` | `varchar` |  | False | False | 0 | 0 | 30 |
| `CourseID` | `int` |  | False | False | 10 | 0 | 4 |
| `ExamName` | `varchar` |  | False | False | 0 | 0 | 150 |
| `ExamWindowStart` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `ExamWindowEnd` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `ExamStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.ExamEnrollment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `ExamEnrollmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `EnrollmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `CourseID` | `int` |  | False | False | 10 | 0 | 4 |
| `ParticipationStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `RegisteredAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.ExamRequiredEquipment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `ExamRequiredEquipmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `EquipmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `QuantityRequired` | `int` |  | False | False | 10 | 0 | 4 |
| `IsMandatory` | `bit` |  | False | False | 1 | 0 | 1 |

## dbo.ExamRequirement

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `RequirementID` | `int` |  | True | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `DurationMinutes` | `smallint` |  | False | False | 5 | 0 | 2 |
| `RequiredEquipment` | `nvarchar` |  | False | False | 0 | 0 | -1 |
| `AccessibilityRequired` | `bit` |  | False | False | 1 | 0 | 1 |
| `SpecialInstructions` | `nvarchar` |  | False | False | 0 | 0 | 1000 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Invigilator

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `InvigilatorID` | `int` |  | True | False | 10 | 0 | 4 |
| `InvigilatorCode` | `varchar` |  | False | False | 0 | 0 | 20 |
| `FullName` | `varchar` |  | False | False | 0 | 0 | 100 |
| `Department` | `varchar` |  | False | False | 0 | 0 | 100 |
| `MaxDailyHours` | `decimal` |  | False | False | 4 | 2 | 5 |
| `Status` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Room

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `RoomID` | `int` |  | True | False | 10 | 0 | 4 |
| `RoomCode` | `varchar` |  | False | False | 0 | 0 | 20 |
| `Building` | `varchar` |  | False | False | 0 | 0 | 100 |
| `Floor` | `smallint` |  | False | False | 5 | 0 | 2 |
| `RoomType` | `varchar` |  | False | False | 0 | 0 | 30 |
| `IsActive` | `bit` |  | False | False | 1 | 0 | 1 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.RoomCapacity

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `RoomCapacityID` | `int` |  | True | False | 10 | 0 | 4 |
| `RoomID` | `int` |  | False | False | 10 | 0 | 4 |
| `Capacity` | `int` |  | False | False | 10 | 0 | 4 |
| `EffectiveFrom` | `date` |  | False | False | 10 | 0 | 3 |
| `EffectiveTo` | `date` |  | False | False | 10 | 0 | 3 |
| `CapacityReason` | `varchar` |  | False | False | 0 | 0 | 200 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.RoomClosure

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `RoomClosureID` | `int` |  | True | False | 10 | 0 | 4 |
| `RoomID` | `int` |  | False | False | 10 | 0 | 4 |
| `ClosureStart` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `ClosureEnd` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `ClosureReason` | `varchar` |  | False | False | 0 | 0 | 200 |
| `ClosureStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.RoomEquipment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `RoomEquipmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `RoomID` | `int` |  | False | False | 10 | 0 | 4 |
| `EquipmentID` | `int` |  | False | False | 10 | 0 | 4 |
| `Quantity` | `int` |  | False | False | 10 | 0 | 4 |
| `EffectiveFrom` | `date` |  | False | False | 10 | 0 | 3 |
| `EffectiveTo` | `date` |  | False | False | 10 | 0 | 3 |

## dbo.ScheduleAssignment

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `AssignmentID` | `int` |  | True | False | 10 | 0 | 4 |
| `AssignmentCode` | `varchar` |  | False | False | 0 | 0 | 100 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `RoomID` | `int` |  | False | False | 10 | 0 | 4 |
| `SchedulingRunID` | `int` |  | False | False | 10 | 0 | 4 |
| `StartTime` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `EndTime` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `AssignedCapacity` | `int` |  | False | False | 10 | 0 | 4 |
| `AssignmentStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.SchedulingException

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `SchedulingExceptionID` | `bigint` |  | True | False | 19 | 0 | 8 |
| `SchedulingRunID` | `int` |  | False | False | 10 | 0 | 4 |
| `ExamID` | `int` |  | False | False | 10 | 0 | 4 |
| `IssueType` | `varchar` |  | False | False | 0 | 0 | 60 |
| `ReasonCode` | `varchar` |  | False | False | 0 | 0 | 60 |
| `Severity` | `varchar` |  | False | False | 0 | 0 | 20 |
| `ExceptionDetails` | `nvarchar` |  | False | False | 0 | 0 | -1 |
| `ExceptionStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `DetectedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `ResolvedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.SchedulingRun

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `SchedulingRunID` | `int` |  | True | False | 10 | 0 | 4 |
| `RunCode` | `varchar` |  | False | False | 0 | 0 | 40 |
| `AlgorithmVersion` | `varchar` |  | False | False | 0 | 0 | 30 |
| `RandomSeed` | `bigint` |  | False | False | 19 | 0 | 8 |
| `RunStatus` | `varchar` |  | False | False | 0 | 0 | 20 |
| `Configuration` | `nvarchar` |  | False | False | 0 | 0 | -1 |
| `StartedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |
| `CompletedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## dbo.Student

| Column | SQL Type | Nullable | Identity | Computed | Precision | Scale | Max Length |
|---|---|---|---|---|---|---|---|
| `StudentID` | `int` |  | True | False | 10 | 0 | 4 |
| `StudentCode` | `varchar` |  | False | False | 0 | 0 | 20 |
| `FirstName` | `varchar` |  | False | False | 0 | 0 | 50 |
| `LastName` | `varchar` |  | False | False | 0 | 0 | 50 |
| `Email` | `varchar` |  | False | False | 0 | 0 | 150 |
| `Department` | `varchar` |  | False | False | 0 | 0 | 100 |
| `Status` | `varchar` |  | False | False | 0 | 0 | 20 |
| `CreatedAt` | `datetime2` |  | False | False | 27 | 7 | 8 |

## Foreign Keys

| Child Table | Child Column | Parent Table | Parent Column |
|---|---|---|---|
| Accommodation | StudentID | Student | StudentID |
| AssignmentEvent | AssignmentID | ScheduleAssignment | AssignmentID |
| AssignmentInvigilator | AssignmentID | ScheduleAssignment | AssignmentID |
| AssignmentInvigilator | ExamID | ScheduleAssignment | ExamID |
| AssignmentInvigilator | SchedulingRunID | ScheduleAssignment | SchedulingRunID |
| AssignmentInvigilator | InvigilatorID | Invigilator | InvigilatorID |
| AssignmentStudent | AssignmentID | ScheduleAssignment | AssignmentID |
| AssignmentStudent | ExamID | ScheduleAssignment | ExamID |
| AssignmentStudent | SchedulingRunID | ScheduleAssignment | SchedulingRunID |
| AssignmentStudent | ExamEnrollmentID | ExamEnrollment | ExamEnrollmentID |
| AssignmentStudent | ExamID | ExamEnrollment | ExamID |
| Availability | InvigilatorID | Invigilator | InvigilatorID |
| Enrollment | CourseID | Course | CourseID |
| Enrollment | StudentID | Student | StudentID |
| Exam | CourseID | Course | CourseID |
| ExamEnrollment | EnrollmentID | Enrollment | EnrollmentID |
| ExamEnrollment | CourseID | Enrollment | CourseID |
| ExamEnrollment | ExamID | Exam | ExamID |
| ExamEnrollment | CourseID | Exam | CourseID |
| ExamRequiredEquipment | EquipmentID | Equipment | EquipmentID |
| ExamRequiredEquipment | ExamID | Exam | ExamID |
| ExamRequirement | ExamID | Exam | ExamID |
| RoomCapacity | RoomID | Room | RoomID |
| RoomClosure | RoomID | Room | RoomID |
| RoomEquipment | EquipmentID | Equipment | EquipmentID |
| RoomEquipment | RoomID | Room | RoomID |
| ScheduleAssignment | ExamID | Exam | ExamID |
| ScheduleAssignment | RoomID | Room | RoomID |
| ScheduleAssignment | SchedulingRunID | SchedulingRun | SchedulingRunID |
| SchedulingException | ExamID | Exam | ExamID |
| SchedulingException | SchedulingRunID | SchedulingRun | SchedulingRunID |

## Key Metadata

| schema_name | table_name | key_name | key_type | column_name | key_ordinal |
|---|---|---|---|---|---|
| dbo | Accommodation | PK__Accommod__DBB309B111A307A7 | PRIMARY KEY | AccommodationID | 1 |
| dbo | AssignmentEvent | PK__Assignme__1AC990D8F73A4FE9 | PRIMARY KEY | AssignmentEventID | 1 |
| dbo | AssignmentInvigilator | PK__Assignme__9982BFA52D7B051A | PRIMARY KEY | AssignmentInvigilatorID | 1 |
| dbo | AssignmentInvigilator | UX_AssignmentInvigilator_Active | UNIQUE INDEX | AssignmentID | 1 |
| dbo | AssignmentInvigilator | UX_AssignmentInvigilator_Active | UNIQUE INDEX | InvigilatorID | 2 |
| dbo | AssignmentStudent | PK__Assignme__653C7F1E36475113 | PRIMARY KEY | AssignmentStudentID | 1 |
| dbo | AssignmentStudent | UQ_AssignmentStudent_Seat | UNIQUE CONSTRAINT | AssignmentID | 1 |
| dbo | AssignmentStudent | UQ_AssignmentStudent_Seat | UNIQUE CONSTRAINT | SeatNumber | 2 |
| dbo | AssignmentStudent | UX_AssignmentStudent_Active | UNIQUE INDEX | ExamEnrollmentID | 1 |
| dbo | AssignmentStudent | UX_AssignmentStudent_Active | UNIQUE INDEX | SchedulingRunID | 2 |
| dbo | Availability | PK__Availabi__DA3979919C089395 | PRIMARY KEY | AvailabilityID | 1 |
| dbo | Course | PK__Course__C92D7187A1558128 | PRIMARY KEY | CourseID | 1 |
| dbo | Course | UQ__Course__FC00E000F516B2B8 | UNIQUE CONSTRAINT | CourseCode | 1 |
| dbo | Enrollment | PK__Enrollme__7F6877FBF52E5365 | PRIMARY KEY | EnrollmentID | 1 |
| dbo | Enrollment | UQ_Enrollment_ID_Course | UNIQUE CONSTRAINT | EnrollmentID | 1 |
| dbo | Enrollment | UQ_Enrollment_ID_Course | UNIQUE CONSTRAINT | CourseID | 2 |
| dbo | Enrollment | UX_Enrollment_Active | UNIQUE INDEX | StudentID | 1 |
| dbo | Enrollment | UX_Enrollment_Active | UNIQUE INDEX | CourseID | 2 |
| dbo | Equipment | PK__Equipmen__3447459976FE00F1 | PRIMARY KEY | EquipmentID | 1 |
| dbo | Equipment | UQ__Equipmen__71DB6E4ECAB1D2E0 | UNIQUE CONSTRAINT | EquipmentName | 1 |
| dbo | Equipment | UQ_Equipment_Code | UNIQUE CONSTRAINT | EquipmentCode | 1 |
| dbo | Exam | PK__Exam__297521A70DFC01F5 | PRIMARY KEY | ExamID | 1 |
| dbo | Exam | UQ__Exam__FFB9F6CFDBFEDEB6 | UNIQUE CONSTRAINT | ExamCode | 1 |
| dbo | Exam | UQ_Exam_ID_Course | UNIQUE CONSTRAINT | ExamID | 1 |
| dbo | Exam | UQ_Exam_ID_Course | UNIQUE CONSTRAINT | CourseID | 2 |
| dbo | ExamEnrollment | PK__ExamEnro__C283D8555221399A | PRIMARY KEY | ExamEnrollmentID | 1 |
| dbo | ExamEnrollment | UQ_ExamEnrollment | UNIQUE CONSTRAINT | ExamID | 1 |
| dbo | ExamEnrollment | UQ_ExamEnrollment | UNIQUE CONSTRAINT | EnrollmentID | 2 |
| dbo | ExamEnrollment | UQ_ExamEnrollment_ID_Exam | UNIQUE CONSTRAINT | ExamEnrollmentID | 1 |
| dbo | ExamEnrollment | UQ_ExamEnrollment_ID_Exam | UNIQUE CONSTRAINT | ExamID | 2 |
| dbo | ExamRequiredEquipment | PK__ExamRequ__D2FE4B7AC990B2C4 | PRIMARY KEY | ExamRequiredEquipmentID | 1 |
| dbo | ExamRequiredEquipment | UQ_ExamRequiredEquipment | UNIQUE CONSTRAINT | ExamID | 1 |
| dbo | ExamRequiredEquipment | UQ_ExamRequiredEquipment | UNIQUE CONSTRAINT | EquipmentID | 2 |
| dbo | ExamRequirement | PK__ExamRequ__7DF11E7DB761A506 | PRIMARY KEY | RequirementID | 1 |
| dbo | ExamRequirement | UQ__ExamRequ__297521A686309400 | UNIQUE CONSTRAINT | ExamID | 1 |
| dbo | Invigilator | PK__Invigila__472FACCFC8C6B1BA | PRIMARY KEY | InvigilatorID | 1 |
| dbo | Invigilator | UQ__Invigila__62F3209409B483BF | UNIQUE CONSTRAINT | InvigilatorCode | 1 |
| dbo | Room | PK__Room__32863919AF0B0E43 | PRIMARY KEY | RoomID | 1 |
| dbo | Room | UQ__Room__4F9D52311B73A84D | UNIQUE CONSTRAINT | RoomCode | 1 |
| dbo | RoomCapacity | PK__RoomCapa__24B1466093216770 | PRIMARY KEY | RoomCapacityID | 1 |
| dbo | RoomCapacity | UQ_RoomCapacity_Room_From | UNIQUE CONSTRAINT | RoomID | 1 |
| dbo | RoomCapacity | UQ_RoomCapacity_Room_From | UNIQUE CONSTRAINT | EffectiveFrom | 2 |
| dbo | RoomClosure | PK__RoomClos__909B66415F27FF34 | PRIMARY KEY | RoomClosureID | 1 |
| dbo | RoomEquipment | PK__RoomEqui__809194EA58B8C458 | PRIMARY KEY | RoomEquipmentID | 1 |
| dbo | RoomEquipment | UQ_RoomEquipment | UNIQUE CONSTRAINT | RoomID | 1 |
| dbo | RoomEquipment | UQ_RoomEquipment | UNIQUE CONSTRAINT | EquipmentID | 2 |
| dbo | RoomEquipment | UQ_RoomEquipment | UNIQUE CONSTRAINT | EffectiveFrom | 3 |
| dbo | ScheduleAssignment | PK__Schedule__32499E57665C4F92 | PRIMARY KEY | AssignmentID | 1 |
| dbo | ScheduleAssignment | UQ_Assignment_ExamRoomRun | UNIQUE CONSTRAINT | ExamID | 1 |
| dbo | ScheduleAssignment | UQ_Assignment_ExamRoomRun | UNIQUE CONSTRAINT | RoomID | 2 |
| dbo | ScheduleAssignment | UQ_Assignment_ExamRoomRun | UNIQUE CONSTRAINT | SchedulingRunID | 3 |
| dbo | ScheduleAssignment | UQ_Assignment_ID_Exam_Run | UNIQUE CONSTRAINT | AssignmentID | 1 |
| dbo | ScheduleAssignment | UQ_Assignment_ID_Exam_Run | UNIQUE CONSTRAINT | ExamID | 2 |
| dbo | ScheduleAssignment | UQ_Assignment_ID_Exam_Run | UNIQUE CONSTRAINT | SchedulingRunID | 3 |
| dbo | ScheduleAssignment | UQ_Assignment_RunCode | UNIQUE CONSTRAINT | AssignmentCode | 1 |
| dbo | ScheduleAssignment | UQ_Assignment_RunCode | UNIQUE CONSTRAINT | SchedulingRunID | 2 |
| dbo | SchedulingException | PK__Scheduli__A21119680B6708D2 | PRIMARY KEY | SchedulingExceptionID | 1 |
| dbo | SchedulingException | UQ_SchedulingException | UNIQUE CONSTRAINT | SchedulingRunID | 1 |
| dbo | SchedulingException | UQ_SchedulingException | UNIQUE CONSTRAINT | ExamID | 2 |
| dbo | SchedulingException | UQ_SchedulingException | UNIQUE CONSTRAINT | ReasonCode | 3 |
| dbo | SchedulingRun | PK__Scheduli__6CBB961DC41974AE | PRIMARY KEY | SchedulingRunID | 1 |
| dbo | SchedulingRun | UQ__Scheduli__4C2D28A870DC37F7 | UNIQUE CONSTRAINT | RunCode | 1 |
| dbo | Student | PK__Student__32C52A7962477B27 | PRIMARY KEY | StudentID | 1 |
| dbo | Student | UQ__Student__1FC886049C1AB2FD | UNIQUE CONSTRAINT | StudentCode | 1 |
| dbo | Student | UQ__Student__A9D10534BB10E1FC | UNIQUE CONSTRAINT | Email | 1 |

## Check Constraints

| schema_name | table_name | constraint_name | definition | is_disabled | is_not_trusted |
|---|---|---|---|---|---|
| dbo | Accommodation | CK_Accommodation_Dates | ([EffectiveTo] IS NULL OR [EffectiveTo]>=[EffectiveFrom]) | False | False |
| dbo | Accommodation | CK_Accommodation_Extension | ([AccommodationType]='EXTENDED_TIME' AND [ExtensionPercentage]>(0) AND [ExtensionPercentage]<=(200) OR [AccommodationType]<>'EXTENDED_TIME' AND [ExtensionPercentage] IS NULL) | False | False |
| dbo | Accommodation | CK_Accommodation_Status | ([AccommodationStatus]='REVOKED' OR [AccommodationStatus]='EXPIRED' OR [AccommodationStatus]='ACTIVE') | False | False |
| dbo | Accommodation | CK_Accommodation_Type | ([AccommodationType]='SPECIAL_EQUIPMENT' OR [AccommodationType]='SEPARATE_ROOM' OR [AccommodationType]='ACCESSIBLE_ROOM' OR [AccommodationType]='EXTENDED_TIME') | False | False |
| dbo | AssignmentEvent | CK_AssignmentEvent_Details | ([EventDetails] IS NULL OR isjson([EventDetails])=(1)) | False | False |
| dbo | AssignmentEvent | CK_AssignmentEvent_Type | ([EventType]='STUDENT_REALLOCATED' OR [EventType]='INVIGILATOR_CHANGED' OR [EventType]='CANCELLED' OR [EventType]='RESCHEDULED' OR [EventType]='CONFIRMED' OR [EventType]='CREATED') | False | False |
| dbo | AssignmentInvigilator | CK_AssignmentInvigilator_Role | ([AssignedRole]='RELIEF' OR [AssignedRole]='ASSISTANT' OR [AssignedRole]='PRIMARY') | False | False |
| dbo | AssignmentInvigilator | CK_AssignmentInvigilator_Status | ([AssignmentStatus]='REMOVED' OR [AssignmentStatus]='ASSIGNED') | False | False |
| dbo | AssignmentStudent | CK_AssignmentStudent_Status | ([AllocationStatus]='REMOVED' OR [AllocationStatus]='ALLOCATED') | False | False |
| dbo | Availability | CK_Availability_Status | ([AvailabilityStatus]='UNAVAILABLE' OR [AvailabilityStatus]='AVAILABLE') | False | False |
| dbo | Availability | CK_Availability_Time | ([AvailableTo]>[AvailableFrom]) | False | False |
| dbo | Course | CK_Course_Credits | ([Credits]>=(1) AND [Credits]<=(10)) | False | False |
| dbo | Course | CK_Course_Status | ([Status]='INACTIVE' OR [Status]='ACTIVE') | False | False |
| dbo | Enrollment | CK_Enrollment_Dates | ([EffectiveTo] IS NULL OR [EffectiveTo]>=[EffectiveFrom]) | False | False |
| dbo | Enrollment | CK_Enrollment_Status | ([EnrollmentStatus]='COMPLETED' OR [EnrollmentStatus]='DROPPED' OR [EnrollmentStatus]='ENROLLED') | False | False |
| dbo | Exam | CK_Exam_Code | ([ExamCode] like 'EXAM-2026-[0-9][0-9][0-9][0-9][0-9][0-9]') | False | False |
| dbo | Exam | CK_Exam_Status | ([ExamStatus]='CANCELLED' OR [ExamStatus]='SCHEDULED' OR [ExamStatus]='READY' OR [ExamStatus]='DRAFT') | False | False |
| dbo | Exam | CK_Exam_Window | ([ExamWindowEnd]>[ExamWindowStart]) | False | False |
| dbo | ExamEnrollment | CK_ExamEnrollment_Status | ([ParticipationStatus]='EXEMPT' OR [ParticipationStatus]='WITHDRAWN' OR [ParticipationStatus]='REGISTERED') | False | False |
| dbo | ExamRequiredEquipment | CK_ExamEquipment_Quantity | ([QuantityRequired]>(0)) | False | False |
| dbo | ExamRequirement | CK_ExamRequirement_Duration | ([DurationMinutes]>=(15) AND [DurationMinutes]<=(600)) | False | False |
| dbo | ExamRequirement | CK_ExamRequirement_Equipment | ([RequiredEquipment] IS NULL OR isjson([RequiredEquipment])=(1)) | False | False |
| dbo | Invigilator | CK_Invigilator_Code | ([InvigilatorCode] like 'INV-[0-9][0-9][0-9][0-9][0-9][0-9]') | False | False |
| dbo | Invigilator | CK_Invigilator_Hours | ([MaxDailyHours]>(0) AND [MaxDailyHours]<=(24)) | False | False |
| dbo | Invigilator | CK_Invigilator_Status | ([Status]='INACTIVE' OR [Status]='ACTIVE') | False | False |
| dbo | Room | CK_Room_Code | ([RoomCode] like 'ROOM-[0-9][0-9][0-9][0-9][0-9][0-9]') | False | False |
| dbo | Room | CK_Room_Floor | ([Floor]>=(0)) | False | False |
| dbo | Room | CK_Room_Type | ([RoomType]='ACCESSIBLE' OR [RoomType]='LAB' OR [RoomType]='STANDARD') | False | False |
| dbo | RoomCapacity | CK_RoomCapacity_Capacity | ([Capacity]>(0)) | False | False |
| dbo | RoomCapacity | CK_RoomCapacity_Dates | ([EffectiveTo] IS NULL OR [EffectiveTo]>=[EffectiveFrom]) | False | False |
| dbo | RoomClosure | CK_RoomClosure_Status | ([ClosureStatus]='COMPLETED' OR [ClosureStatus]='CANCELLED' OR [ClosureStatus]='ACTIVE') | False | False |
| dbo | RoomClosure | CK_RoomClosure_Time | ([ClosureEnd]>[ClosureStart]) | False | False |
| dbo | RoomEquipment | CK_RoomEquipment_Dates | ([EffectiveTo] IS NULL OR [EffectiveTo]>=[EffectiveFrom]) | False | False |
| dbo | RoomEquipment | CK_RoomEquipment_Quantity | ([Quantity]>(0)) | False | False |
| dbo | ScheduleAssignment | CK_Assignment_Capacity | ([AssignedCapacity]>(0)) | False | False |
| dbo | ScheduleAssignment | CK_Assignment_Status | ([AssignmentStatus]='CANCELLED' OR [AssignmentStatus]='CONFIRMED' OR [AssignmentStatus]='PROPOSED') | False | False |
| dbo | ScheduleAssignment | CK_Assignment_Time | ([EndTime]>[StartTime]) | False | False |
| dbo | SchedulingException | CK_Exception_JSON | ([ExceptionDetails] IS NULL OR isjson([ExceptionDetails])=(1)) | False | False |
| dbo | SchedulingException | CK_Exception_Reason | ([ReasonCode]='OTHER' OR [ReasonCode]='INVALID_REQUIREMENT' OR [ReasonCode]='NO_ELIGIBLE_STUDENTS' OR [ReasonCode]='NO_VALID_TIMESLOT' OR [ReasonCode]='ACCOMMODATION_CONFLICT' OR [ReasonCode]='STUDENT_CONFLICT' OR [ReasonCode]='NO_INVIGILATOR' OR [ReasonCode]='ROOM_CLOSED' OR [ReasonCode]='NO_EQUIPMENT' OR [ReasonCode]='NO_ROOM_CAPACITY') | False | False |
| dbo | SchedulingException | CK_Exception_Resolution | ([ExceptionStatus]='OPEN' AND [ResolvedAt] IS NULL OR [ExceptionStatus]<>'OPEN' AND [ResolvedAt] IS NOT NULL) | False | False |
| dbo | SchedulingException | CK_Exception_Severity | ([Severity]='CRITICAL' OR [Severity]='HIGH' OR [Severity]='MEDIUM' OR [Severity]='LOW') | False | False |
| dbo | SchedulingException | CK_Exception_Status | ([ExceptionStatus]='WAIVED' OR [ExceptionStatus]='RESOLVED' OR [ExceptionStatus]='OPEN') | False | False |
| dbo | SchedulingRun | CK_SchedulingRun_Config | ([Configuration] IS NULL OR isjson([Configuration])=(1)) | False | False |
| dbo | SchedulingRun | CK_SchedulingRun_Dates | ([CompletedAt] IS NULL OR [CompletedAt]>=[StartedAt]) | False | False |
| dbo | SchedulingRun | CK_SchedulingRun_Status | ([RunStatus]='CANCELLED' OR [RunStatus]='FAILED' OR [RunStatus]='COMPLETED' OR [RunStatus]='STARTED') | False | False |
| dbo | Student | CK_Student_Code | ([StudentCode] like 'STU-[0-9][0-9][0-9][0-9][0-9][0-9]') | False | False |
| dbo | Student | CK_Student_Status | ([Status]='GRADUATED' OR [Status]='INACTIVE' OR [Status]='ACTIVE') | False | False |
