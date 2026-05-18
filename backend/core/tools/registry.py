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


def call(name: str, args: dict) -> dict:
    """Invoke a registered tool. Raises KeyError if not found."""
    if name not in REGISTRY:
        return {"status": "error", "reason": f"unknown tool: {name!r}"}
    try:
        return REGISTRY[name](**args)
    except TypeError as e:
        return {"status": "error", "reason": f"bad arguments to {name}: {e}"}
    except Exception as e:
        return {"status": "error", "reason": f"{name} raised: {e}"}
