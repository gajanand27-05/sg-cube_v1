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
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    func: Callable[..., dict]

    def __call__(self, **kwargs) -> dict:
        return self.func(**kwargs)


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


def tool(func: Callable[..., dict]) -> Callable[..., dict]:
    """Register `func` as a callable tool. The function's docstring becomes
    the LLM-facing description; its type-hinted parameters become the schema.

    Functions MUST return a dict. Optional params (those with default values)
    are not listed in the `required` array.
    """
    name = func.__name__
    description = (func.__doc__ or "").strip().split("\n")[0]

    sig = inspect.signature(func)
    hints = get_type_hints(func)
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

    REGISTRY[name] = Tool(name=name, description=description, schema=schema, func=func)
    return func


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


def call(name: str, args: dict) -> dict:
    """Invoke a registered tool. Falls back to fuzzy name resolution before
    giving up — see _resolve_name."""
    resolved = _resolve_name(name, args)
    if resolved is None:
        return {"status": "error", "reason": f"unknown tool: {name!r}"}
    try:
        return REGISTRY[resolved](**args)
    except TypeError as e:
        return {"status": "error", "reason": f"bad arguments to {resolved}: {e}"}
    except Exception as e:
        return {"status": "error", "reason": f"{resolved} raised: {e}"}
