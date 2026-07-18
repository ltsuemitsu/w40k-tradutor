# GUI Roadmap — Completing the Interactive Translation App Vision

This document tracks the current state of the desktop GUI and what is still needed to deliver the **full vision** described in [SCENARIOS.md](SCENARIOS.md).

The goal is a **professional, Warhammer 40k-flavored, interactive desktop application** that lets a translator comfortably execute all four core scenarios without touching the terminal after initial setup.

---

## Current Status (as of June 2026)

**Delivered (MVP + Project System):**
- Native PySide6 desktop app with grimdark 40k theme (`tradutor_desktop.py`)
- Tab-based workflow covering all 4 scenarios:
  - **Translate tab**: Prominent "Preserve Wiki & Core Mechanics" toggle (Scenario 1 vs 2), provider selector (DeepSeek / GLM), params, dry-run, real execution.
  - **Game Update tab** (Scenario 3): Free English-English diff + one-click generation of "Preserve ON" and "Full Narrative" delta files.
  - **Glossary tab**: Fully interactive table with **Preserve** checkbox per term (critical for 2.1), add/delete/filter, Wiki Sync button, direct save.
  - **Audit & Merge tab** (Scenario 4 + quality loop).
- **Project / Workspace system** (major step toward full vision) ✅:
  - New/Open/Save Project with `.w40k` / `.json` files + Recent submenu.
  - Remembers ALL paths (translate, update, audit, merge, glossary), preserve toggle, provider choice, batch/workers/temp, dry-run.
  - Prominent project bar with quick New/Open/Save buttons + live label.
  - Auto-restores last project on launch.
  - Full state collect/apply methods.
- **Direct integration + large file support** ✅:
  - TranslationWorker wired to Translate button with live signals (progress, log, stats). Still leverages the proven tradutor.py batch/parallel/skip/blacklist logic (your previous workflow) for 78k+ line files while giving GUI live feedback and cancel.
  - Interactive Blacklist Builder: Pre-scan huge files for EULA (hundreds of words), very long legal, placeholders; checkable table to build blacklist.json interactively.
  - Glossary "Populate first (AI)" button + strategy.
  - Live/manual Wiki scrape button (experimental on-demand + offline data browser).
- Live operation log + basic progress bar.
- Multi-provider surface + per-run key input.
- Robust launchers: `launch_gui.bat` (double-click friendly, auto-venv + auto-deps) + `launch_gui.ps1`.
- Core engine update so the `preserve` flag is respected first-class.
- CWD handling so the app works correctly when launched via .bat / shortcut / double-click.

**What's still missing for a "complete interactive translation app":**
- True project/workspace management
- High-quality interactive review tools (side-by-side, selective re-translation)
- Tight live integration (progress, cancellation, cost)
- Professional distribution (standalone .exe)
- Persistent & secure credential management
- Polish that makes daily use delightful

---

## Prioritized Remaining Work

### Phase 1 — Make it Feel Like a Real App (High Impact)

| # | Task | Why it matters | Effort |
|---|------|----------------|--------|
| 1 | **Project / Workspace System** | ✅ **COMPLETED** — Full state (all tabs, preserve toggle, params, provider). `.w40k` files, auto-restore last project, prominent UI bar, recent support foundation. | Done |
| 2 | **Direct Function Integration + Live Progress** | Currently uses subprocess for translation. Move key paths (translation, diff, glossary) to direct calls with Qt signals / callbacks. This enables:<br>• Accurate live item/token/cost counters<br>• Proper Cancel button<br>• Per-string status | High |
| 3 | **Interactive String Reviewer** | When Audit or Smart-Diff finds problems, show a nice side-by-side viewer (Original EN / Current PT / Proposed). Allow inline editing or "Send this string for re-translation". | High (core of "interactive") |
| 4 | **Persistent & Secure API Keys** | Named provider profiles (DeepSeek, GLM-4, etc.). Store keys securely (Windows DPAPI + keyring or simple encrypted file + master password on first use). No more pasting keys every time. | Medium |
| 5 | **Better Merge & Audit UX** | In Merge tab: show a real preview table of changes (before/after) with ability to uncheck individual items. Same for Audit results. | Medium |

### Phase 2 — Professional Polish & Distribution

| # | Task | Details |
|---|------|---------|
| 6 | **Standalone Packaging** | Use PyInstaller (or Nuitka) to produce a single `W40kTradutor.exe` that users can download and run without having Python installed. Include all data (wiki terms, etc.). Add an icon. |
| 7 | **Drag & Drop + Quality of Life** | Drag files onto the main window. "Use last glossary", "Load from current project", recent files menu. |
| 8 | **Live Cost & Statistics Dashboard** | During translation: show tokens used so far, estimated cost, items preserved vs translated, ETA. Persist per-project usage history. |
| 9 | **Glossary Power Features** | Bulk "Set Preserve for category X", "Find strings in current EN file that contain this term", export only wiki terms vs user terms, simple conflict detection. |
| 10 | **Theming & Branding** | More 40k flavor: subtle aquila/skull icons (simple SVG or Unicode), better typography, status colors that feel grimdark (red for "still English", gold for preserved, green for clean). First-run wizard with scenario explanations. |

### Phase 3 — Advanced / Nice-to-Have

- Run history with "Re-run with same settings" and "Compare two PT versions".
- Selective re-translation queue (user picks 5 problematic strings → translates only those with special context).
- Smart suggestions (e.g. "This string contains 3 glossary terms — consider preserving them").
- HTML/PDF export of audit reports.
- Built-in glossary term extractor from previous translations (revive some old logic in a nice UI).
- Optional: light web companion (local FastAPI + simple React page) for viewing reports on another device.

---

## Current Architecture Notes (for implementers)

- The app is intentionally thin on top of the existing tools right now (`subprocess` calls to `tradutor.py`, `diff_tool.py`, etc.).
- Moving to direct integration (Phase 1 item #2) is the biggest architectural change and the key to making the app feel truly "interactive".
- Glossary editing is already direct (good example).
- Delta generation for updates is already direct (another good example).
- Keep the CLI scripts working and powerful — the GUI is an ergonomic layer, not a replacement.

---

## Quick Wins You Can Do Today

1. Double-click `launch_gui.bat` (or right-click → Run with PowerShell the `.ps1`).
2. Go to the Glossary tab and flip some `preserve` checkboxes — this directly implements the model you asked for in scenario 2.1.
3. Use the Game Update tab to generate a delta and feed it back into Translate with the toggle in different states.
4. Create a desktop shortcut to `launch_gui.bat` for one-click access.

---

## How to Track Progress

Use the live todo system or keep this file updated. Major milestones could be:

- v0.5 "Usable for daily work" — Phases 1.1–1.3 + packaging basics
- v0.8 "Professional tool" — All of Phase 1 + packaging + key Phase 2 items
- v1.0 "Complete vision" — Most of Phase 2 + selected Phase 3 features

---

**Next step recommendation (June 2026):**

Focus first on **Project system + Direct integration + Interactive string viewer**. These three changes will make the biggest difference in turning "a launcher for the scripts" into "an interactive translation application".

When you're ready, say which item(s) from the table above you want to tackle next and I'll implement them.
