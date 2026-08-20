from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
STAGER = DESKTOP / "stage-package-resources.js"
AFTER_PACK = DESKTOP / "after-pack.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_stager_materializes_a_loose_exact_source_ref_before_packaging() -> None:
    text = read(STAGER)
    assert "runGit(['--git-dir', seedPath, 'update-ref', packageRef, head]" in text
    assert "path.join(seedPath, 'refs', 'heads', 'nexus-package-source')" in text
    assert "exact-source seed loose ref is missing" in text
    assert "seed loose ref mismatch" in text
    assert text.index("'clone', '--depth', '1', '--bare'") < text.index("'--git-dir', seedPath, 'update-ref', packageRef, head")


def test_after_pack_proves_the_packaged_seed_is_a_real_git_repository() -> None:
    text = read(AFTER_PACK)
    for marker in (
        "path.join(seed, 'refs', 'heads', 'nexus-package-source')",
        "execFileSync('git', ['--git-dir', seed, 'rev-parse', 'refs/heads/nexus-package-source']",
        "execFileSync('git', ['--git-dir', seed, 'fsck', '--no-dangling']",
        "packaged owner bootstrap Git seed is invalid",
        "packaged owner bootstrap Git ref mismatch",
    ):
        assert marker in text
    assert "source-sha.txt" in text
    assert "loose ref mismatch" in text
