"""Tool registry + @tool decorator.

A tool is a Python function annotated with `@tool`. We introspect its
signature + docstring to produce a JSON-schema description the LLM can read,
and we keep the function callable for the executor to invoke.

Example:

    @tool
    def set_volume(level: int) -> dict:
        '''Set system volume to a value between 0 and 100.'''
        ...

    REGISTRY["set_volume"]          # -> Tool instance
    REGISTRY["set_volume"].schema   # -> JSON schema dict
    REGISTRY["set_volume"](level=50)  # -> dict result
"""
import inspect
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, get_type_hints

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class ToolStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    PENDING_CONFIRMATION = "pending_confirmation"


class SecurityLevel(str, Enum):
    SAFE = "safe"              # Trusted (e.g., read files, open apps)
    CAUTION = "caution"        # Needs confirmation (e.g., delete files, send email)
    CRITICAL = "critical"      # High risk, needs extra warning (e.g., shutdown, format)


class CapabilityTier(str, Enum):
    """Phase-0 capability tier used by the Guardian confirmation gate.

    Coexists with SecurityLevel (which drives the sandbox layer and the
    conditional deep-verification trigger). The tier axis specifically
    governs *whether the user is prompted before execution*:

    - READONLY:     no side effects — read a value / fetch data / describe
                    something. Passes without confirmation.
    - SYSTEM_WRITE: mutates machine / app / browser / stored state but
                    reversible. Requires confirmation unless the
                    AUTO_CONFIRM_SYSTEM_WRITE setting is true.
    - DESTRUCTIVE:  hard to undo (shell commands, deletion, external
                    messages, power state). ALWAYS requires confirmation;
                    no flag can silence this.

    Default for any untagged tool is DESTRUCTIVE — a forgotten tier
    fails safe (asks before firing) instead of silently getting execute
    permission. This is the load-bearing decision of Phase 0.
    """
    READONLY = "readonly"
    SYSTEM_WRITE = "system_write"
    DESTRUCTIVE = "destructive"


class ToolResult(BaseModel):
    """Standardized result returned by every tool."""
    status: ToolStatus
    message: str | None = None
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 100.0  # 0.0 - 100.0
    confidence_reason: list[str] = Field(default_factory=list)

    @classmethod
    def success(cls, message: str, data: dict[str, Any] | None = None, confidence: float = 100.0, confidence_reason: list[str] | None = None) -> "ToolResult":
        return cls(
            status=ToolStatus.SUCCESS, 
            message=message, 
            data=data or {},
            confidence=confidence,
            confidence_reason=confidence_reason or []
        )

    @classmethod
    def blocked(cls, reason: str, confidence: float = 0.0, confidence_reason: list[str] | None = None) -> "ToolResult":
        return cls(
            status=ToolStatus.BLOCKED, 
            reason=reason,
            confidence=confidence,
            confidence_reason=confidence_reason or []
        )

    @classmethod
    def error(cls, reason: str, confidence: float = 0.0, confidence_reason: list[str] | None = None) -> "ToolResult":
        return cls(
            status=ToolStatus.ERROR, 
            reason=reason,
            confidence=confidence,
            confidence_reason=confidence_reason or []
        )

    @classmethod
    def pending(cls, confirmation_token: str, message: str) -> "ToolResult":
        return cls(
            status=ToolStatus.PENDING_CONFIRMATION,
            message=message,
            data={"token": confirmation_token}
        )


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    func: Callable[..., dict | ToolResult]
    security: SecurityLevel = SecurityLevel.SAFE
    # Capability tier — Guardian's confirmation gate keys off this.
    # Default is DESTRUCTIVE so any tool that forgets to declare a tier
    # fails safe (asks user) rather than silently getting exec permission.
    tier: CapabilityTier = CapabilityTier.DESTRUCTIVE
    # Phase 0.6: per-tool trust flag. Only meaningful on SYSTEM_WRITE —
    # a trusted SYSTEM_WRITE tool skips the confirmation prompt. On
    # READONLY it's redundant (no prompt to skip). On DESTRUCTIVE the
    # decorator forces this to False and logs a warning: destructive
    # tools always prompt, no override permitted.
    trusted: bool = False

    async def __call__(self, request_id: Optional[str] = None, **kwargs) -> ToolResult:
        from backend.core.runtime import runtime
        return await runtime.run_tool(self.name, self.func, kwargs, request_id=request_id)


REGISTRY: dict[str, Tool] = {}


_PRIMITIVE_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _type_to_json(py_type: Any) -> str:
    return _PRIMITIVE_TYPES.get(py_type, "string")


