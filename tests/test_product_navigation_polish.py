from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDE = ROOT / "product_ui" / "product-extra.css"
BASE = ROOT / "product_ui" / "product-extra-base.css"
INDEX = ROOT / "product_ui" / "index.html"


def test_navigation_override_preserves_existing_extra_styles():
    text = OVERRIDE.read_text(encoding="utf-8")
    base = BASE.read_text(encoding="utf-8")
    assert text.startswith('@import url("/ui/product-extra-base.css");')
    assert ".settings-layout" in base
    assert "NEXUS readability floor" in base


def test_sidebar_is_vertically_scrollable_without_page_runtime_changes():
    text = OVERRIDE.read_text(encoding="utf-8")
    assert ".sidebar nav{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden" in text
    assert "overscroll-behavior:contain" in text
    assert ".side-foot{flex:0 0 auto}" in text


def test_numeric_nav_labels_are_visually_replaced_by_semantic_icons():
    text = OVERRIDE.read_text(encoding="utf-8")
    for view in ("overview","data","research","paper","risk","ai","strategies","agents","audit","live"):
        assert f'button[data-view="{view}"]>span::before' in text
    assert "font-size:0!important" in text


def test_refresh_and_sidebar_toggle_visual_order_is_swapped_only_in_css():
    css = OVERRIDE.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert ".topbar>.top-status{display:contents}" in css
    assert "#reload{order:0}" in css
    assert "#sidebarToggle{order:3}" in css
    assert 'id="reload"' in html and 'id="sidebarToggle"' in html
