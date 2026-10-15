import json

from vf.core import db
from vf.modules.library import seed, service
from vf.modules.library import variables as V


def _count(sql, params=()):
    return db.fetch_value(sql, params)


def test_seed_brings_the_whole_factory_library(database):
    stats = seed.sync()
    assert stats["categories_added"] == 756
    assert stats["styles_added"] == 67
    assert _count("SELECT COUNT(*) FROM preset_categories") == 756
    assert _count("SELECT COUNT(*) FROM preset_categories WHERE parent IS NULL") == 12
    assert _count("SELECT COUNT(*) FROM presets WHERE is_builtin = 1 AND kind = 'style'") == 36
    assert _count("SELECT COUNT(*) FROM presets WHERE is_builtin = 1 AND kind = 'photo_style'") == 31
    # every parent and every style category is a real category
    assert _count("SELECT COUNT(*) FROM preset_categories c WHERE parent IS NOT NULL AND NOT EXISTS "
                  "(SELECT 1 FROM preset_categories p WHERE p.slug = c.parent)") == 0
    assert _count("SELECT COUNT(*) FROM presets p WHERE category IS NOT NULL AND NOT EXISTS "
                  "(SELECT 1 FROM preset_categories c WHERE c.slug = p.category)") == 0
    # every shipped preview is on disk
    rows = db.fetch_all("SELECT * FROM presets WHERE preview_seed IS NOT NULL")
    assert len(rows) == 36
    assert all(seed.preview_path(r["preview_seed"]) for r in rows)


def test_seed_styles_fit_the_limits():
    _cats, styles = seed.load()
    for s in styles:
        assert len(s["prompt"]) <= V.MAX_STYLE_CHARS, s["code"]
        keys = {V.variable_key(m.group(1)) for m in V.VARIABLE_RE.finditer(s["prompt"])}
        assert len(keys) <= V.MAX_PROMPT_VARIABLES, s["code"]
        assert len(s["title"]) <= service.MAX_TITLE_CHARS, s["code"]


def test_resync_changes_nothing_and_keeps_own_styles(database):
    seed.sync()
    own = service.create_style({"title": "Mine", "prompt": "Neon {{brand|ACME}}"})
    copy = service.copy_style(service.get_style("style-14")["id"])
    service.update_style(copy["id"], {"prompt": "edited by me"})
    stats = seed.sync()
    assert not any(stats.values())
    assert service.get_style(own["id"])["prompt"] == "Neon {{brand|ACME}}"
    assert service.get_style(copy["id"])["prompt"] == "edited by me"
    assert service.get_style(copy["id"])["copied_from"] == "style-14"


def test_seed_update_overwrites_builtins_and_hides_removed(database, tmp_path):
    seed.sync()
    cats = json.loads((seed.SEED_DIR / "categories.json").read_text(encoding="utf-8"))
    styles = json.loads((seed.SEED_DIR / "styles.json").read_text(encoding="utf-8"))
    style_1 = next(s for s in styles["styles"] if s["code"] == "style-1")
    style_1["title"] = "New title"
    styles["styles"] = [s for s in styles["styles"] if s["code"] != "style-2"]
    dropped = next(c for c in cats["categories"] if c["depth"] == 3 and not any(
        s["category"] == c["slug"] for s in styles["styles"]))
    cats["categories"] = [c for c in cats["categories"] if c["slug"] != dropped["slug"]]
    root = tmp_path / "seed"
    root.mkdir()
    (root / "categories.json").write_text(json.dumps(cats, ensure_ascii=False), encoding="utf-8")
    (root / "styles.json").write_text(json.dumps(styles, ensure_ascii=False), encoding="utf-8")

    old_2 = service.get_style("style-2")
    stats = seed.sync(root)
    assert stats["styles_updated"] == 1 and stats["styles_removed"] == 1 and stats["categories_removed"] == 1
    assert service.get_style("style-1")["title"] == "New title"
    # gone from the seed: hidden from the lists, still there for old works
    removed = service.get_style(old_2["id"])
    assert removed["removed"] is True
    listed = {s["id"] for s in service.list_styles(tab="all", limit=200)["items"]}
    assert old_2["id"] not in listed
    assert service.render_style(old_2["id"])["prompt"]
    tree = {c["slug"] for c in service.category_tree()["items"]}
    assert dropped["slug"] not in tree

    # the next release brings them back
    stats = seed.sync()
    assert service.get_style(old_2["id"])["removed"] is False
    assert dropped["slug"] in {c["slug"] for c in service.category_tree()["items"]}


def test_seed_preview_path_stays_inside_the_seed():
    assert (seed.SEED_DIR.parent / "models.json").is_file()
    assert seed.preview_path("../models.json") is None
    assert seed.preview_path("/etc/hostname") is None
    assert seed.preview_path("previews/style-1.jpg") is not None