def tool(security: Any = SecurityLevel.SAFE, tier: Any = None, trusted: bool = False) -> Any:
    """Register a function as a tool. Supports:
      @tool                                                     # bare (tier → DESTRUCTIVE, trusted=False — fail closed)
      @tool(tier=CapabilityTier.READONLY)                       # explicit tier
      @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)     # trusted allowlist entry
      @tool(security=SecurityLevel.CAUTION)                     # legacy security only
      @tool(security=SecurityLevel.CAUTION, tier=..., trusted=True)  # all three

    `trusted=True` on a DESTRUCTIVE tool is a bug — destructive tools
    always prompt, no override. The decorator forces it back to False
    and logs a warning at registration time so the misdeclaration is
    visible in the boot log rather than silently taking effect.
    """
    func = None

    if callable(security):
        # Used as @tool bare — first positional is the function itself.
        func = security
        security = SecurityLevel.SAFE
        # tier stays None → resolves to DESTRUCTIVE below (fail closed)
        # trusted stays False

    # Resolve tier default. Missing / unknown → DESTRUCTIVE. Any @tool
    # that forgets to declare a tier gets the safest treatment (Guardian
    # will prompt every time) instead of silent execute permission.
    resolved_tier = tier if isinstance(tier, CapabilityTier) else CapabilityTier.DESTRUCTIVE

    # Enforce the DESTRUCTIVE + trusted=True invariant at registration time.
    resolved_trusted = bool(trusted)

    def decorator(f: Callable[..., dict]) -> Callable[..., dict]:
        name = f.__name__
        description = (f.__doc__ or "").strip().split("\n")[0]

        # Phase 0.6: destructive tools cannot be trusted. If someone
        # declares one, ignore the flag and warn — the invariant is
        # non-negotiable per the tier contract.
        effective_trusted = resolved_trusted
        if effective_trusted and resolved_tier == CapabilityTier.DESTRUCTIVE:
            log.warning(
                "Tool %r declared trusted=True with tier=DESTRUCTIVE — ignoring trusted; "
                "destructive tools always require confirmation",
                name,
            )
            effective_trusted = False

        sig = inspect.signature(f)
        hints = get_type_hints(f)
        properties: dict[str, dict] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            ann = hints.get(pname, str)
            # Strip Optional[...] / Union[..., None]
            origin = getattr(ann, "__origin__", None)
            if origin is type(None):
                ann_type = str
            else:
                args = getattr(ann, "__args__", ())
                non_none = [a for a in args if a is not type(None)]
                ann_type = non_none[0] if non_none else ann
            properties[pname] = {"type": _type_to_json(ann_type)}
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        schema = {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

        REGISTRY[name] = Tool(
            name=name,
            description=description,
            schema=schema,
            func=f,
            security=security,
            tier=resolved_tier,
            trusted=effective_trusted,
        )
        return f

    if func:
        return decorator(func)
    return decorator


def all_schemas() -> list[dict]:
    return [t.schema for t in REGISTRY.values()]


def schemas_prompt() -> str:
    """Render the registry as compact JSON suitable for inclusion in the
    LLM system prompt."""
    return json.dumps(all_schemas(), indent=2)


def _resolve_name(name: str, args: dict) -> str | None:
    """Fuzzy-match a tool name. LLMs (gemma4 in particular) often drop
    suffixes ("summarize" -> "summarize_url") or generalize ("weather" ->
    "get_weather"). When the exact name is missing, look for tools whose
    name *contains* the requested name, then disambiguate by which one's
    required params best match the provided args.

    Returns the resolved name, or None if no confident match.
    """
    if name in REGISTRY:
        return name

    q = name.lower()
    if not q:
        return None

    # Candidates: any tool whose name contains the requested string.
    candidates = [n for n in REGISTRY if q in n.lower()]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Multiple matches — score by how well args fit each candidate's params.
    arg_keys = set(args.keys())

    def score(tool_name: str) -> tuple[int, int, int]:
        params = REGISTRY[tool_name].schema["parameters"]
        required = set(params.get("required", []))
        properties = set(params.get("properties", {}).keys())
        missing_required = len(required - arg_keys)
        matched_known = len(arg_keys & properties)
        # Lower missing_required is better; higher matched_known is better;
        # shorter name is better as a tiebreaker (closer to what the LLM said).
        return (-missing_required, matched_known, -len(tool_name))

    best = max(candidates, key=score)
    # Reject if the best candidate is still missing required args — we'd
    # rather surface "unknown tool" than dispatch to a wrong tool.
    best_params = REGISTRY[best].schema["parameters"]
    if set(best_params.get("required", [])) - arg_keys:
        return None
    return best


async def call(name: str, args: dict, request_id: Optional[str] = None) -> ToolResult:
    """Invoke a registered tool. Falls back to fuzzy name resolution before
    giving up — see _resolve_name."""
    resolved = _resolve_name(name, args)
    if resolved is None:
        return ToolResult.blocked(f"unknown tool: {name!r}")
    
    # ── Security Layer ───────────────────────────────────────────────
    from backend.core.tools.sandbox import guard
    check_res = guard.check(resolved, args)
    if check_res:
        return check_res
    # ────────────────────────────────────────────────────────────────

    args = _coerce_args(resolved, args)
    return await REGISTRY[resolved](request_id=request_id, **args)


def _coerce_args(tool_name: str, args: dict) -> dict:
    """Remap argument names when the LLM hallucinates parameter aliases.

    gemma frequently calls open_app({"app_name": "notepad"}) when the schema
    says `name`, or summarize_url({"link": ...}) instead of `url`. We accept
    these by mapping any unknown arg key onto the closest schema param via
    substring containment — same trick the tool-name resolver uses.
    """
    if not isinstance(args, dict) or not args:
        return args
    schema_params = REGISTRY[tool_name].schema["parameters"].get("properties", {})
    valid = set(schema_params.keys())
    if not valid:
        return args
    out: dict = {}
    for key, value in args.items():
        if key in valid:
            out[key] = value
            continue
        # Find the schema param closest to this hallucinated key.
        k = key.lower()
        # Prefer one where the schema name is contained in the hallucinated key
        # ("name" in "app_name", "url" in "page_url"), then the reverse.
        contained = [p for p in valid if p.lower() in k]
        if not contained:
            contained = [p for p in valid if k in p.lower()]
        if len(contained) == 1 and contained[0] not in out:
            out[contained[0]] = value
        else:
            # Ambiguous or no match — keep the original key (will TypeError).
            out[key] = value
    return out
