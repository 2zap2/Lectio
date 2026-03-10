---
title: "Lectio Sync — Project Completion Plan"
date: "2026-02-27T00:00:00Z"
status: completed
estimated_effort: "1–2 days"
---

# Lectio Sync — Project Completion

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

There is no PLANS.md in this repository. All conventions followed here are drawn from the planning skill embedded in `.agents/skills/planning/SKILL.md`.


## Purpose / Big Picture

The Lectio Sync project is a functional, working Python tool that converts a Lectio school schedule into iCalendar (`.ics`) feeds hosted on GitHub Pages. The core functionality is implemented and tests pass. What remains is to finish the project to a quality level appropriate for an open public GitHub repository: removing personal data that was accidentally committed, cleaning up the code, removing development-time scaffolding from the README, and adding standard project metadata (license, clean pyproject.toml).

After this plan is executed, someone new to the project can clone the repo, read the README, install dependencies, and run the tool in under ten minutes — without encountering any personal schedule data or confusing development notes.


## Progress

- [x] Milestone 1: Remove personal data from git history surface
- [x] Milestone 2: Code quality and structural improvements
- [x] Milestone 3: GitHub Actions cleanup
- [x] Milestone 4: README overhaul
- [x] Milestone 5: Project metadata and finishing touches
- [x] Milestone 6: Final validation — full test run, smoke test, and ICS spot-check


## Surprises & Discoveries

- `docs/execplans and HTML examples/HTML example of calendar for classrooms` contains a real Lectio student ID (`elevid=67380947456`) embedded in navigation links. This was not caught by the `.gitignore` (which only excludes `*.html`, not files without extensions). This file needs to be deleted or fully anonymised before the repo is considered safe for public viewing.
- `Avanceret skema - Lectio - TEC.html` is excluded by `.gitignore` (`*.html`) and has never been committed — confirmed via `git ls-files`. No action needed there.
- `install_skills.ps1` contains a syntax error: `[param(` instead of `param(`. PowerShell ignores a leading `[` before `param(` in some versions but it is non-standard and should be fixed.
- `config.py` defines two nearly identical functions (`load_config_from_env` and `load_config_from_env_with_overrides`) that each define local helper functions `_int` and `_bool` independently. This is pure code duplication. The first function can be made a thin wrapper around the second.
- All test files use `sys.path.insert(0, ...)` to inject the `src/` directory. This can be replaced with a `pytest` configuration that sets `pythonpath = src` in `pyproject.toml`, making tests cleaner and reducing boilerplate.
- The `.gitignore` has a truncated comment: `# Output (we want to COMMIT docs/calendar.ics for GitHub Pages)` with no associated pattern. This silently means the ICS output files are committed — which is intentional but should be made explicit.
- Two GitHub Actions workflows exist: `build-ics.yml` (for the offline HTML-in-repo path) and `update-calendar.yml` (for the live cookie-based fetch path). Both have scheduled triggers, meaning the workflow will fire twice a day on two different schedules. The `build-ics.yml` workflow will always skip because the `input/lectio.html` file does not exist in the repo. It should be removed or repurposed as a manual-only workflow, to avoid confusion.
- The README still contains its original "development dialogue" sections: "This README is the living spec for what we build in this conversation", "What I need from you to build this", and "Next step: Reply with…". These make the project look unfinished and expose design discussion that isn't meaningful to a new reader.
- `docs/sample_opgaver.html` uses school ID `681` and `elevid=123` but these are fake fixture values (exercise IDs `99990001`–`99990003`); they are not real personal data.


## Decision Log

- Decision: Delete `docs/execplans and HTML examples/HTML example of calendar for classrooms` entirely rather than anonymising it.
  Rationale: The file is a raw example extracted from a real browser session. It contains a real student ID (`elevid=67380947456`). Anonymising it meaningfully would require replacing dozens of embedded URL parameters. The file is referenced only in `classroom-finder-free-rooms-ics.md` as a context example; that reference can stay because the markdown still describes the structure without needing the raw HTML. Deleting the file is safer, simpler, and has no impact on the tool's functionality.
  Date/Author: 2026-02-27 / Planning agent

- Decision: Use `[tool.pytest.ini_options]` in `pyproject.toml` to set `pythonpath = ["src"]` instead of adding a `conftest.py` or `pytest.ini`.
  Rationale: The project already uses `pyproject.toml` as its single configuration file. Centralising pytest configuration there avoids introducing another top-level config file. `pythonpath` support was added in pytest 7.0; the project has no pinned pytest version, so this is safe.
  Date/Author: 2026-02-27 / Planning agent

