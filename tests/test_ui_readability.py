from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "product_ui" / "index.html"
CSS = ROOT / "product_ui" / "product-extra.css"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readability_overrides_load_after_base_styles():
    html = read(INDEX)
    assert html.index('/ui/product.css') < html.index('/ui/product-extra.css')


def test_secondary_text_has_a_real_pixel_floor_without_global_zoom():
    css = read(CSS)
    for marker in (
        '--nexus-readable-meta:max(12px,.76rem)',
        '--nexus-readable-secondary:max(13px,.82rem)',
        '--nexus-readable-value:max(15px,.94rem)',
        '.hero-card small',
        '.metric small',
        '.strategy-card p',
        '.risk-grid small',
        '.compact-row span',
        '.settings-form label',
        'font-size:var(--nexus-readable-secondary)!important',
        'font-size:var(--nexus-readable-value)!important',
        'line-height:1.5!important',
    ):
        assert marker in css
    readability = css[css.index('/* NEXUS readability floor') :]
    assert 'zoom:' not in readability
    assert 'transform:scale' not in readability.replace(' ', '')


def test_1366x768_layout_never_shrinks_readability_floor():
    css = read(CSS)
    marker = '@media(max-width:1366px),(max-height:768px)'
    assert marker in css
    compact = css[css.index(marker):]
    assert 'font-size:var(--nexus-readable-secondary)!important' in compact
    assert 'font-size:var(--nexus-readable-value)!important' in compact
    for forbidden in ('font-size:9px', 'font-size:10px', 'font-size:11px'):
        assert forbidden not in compact
