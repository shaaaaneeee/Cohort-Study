-- Tables of the cohort dataset, in PostgreSQL.
--
-- Names are unqualified: whoever applies this file sets search_path to the
-- target schema first (the seed command and docker/postgres-init.sh do), so the
-- same file creates the tables in "cohort" for the app and in throwaway
-- schemas for the tests. config/mapping.yaml binds these tables and columns
-- to the roles the engine uses; the engine never names them itself.
--
-- Patient and episode IDs are text: they are labels, not numbers, and text
-- keeps leading zeros that a numeric type would drop.

CREATE TABLE IF NOT EXISTS master_patient (
    patient_id        TEXT PRIMARY KEY,
    date_of_birth     DATE NOT NULL,
    ethnicity         TEXT,
    gender            TEXT,
    residence_status  TEXT
);

-- Only the year of diagnosis is known, so a diagnosis cannot be placed
-- before or after an index date in the same year.
CREATE TABLE IF NOT EXISTS chronic_conditions (
    patient_id      TEXT NOT NULL,
    condition_name  TEXT NOT NULL,
    diagnosis_year  INTEGER NOT NULL
);

-- Triage level is text because it is a category (P1 to P4), not a quantity.
CREATE TABLE IF NOT EXISTS ed_episodes (
    patient_id       TEXT NOT NULL,
    episode_id       TEXT PRIMARY KEY,
    attendance_date  DATE NOT NULL,
    mode_of_arrival  TEXT,
    triage_level     TEXT,
    disposition      TEXT,
    los_hours        DOUBLE PRECISION
);

-- No primary key: a patient who left and re-enrolled has two rows. The
-- cohort uses the first enrolment.
CREATE TABLE IF NOT EXISTS program_members (
    patient_id       TEXT NOT NULL,
    enrollment_date  DATE NOT NULL
);

-- Every feature joins an event table to the cohort on patient_id and filters
-- by date.
CREATE INDEX IF NOT EXISTS chronic_conditions_patient ON chronic_conditions (patient_id);
CREATE INDEX IF NOT EXISTS ed_episodes_patient_date ON ed_episodes (patient_id, attendance_date);
CREATE INDEX IF NOT EXISTS program_members_patient ON program_members (patient_id);