- Decision: Remove `build-ics.yml` entirely rather than repurposing it.
  Rationale: The "HTML in repo" workflow path was designed for local development scenarios where someone would commit the HTML file. With the cookie-fetch workflow (`update-calendar.yml`) in place and the HTML excluded by `.gitignore`, the `build-ics.yml` path is dead code. Removing it eliminates scheduled builds that always silently skip.
  Date/Author: 2026-02-27 / Planning agent

- Decision: Add MIT license.
  Rationale: This is a personal tool with no stated license. A public GitHub repo without a license is "all rights reserved" by default, which makes it legally unclear whether others can learn from or adapt the code. MIT is the simplest open license that allows reuse; it is appropriate for a personal utility.
  Date/Author: 2026-02-27 / Planning agent


## Outcomes & Retrospective

All 6 milestones completed on 2026-02-27. 60/60 tests pass. One pre-existing bug was discovered and fixed during validation: `html_parser.py` was assembling the assignments SUMMARY in the order `{Opgavetitel} • {Hold} • {Elevtid} • {Status}` instead of the spec order `{Status} • {Opgavetitel} • {Hold} • {Elevtid}`. This was corrected as part of the validation pass.

All acceptance criteria met:
- Personal student ID `67380947456` removed from tracked files.
- `docs/execplans and HTML examples/HTML example of calendar for classrooms` deleted.
- `LICENSE` (MIT) created.
- README no longer contains development-dialogue sections.
- `build-ics.yml` deleted.
- `py -m lectio_sync --help` exits 0 without errors.
- Committed and pushed to `main` as `45335b8`.


## Context and Orientation

### What the project does

`lectio-sync` is a Python package (`src/lectio_sync/`) that:

1. Reads a Lectio "Advanced Schedule" HTML page (either from a local file or fetched live via a cookie).
2. Parses it into `LectioEvent` dataclass objects.
3. Writes iCalendar (`.ics`) files to `docs/` for three feeds: `calendar.ics` (schedule), `assignments.ics` (homework deadlines), `free_classrooms.ics` (rooms available right now).
4. GitHub Actions (`.github/workflows/update-calendar.yml`) fetches live data daily and commits the new ICS files so GitHub Pages serves them.

### Key file map

    src/lectio_sync/
      __init__.py          — package entry point (exports nothing public)
      __main__.py          — `python -m lectio_sync` entry point → calls cli.main()
      cli.py               — argparse CLI surface; orchestrates fetch + parse + write
      config.py            — Config dataclass + env-var loaders (has duplication)
      event_model.py       — LectioEvent dataclass
      html_parser.py       — HTML → LectioEvent list (schedule + assignments)
      ical_writer.py       — LectioEvent list → .ics string (RFC 5545 compliant)
      lectio_fetch.py      — HTTP fetch with cookie, gzip decompression, diagnostics
      cookie_refresh.py    — Playwright-based cookie capture + GitHub Secret update
      free_classrooms.py   — derives free-classroom events from schedule events

    tests/
      test_assignments_parser.py
      test_cookie_refresh.py
      test_free_classrooms.py
      test_html_parser.py    ← uses Avanceret skema - Lectio - TEC.html (local only)
      test_ical_writer.py
      test_lectio_fetch.py

    docs/
      calendar.ics           ← served via GitHub Pages; updated daily by GitHub Actions
      assignments.ics        ← served via GitHub Pages; updated daily by GitHub Actions
      free_classrooms.ics    ← served via GitHub Pages; updated daily by GitHub Actions
      sample_opgaver.html    ← sanitised fixture HTML (safe)
      assignments-plan.md    ← development notes (internal, keep or move)
      execplans and HTML examples/
        HTML example of calendar for classrooms   ← CONTAINS REAL elevid; DELETE
        classroom-finder-free-rooms-ics.md        ← safe (no student ID)
        cookie-header-refresh-options.md           ← safe
        fix-gh-actions-fetch-lectio.md             ← safe
        keep-lectio-sync-working-4-weeks.md        ← safe

    .github/
      workflows/
        update-calendar.yml    ← the primary CI workflow (keep and clean up)
        build-ics.yml          ← dead-code workflow (remove)
      copilot-instructions.md  ← agent formatting rules (keep)
      AGENT_FORMATTING.md      ← agent formatting rules (keep)

    pyproject.toml    ← missing: author, license, homepage, pytest config
    README.md         ← has development-dialogue sections; needs overhaul
    scripts/
      bootstrap.ps1             ← good; keep
      install_skills.ps1        ← syntax error `[param(` → `param(`
      refresh_cookie.ps1        ← good; keep
      update_ics.ps1            ← good; keep
      update_ics_and_push.ps1   ← check content

