"""Architecture rules that must not erode."""

import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
VF = APP / "vf"
GATEWAY = VF / "core" / "google"


def _py_files():
    return [p for p in VF.rglob("*.py") if "__pycache__" not in p.parts]


def test_only_gateway_imports_google_sdk():
    bad = []
    pattern = re.compile(r"^\s*(from|import)\s+google(\.|\s|$)", re.M)
    for path in _py_files():
        if GATEWAY in path.parents:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            bad.append(str(path.relative_to(APP)))
    assert bad == [], f"google SDK imported outside the gateway: {bad}"


def test_only_gateway_mentions_google_endpoints():
    bad = []
    for path in _py_files():
        if GATEWAY in path.parents:
            continue
        if "googleapis.com" in path.read_text(encoding="utf-8"):
            bad.append(str(path.relative_to(APP)))
    assert bad == []


def test_model_ids_live_only_in_the_seed():
    seed = json.loads((APP / "seeds" / "models.json").read_text(encoding="utf-8"))
    ids = [m["id"] for m in seed["models"]]
    roots = [VF, APP / "prompts", APP.parent / "web" / "pages", APP.parent / "web" / "components",
             APP.parent / "web" / "composables", APP.parent / "web" / "stores",
             APP.parent / "web" / "utils", APP.parent / "web" / "layouts", APP.parent / "web" / "plugins",
             APP.parent / "web" / "i18n", APP / "migrations"]
    bad = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".md", ".vue", ".ts", ".js", ".json", ".sql"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for model_id in ids:
                if re.search(rf"(?<![\w.-]){re.escape(model_id)}(?![\w.-])", text):
                    bad.append(f"{path.relative_to(APP.parent)}: {model_id}")
    assert bad == [], "model ids must come from seeds/models.json only"


def test_no_window_confirm_in_web():
    web = APP.parent / "web"
    if not web.exists():
        return
    bad = []
    for path in web.rglob("*"):
        if "node_modules" in path.parts or ".nuxt" in path.parts or ".output" in path.parts:
            continue
        if path.is_file() and path.suffix in (".vue", ".ts", ".js"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\b(window\.)?confirm\(", text) and "useConfirm" not in text:
                bad.append(str(path.relative_to(web)))
    assert bad == []
