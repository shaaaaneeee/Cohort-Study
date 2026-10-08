-- Tables for the local DuckDB database. The engine never reads these names
-- directly; config/mapping.yaml binds them to the roles it understands.
--
-- Patient and episode IDs are text: they are labels, not numbers, and text
-- keeps leading zeros that a numeric type would drop.

CREATE TABLE IF NOT EXISTS master_patient (
    patient_id        VARCHAR PRIMARY KEY,
    date_of_birth     DATE NOT NULL,
    ethnicity         VARCHAR,
    gender            VARCHAR,
    residence_status  VARCHAR
);

-- Only the year of diagnosis is known, so a diagnosis cannot be placed
-- before or after an index date in the same year.
CREATE TABLE IF NOT EXISTS chronic_conditions (
    patient_id      VARCHAR NOT NULL,
    condition_name  VARCHAR NOT NULL,
    diagnosis_year  INTEGER NOT NULL
);

-- Triage level is text because it is a category (P1 to P4), not a quantity.
CREATE TABLE IF NOT EXISTS ed_episodes (
    patient_id       VARCHAR NOT NULL,
    episode_id       VARCHAR PRIMARY KEY,
    attendance_date  DATE NOT NULL,
    mode_of_arrival  VARCHAR,
    triage_level     VARCHAR,
    disposition      VARCHAR,
    los_hours        DOUBLE
);

-- No primary key: a patient who left and re-enrolled has two rows. The
-- cohort uses the first enrolment.
CREATE TABLE IF NOT EXISTS program_members (
    patient_id       VARCHAR NOT NULL,
    enrollment_date  DATE NOT NULL
);
