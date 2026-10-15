"""Prompts are versioned files, not strings in code.

Layout: ``app/prompts/<group>/<CODE>/v<N>.md`` with a YAML header::

    ---
    code: vision.describe_photo
    version: 2
    role: vision_describe        # which model setting answers it
    response: json               # json | text | image
    description: Describe a product photo for the studio
    ---
    You look at a photo ... {{brand_name}} ...

A JSON answer may have a schema next to it: ``v<N>.schema.json``.
The highest version is the active one; old versions stay for the journal.
``{{name}}`` placeholders must all be filled; a missing one is an error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vf.core.errors import AppError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_FILE = re.compile(r"^v(\d+)\.md$")
RESPONSES = ("json", "text", "image")


@dataclass
class PromptFile:
    code: str
    version: int
    role: str | None
    response: str
    description: str
    body: str
    schema: dict | None
    path: Path
    variables: list[str] = field(default_factory=list)


@dataclass
class RenderedPrompt:
    code: str
    version: int
    role: str | None
    text: str
    response: str
    schema: dict | None


_cache: dict[str, dict[int, PromptFile]] | None = None


def _parse(path: Path) -> PromptFile:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path}: no YAML header")
    _, header, body = raw.split("---", 2)
    meta = yaml.safe_load(header) or {}
    version = int(_FILE.match(path.name).group(1))
    code = str(meta.get("code") or "")
    if not code:
        raise ValueError(f"{path}: header has no code")
    if int(meta.get("version", version)) != version:
        raise ValueError(f"{path}: header version {meta.get('version')} != file name v{version}")
    if path.parent.name != code:
        raise ValueError(f"{path}: folder name must equal code {code!r}")
    response = str(meta.get("response") or "text")
    if response not in RESPONSES:
        raise ValueError(f"{path}: bad response {response!r}")
    schema_path = path.with_name(f"v{version}.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else None
    body = body.strip("\n")
    return PromptFile(code=code, version=version, role=meta.get("role"), response=response,
                      description=str(meta.get("description") or ""), body=body, schema=schema, path=path,
                      variables=sorted(set(_VAR.findall(body))))


def load(directory: Path | None = None, *, force: bool = False) -> dict[str, dict[int, PromptFile]]:
    global _cache
    if _cache is not None and not force and directory is None:
        return _cache
    found: dict[str, dict[int, PromptFile]] = {}
    root = directory or PROMPTS_DIR
    for path in sorted(root.rglob("v*.md")):
        if not _FILE.match(path.name):
            continue
        pf = _parse(path)
        if pf.version in found.setdefault(pf.code, {}):
            raise ValueError(f"duplicate prompt {pf.code} v{pf.version}")
        found[pf.code][pf.version] = pf
    if directory is None:
        _cache = found
    return found


def check_all() -> list[str]:
    """Problems with prompt files (empty list = fine). Run at startup and in tests."""
    from vf.core import models_registry

    problems: list[str] = []
    try:
        table = load(force=True)
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]
    for code, versions in table.items():
        for pf in versions.values():
            if pf.role and pf.role not in models_registry.ROLES:
                problems.append(f"{code} v{pf.version}: unknown role {pf.role!r}")
            if pf.response == "json" and pf.schema is not None and pf.schema.get("type") not in ("object", "array"):
                problems.append(f"{code} v{pf.version}: schema must describe an object or array")
    return problems


def get(code: str, version: int | None = None) -> PromptFile:
    versions = load().get(code)
    if not versions:
        raise AppError("prompt_unknown", 500, code=code)
    if version is None:
        return versions[max(versions)]
    if version not in versions:
        raise AppError("prompt_unknown", 500, code=code, version=version)
    return versions[version]


def fill(template: str, values: Mapping[str, Any]) -> str:
    missing = [name for name in _VAR.findall(template) if name not in values]
    if missing:
        raise AppError("prompt_missing_vars", 500, missing=sorted(set(missing)))
    return _VAR.sub(lambda m: _as_text(values[m.group(1)]), template)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def render(code: str, version: int | None = None, **values: Any) -> RenderedPrompt:
    pf = get(code, version)
    return RenderedPrompt(code=pf.code, version=pf.version, role=pf.role, text=fill(pf.body, values),
                          response=pf.response, schema=pf.schema)


def catalog() -> list[dict]:
    """For the UI: every prompt with its active version."""
    out = []
    for code, versions in sorted(load().items()):
        active = versions[max(versions)]
        out.append({"code": code, "version": active.version, "versions": sorted(versions),
                    "role": active.role, "response": active.response, "description": active.description,
                    "variables": active.variables})
    return out


async def run_prompt(code: str, variables: Mapping[str, Any] | None = None, *, purpose: str,
                     images: Sequence[Any] = (), model_id: str | None = None, system: str | None = None,
                     search: bool = False, refs: Sequence[tuple[str, int]] = (),
                     cancel: Callable[[], bool] | None = None, version: int | None = None,
                     temperature: float | None = None, max_output_tokens: int | None = None,
                     thinking_level: str | None = None, aspect_ratio: str | None = None,
                     image_size: str | None = None):
    """Render a prompt file and send it. The model comes from the prompt's role
    unless ``model_id`` is given. Returns ``google.GenerateResult``."""
    from vf.core import google

    rp = render(code, version, **(variables or {}))
    contents: list[Any] = [*images, rp.text]
    return await google.generate(
        purpose=purpose, contents=contents, model_id=model_id, role=None if model_id else rp.role,
        system=system, prompt=google.PromptInfo(rp.code, rp.version), response=rp.response,
        schema=rp.schema, search=search, refs=refs, cancel=cancel, temperature=temperature,
        max_output_tokens=max_output_tokens, thinking_level=thinking_level, aspect_ratio=aspect_ratio,
        image_size=image_size,
    )
