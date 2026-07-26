# W40K Rogue Trader Translator — Scenarios, Optimized Flows & GUI Design

This document defines the **exact user scenarios** the desktop application must support perfectly. It also specifies the glossary model improvements, provider support, optimizations, and how the GUI will surface each flow.

---

## 1. Glossary Model Improvements (Foundational — Scenario 2.1)

### Current State (Problems)
- Wiki terms from `wiki_sync.py` are created with:
  ```json
  {
    "term_english": "Plasma Gun",
    "term_translated": "Plasma Gun",
    "category": "weapon",
    "preserve": true,
    "source": "wiki"   // already present on many entries
  }
  ```
- The translator (`SmartGlossary.should_preserve`) **ignores** the `preserve` boolean. It only looks at `--mode preserve` + `--preserve-cats` whitelist + exact term match by category.
- Having `term_translated == term_english` for preserved terms feels semantically wrong.
- No clear "this is a wiki/mechanic term that the user wants to protect via toggle".

### Target Model (Minimal, Backward Compatible)
Every glossary entry will support:

```json
{
  "term_english": "Plasma Gun",
  "term_translated": "Plasma Gun",     // Still useful for prompt consistency + future localized display
  "category": "weapon",
  "preserve": true,                    // FIRST-CLASS FLAG: when active, skip LLM for exact matches
  "source": "wiki",                    // "wiki" | "manual" | "seed" | "auto"
  "context": "WH40K Wiki — weapon",
  "confidence": "high",
  ...
}
```

**Behavior rules (enforced in core):**
- `preserve: true` → this term is a candidate for protection.
- A global/runtime **"Preserve Wiki & Core Mechanics"** toggle (in GUI and CLI `--preserve-wiki`) activates protection for all terms where `preserve == true` **or** category is in the active preserve list.
- When protection triggers on a string:
  - The original English text is copied to output.
  - Marked with `_preserved: true` (or `_wiki_preserved`).
  - Never sent to the LLM.
- The glossary is **always** injected (top N terms) into the system prompt for consistency, regardless of the preserve toggle.
- User can flip `preserve` per term in the GUI (or bulk by category).
- `wiki_sync` will set `preserve: true` + `source: "wiki"` by default for new terms.
- `term_translated` can differ from English for user-added terms that still want consistency help even when preserved (rare).

**Migration**: Old entries without `preserve` are treated as `preserve: false` unless their category is in the classic preserve list (for compat).

This directly solves the user's requirement: **flag (wiki_term) + simple toggle controls whether we skip translation**.

---

## 2. The Four Core Scenarios

### Scenario 1: Full New Translation (Maximum Translation, Glossary Consistency)

**Goal**: Translate an entire new English JSON (e.g. first localization of a data file or major overhaul) into PT-BR. Everything possible should be translated, but the glossary must guarantee high consistency from the first string to the last.

**Key Characteristics**:
- Preserve toggle = **OFF**.
- Narrative, descriptions, conversations, UI text, etc. → all go to LLM.
- Glossary still provides strong consistency (spelling of names, tone, recurring phrases).
- Use lower temperature (0.1–0.2).
- Dry-run recommended first to validate tag protection.

**Optimized Flow (GUI)**:
1. Open/Create Project (remembers paths + glossary).
2. Select full `enGB.json` (or drag-drop).
3. Select (or create) `glossary.json`.
4. In Translate panel:
   - Provider selector (DeepSeek / GLM-Zhipu + custom).
   - **Preserve Wiki & Core Mechanics** toggle = **unchecked**.
   - Batch size, workers, temperature, model.
   - Optional: "Inject full glossary for consistency" (recommended ON).
5. (Strongly recommended) Run **Dry Run** first — review a sample of protected tags and output format.
6. Click **Start Translation**.
7. Live progress + structured log (tokens, cost estimate, preserved count = 0 or very low, success/fail).
8. On completion: the output `ptBR.json` is ready. Project remembers it.
9. Optional: immediately run Audit (see below).

**Artifacts produced**:
- `ptBR.json` (or user-named).
- Updated `glossary.json` (if any auto-extraction is re-enabled later).
- Run log / stats (saved in project).

---

### Scenario 2: Full New Translation with Wiki/Mechanic Preservation (Most Common)

**Goal**: Same as Scenario 1, but **game mechanics stay in English** while narrative text is translated. This is the desired output for Rogue Trader localization (players expect "Plasma Gun", "Weapon Skill", talents, etc. to remain recognizable).

