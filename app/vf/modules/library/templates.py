"""Service prompt templates ("layers") — the parts a prompt is assembled from.

The files live in ``app/prompts/layers/<group>/<CODE>/v<N>.md`` like every other
prompt file (``vf.core.prompts`` loads, versions and checks them). Their header
carries ``engine: layers``: the body uses the factory template grammar, which is
richer than the plain ``{{name}}`` of ``prompts.fill``:

* ``{{name}}`` — a value; every placeholder left after the conditions are
  resolved must be given (a missing one raises ``prompt_missing_vars``);
* ``{{#if name}} … {{else}} … {{/if}}`` — a branch; on a line of its own it takes
  the line with it, inline it keeps the surrounding text. Absent, blank, empty,
  zero and false read as "no";
* ``{{#each items}} … {{this}} / {{this.field}} / {{@index}} … {{/each}}``;
* ``%OTHER_LAYER%`` — the active text of another layer file, pasted in before
  anything else (layers inside layers up to 5 deep; an unknown token stays as is).

Usage from a module::

    from vf.modules.library import render_layer
    text = render_layer("IMAGE_PART_STYLE_SAMPLE", {"n": 3})
    pf = prompts.get("IMAGE_PART_STYLE_SAMPLE")   # pf.version for the journal

Values are substituted once; text inside a value is never read as a template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from vf.core import prompts
from vf.core.errors import AppError

ENGINE = "layers"

_LAYER_TOKEN_RE = re.compile(r"%([^%\n]{1,80})%")
_EACH_RE = re.compile(r"\{\{#each\s+([\w.]+)\s*\}\}([\s\S]*?)\{\{/each\}\}")
_EACH_INNER_RE = re.compile(r"\{\{(this|@index|this\.[\w.]+)\}\}")
_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_IF_BODY = r"((?:(?!\{\{#if\s)[\s\S])*?)"
_IF_STANDALONE_RE = re.compile(
    r"^[ \t]*\{\{#if\s+([\w.@]+)\s*\}\}[ \t]*\r?\n" + _IF_BODY + r"^[ \t]*\{\{/if\}\}[ \t]*(?:\r?\n|\Z)",
    re.MULTILINE,
)
_IF_INLINE_RE = re.compile(r"\{\{#if\s+([\w.@]+)\s*\}\}" + _IF_BODY + r"\{\{/if\}\}")
_ELSE_STANDALONE_RE = re.compile(r"^[ \t]*\{\{else\}\}[ \t]*\r?\n", re.MULTILINE)
_ELSE_INLINE_RE = re.compile(r"\{\{else\}\}")
_MAX_LAYER_DEPTH = 5


def normalize_token(raw: Any) -> str:
    """``%Avatar master rule%`` and ``%AVATAR_MASTER_RULE%`` are the same layer."""
    text = re.sub(r"^%+|%+$", "", str(raw or "")).strip().upper()
    return re.sub(r"[\s_-]+", "_", text)


def _layer_codes() -> dict[str, str]:
    """Normalised token -> code, for every prompt file that may be pasted as a layer."""
    return {normalize_token(code): code for code in prompts.load()}


def resolve_layers(text: str, *, max_depth: int = _MAX_LAYER_DEPTH) -> tuple[str, list[str]]:
    """Paste ``%TOKEN%`` layers. Returns the text and the codes used (for the journal)."""
    codes = _layer_codes()
    used: list[str] = []
    cur = text
    for _ in range(max_depth):
        changed = False

        def _sub(match: re.Match) -> str:
            nonlocal changed
            code = codes.get(normalize_token(match.group(1)))
            if not code:
                return match.group(0)
            changed = True
            if code not in used:
                used.append(code)
            return prompts.get(code).body

        cur = _LAYER_TOKEN_RE.sub(_sub, cur)
        if not changed:
            break
    return cur, used


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, Mapping) else getattr(cur, part, None)
    return cur


def _has_path(obj: Any, path: str) -> bool:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return False
    return True


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict | set):
        return len(value) > 0
    if isinstance(value, int | float):
        return value != 0
    return bool(value)


def _split_else(body: str) -> tuple[str, str]:
    for pattern in (_ELSE_STANDALONE_RE, _ELSE_INLINE_RE):
        parts = pattern.split(body, maxsplit=1)
        if len(parts) == 2:
            return parts[0], parts[1]
    return body, ""


def _render_conditions(text: str, context: Mapping[str, Any]) -> str:
    out = text
    for _ in range(10):
        changed = False

        def _one(match: re.Match) -> str:
            nonlocal changed
            changed = True
            yes, no = _split_else(match.group(2))
            return yes if _truthy(_get_path(context, match.group(1))) else no

        out = _IF_STANDALONE_RE.sub(_one, out)
        out = _IF_INLINE_RE.sub(_one, out)
        if not changed:
            break
    return out


def render_text(template: str, values: Mapping[str, Any] | None = None, *, strict: bool = True) -> str:
    """Render a template body (layers already pasted). ``strict``: a ``{{name}}``
    left after the conditions must be in ``values``."""
    context = dict(values or {})

    def _each(match: re.Match) -> str:
        items = _get_path(context, match.group(1))
        if not isinstance(items, list | tuple):
            return ""
        parts = []
        for index, item in enumerate(items):
            scoped = {**context, "this": item, "@index": index}
            body = _render_conditions(match.group(2), scoped)
            parts.append(_EACH_INNER_RE.sub(lambda m, s=scoped: _stringify(_get_path(s, m.group(1))), body))
        return "".join(parts)

    out = _EACH_RE.sub(_each, template)
    out = _render_conditions(out, context)
    if strict:
        missing = sorted({name for name in _VAR_RE.findall(out) if not _has_path(context, name)})
        if missing:
            raise AppError("prompt_missing_vars", 500, missing=missing)
    return _VAR_RE.sub(lambda m: _stringify(_get_path(context, m.group(1))), out)


def render_layer(code: str, values: Mapping[str, Any] | None = None, *, version: int | None = None) -> str:
    """The text of one layer file with its layers pasted and its values filled."""
    pf = prompts.get(code, version)
    body, _used = resolve_layers(pf.body)
    return render_text(body, values)


def layer_variables(code: str, version: int | None = None) -> dict[str, list[str]]:
    """What a layer reads: ``{"values": [...], "conditions": [...], "lists": [...], "layers": [...]}``."""
    pf = prompts.get(code, version)
    body, used = resolve_layers(pf.body)
    conditions = sorted(set(re.findall(r"\{\{#if\s+([\w.@]+)\s*\}\}", body)))
    lists = sorted(set(re.findall(r"\{\{#each\s+([\w.]+)\s*\}\}", body)))
    names = sorted({n for n in _VAR_RE.findall(body) if n not in ("else", "this", "@index")
                    and not n.startswith("this.")})
    return {"values": names, "conditions": conditions, "lists": lists, "layers": used}


def is_layer_file(pf: prompts.PromptFile) -> bool:
    """True for files written in this grammar (header ``engine: layers``)."""
    return _engine_of(pf) == ENGINE


def _engine_of(pf: prompts.PromptFile) -> str | None:
    import yaml

    raw = pf.path.read_text(encoding="utf-8")
    try:
        meta = yaml.safe_load(raw.split("---", 2)[1]) or {}
    except (IndexError, yaml.YAMLError):
        return None
    return meta.get("engine")


def layer_codes() -> list[str]:
    """Every prompt code whose active file uses this grammar."""
    out = []
    for code, versions in sorted(prompts.load().items()):
        if is_layer_file(versions[max(versions)]):
            out.append(code)
    return out


def check_layers() -> list[str]:
    """Problems with layer files: an unknown ``%TOKEN%`` or a token loop. Empty = fine."""
    problems: list[str] = []
    codes = _layer_codes()
    for code in layer_codes():
        pf = prompts.get(code)
        for token in _LAYER_TOKEN_RE.findall(pf.body):
            name = normalize_token(token)
            if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", name) and name not in codes:
                problems.append(f"{code}: unknown layer %{token}%")
        body, _used = resolve_layers(pf.body)
        leftover = [t for t in _LAYER_TOKEN_RE.findall(body) if normalize_token(t) in codes]
        if leftover:
            problems.append(f"{code}: layers nested deeper than {_MAX_LAYER_DEPTH}: {leftover}")
    return problems


def describe(code: str) -> dict:
    pf = prompts.get(code)
    if not is_layer_file(pf):
        raise AppError("prompt_unknown", 404, code=code)
    return {"code": pf.code, "version": pf.version, "description": pf.description, **layer_variables(code)}
