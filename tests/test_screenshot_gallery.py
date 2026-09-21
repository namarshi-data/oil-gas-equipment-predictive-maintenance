"""Protect curated screenshot indexes from gallery regeneration."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_screenshot_gallery.py"


@pytest.fixture
def gallery_root(tmp_path):
    screenshots = tmp_path / "screenshots"
    entries = []
    for group, name, phase in [
        ("powerbi-native", "01-report.png", "user-supplied-native"),
        ("assistant", "01-answer.jpg", "after"),
    ]:
        path = screenshots / group / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unchanged screenshot fixture")
        entries.append({
            "file": f"{group}/{name}", "title": "Example <script>bad</script>",
            "surface": group, "phase": phase, "url": None, "viewport": None,
            "captured_at": None, "page_id": "executive_roi" if group == "powerbi-native" else None,
            "question": '<img src=x onerror="bad()">' if group == "assistant" else None,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (screenshots / "capture-manifest.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    (screenshots / "README.md").write_bytes(b"# Authored overview\r\nPersonal explanation that must survive.\r\n[Native](powerbi-native/01-report.png) [Answer](assistant/01-answer.jpg)\r\n")
    (screenshots / "powerbi-native/README.md").write_bytes(b"# Authored native guide\r\n[Image](01-report.png)\r\n")
    (screenshots / "index.html").write_bytes(b"previous valid gallery")
    return tmp_path


def run_gallery(root):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)], text=True, capture_output=True)


def test_generation_preserves_authored_indexes_and_evidence(gallery_root):
    folder = gallery_root / "screenshots"
    preserved = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file() and p.name != "index.html"}
    result = run_gallery(gallery_root)
    assert result.returncode == 0, result.stderr
    assert all(p.read_bytes() == content for p, content in preserved.items())
    summary = json.loads(result.stdout)
    assert summary["authored_markdown_preserved"] is True
    assert summary["markdown_image_coverage"] == {"README.md": 2, "powerbi-native/README.md": 1}
    rendered = (folder / "index.html").read_text(encoding="utf-8")
    assert rendered.count('<img src="') == 2
    assert "<script>bad</script>" not in rendered
    assert "&lt;script&gt;bad&lt;/script&gt;" in rendered
    assert "&lt;img src=x onerror=&quot;bad()&quot;&gt;" in rendered
    assert "Not recorded" not in rendered


@pytest.mark.parametrize("problem", ["missing_index", "missing_reference", "broken_link", "altered_image"])
def test_invalid_evidence_stops_before_writing(gallery_root, problem):
    folder = gallery_root / "screenshots"
    authored = folder / "README.md"
    if problem == "missing_index":
        authored.unlink()
    elif problem == "missing_reference":
        authored.write_text("[Native](powerbi-native/01-report.png)", encoding="utf-8")
    elif problem == "broken_link":
        with authored.open("a", encoding="utf-8") as handle:
            handle.write("[Missing guide](missing.md)")
    else:
        (folder / "assistant/01-answer.jpg").write_bytes(b"different image")
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    result = run_gallery(gallery_root)
    assert result.returncode != 0
    assert "Gallery not generated" in result.stderr
    assert all(p.read_bytes() == content for p, content in before.items())