**Key Characteristics**:
- Preserve toggle = **ON** (default for most projects).
- Exact matches against glossary terms that have `preserve: true` (or matching categories: weapon, talent, skill, ability, attribute, lore, armour, etc.) are **skipped** — original English copied.
- Descriptions, conversations, flavor, quest text, etc. → translated.
- Still gets full glossary consistency for the parts that *are* translated.
- Much lower token usage than Scenario 1.

**Optimized Flow (GUI)**:
- Identical to Scenario 1, except:
  - **Preserve Wiki & Core Mechanics** toggle = **checked** (big prominent control).
  - In the log you will see "Preserved: XXX" count (the wiki + mechanic terms).
- The same project can be re-run with the toggle flipped if the user changes their mind later (using `--resume` / existing output as base).

**How preservation actually works (no LLM call for protected strings)**:
```python
if preserve_toggle_active and glossary.should_preserve(text):
    output[key] = {"Offset": ..., "Text": original_english_text, "_preserved": True}
    continue   # never reaches TranslationEngine
```

---

### Scenario 3: Game Update / Patch — Detect Changes & Generate Minimal Work (Zero LLM Cost for Diff)

**Goal**: When the game releases a new data file (`enGB_new.json`), quickly figure out exactly what needs re-translation without re-processing the entire game or wasting tokens on unchanged content.

**Key Characteristics**:
- Pure structural comparison: English vs English (by UUID key + Text content).
- No AI involved in the diff step.
- Produces small "delta" JSON files containing only the strings that are new or changed.
- User can then translate those deltas under either preservation mode (Scenario 1-style or Scenario 2-style).

**Optimized Flow (GUI — "Game Update" Panel)**:
1. Load:
   - **New English** (patch file)
   - **Previous English** (the exact file that was used to produce the current translation)
   - (Optional) Current `ptBR.json` for context
2. Click **Analyze Changes** (instant).
   - Report:
     - New UUIDs: N
     - Modified text (existing UUID): M
     - Removed (usually ignore): R
     - Unchanged: U
3. **Generate Delta Files** (one-click options):
   - "Delta - Preserve Wiki ON" → small JSON ready to translate with preserve toggle **ON**
   - "Delta - Full Narrative (no preserve)" → small JSON ready to translate with preserve toggle **OFF**
   - Or a single combined delta + choice later.
4. The delta files contain the original English strings + metadata (`_status: "new" | "modified"`, `_old_text` if modified).
5. User then goes to the normal **Translate** panel, loads the tiny delta as input, chooses the matching preserve setting, runs the translation → produces a corrections file.
6. Proceed to Scenario 4 (Merge).

**Optimizations realized here**:
- Diff is pure Python (dict key + string compare or hash) — milliseconds even on large files.
- Only the delta ever touches the LLM.
- You can maintain two parallel correction streams if some patch content needs different treatment.

---

### Scenario 4: Merge Corrections (Safe Application of Retranslated Deltas)

**Goal**: Take one or more correction / delta-translation results and apply them cleanly into the main translated file.

**Key Characteristics**:
- Visual preview of every change before applying.
- Automatic backup of the base file.
- Guard against common mistakes (e.g. trying to merge an untranslated validator output).
- Supports multiple correction files in one merge.

**Optimized Flow (GUI)**:
1. Open **Merge / Apply Fixes** panel.
2. Select:
   - Base file (your main `ptBR.json`)
   - One or more Corrections files (outputs from translating deltas, or manual fixes)
3. Click **Preview Changes**.
   - Table shows:
     - Key (truncated)
     - Issue / reason (from `_issue`, `_status`, etc.)
     - Old text (in base)
     - New text (from correction)
     - Action (Update / Add / Skip)
4. Review, deselect anything you don't want.
5. Click **Apply & Backup**.
   - Timestamped backup created (`ptBR.json.20260616_143022.backup`).
   - Changes applied atomically.
   - Report of how many altered / added / skipped.

**Current core** (`merge.py`) already does most of this safely. The GUI makes the preview and multi-file support excellent.

---

## 3. Supporting Flows (Used Across Scenarios)

### Audit / Quality Check
- Load original EN + current PT + glossary.
- Run `diff_tool --audit` equivalent.
- Categorized results (Not translated / Partial English / Broken tags / Glossary preserved (good) / OK).
- Side-by-side viewer per row.
- "Export Problems for Retranslation" button → feeds Scenario 3/4.

