"""Helpers for tests that need a real database."""
from pathlib import Path

import duckdb
import pandas as pd

from cohort_studio import loader, synthetic
from cohort_studio.mapping import Mapping
from cohort_studio.repository import SqlRepository, open_repository


def build_database(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Write tables to CSV and load them with the real loader, as a user would."""
    csv_dir = path.parent / f"{path.stem}_csv"
    con = duckdb.connect(str(path))
    loader.create_tables(con)
    for csv_path in synthetic.write_csv(tables, csv_dir):
        loader.load_file(con, csv_path)
    con.close()


def repository_for(path: Path, mapping: Mapping) -> SqlRepository:
    """A repository on the database at path, through the same code the app uses."""
    mapping = mapping.model_copy(deep=True)
    mapping.backend.database = str(path)
    return open_repository(mapping)


def hand_made_tables() -> dict[str, pd.DataFrame]:
    """Four patients, a member with no patient record, and twelve ED visits.

    Every treated patient enrols on 15 June 2021. Day numbers in the
    comments are days from that date.
    """
    patients = pd.DataFrame([
        # T1 turns 61 the day after the index date, so is still 60.
        ("T1", "1960-06-16", "Chinese", "F", "Citizen"),
        # T2 turns 50 on the index date. T2 has no ED visits and no conditions.
        ("T2", "1971-06-15", "Malay", "M", "Citizen"),
        ("C1", "1950-01-01", "Chinese", "F", "PR"),
        # C2 is 17 at the index date.
        ("C2", "2004-01-01", "Indian", "M", "Citizen"),
    ], columns=["patient_id", "date_of_birth", "ethnicity", "gender", "residence_status"])
    members = pd.DataFrame([
        ("T1", "2021-06-15"),
        ("T1", "2022-03-01"),   # re-enrolment; the first enrolment is the index
        ("T2", "2021-06-15"),
        ("T9", "2021-06-15"),   # no patient record
    ], columns=["patient_id", "enrollment_date"])
    episodes = pd.DataFrame([
        ("T1", "E01", "2020-06-14", "SCDF", "P2", "Discharged", 1.0),          # day -366
        ("T1", "E02", "2020-06-15", "SCDF", "P2", "Admitted", 2.0),            # day -365
        ("T1", "E03", "2021-06-14", "Own transport", "P3", "Discharged", 4.0), # day -1
        ("T1", "E04", "2021-06-15", "SCDF", "P1", "Admitted", 9.0),            # day 0
        ("T1", "E05", "2021-06-16", "SCDF", "P2", "Admitted", 5.0),            # day 1
        ("T1", "E06", "2021-06-16", "Own transport", "P3", "Discharged", 3.0), # day 1 again
        ("T1", "E07", "2022-06-15", "Own transport", "P4", "Discharged", 1.5), # day 365
        ("T1", "E08", "2022-06-16", "Own transport", "P4", "Discharged", 2.5), # day 366
        ("C1", "E09", "2021-01-01", "SCDF", "P3", "Discharged", 6.0),          # day -165
        ("C1", "E10", "2021-05-31", "Own transport", "P3", "Discharged", 3.0), # day -15, May
        ("C1", "E11", "2021-06-01", "Own transport", "P3", "Discharged", 3.0), # day -14, June
        ("C2", "E12", "2021-03-01", "Own transport", "P3", "Discharged", 2.0), # day -106
    ], columns=["patient_id", "episode_id", "attendance_date", "mode_of_arrival",
                "triage_level", "disposition", "los_hours"])
    conditions = pd.DataFrame([
        ("T1", "diabetes", 2020),   # the year before the index year
        ("T1", "copd", 2021),       # the index year: may be after the index date
        ("C1", "diabetes", 2021),
        ("C1", "asthma", 2015),
    ], columns=["patient_id", "condition_name", "diagnosis_year"])
    return {"master_patient": patients, "program_members": members,
            "ed_episodes": episodes, "chronic_conditions": conditions}
