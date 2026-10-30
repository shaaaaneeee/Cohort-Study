# The study assistant: architecture

The assistant lets a user describe a cohort study in plain words instead of
setting every control in the builder. It is a thin layer in front of the
existing engine: the language model translates the question into a study
definition, and everything after that is the same deterministic code the
builder uses.

```
 user ──question──▶ web/chat.js ──POST /api/chat──▶ assistant.converse()
                                                       │   ▲
                                         prompt + tools │   │ tool results
                                                       ▼   │
                                                  LLMClient (llm.py)
                                                       │
                                     propose_study(StudySpec as JSON)
                                                       │
                                     StudySpec.model_validate  (features.py)
                                     validate_study            (validator.py)
                                                       │
                                     errors ─▶ back to the model to fix
                                     none   ─▶ draft returned to the page
                                                       │
 user reviews and edits it in steps 1-2 ◀── "Review in builder"
                                                       │
                           Run analysis ─▶ POST /api/analysis (unchanged)
                                           repository ─▶ SQL ─▶ matching ─▶ model
```

## Who decides what

| Decision | Made by |
|---|---|
| Reading the question, choosing features, windows, filters and defaults | The language model, as a proposal |
| Whether a study is well-formed (types, names, window order) | `StudySpec` schema, `features.py` |
| Whether it is a sound design (look-ahead, one outcome, outcome reused as covariate, granularity) | `validate_study`, `validator.py` |
| Whether the data can answer it (exposures, sources, values) | The prompt lists only what the mapping config has; the validator checks every name and value |
| The comparison group and matching | Fixed by the engine (`sql.py`, `matching.py`); not something the model can change |
| Which statistical model to fit | `implied_model`, `models.py`, from the outcome's aggregation |
| Every number in the result | `run_analysis`, `analysis.py`. The model never sees the data or the result |
| Running the study at all | The user, by clicking Run analysis after reviewing the draft |

The model can only make a proposal. If it proposes something unsound, the
proposal is refused with the same issues the builder would show, and the model
has to fix it. Up to eight model calls are allowed per user turn
(`MAX_STEPS`), so a model that cannot produce a valid study ends the turn
rather than looping.

## The pieces

- `cohort_studio/llm.py`: the `LLMClient` interface (one call: system prompt,
  messages and tools in; text and tool calls out). `AnthropicClient` uses Claude
  through the `anthropic` SDK. `ScriptedClient` replays canned replies, for
  tests and for demos without an API key. Another provider would be one more
  class with the same `step` method.
- `cohort_studio/assistant.py`: `converse()`, one user turn. It builds the
  prompt from the same catalogue as `/api/metadata`, including dimension
  values, and runs the tool loop. It returns the status (`ready`, `asking` or
  `unsupported`), the reply, the draft and its issues.
- `cohort_studio/api.py`: `POST /api/chat`. The server stores nothing between
  turns. The page sends the whole visible conversation and the current draft
  each time.
- `web/chat.js`: the Ask tab. "Review in builder" loads the draft into the
  builder through the same `setStudy` that opening a study file uses.

## Tools the model has

| Tool | What happens |
|---|---|
| `propose_study` | The whole study as JSON. It is parsed and validated, and the issues go back to the model. If there are no errors it becomes the draft |
| `list_values` | All values of one dimension, for dimensions with more values than the prompt shows |
| `ask_user` | Ends the turn with up to four questions (scenario B) |
| `report_unsupported` | Ends the turn saying what the data lacks and what is possible instead (scenario C) |

## Demonstration scenarios

`examples/assistant/` holds one scripted conversation per scenario in the
proposal. `tests/test_assistant.py` replays them, so they keep working as the
code changes.

| Scenario | Script | Outcome |
|---|---|---|
| A: complete request | `scenario_a_complete.json` | A ready study in one turn |
| B: ambiguous request | `scenario_b_ambiguous.json` | Questions first, then a ready study |
| C: unsupported request | `scenario_c_unsupported.json` | An explanation and the closest possible study, no draft |

## Extending it

- **New data:** add sources or exposures to `config/mapping.yaml`. The prompt
  is built from the mapping, so the assistant offers them with no code change.
- **New design rules:** add them to `validator.py`. The assistant is held to
  them automatically.
- **Another model provider:** write a class with `step()` in `llm.py` and add
  it to `client_from_env`.
- **Not done yet:** authentication (the server listens on localhost only),
  streaming replies, and an evaluation set of real questions to measure how
  often the drafted study matches what an analyst would have built.
