"""The study tools, served to AI agents over MCP.

An assistant such as Databricks Genie Code connects to /mcp and can call:

    describe_data   what the data holds: exposures, sources, filters, outcomes
    list_values     the allowed values of one filter
    review_study    what a draft still leaves open, as questions with options
    check_study     validate a study, with patient counts, a plain-English
                    summary and a confirmation code
    run_study       run the full analysis (matching + outcome model), only
                    with the confirmation code of the study the user confirmed

Every tool goes through StudyService, so every agent gets the same tested
method and the same checks. It never sends or receives SQL, and never sees
patient-level rows: only counts and results.

In a Databricks App the platform signs in every caller. Elsewhere, set
MCP_TOKEN and every request must carry "Authorization: Bearer <MCP_TOKEN>".
"""

import hmac
import logging
from typing import Any

from pydantic import ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from app import __version__
from app.analysis.validation import issues_from_pydantic
from app.core.exceptions import AnalysisError, DataSourceError, StudyError
from app.core.jsonsafe import clean
from app.mcp_protocol import McpServer
from app.schemas.study import StudySpec
from app.services.clarify import confirmation_code as study_code
from app.services.clarify import review, summary
from app.services.study import StudyService

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Tools for observational cohort studies on the Cohort Studio data: does an
exposure (e.g. a programme) change an outcome (e.g. ED attendances,
admissions)? Use these tools for ANY such question, including subgroups
("for diabetics", "for the elderly") and outcome variants (any visit, time to
first visit, admissions), instead of querying the tables yourself. A
before/after or unmatched members-vs-non-members comparison is biased because
sicker patients enrol; these tools match and model with a fixed, tested method.
If the data cannot answer the question (e.g. no deaths data), say so.
If the user asks for an unmatched or "raw" members-vs-non-members comparison,
do not compute one yourself: explain that it would mostly show who enrols,
not what the programme does, and offer the matched study with these tools.

Always follow these steps, in order:
1. describe_data, to learn the data and the study format (StudySpec).
2. review_study with your draft (it may be partial). It lists what is still
   open: outcome, follow-up, covariates, population.
3. Ask the user every open question, showing its options and default. Never
   choose for the user and never assume; wait for their answers. Apply each
   answer to the draft as the option says. If the user says to use the
   defaults, first tell them what each default is and any "why" warning the
   question carries (e.g. that matching without prior use can make the
   programme look harmful), and offer to change them, before running.
4. check_study. Fix any errors. Show the user its summary and the patient
   counts, and ask them to confirm.
5. Only after the user confirms, run_study with the same study and the
   confirmation_code from check_study.
