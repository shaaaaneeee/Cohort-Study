"""A minimal MCP server over HTTP: JSON-RPC 2.0 requests, JSON responses.

Written here instead of using the `mcp` package, so the app installs from
common packages only (some company package mirrors block `mcp`). It serves
the parts of the protocol the study tools need, statelessly:

    initialize, ping, tools/list, tools/call    answered
    notifications (no "id")                     accepted, 202 with no body
    anything else, e.g. server/discover         -32601 Method not found

Every request is answered on its own, with no session, so the app can run
behind any load balancer. GET (a server-sent event stream) is not offered:
405. This is the "streamable HTTP" transport with JSON responses, protocol
revisions 2024-11-05 to 2025-11-25. A client of the newer stateless revision
probes server/discover first and falls back to initialize on -32601.
"""

import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

JSON_TYPES = {"string": str, "object": dict, "array": list, "boolean": bool}


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    function: Callable[..., Any]

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class McpServer:
    name: str
    version: str
    instructions: str
    tools: dict[str, Tool] = field(default_factory=dict)

    def tool(
        self, properties: dict[str, dict[str, Any]] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a function as a tool. Every listed property is required."""

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            props = properties or {}
            self.tools[function.__name__] = Tool(
                name=function.__name__,
                description=inspect.cleandoc(function.__doc__ or ""),
                input_schema={"type": "object", "properties": props, "required": list(props)},
                function=function,
            )
            return function

        return register

    # ------------------------------------------------------------ JSON-RPC

    async def handle(self, message: Any) -> dict[str, Any] | None:
        """The response to one JSON-RPC message, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
        if "method" not in message:
            return None  # a response or a notification from the client: nothing to answer
        if "id" not in message:
            return None
        msg_id = message["id"]
        method = message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(msg_id, INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            return _result(msg_id, self._initialize(params))
        if method == "ping":
            return _result(msg_id, {})
        if method == "tools/list":
            return _result(msg_id, {"tools": [t.listing() for t in self.tools.values()]})
        if method == "tools/call":
            return await self._call(msg_id, params)
        return _error(msg_id, METHOD_NOT_FOUND, "Method not found", method)

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested
            if requested in PROTOCOL_VERSIONS
            else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": self.instructions,
        }

    async def _call(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return _result(msg_id, _content(f"Unknown tool: {name}", error=True))
        if not isinstance(arguments, dict):
            return _result(msg_id, _content("arguments must be an object", error=True))
        problem = _check_arguments(tool, arguments)
        if problem:
            return _result(msg_id, _content(f"Invalid arguments for {name}: {problem}", error=True))
        log.info("mcp tool call", extra={"tool": name})
        try:
            # The tools query the warehouse and fit models: keep the event loop free.
            output = await run_in_threadpool(tool.function, **arguments)
        except Exception:
            log.exception("mcp tool failed", extra={"tool": name})
            return _result(msg_id, _content(f"Error executing tool {name}.", error=True))
        text = output if isinstance(output, str) else json.dumps(output, indent=2, default=str)
        return _result(msg_id, _content(text))

    # ----------------------------------------------------------------- HTTP

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """The ASGI app to mount at /mcp."""
        if scope["type"] != "http":
            return
        request = Request(scope, receive)
        response: Response
        if request.method != "POST":
            response = Response(status_code=405, headers={"Allow": "POST"})
        else:
            response = await self._post(request)
        await response(scope, receive, send)

    async def _post(self, request: Request) -> Response:
        try:
            body = json.loads(await request.body())
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "Parse error"), status_code=400)
        if isinstance(body, list):  # a batch (protocol 2025-03-26)
            if not body:
                return JSONResponse(_error(None, INVALID_REQUEST, "Empty batch"), status_code=400)
            answers = [a for a in [await self.handle(m) for m in body] if a is not None]
            return JSONResponse(answers) if answers else Response(status_code=202)
        answer = await self.handle(body)
        return JSONResponse(answer) if answer is not None else Response(status_code=202)


def _check_arguments(tool: Tool, arguments: dict[str, Any]) -> str | None:
    schema = tool.input_schema
    missing = [k for k in schema["required"] if k not in arguments]
    if missing:
        return f"missing {', '.join(missing)}"
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if spec is None:
            return f"unknown argument {key}"
        expected = JSON_TYPES.get(spec.get("type", ""))
        if expected and not isinstance(value, expected):
            return f"{key} must be a {spec['type']}"
    return None


def _content(text: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}
