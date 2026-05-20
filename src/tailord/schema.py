"""JSON-Schema validation for vault files. Wraps `jsonschema` so callers
deal with (path, message) tuples instead of draft versions and format
checkers. Schemas live under FRAMEWORK_ROOT/schemas/."""
from __future__ import annotations

import functools
from typing import Any, Iterable

import yaml

from tailord.paths import SCHEMAS_DIR


@functools.lru_cache(maxsize=None)
def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{name}.schema.yaml"
    if not path.exists():
        raise FileNotFoundError(f"schema not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _format_path(error_path: Iterable[Any]) -> str:
    parts: list[str] = []
    for p in error_path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append(f".{p}" if parts else str(p))
    return "".join(parts) or "(root)"


def validate(schema_name: str, document: dict[str, Any]) -> list[tuple[str, str]]:
    """Returns (path, message) tuples — empty when the document is valid.
    jsonschema is imported lazily so the dep is only required when schema
    validation actually runs."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as e:
        raise SystemExit(
            "jsonschema is required for schema validation. Install with:\n"
            "  pip install jsonschema\n"
            f"(import error: {e})"
        )

    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return [(_format_path(e.absolute_path), e.message) for e in errors]
