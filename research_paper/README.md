# SEIAN Research Paper

This independent manuscript folder does not change the simulator, dashboard,
PSCAD workspace, or the networking team's code. It uses a conventional LaTeX
`article` layout, numbered references, and separate section files so that the
paper can later be moved into a journal or conference template.

## Read and Edit

- `build/main.pdf`: compiled manuscript.
- `main.tex`: document format, title, author placeholders, and section order.
- `sections/`: the manuscript text.
- `references.bib`: researched scholarly sources and official documentation.
- `research_notes.md`: source audit, claim boundaries, and submission checklist.
- `data/evidence_snapshot.json`: frozen saved-result evidence, not new experiments.
- `data/provenance.json`: original input hashes and repository revision.
- `data/scenario_summary.csv`: machine-readable values behind the results table.
- `figures/` and `tables/`: generated publication assets.

The draft deliberately describes an **SDN-inspired, batch-driven LV switching
testbed**, not a completed real-time SDN microgrid. Numerical results come from
the six existing saved PSCAD scenarios. Full-rate summaries are distinguished
from decimated preview traces. Missing calibration, live controller transport,
relay feedback, and transactional command handling are discussed explicitly.

## Build the PDF

From this directory, with a TeX installation providing `pdflatex` and `bibtex`:

```powershell
.\build.ps1
```

The build is offline, disables shell escape and automatic MiKTeX package
installation, and places all document outputs in `build/`. LaTeX package/font
availability is a prerequisite. The supplied PDF can be read without TeX.

To regenerate plots and tables from the included frozen snapshot:

```powershell
py -B scripts/prepare_artifacts.py
.\build.ps1
```

Python dependencies for this optional step are listed in `requirements.txt`.
No PSCAD license, simulator imports, or running application is needed to build
the paper or regenerate its plots.

Optional PDF verification is available with `py -B scripts/verify_paper.py`
(requires PyMuPDF and Pillow). It checks resolved citations, page bounds,
overfull boxes, and unchanged source hashes, and renders inspection sheets
inside `build/`. The delivered 16-page PDF passed these checks with all 12
references resolved. Four original figures and seven tables are included.

## Refresh Evidence Deliberately

Only after reviewing new experiment results, refresh the snapshot from the
unchanged sibling project:

```powershell
py -B scripts/prepare_artifacts.py --snapshot
```

This command only reads existing project inputs and writes inside this paper
folder. It never starts PSCAD or Streamlit. It also records input SHA-256 hashes.
Review all numerical prose after a refresh: generated tables update
automatically, but prose is intentionally not rewritten by the script.

## Before Submission

Replace author, affiliation, and contact placeholders. Resolve the research
limitations and complete the checklist in `research_notes.md`. Freeze and
archive full-rate `.psout` files for each experimental condition; they are not
included in this manuscript folder. Confirm authorship and the contributions
of the networking colleagues. Select the venue, adjust the template, and review
all claims and references. No funding, ethics approval, public dataset release,
or publication status is asserted by this draft.
