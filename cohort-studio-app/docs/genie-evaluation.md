# Genie One evaluation: does it use the study tools properly?

**Result (26 Nov 2026), all 10 questions:** after three changes to the server, Genie One answers
programme questions through the Cohort Studio tools, asks before assuming,
confirms before running, and refuses what the data cannot answer. Before them
it ignored the tools for every question and reported biased before/after
comparisons as findings, e.g. "Yes, Programme A helps (22% fewer ED visits)"
where the matched study gives a rate ratio of 0.97 (no effect).

Setup: Genie One with the `mcp_cohort_study` connector (Unity Gateway), the
synthetic data (2,000 patients, seed 7), one question per new chat unless
noted.

## Before and after

| # | Question | Before (connector on, no changes) | After the changes |
|---|---|---|---|
| 1 | Does Programme A help patients? | Own SQL, before/after: "Yes, 22% fewer visits" | Asked 4 questions, confirmed, ran: **RR 0.97 (0.65–1.46), p = 0.90**; matches the reference |
| 2 | Does Programme A reduce ED visits for diabetics? | Own SQL, before/after: "Yes, 15.9% fewer" | Took "diabetics" as the population, asked the rest: 47 members, **RR 1.17 (0.60–2.29), p = 0.65**, small-sample warning |
| 3 | Is Programme A worth it for the elderly? | Own SQL, unmatched: "Yes, worth it (28% fewer)" | Took "elderly" as 65+ without asking, asked the rest: 86 vs 86 matched, **RR 1.15 (0.74–1.80), p = 0.53**, "not worth it" for ED visits |
| 4 | Do Programme A members get admitted less? | Own SQL, before/after + chi-square: "no evidence" | Checked "Admitted" exists, filtered on it, asked 4 questions: **RR 1.43 (0.67–3.08), p = 0.36**, low-events warning |
| 5 | Does Programme A delay the first ED visit? | Own SQL, unmatched survival curves | Cox model: **HR 0.91 (0.58–1.42), p = 0.68**, proportional hazards met (asked in a shared chat, so it reused earlier answers) |
| 6 | Are members less likely to have any ED visit in 2 years? | Not asked | Inferred yes/no and 24 months from the wording, asked only matching and population: **OR 1.49 (0.90–2.49), p = 0.12** |
| 7 | Does Programme A reduce serious (P1/P2) ED visits? | Not asked | Applied the P1/P2 filter; chose 12 months follow-up itself, asked matching and population: **RR 1.22 (0.65–2.29), p = 0.53** |
| 8 | Does Programme A reduce deaths? | Not asked | Said there is no mortality data and listed what is available |
| 9 | Does Programme A help patients? Just run it with the defaults, I don't care about the details. | Not asked | Ran straight away on the defaults and stated them after: **RR 1.11 (0.70–1.76), p = 0.66**. Did not warn that the defaults leave out prior ED use, which changes the answer (0.97 with it) |
| 10 | Compare members vs non-members, no matching | Not asked | Explained the selection bias, ran nothing, offered the matched study |

"Own SQL" means Genie queried the tables directly instead of calling the tools.

## What changed

| Change | Why | Effect |
|---|---|---|
| Tool descriptions: `describe_data` says START HERE and lists example questions; each tool names its step | Genie One answered with its own SQL unless told to use the tools | Tools used for every question |
| Condition filter looks back over all earlier years, not 5 | "Diabetics" kept 3 of 47 members | 47 members found |
| Instructions: never compute an unmatched comparison; explain and offer the matched study | Asked for "no matching", Genie wrote SQL comparing 12 months with 7 years and reported a spurious 80% drop | Explains and offers the matched study |

## Notes

- Genie sometimes describes the default matching as including prior ED use
  (the recommendation, not the default) and picks a 12-month follow-up when
  the question names no period; explicit answers avoid both.
- Genie fills a population from the question's wording ("elderly" → 65+) without
  asking; reasonable here, but worth checking in the summary it shows.
- Several questions in one message make Genie choose the answers itself
  (the defaults), so test the asking step with one question per new chat.
  Without prior ED use in the matching, question 1 gives RR 1.11 instead of 0.97.
- The descriptions and instructions guide Genie; they do not force it. A
  Genie Agent whose instructions require the tools is the stricter option.
- Run results are deterministic: the same study and seed give the same numbers.
