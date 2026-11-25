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

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from app.analysis.validation import issues_from_pydantic
from app.core.exceptions import AnalysisError, DataSourceError, StudyError
from app.core.jsonsafe import clean
from app.schemas.study import StudySpec
from app.services.clarify import confirmation_code as study_code
from app.services.clarify import review, summary
from app.services.study import StudyService

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Tools for observational cohort studies on the Cohort Studio data: does an
exposure (e.g. a programme) change an outcome (e.g. ED attendances)?
Use these tools for any such question instead of writing your own analysis:
they use a fixed, tested method (propensity score matching, then the outcome
model the outcome type calls for).

Always follow these steps, in order:
1. describe_data, to learn the data and the study format (StudySpec).
2. review_study with your draft (it may be partial). It lists what is still
   open: outcome, follow-up, covariates, population.
3. Ask the user every open question, showing its options and default. Never
   choose for the user and never assume; wait for their answers. Apply each
   answer to the draft as the option says.
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


def build_mcp(service: StudyService) -> MCPServer:
    mcp: MCPServer = MCPServer("cohort-studio", instructions=INSTRUCTIONS)

    @mcp.tool()
    def describe_data() -> Any:
        """What the data holds: exposures, sources, filters and allowed aggregations.

        Call this first. The study schema accepted by check_study and run_study
        is in 'study_schema'.
        """
        try:
            return clean({**service.metadata(), "study_schema": StudySpec.model_json_schema()})
        except Exception as e:
            return _failure(e)

    @mcp.tool()
    def list_values(source: str, dimension: str) -> dict[str, Any]:
        """Every allowed value of one filter.

        Example: source 'ed_episodes', dimension 'triage_level'.
        """
        try:
            return {"ok": True, "values": service.dimension_values(source, dimension)}
        except LookupError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return _failure(e)

    @mcp.tool()
    def review_study(study: dict[str, Any]) -> Any:
        """List what a draft study still leaves open, as questions to ask the user.

        Call this before check_study. The draft may be partial, even {}. Each
        question has options; an option either sets fields ("set"), adds a
        feature ("add_feature") or sets the outcome window ("outcome_window").
        Ask the user every question and apply their answers; do not choose.
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

    @mcp.tool()
    def check_study(study: dict[str, Any]) -> Any:
        """Validate a study definition and count the patients left after each eligibility step.

        Returns design issues (errors must be fixed before running), the outcome
        model the study implies, the treated/control counts per step, a plain-
        English summary to show the user, and the confirmation_code run_study
        needs once the user has confirmed.
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

    @mcp.tool()
    def run_study(study: dict[str, Any], confirmation_code: str) -> Any:
        """Run the full analysis: propensity score matching, balance check, outcome model.

        Only for a study the user has confirmed: pass the confirmation_code that
        check_study returned for this exact study. Returns the effect estimate
        with its 95% CI and p-value, a plain-English interpretation, cohort
        sizes, covariate balance and warnings.
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


def mcp_asgi_app(mcp: MCPServer, token: str | None) -> ASGIApp:
    """The MCP endpoint as an app to mount at /mcp.

    Stateless and JSON responses, so it runs behind any load balancer. The
    host check is off because the service sits behind a proxy with its own
    domain; the bearer token (or the platform's sign-in, when token is None)
    is what protects it.
    """
    app = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return app if token is None else BearerAuth(app, token)