### Glossary Management (Always Available)
- Full table view (filter by category, search, show only `preserve:true`).
- Edit any field inline, especially the **Preserve** checkbox.
- Add / Remove.
- Bulk actions (set preserve on all "weapon", etc.).
- **Wiki Sync** button (with review table for new candidates).
- Import / Export CSV (great for mass editing in Excel).
- Stats: total, preserved count, per-category breakdown.

### Provider & Key Management
- Global Settings (or per-project override):
  - Named providers:
    - DeepSeek (recommended for speed/cost)
    - Zhipu GLM (glm-4-plus, glm-4-air, etc.)
    - Custom (any OpenAI-compatible)
  - Secure key storage (not plain text in env if possible).
  - Model selector per provider.
- In every Translate run the user sees and can override the active provider.

---

## 4. Overall Optimizations & Architecture Principles

1. **Never translate what doesn't need it** (preserve logic + update diff).
2. **English-English diff is authoritative and free**.
3. **Glossary is loaded once** and used for two purposes:
   - Local fast skip/preserve decisions.
   - Prompt injection for the strings that *do* go to the LLM.
4. **Small delta artifacts** for patch work.
5. **Atomic saves + resume** are non-negotiable (already excellent).
6. **One project file / workspace** remembers all paths, last-used provider + toggle state, glossary reference.
7. **GUI never blocks** — long-running operations (translation, wiki sync, large audits) run in background threads with progress + cancel.
8. **CLI scripts remain first-class** — the desktop app calls the same logic (or thin wrappers). Power users can still script.

---

## 5. GUI Structure & 40k Theme Direction

### Aesthetic
- Base: near-black (#0a0a12), charcoal, deep burgundy (#3a1f1f).
- Accents: Imperial gold (#c9a84c, #d4af37), parchment for cards/text areas.
- Text: high-contrast off-white / light parchment.
- Danger: blood red for "still English", "tag broken", errors.
- Subtle gothic framing, small icons (skull, aquila, cog if we embed simple assets or use Unicode).

### Main Areas (Proposed Layout)
- Top bar: Project name + current glossary stats (X terms, Y preserved) + Provider indicator + Settings gear.
- Left sidebar or top tabs:
  - **Dashboard**
  - **Translate** (Scenarios 1 & 2 — the big preserve toggle lives here)
  - **Game Update** (Scenario 3)
  - **Glossary**
  - **Audit**
  - **Merge** (Scenario 4)
- Central area changes per tab.
- Bottom / side: Live log + progress bar (visible during any long operation).
- Big obvious action buttons in each major flow.

### Key Controls
- **Preserve Wiki & Core Mechanics** — large, always-visible checkbox or prominent switch in Translate + Update flows.
- Provider dropdown + "Manage Keys..." button.
- Dry-run mode as a first-class safe choice.
- File pickers with "Use current project reference" quick buttons.

---

## 6. Implementation Notes for the Desktop App

- The GUI will be a separate entry point (the legacy desktop entry point was removed in v2.0; the app now launches via `w40k_translator.py`).
- Core logic lives in a clean `core/` package (or the existing modules are made import-friendly).
- First version can drive the existing `tradutor.py`, `diff_tool.py`, etc. via function calls + threading (preferred) or subprocess + stdout parsing (quick start).
- Glossary editing will directly use the data functions from `glossary_manager.py` + the new model.
- All long operations report progress via callbacks / Qt signals or Flet equivalents.
- Project state stored in a small JSON next to the glossary or in `%APPDATA%`.

---

## 7. Success Criteria (for each scenario)

- User can complete the full flow for Scenarios 1–4 **without ever opening a terminal** after initial setup.
- Preserve decisions are obvious and controllable via one toggle.
- Patch updates only cost tokens on actual new/changed content.
- Glossary `preserve` flag is respected and editable.
- Both DeepSeek and GLM/Zhipu keys work cleanly.
- 40k grimdark theme is consistent and immersive without hurting usability.
- Safety (dry-run, previews, backups) is excellent.

---

**This document is the contract.** Any GUI implementation or core changes should map directly back to these flows.

Next: Implement the desktop GUI (starting with structure + Translate + Glossary tabs, using the scenarios above as the primary user journeys).
