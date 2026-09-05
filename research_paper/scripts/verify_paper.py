"""Check compiled paper integrity and render local page sheets for inspection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import fitz
from PIL import Image, ImageDraw

PAPER = Path(__file__).resolve().parents[1]
BUILD = PAPER / "build"


def main() -> None:
    log = (BUILD / "main.log").read_text(encoding="utf-8", errors="replace")
    bbl = (BUILD / "main.bbl").read_text(encoding="utf-8")
    assert "Fatal error" not in log
    assert not re.search(r"(Citation|Reference) .+ undefined|There were undefined", log)
    assert "Overfull" not in log, "Resolve overfull boxes before finalizing."
    bib_keys = re.findall(r"\\bibitem\{([^}]+)\}", bbl)
    assert len(bib_keys) == 12
    sources = [PAPER / "main.tex", *sorted((PAPER / "sections").glob("*.tex"))]
    cited = {key for source in sources for group in re.findall(r"\\cite\{([^}]+)\}", source.read_text())
             for key in group.split(",")}
    assert cited == set(bib_keys)

    provenance = json.loads((PAPER / "data" / "provenance.json").read_text())
    changed = [entry["path"] for entry in provenance["inputs"]
               if hashlib.sha256((PAPER.parent / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]]
    assert not changed, f"Source inputs changed since snapshot: {changed}"

    doc = fitz.open(BUILD / "main.pdf")
    pages = []
    thumbnails = []
    for number, page in enumerate(doc, 1):
        words = page.get_text("words")
        assert len(words) > 50, f"Sparse/orphan page {number}: {len(words)} words"
        assert all(0 <= w[0] < w[2] <= page.rect.width + 0.5 and
                   0 <= w[1] < w[3] <= page.rect.height + 0.5 for w in words), number
        pix = page.get_pixmap(matrix=fitz.Matrix(1.15, 1.15), alpha=False)
        picture = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        picture.save(BUILD / f"page-{number:02d}.png")
        picture.thumbnail((300, 425))
        tile = Image.new("RGB", (320, 455), "#dddddd")
        tile.paste(picture, ((320 - picture.width) // 2, 20))
        ImageDraw.Draw(tile).text((10, 440), f"Page {number}", fill="black")
        thumbnails.append(tile)
        pages.append({"page": number, "words": len(words), "width_pt": page.rect.width,
                      "height_pt": page.rect.height})
    for start in range(0, len(thumbnails), 8):
        sheet = Image.new("RGB", (1280, 910), "#dddddd")
        for offset, tile in enumerate(thumbnails[start:start + 8]):
            sheet.paste(tile, ((offset % 4) * 320, (offset // 4) * 455))
        sheet.save(BUILD / f"contact-sheet-{start // 8 + 1}.png")

    report = {"pdf_pages": len(doc), "references": len(bib_keys), "pages": pages,
              "unresolved_citations_or_references": False, "overfull_boxes": False,
              "input_hashes_unchanged": True, "verified_source_inputs": len(provenance["inputs"]),
              "pscad_runs_during_preparation": 0,
              "pdf_sha256": hashlib.sha256((BUILD / "main.pdf").read_bytes()).hexdigest()}
    (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "pages"}, indent=2))


if __name__ == "__main__":
    main()
