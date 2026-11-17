"""The study tools, served to AI assistants over MCP.

An assistant such as Databricks Genie Code connects to /mcp and can call:

    describe_data   what the data holds: exposures, sources, filters, outcomes
    list_values     the allowed values of one filter
    check_study     validate a study definition, with patient counts per step
    run_study       run the full analysis (matching + outcome model)

Every tool goes through StudyService, the same code the web app uses, so the
assistant gets the same tested method and the same checks. It never sends or
receives SQL, and never sees patient-level rows: only counts and results.

Enabled only when MCP_TOKEN is set; every request must then carry
"Authorization: Bearer <MCP_TOKEN>".
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
from app.services.study import StudyService

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Tools for observational cohort studies on the Cohort Studio data: does an
exposure (e.g. a programme) change an outcome (e.g. ED attendances)?
Start with describe_data. A study is a JSON object (StudySpec): exposure,
optional age limits and person filters, person covariates, and features (each
a covariate, inclusion criterion or exactly one outcome). Use check_study to
validate a draft and see how many patients remain, then run_study to get the
matched estimate. Prefer these tools over writing your own matching code: they
use a fixed, tested method (propensity score matching, then the outcome model
the outcome type calls for). If the question is vague, ask the user which
outcome, follow-up, covariates and population they want before running."""


def _study(study: dict[str, Any]) -> StudySpec | dict[str, Any]:
    """The study, or an error answer the assistant can act on."""
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
        return {"ok": False, "error": "The database could not be reached. Try again later."}
    raise e


def build_mcp(service: StudyService) -> MCPServer:
    mcp: MCPServer = MCPServer("cohort-studio", instructions=INSTRUCTIONS)

    @mcp.tool()
    def describe_data() -> Any:
        """What the data holds: exposures, sources, filters and allowed aggregations.

        Call this first. The study schema accepted by check_study and run_study
        is in 'study_schema'.
        """
        return clean({**service.metadata(), "study_schema": StudySpec.model_json_schema()})

    @mcp.tool()
    def list_values(source: str, dimension: str) -> dict[str, Any]:
        """Every allowed value of one filter.

        Example: source 'ed_episodes', dimension 'triage_level'.
        """
        try:
            return {"ok": True, "values": service.dimension_values(source, dimension)}
        except LookupError as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    def check_study(study: dict[str, Any]) -> Any:
        """Validate a study definition and count the patients left after each eligibility step.

        Returns design issues (errors must be fixed before running), the outcome
        model the study implies, and the treated/control counts per step.
        """
        spec = _study(study)
        if isinstance(spec, dict):
            return spec
        try:
            checked = service.check(spec)
            if any(i["level"] == "error" for i in checked["issues"]):
                return clean({"ok": False, **checked})
            return clean({"ok": True, **checked, "attrition": service.attrition(spec)})
        except Exception as e:
            return _failure(e)

    @mcp.tool()
    def run_study(study: dict[str, Any]) -> Any:
        """Run the full analysis: propensity score matching, balance check, outcome model.

        Returns the effect estimate with its 95% CI and p-value, a plain-English
        interpretation, cohort sizes, covariate balance and warnings.
        """
        spec = _study(study)
        if isinstance(spec, dict):
            return spec
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


def mcp_asgi_app(mcp: MCPServer, token: str) -> ASGIApp:
    """The MCP endpoint as an app to mount at /mcp.

    Stateless and JSON responses, so it runs behind any load balancer. The
    host check is off because the service sits behind a proxy with its own
    domain; the bearer token is what protects it.
    """
    app = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerAuth(app, token)
