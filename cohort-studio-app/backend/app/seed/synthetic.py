"""Synthetic data with a known programme effect and a known selection bias.

The statistics are tested by running them on data where the right answer is
known in advance. This module produces the four tables of ddl.sql for a
made-up population in which:

  - ED attendance rate rises with age and with chronic conditions.
  - Older patients and those with diabetes, COPD, heart failure or CKD are
    more likely to enrol in the programme. Those patients also attend ED
    more, so a crude comparison makes the programme look harmful. This is
    the planted selection bias the analysis has to remove.
  - After enrolment a member's ED attendance rate is multiplied by
    RATE_RATIO. This is the planted effect the analysis has to recover. It
    applies equally to every kind of attendance, so the rate ratio for, say,
    SCDF-conveyed attendances is RATE_RATIO too.
  - Every patient's rate is also multiplied by an unmeasured frailty (gamma,
    mean 1). It makes the counts overdispersed, as real ED counts are. It is
    independent of enrolment, so it does not confound. The dispersion a
    model sees grows with the mean count: with a 12-month window and the
    default variance it is only about 1.2, so testing the switch to negative
    binomial needs a longer window or a larger frailty_variance.

What this data does not test: enrolment depends only on things the analysis
measures exactly at baseline. Ages are fixed by birth date. All diagnoses
are made before 2018, before any index date, so "diagnosed before the index
year" and "before the index date" coincide (the year-granularity rule is
tested on hand-built data instead). Real programmes often enrol people after
a run of ED visits. With controls drawn from people who never enrolled, that
kind of selection leaves bias that adjusting for prior ED use does not fully
remove, and this data does not reproduce it.

    python -m cohort_studio.synthetic data/synthetic --patients 20000 --seed 7
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA_START = np.datetime64("2018-01-01")
DATA_END = np.datetime64("2025-12-31")
# Enrolment runs from 2020 to 2023, leaving at least two years of data
# before and after every enrolment for look-back and follow-up windows.
ENROL_START = np.datetime64("2020-01-01")
ENROL_END = np.datetime64("2023-12-31")
# Age effects use age on this date. The analysis uses age at index date,
# which differs by a year or two; the error that adds is negligible.
AGE_REFERENCE = np.datetime64("2022-01-01")

# The planted effect: ED attendance rate after enrolment / rate before.
RATE_RATIO = 0.70
FRAILTY_VARIANCE = 0.5

# ED attendances per year at age 60 with no chronic conditions.
ED_BASE_RATE = 0.25
ED_LOG_RATE_RATIO_PER_DECADE = 0.20
ENROL_BASE_LOG_ODDS = -3.2
ENROL_LOG_ODDS_RATIO_PER_DECADE = 0.40
# Each condition's prevalence rises with age by this log odds ratio per decade.
PREVALENCE_LOG_ODDS_RATIO_PER_DECADE = 0.40

# condition: (prevalence at age 60,
#             log rate ratio on ED attendance,
#             log odds ratio on enrolment)
CONDITIONS = {
    "diabetes": (0.15, 0.40, 1.00),
    "hypertension": (0.30, 0.10, 0.20),
    "copd": (0.07, 0.70, 1.20),
    "heart_failure": (0.05, 0.80, 1.20),
    "ckd": (0.06, 0.50, 0.80),
    "depression": (0.10, 0.30, 0.00),
    "asthma": (0.08, 0.20, 0.00),
}

ETHNICITY = {"Chinese": 0.74, "Malay": 0.14, "Indian": 0.09, "Others": 0.03}
RESIDENCE = {"Citizen": 0.85, "PR": 0.10, "Foreigner": 0.05}
TRIAGE = {"P1": 0.05, "P2": 0.30, "P3": 0.55, "P4": 0.10}
# Chance of admission by triage level.
ADMITTED = {"P1": 0.70, "P2": 0.45, "P3": 0.20, "P4": 0.05}


def generate(
    patients: int = 20000,
    seed: int = 7,
    rate_ratio: float = RATE_RATIO,
    frailty_variance: float = FRAILTY_VARIANCE,
) -> dict[str, pd.DataFrame]:
    """Return the four tables as DataFrames, keyed by table name."""
    rng = np.random.default_rng(seed)
    n = patients

    # ------------------------------------------------------------ people
    birth = np.datetime64("1935-01-01") + rng.integers(0, 365 * 66, n).astype("timedelta64[D]")
    age = (AGE_REFERENCE - birth).astype(int) / 365.25
    decades = (age - 60) / 10
    master_patient = pd.DataFrame(
        {
            "patient_id": [f"P{i:06d}" for i in range(1, n + 1)],
            "date_of_birth": birth,
            "ethnicity": rng.choice(list(ETHNICITY), n, p=list(ETHNICITY.values())),
            "gender": rng.choice(["F", "M"], n),
            "residence_status": rng.choice(list(RESIDENCE), n, p=list(RESIDENCE.values())),
        }
    )

    # -------------------------------------------------------- conditions
    log_rate = np.log(ED_BASE_RATE) + ED_LOG_RATE_RATIO_PER_DECADE * decades
    log_odds_enrol = ENROL_BASE_LOG_ODDS + ENROL_LOG_ODDS_RATIO_PER_DECADE * decades
    condition_rows = []
    for condition, (prevalence, log_rr, log_or) in CONDITIONS.items():
        log_odds = (
            np.log(prevalence / (1 - prevalence)) + PREVALENCE_LOG_ODDS_RATIO_PER_DECADE * decades
        )
        has = rng.random(n) < 1 / (1 + np.exp(-log_odds))
        log_rate = log_rate + log_rr * has
        log_odds_enrol = log_odds_enrol + log_or * has
        years = rng.integers(1995, 2018, n)
        for i in np.flatnonzero(has):
            condition_rows.append((master_patient.patient_id[i], condition, int(years[i])))
    chronic_conditions = pd.DataFrame(
        condition_rows, columns=["patient_id", "condition_name", "diagnosis_year"]
    )

    # --------------------------------------------------------- enrolment
    enrolled = rng.random(n) < 1 / (1 + np.exp(-log_odds_enrol))
    enrol_days = int((ENROL_END - ENROL_START).astype(int)) + 1
    enrol_date = ENROL_START + rng.integers(0, enrol_days, n).astype("timedelta64[D]")
    program_members = pd.DataFrame(
        {
            "patient_id": master_patient.patient_id[enrolled].to_numpy(),
            "enrollment_date": enrol_date[enrolled],
        }
    )

    # -------------------------------------------------------- ED episodes
    if frailty_variance > 0:
        frailty = rng.gamma(1 / frailty_variance, frailty_variance, n)
    else:
        frailty = np.ones(n)
    rate = np.exp(log_rate) * frailty

    # Two stretches of time per patient. Before: from the start of the data
    # to the enrolment date (inclusive), or to the end of the data for
    # patients who never enrol. After: from the day after enrolment to the
    # end of the data, at the reduced rate.
    before_end = np.where(enrolled, enrol_date, DATA_END)
    stretches = [
        (np.full(n, DATA_START), before_end, rate),
        (
            before_end + np.timedelta64(1, "D"),
            np.where(enrolled, DATA_END, before_end),
            rate * rate_ratio,
        ),
    ]
    who_parts = []
    when_parts = []
    for start, end, stretch_rate in stretches:
        days = np.maximum((end - start).astype(int) + 1, 0)
        counts = rng.poisson(stretch_rate * days / 365.25)
        idx = np.repeat(np.arange(n), counts)
        offsets = (rng.random(len(idx)) * days[idx]).astype(int)
        who_parts.append(idx)
        when_parts.append(start[idx] + offsets.astype("timedelta64[D]"))
    who = np.concatenate(who_parts)
    when = np.concatenate(when_parts)
    order = np.lexsort((when, who))
    who = who[order]
    when = when[order]
    m = len(who)

    # Older patients are more often brought by SCDF ambulance.
    p_scdf = np.clip(0.15 + 0.10 * decades[who], 0.05, 0.60)
    scdf = rng.random(m) < p_scdf
    other = rng.choice(["Own transport", "Private ambulance"], m, p=[0.85, 0.15])
    triage = rng.choice(list(TRIAGE), m, p=list(TRIAGE.values()))
    p_admit = pd.Series(triage).map(ADMITTED).to_numpy()
    admitted = rng.random(m) < p_admit
    left = (~admitted) & (rng.random(m) < 0.04)
    disposition = np.where(
        admitted, "Admitted", np.where(left, "Left without being seen", "Discharged")
    )
    los = rng.lognormal(np.log(3.0), 0.5, m) + admitted * rng.lognormal(np.log(6.0), 0.4, m)

    ed_episodes = pd.DataFrame(
        {
            "patient_id": master_patient.patient_id.to_numpy()[who],
            "episode_id": [f"E{k:07d}" for k in range(1, m + 1)],
            "attendance_date": when,
            "mode_of_arrival": np.where(scdf, "SCDF", other),
            "triage_level": triage,
            "disposition": disposition,
            "los_hours": np.round(los, 1),
        }
    )

    return {
        "master_patient": master_patient,
        "chronic_conditions": chronic_conditions,
        "ed_episodes": ed_episodes,
        "program_members": program_members,
    }


def write_csv(tables: dict[str, pd.DataFrame], out_dir: str | Path) -> list[Path]:
    """Write each table to <out_dir>/<table>.csv, ready for the loader."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for table, frame in tables.items():
        path = out_dir / f"{table}.csv"
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Write synthetic CSV files with a known effect.")
    parser.add_argument("out_dir")
    parser.add_argument("--patients", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rate-ratio", type=float, default=RATE_RATIO)
    parser.add_argument("--frailty-variance", type=float, default=FRAILTY_VARIANCE)
    args = parser.parse_args()

    tables = generate(args.patients, args.seed, args.rate_ratio, args.frailty_variance)
    for path in write_csv(tables, args.out_dir):
        print(f"{path}: {len(tables[path.stem])} rows")
    print(f"Planted rate ratio after enrolment: {args.rate_ratio}")


if __name__ == "__main__":
    main()
