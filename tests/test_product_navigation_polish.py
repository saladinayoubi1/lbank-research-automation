from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "product_ui" / "product-extra.css"
INDEX = ROOT / "product_ui" / "index.html"


def test_navigation_polish_preserves_existing_extra_styles():
    text = CSS.read_text(encoding="utf-8")
    assert ".settings-layout" in text
    assert "NEXUS readability floor" in text
    assert "research-layout" in text
    assert "@import" not in text


def test_sidebar_is_vertically_scrollable_without_page_runtime_changes():
    text = CSS.read_text(encoding="utf-8")
    assert ".sidebar nav{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden" in text
    assert "overscroll-behavior:contain" in text
    assert ".side-foot{flex:0 0 auto}" in text


def test_nav_uses_semantic_icon_glyphs_in_dom_and_no_numeric_labels():
    html = INDEX.read_text(encoding="utf-8")
    icons = {
        "overview": "⌂",
        "data": "▦",
        "research": "∑",
        "paper": "↗",
        "risk": "◆",
        "ai": "✦",
        "strategies": "⎇",
        "agents": "⚙",
        "audit": "◎",
        "live": "⊘",
    }
    for view, glyph in icons.items():
        assert f'data-view="{view}"' in html
        assert f'<span class="nav-icon" aria-hidden="true">{glyph}</span>' in html
    for label in ("01","02","03","04","05","06","07","08","09","10"):
        assert f'<span>{label}</span>' not in html


def test_css_keeps_semantic_icon_projection_and_hides_legacy_number_text():
    text = CSS.read_text(encoding="utf-8")
    for view in ("overview","data","research","paper","risk","ai","strategies","agents","audit","live"):
        assert f'button[data-view="{view}"]>span::before' in text
    assert "font-size:0!important" in text


def test_refresh_and_sidebar_toggle_visual_order_is_swapped_only_in_css():
    css = CSS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert ".topbar>.top-status{display:contents}" in css
    assert "#reload{order:0}" in css
    assert "#sidebarToggle{order:3}" in css
    assert 'id="reload"' in html and 'id="sidebarToggle"' in html