Report the estimate, its 95% CI and p-value, and the warnings, in plain words."""


def _study(study: dict[str, Any]) -> StudySpec | dict[str, Any]:
    """The study, or an error answer the agent can act on."""
    try:
        return StudySpec.model_validate(study)
    except ValidationError as e:
        return {"ok": False, "issues": issues_from_pydantic(e.errors())}


def _failure(e: Exception) -> dict[str, Any]:
    if isinstance(e, StudyError):
        return {"ok": False, "issues": e.issues}
    if isinstance(e, AnalysisError):
        return {"ok": False, "error": str(e)}
    if isinstance(e, DataSourceError):
        # Our own messages (which part failed), never the driver's details.
        return {"ok": False, "error": f"{e} Try again later."}
    raise e


STUDY = {"type": "object", "additionalProperties": True, "description": "A StudySpec, as JSON"}


def build_mcp(service: StudyService) -> McpServer:
    mcp = McpServer("cohort-studio", __version__, INSTRUCTIONS)

    @mcp.tool()
    def describe_data() -> Any:
        """START HERE for any question on whether a programme affects patient outcomes.

        Use the Cohort Studio tools, not your own SQL, for questions like "does
        Programme A help patients?", "does it reduce ED visits / admissions?",
        "is it worth it for the elderly / diabetics?", "does it delay the first
        ED visit?". A before/after or unmatched comparison of members vs
        non-members is biased (sicker patients enrol); these tools match each
        member to a similar non-member and fit the right model, with a fixed,
        tested method. Even when asked for "no matching", don't query the
        tables yourself: explain the bias and offer the matched study.

        Step 1 of 5: describe_data → review_study → ask the user → check_study
        → (user confirms) → run_study. Returns the exposures, outcome sources,
        filters and the study schema ('study_schema').
        """
        try:
            return clean({**service.metadata(), "study_schema": StudySpec.model_json_schema()})
        except Exception as e:
            return _failure(e)

    @mcp.tool({"source": {"type": "string"}, "dimension": {"type": "string"}})
    def list_values(source: str, dimension: str) -> dict[str, Any]:
        """Every allowed value of one filter, e.g. triage levels or condition names.

        Use before filtering on a value, to spell it as the data does.
        Example: source 'ed_episodes', dimension 'triage_level'.
        """
        try:
            return {"ok": True, "values": service.dimension_values(source, dimension)}
        except LookupError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return _failure(e)

    @mcp.tool({"study": STUDY})
    def review_study(study: dict[str, Any]) -> Any:
        """List the study choices still open, as questions to ask the user before analysing.

        Step 2 of the Cohort Studio workflow, after describe_data. Pass the
        draft study, even partial or {}. Returns questions (outcome, follow-up,
        what to match on, population), each with options and a default. Ask the
        user every question and wait for the answers; never choose for them.
        Apply an answer as its option says: "set" fields, "add_feature", or
        "outcome_window".
        """
        try:
            meta = service.metadata()
            try:
                conditions = service.dimension_values("condition", "condition_name")
            except LookupError:
                conditions = []
            return clean({"ok": True, **review(study or {}, meta, conditions)})
        except Exception as e:
            return _failure(e)

    @mcp.tool({"study": STUDY})
    def check_study(study: dict[str, Any]) -> Any:
        """Check a study and get the summary the user must confirm before it runs.

        Step 4 of the Cohort Studio workflow. Returns design errors to fix,
        patient counts after each eligibility step, the outcome model the study
        implies, a plain-English summary to show the user, and the
        confirmation_code run_study needs once the user says yes.
        """
        spec = _study(study)
        if isinstance(spec, dict):
            return spec
        try:
            checked = service.check(spec)
            if any(i["level"] == "error" for i in checked["issues"]):
                return clean({"ok": False, **checked})
            return clean(
                {
                    "ok": True,
                    **checked,
                    "attrition": service.attrition(spec),
                    "summary": summary(spec, service.metadata()),
                    "confirmation_code": study_code(spec),
                    "next": "Show the user the summary and counts and ask them to confirm. "
                    "Only then call run_study with this confirmation_code.",
                }
            )
        except Exception as e:
            return _failure(e)

    @mcp.tool({"study": STUDY, "confirmation_code": {"type": "string"}})
    def run_study(study: dict[str, Any], confirmation_code: str) -> Any:
        """Run the confirmed study: matching, balance check, outcome model, effect estimate.

        Step 5 of the Cohort Studio workflow, only after the user has confirmed
        the summary from check_study: pass that study and its confirmation_code.
        Returns the effect (rate, odds or hazard ratio) with its 95% CI and
        p-value, cohort sizes, covariate balance, warnings and a plain-English
        interpretation. Report these to the user; do not recompute them with SQL.
        """
        spec = _study(study)
        if isinstance(spec, dict):
            return spec
        if confirmation_code != study_code(spec):
            return {
                "ok": False,
                "error": "This study has not been confirmed. Call check_study, show the user "
                "its summary, ask them to confirm, then pass its confirmation_code. If the "
                "study changed after check_study, check it again.",
            }
        try:
            log.info("mcp run_study")
            return clean({"ok": True, **service.analysis(spec)})
        except Exception as e:
            return _failure(e)

    return mcp


class BearerAuth:
    """Rejects any request without "Authorization: Bearer <token>"."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(sent, self.expected):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error":"A valid bearer token is required."}',
                    }
                )
                return
        await self.app(scope, receive, send)


class TrailingSlash:
    """Serves POST /mcp as /mcp/ instead of redirecting.

    A redirect behind a proxy can point at the wrong scheme or host, and some
    clients drop the Authorization header when they follow it.
    """

    def __init__(self, app: ASGIApp, path: str = "/mcp"):
        self.app = app
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self.path:
            scope = {**scope, "path": self.path + "/", "raw_path": (self.path + "/").encode()}
        await self.app(scope, receive, send)


def mcp_asgi_app(mcp: McpServer, token: str | None) -> ASGIApp:
    """The MCP endpoint as an app to mount at /mcp.

    Stateless, with JSON responses, so it runs behind any load balancer. The
    bearer token (or the platform's sign-in, when token is None) protects it.
    """
    return mcp if token is None else BearerAuth(mcp, token)
