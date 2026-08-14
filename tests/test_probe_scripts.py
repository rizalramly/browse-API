"""Pure helpers of the egress probe scripts (plans 1.1 and 1.2) — no network."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).parent.parent / "scripts"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ceiling = load("ceiling_probe")
engine = load("engine_probe")


# --- ceiling_probe: block classification + recommendation ---


def test_block_signatures() -> None:
    classify = ceiling.classify_response
    assert classify(429, "https://google.com/search", "") == "block"
    assert classify(403, "https://google.com/search", "") == "block"
    assert classify(302, "https://www.google.com/sorry/index", "") == "block"
    assert classify(200, "https://google.com/search", "Our systems have detected "
                    "unusual traffic from your network") == "block"
    assert classify(200, "https://google.com/search", "<html>10 results</html>") == "ok"
    assert classify(500, "https://google.com/search", "") == "error"


def test_suggested_qps_leaves_headroom() -> None:
    assert ceiling.suggest_outbound_qps(2.0) == 0.5
    assert ceiling.suggest_outbound_qps(1.0, headroom=0.5) == 0.5


# --- engine_probe: settings.yml regeneration ---


def make_results() -> list[object]:
    return [
        engine.ProbeResult("google", "https://g", 200, "ok"),
        engine.ProbeResult("duckduckgo", "https://d", 403, "block"),
        engine.ProbeResult("brave", "https://b", 0, "error"),
    ]


def test_rendered_section_is_evidence_annotated() -> None:
    section = engine.render_engines_section(make_results(), checked="2026-08-14")
    assert engine.MARKER_BEGIN in section and engine.MARKER_END in section
    assert "  - name: google\n    disabled: false  # passes proxy (checked 2026-08-14)" in section
    assert "  - name: duckduckgo\n    disabled: true  # BLOCK via proxy: HTTP 403" in section
    assert "  - name: brave\n    disabled: true  # ERROR via proxy: network failure" in section


def test_merge_appends_when_no_markers() -> None:
    settings = "use_default_settings: true\nserver:\n  limiter: false\n"
    section = engine.render_engines_section(make_results(), "2026-08-14")
    merged = engine.merge_into_settings(settings, section)
    assert merged.startswith("use_default_settings: true")
    assert merged.count(engine.MARKER_BEGIN) == 1


def test_merge_replaces_existing_block_idempotently() -> None:
    settings = "use_default_settings: true\n"
    section_v1 = engine.render_engines_section(make_results(), "2026-01-01")
    merged_v1 = engine.merge_into_settings(settings, section_v1)
    section_v2 = engine.render_engines_section(
        [engine.ProbeResult("google", "https://g", 200, "ok")], "2026-08-14"
    )
    merged_v2 = engine.merge_into_settings(merged_v1, section_v2)
    assert merged_v2.count(engine.MARKER_BEGIN) == 1
    assert "2026-01-01" not in merged_v2
    assert "duckduckgo" not in merged_v2  # old entries fully replaced
    assert "checked 2026-08-14" in merged_v2


def test_merge_preserves_content_after_block() -> None:
    settings = ("use_default_settings: true\n\n" + engine.MARKER_BEGIN
                + "\nengines:\n  - name: old\n    disabled: true\n" + engine.MARKER_END
                + "\n\nui:\n  static_use_hash: true\n")
    section = engine.render_engines_section(make_results(), "2026-08-14")
    merged = engine.merge_into_settings(settings, section)
    assert "ui:\n  static_use_hash: true" in merged
    assert "name: old" not in merged