### Running tests

From the repo root, with `lectio-sync` installed in the active environment:

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest tests/ -v
    Expected outcome: all tests pass

`test_html_parser.py` requires `Avanceret skema - Lectio - TEC.html` to be present locally. It is excluded from git and will be skipped or error in CI. That test should be guarded with a `pytest.mark.skipif` when the file does not exist.


## Plan of Work

Work proceeds in five sequential milestones plus a final validation pass. Each milestone is independently verifiable.

### Milestone 1 — Personal data removal

The goal of this milestone is to ensure no real personal identifiers (student IDs) exist in committed static files.

**Step 1.1 — Delete the raw HTML example with real student ID.**

Delete the file `docs/execplans and HTML examples/HTML example of calendar for classrooms`. This file contains `elevid=67380947456`. There is no extension, so `.gitignore`'s `*.html` rule does not cover it. Simply delete it from disk and from git tracking.

    Working directory: C:\Users\Arthu\Lectio
    Commands:
      git rm "docs/execplans and HTML examples/HTML example of calendar for classrooms"

If the file is untracked: `Remove-Item "docs\execplans and HTML examples\HTML example of calendar for classrooms"`.

**Step 1.2 — Update `.gitignore` to document the ICS commit policy.**

The `.gitignore` has this truncated comment with no associated pattern:

    # Output (we want to COMMIT docs/calendar.ics for GitHub Pages)

Replace it with a full explanation:

    # The three ICS output files are intentionally committed so GitHub Pages can serve them.
    # GitHub Actions overwrites them with live data on each run.
    # Do NOT add docs/*.ics to .gitignore.

**Step 1.3 — Guard `test_html_parser.py` against missing fixture.**

`test_html_parser.py` requires `Avanceret skema - Lectio - TEC.html`. When the file does not exist (e.g., in CI), all three tests in the class fail with `FileNotFoundError`. Add a `pytest.mark.skipif` guard at the class level so those tests are skipped cleanly when the fixture is absent.

In `tests/test_html_parser.py`, directly after the `import` block, add:

    import pytest
    from pathlib import Path

    _FIXTURE = Path(__file__).resolve().parents[1] / "Avanceret skema - Lectio - TEC.html"

Then on `HtmlParserTests`, add:

    @pytest.mark.skipif(not _FIXTURE.exists(), reason="Local Lectio fixture not present")
    class HtmlParserTests(unittest.TestCase):
        ...


### Milestone 2 — Code quality and structural improvements

The goal is a cleaner, more maintainable codebase with no duplication and standard project tooling.

**Step 2.1 — Deduplicate `config.py`.**

`load_config_from_env` and `load_config_from_env_with_overrides` each define identical `_int` and `_bool` helpers. Refactor so `load_config_from_env` is a one-line wrapper:

In `src/lectio_sync/config.py`, remove the body of `load_config_from_env` and replace it with a delegation call:

    def load_config_from_env() -> Config:
        return load_config_from_env_with_overrides()

This preserves the public API while removing ~40 lines of duplicate code.

**Step 2.2 — Fix `install_skills.ps1` syntax error.**

In `scripts/install_skills.ps1`, find the line:

    [param(

and replace it with:

    param(

The closing `)]` on the last parameter must also be changed to `)` to match.

**Step 2.3 — Add pytest configuration to `pyproject.toml`.**

Add the following section to `pyproject.toml`:

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    pythonpath = ["src"]

This lets pytest find the `lectio_sync` package without each test file injecting `sys.path`. After this, the `sys.path.insert(0, ...)` lines in every test file can be removed.

Remove from each of the six test files:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

The `from pathlib import Path` line in `test_html_parser.py` should be kept because `_FIXTURE` uses it; just remove the `sys.path.insert` line.

**Step 2.4 — Verify no encoding corruption in `html_parser.py`.**

The source file appears clean (verified by `Select-String`), but visually confirm that `_compose_title` uses the correct Danish Unicode string `"lærer:"` (U+00E6) rather than a mojibake sequence. Open `src/lectio_sync/html_parser.py` and search for `"l" followed by an AE character`. If the match is `"lærer:"` and `"lærere:"`, no change is needed. If it reads `"lÃ¦rer:"`, the file has been saved with incorrect encoding and must be re-saved as UTF-8.

**Step 2.5 — Minor: remove redundant `# pyright: reportMissingImports=false` comments.**

These appear in test files at the top. Because `pyproject.toml` will now configure `pythonpath = ["src"]`, Pylance/Pyright will resolve the imports correctly and these suppression comments are no longer needed. Remove them from all test files.


### Milestone 3 — GitHub Actions cleanup

The goal is a single, clear CI workflow with no dead code.

**Step 3.1 — Delete `build-ics.yml`.**

    Working directory: C:\Users\Arthu\Lectio
    Command: git rm .github/workflows/build-ics.yml

This workflow requires `input/lectio.html` which is excluded from the repo by `.gitignore`. Every scheduled run silently skips. It is dead code and a source of confusion.

**Step 3.2 — Review and clean up `update-calendar.yml`.**

The workflow looks good overall. Apply the following smaller improvements:

- Confirm the `time gate` step uses `zoneinfo` which is stdlib in Python 3.9+. Since the workflow installs Python 3.11, this is fine.
- Add a comment at the top explaining this is the *only* automated workflow now that `build-ics.yml` is deleted.
- The `git add docs/assignments.ics docs/free_classrooms.ics` step will fail silently if `--assignments-out` was not generated. Consider using `git add docs/` instead, or add `--force` only if both optional outputs might not exist.

Actually, `git add` on non-existent files does error. Change the commit step to:

    git add --force docs/calendar.ics docs/assignments.ics docs/free_classrooms.ics || git add docs/calendar.ics

Or more cleanly, use a glob:

    git add docs/*.ics


### Milestone 4 — README overhaul

The goal is a README that serves as a helpful user guide for someone who has just cloned the repo — not a development conversation transcript.

**What to remove:**

- The line: `This README is the living spec for what we build in this conversation.`
- The section `## What I need from you to build this` (and all seven subsections beneath it).
- The section `## Next step` at the very end.
- The speculative note in `## Project structure (planned)`: remove `(planned)` from the heading, remove the sentence "We'll add these files as we implement:", and update the list to reflect actual implemented files (tests, scripts, free_classrooms, etc.).
- Under `## Running daily at 08:00`, the note "If you keep HTML local only, disable the scheduled workflow and use Task Scheduler + `scripts/update_ics_and_push.ps1`." is accurate but should reference the one remaining workflow by name.

**What to add:**

Add a new `## Getting Started` section immediately after the goal section, with:

1. Prerequisites: Python 3.11+, `beautifulsoup4`, `lxml`, `python-dateutil` (optionally `playwright` for cookie refresh).
2. Install: `py -m pip install -e .`
3. Local run (file mode): the `update_ics.ps1` command.
4. Subscribe URL pattern: `https://<username>.github.io/<repo>/calendar.ics`
5. GitHub Actions setup: set `LECTIO_SCHEDULE_URL` and `LECTIO_COOKIE_HEADER` secrets; run `update-calendar.yml` via `workflow_dispatch` to verify.

**What to fix:**

- Section heading `## Project structure (planned)` → `## Project structure`
- Remove `Optional later: tests/ (if you want automated tests)` — tests exist.
- Keep all the parsing rules (sections 1–10) as-is; they are the authoritative specification and are valuable reference material.

**Format note:** The existing encoding issues visible in the terminal (`â€¢` for `•`, `Ã¸` for `ø`) are rendering artifacts from the Windows terminal reading a UTF-8 file. The README source uses `\u2022` bullet (`•`) and proper Danish characters. Confirm the README is saved as UTF-8 (no BOM) and no literal `â€¢` sequences appear in the raw file.


### Milestone 5 — Project metadata and finishing touches

**Step 5.1 — Add MIT license.**

Create `LICENSE` at the repo root:

    MIT License

    Copyright (c) 2026 <your name>

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

**Step 5.2 — Update `pyproject.toml` with metadata.**

Add fields to the `[project]` table:

    authors = [{ name = "Your Name" }]
    license = { text = "MIT" }
    keywords = ["lectio", "icalendar", "ics", "calendar", "school"]
    classifiers = [
      "Programming Language :: Python :: 3",
      "License :: OSI Approved :: MIT License",
      "Operating System :: OS Independent",
    ]

    [project.urls]
    Homepage = "https://github.com/<username>/<repo>"
    "Bug Tracker" = "https://github.com/<username>/<repo>/issues"

Replace `<username>` and `<repo>` with the actual GitHub values.

**Step 5.3 — Bump version from `0.1.0` to `1.0.0`.**

The tool is working and has tests. `0.1.0` signals "not ready yet". Change to `1.0.0` in `pyproject.toml` to reflect that the project is complete.

    version = "1.0.0"

**Step 5.4 — Update `docs/assignments-plan.md`.**

This file in `docs/` is a development plan document for the assignments feature. It was useful during development. For a finished project it either:
- Belongs under `docs/execplans and HTML examples/` or `.agents/plans/` rather than at the top of `docs/` (where calendar outputs live), or
- Can be left where it is, acknowledged as a design document.

Move it to `.agents/plans/assignments-feature.md` to declutter `docs/`.

    Working directory: C:\Users\Arthu\Lectio
    Command: git mv docs/assignments-plan.md .agents/plans/assignments-feature.md


### Milestone 6 — Final validation

**Run the full test suite and observe passing results:**

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest tests/ -v
    Expected: all tests pass; the three html_parser tests are skipped cleanly
    if the fixture HTML is not present.

**Spot-check the CLI with an empty ICS:**

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m lectio_sync --help
    Expected: prints usage, no errors, exit code 0.

**Verify no personal student ID is present in tracked files:**

    Working directory: C:\Users\Arthu\Lectio
    Command: git grep -r "67380947456"
    Expected: no output (empty match set).

**Commit all changes:**

    Working directory: C:\Users\Arthu\Lectio
    Commands:
      git add -A
      git commit -m "Project completion: remove personal data, clean code, overhaul README, add license"
      git push


## Concrete Steps

The following ordered list reflects exact execution order. Check each off as done.

1. `git rm "docs/execplans and HTML examples/HTML example of calendar for classrooms"`
2. Update `.gitignore` comment (Milestone 1.2).
3. Edit `tests/test_html_parser.py` to guard with `pytest.mark.skipif` (Milestone 1.3).
4. Simplify `src/lectio_sync/config.py` — make `load_config_from_env` delegate to `load_config_from_env_with_overrides` (Milestone 2.1).
5. Fix `scripts/install_skills.ps1` syntax error `[param(` → `param(` (Milestone 2.2).
6. Add `[tool.pytest.ini_options]` to `pyproject.toml` (Milestone 2.3).
7. Remove `sys.path.insert` lines from all six test files (Milestone 2.3).
8. Remove `# pyright: reportMissingImports=false` lines from test files (Milestone 2.5).
9. Verify encoding in `html_parser.py` (Milestone 2.4).
10. `git rm .github/workflows/build-ics.yml` (Milestone 3.1).
11. Update `update-calendar.yml` commit step to use `docs/*.ics` glob (Milestone 3.2).
12. Overhaul `README.md`: remove development dialogue sections, add Getting Started, update Project structure heading (Milestone 4).
13. Create `LICENSE` (MIT) (Milestone 5.1).
14. Update `pyproject.toml` metadata: authors, license, keywords, classifiers, URLs (Milestone 5.2).
15. Bump version to `1.0.0` (Milestone 5.3).
16. `git mv docs/assignments-plan.md .agents/plans/assignments-feature.md` (Milestone 5.4).
17. Run full validation (Milestone 6).
18. Commit and push all changes.


## Validation and Acceptance

The project is complete when:

1. `py -m pytest tests/ -v` reports all tests passing (or explicitly skipped for the html_parser tests when the fixture is absent). No failures.
2. `git grep "67380947456"` returns no matches.
3. `docs/execplans and HTML examples/HTML example of calendar for classrooms` does not exist in the working tree.
4. `LICENSE` exists and contains "MIT License".
5. `README.md` does not contain the text "living spec for what we build in this conversation" or "What I need from you".
6. `.github/workflows/build-ics.yml` does not exist.
7. `py -m lectio_sync --help` exits 0 without errors.


## Idempotence and Recovery

All file edits in this plan are idempotent: editing a file a second time to the same state produces the same result. The `git rm` and `git mv` steps will output "fatal: pathspec ... did not match" if already applied; those errors can be ignored.

If a step fails mid-way, inspect `git status` to see what has been staged, then either revert (`git checkout -- <file>`) or continue from the next step. No database migrations or destructive operations are involved.


## Artifacts and Notes

`config.py` before refactor (for reference):

    def load_config_from_env() -> Config:
        import os
        lectio_html_path = Path(os.environ.get("LECTIO_HTML_PATH", ""))
        ...
        # ~40 lines of duplicated logic

After refactor:

    def load_config_from_env() -> Config:
        """Load configuration from environment variables with default values."""
        return load_config_from_env_with_overrides()


## Interfaces and Dependencies

No new external dependencies are introduced. All changes are to existing files and project configuration. The public interface of `lectio_sync` (importable modules, CLI flags, ICS output format) is unchanged.

`pyproject.toml` will gain a `[tool.pytest.ini_options]` section. This requires pytest ≥ 7.0 for `pythonpath` support. Verify with `py -m pytest --version`; both 7.x and 8.x are fine.
