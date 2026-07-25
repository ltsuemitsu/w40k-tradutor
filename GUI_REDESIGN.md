# GUI Redesign — Project-Centric Translator

> Status: **design proposal** (v1). No code written yet.
> Goal: kill the *"I don't know wtf I'm doing"* feeling.

The current GUI mirrors the **tools** (tabs per script). The redesign mirrors the
**user's journeys**. The engine (`tradutor.py`, `diff_tool.py`, `merge.py`,
`glossary_manager.py`, `wiki_sync.py`, `scripts/`) stays **untouched** — the new
GUI orchestrates it via subprocess and direct imports.

---

## 1. Design principles

1. **Project-centric, app owns the folder.**
   The user never chooses output paths per run. The app manages one folder per
   translation project and knows where everything lives. No more scattered
   `ptBR_final_FINAL2.json` chaos.

2. **State-first: every screen answers three questions.**
   *Where am I? What just happened? What happens next?*
   The Home dashboard is the anchor; every journey ends by returning Home with a
   clear new state.

3. **Free before paid.**
   Everything free (Pre-Scan, glossary check, fullize, diff, audit, merge) is
   shown *before* anything that costs API money. Every paid action shows a
   cost/scope estimate first and requires one explicit click.

4. **One primary action per screen.**
   Engine knobs (workers, batch sizes, save-every) never appear in journeys.
   They live in Settings, defaulting to "auto".

5. **Advanced stays reachable, out of the way.**
   Glossary editing, wiki sync, model profiles: one click deeper, never in the
   main flow.

6. **Never lose work.**
   Resume by default; backups before every merge; the app remembers what has
   been done (project.json), so re-opening the app = continuing, not starting
   over.

---

## 2. The Project (folder contract)

One folder per translation project. Created by the app, or **adopted** from
existing files (see §3).

```
RogueTraderPT/                  ← the project folder
  project.json                  ← state (tracks exact file paths)
  input/
    enGB_1.6.1.514.json         ← current game dump (versioned name kept)
  output/
    ptBR_preserved_1.6.1.514.json  ← master Preserved track (versioned)
    ptBR_full_1.6.1.514.json       ← master Full track (versioned)
  patches/
    2025-09-10_delta.json       ← EN→EN delta
    2025-09-10_delta_pt.json    ← translated delta
  audit/
    2025-09-12_audit.json       ← categorized report
    2025-09-12_retry_uuids.json ← failed/identical/suspect UUID list
  release/
    traducao_FULL_1.6.1.514.zip       ← mod-page-ready package
    traducao_PRESERVED_1.6.1.514.zip
  backups/
    2025-09-10_pre-merge_ptBR_full_1.6.1.514.json
```

**Versioned-name convention (locked 2026-07-25):** files keep their
version-carrying names (`enGB_<ver>.json`, `ptBR_<track>_<ver>.json`) so the
game version is visible at a glance. The app **never renames or copies** the
user's files — `project.json` tracks the exact current path of the input and
each track, and every flow resolves paths from there. Renames happen only on
an explicit version bump (Patch Day merges into `ptBR_<track>_<new_ver>.json`;
the previous version's master is preserved in `backups/`).

`project.json` (owned by the app, never edited by hand):

```json
{
  "app_version": "2.0",
  "game_profile": "rogue_trader",
  "game_version": "1.3.2",
  "glossary": "glossary.json",
  "glossary_stamp": {"terms": 2694, "built_for": "rogue_trader"},
  "input": {"file": "input/enGB.json", "original_name": "enGB_1.6.1.514.json", "sha256": "…", "strings": 70412},
  "tracks": {
    "preserved": {"status": "done", "updated": "2025-09-01", "translated": 52100, "skipped_free": 18312},
    "full":      {"status": "done", "updated": "2025-09-01"}
  },
  "last_audit": {"date": "2025-09-12", "failed": 12, "identical": 340, "suspect": 88},
  "releases": [{"version": "1.4", "date": "2025-09-13", "track": "full"}]
}
```

This file is what lets the Home screen say *"Preserved 100% ✓ · Full 100% ✓ ·
12 strings failed last audit"* instead of the user remembering.

**Filename convention**: game dumps and outputs carry the game version in the
filename (`enGB_1.6.1.514.json`, `ptBR_full_1.6.1.514.json`). The app copies
the input to the canonical `input/enGB.json` but records the source filename
in `input.original_name` and auto-detects `game_version` from it (editable
from the Home dashboard when detection fails).

---

## 3. Adopting existing files (first-run onboarding)

For users who already translated (the maintainer included):

**"Adopt existing translation"** dialog:

1. Point at an existing folder or loose files.
2. The app detects which files look like EN dumps / preserved / full outputs
   (schema sniffing: `{strings: {uuid: {Text}}}` + PT-BR heuristics + preserve-map).
3. User confirms the mapping → app **copies** (never moves) them into the
   project structure, backfills `project.json`, done.
4. From then on, everything is managed.

---

## 4. The screens

### 4.0 Home (dashboard)

The app opens here. Always.

```
┌──────────────────────────────────────────────────────────┐
│  W40K TRANSLATOR                           [Settings ⚙]  │
│                                                          │
│  INPUT    enGB.json ✓ 70,412 strings · game v1.3.2       │
│  TRACKS   Preserved ✓ 100%     Full ✓ 100%               │
│  AUDIT    ⚠ 12 failed · 340 identical · 88 suspect       │
│  GLOSSARY 2,694 terms · Rogue Trader ✓                   │
│                                                          │
│  Fluxo: ① traduzir → ② auditar → ③ publicar              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────┐ ┌────────┐ │
│  │ ① Nova      │ │ ② Corrigir &│ │ ③ Final.│ │ ④ Dia  │ │
│  │ Tradução    │ │ Auditar     │ │& Publicar│ │de Patch│ │
│  └─────────────┘ └─────────────┘ └─────────┘ └────────┘ │
│  [ ⑤ Glossário (construção e manutenção) ]               │
└──────────────────────────────────────────────────────────┘
```

Buttons light up / grey out based on state (e.g. ② needs an output; ③ needs a
clean-or-confirmed audit — see the audit gate below; ④ needs an output).
Greyed-out buttons explain *why* on hover — that alone removes half the
confusion.

**Journey order matters (locked 2026-07-25):** the canonical flow is
**① translate → ② audit & fix → ③ package**. A release should ship 100%
audited; ④ Patch Day feeds new deltas back into ①→②→③; ⑤ Glossary is its own
space (maintenance + auto-build), not a step in the flow.

### 4.1 ① New Translation (wizard, 3 steps)

The **primary journey**. Preserve-mode is the default and first-class.

- **Step 1 — Input.** Shows `input/enGB.json` if present, or "drop your
  enGB.json here" (with a helper: *"find it in
  …\WH40KRT_Data\StreamingAssets\Localization"*). Track choice:
  ◉ Preserved (recommended — mechanics/wiki names stay EN) / ○ Full only later.
- **Step 2 — Pre-Flight (free).** Runs Pre-Scan + glossary health:
  - `52,100 strings to translate · 18,312 free (skips + exact terms)`
  - `Glossary coverage: 96% ✓` (see §5 for the low-coverage warning)
  - `New term candidates: 41 found` → optional review
  - **Cost estimate**: `≈ $1.20 on deepseek-v4-flash · ~3.5 h`
  - Model picker (profiles only; no knobs).
- **Step 3 — Run.** Progress bar + live counters (done/free/failed/ETA/cost so
  far), **Pause** and **Stop** (resume-safe by engine design). On finish:
  *"Preserved track done ✓ — next: audit & fix before publishing"* → journey ②.

### 4.2 ② Fix & Audit (comes BEFORE packaging)

Where placeholder-mangling (`$TERM4$`, `{mf|him|her}` leftovers) gets cleaned.
**Runs before every release** — see the audit gate in §4.3.

1. **Run audit** (free) → categorized table:
   `Failed (API errors) · Identical (EN = PT) · Suspect (leaked placeholders,
   broken tags, gender-tag artifacts)`.
2. Each row shows EN vs PT side by side; filter by category; select all/none.
3. **Retry selected** → exports UUID list → engine re-translates only those
   (`--retranslate-map`) → auto-merge back with backup.
4. **Edit manually** for one-off fixes (inline editor, writes through merge
   path so backups still happen).
5. Audit result + timestamp recorded in `project.json.last_audit` — this is
   what the release gate checks.

### 4.3 ③ Finish & Release (gated by audit)

- **Fullize card**: *"Turn your Preserved translation into 100% PT — FREE, no
  API."* One button → `output/ptBR_full.json`.
- **Release card**: pick track (Preserved / Full), version tag → **Export mod
  package**: zip containing the file already renamed to `enGB.json` +
  auto-generated `INSTALL.txt` (backup original, drop into Localization
  folder) + optional changelog stub. Built for uploading straight to Nexus.
  Exported zips follow the user's naming convention
  `traducao_<TRACK>_<game_version>.zip` (e.g. `traducao_FULL_1.6.1.514.zip`),
  using the `game_version` recorded in project.json.
- **Audit gate (locked 2026-07-25)** — a release ships 100% audited:
  - Outputs changed since the last audit (or audit never ran) → **export
    blocked**: *"Rode a auditoria antes de publicar."*
  - Last audit has `failed`/`suspect` > 0 → counts shown, export requires an
    explicit *"exportar mesmo assim"* confirmation (some flags are false
    positives, e.g. proper nouns in "identical" — override exists but is
    never the default path).
  - Clean audit newer than the outputs → export flows normally.
- Shows the diff vs. the previous release ("312 strings changed since v1.3").

### 4.4 ④ Patch Day

The money-anxiety killer.

1. Drop the **new** `enGB.json` (old one is already archived in `input/`).
2. Free diff → **"The patch changed 1,240 of 70,412 strings. Translating only
   the delta ≈ $0.08."**
3. Run → translate delta → **auto-merge into both masters with timestamped
   backup** → both outputs + project.json updated.
4. Ends with: *"Your translation is current again ✓ — export a new release?"*

### 4.5 ⑤ Glossary (its own space — maintenance + auto-build)

The glossary is a first-class citizen, not a side tool. For Rogue Trader it is
already built (2,694 terms); this space is what keeps it alive for DLCs and
future games.

- **Term table**: search/filter by category, preserve/inline flags, add / edit /
  remove.
- **Wiki seed** button (existing live-wiki fetch).
- **Glossary auto-build (locked 2026-07-25)**: the candidate scanner (already
  used read-only in Pre-Flight) becomes a builder workflow:
  1. Scan the current input → ranked list of unknown repeated EN terms.
  2. User approves / rejects candidates.
  3. Approved terms get PT translations: typed manually **or** suggested in
     batch by the LLM (small, explicit API cost — one batch, not the whole
     game) with human review before merging.
  4. Merge into the glossary with the proper category/preserve flags → stamp
     updated. Pre-Flight links here when it finds candidates ("41 termos
     novos encontrados — revisar no Glossário").
- Glossary stamp shown everywhere: *"built for Rogue Trader · 2,694 terms"*.

### 4.6 Settings (⚙)

- **API keys** — keyring storage (keep existing implementation), per provider.
- **Model profiles** — editable table: model name, workers, batch size per
  Pre-Scan tier (short/medium/long), save-every. Saved to `user_profiles.json`
  in the project/app config, **overriding** `model_profiles.py` without code
  edits. New model drops → add a row here.
- **Defaults** — default model, theme, project folder location.

---

## 5. Glossary health & game profiles (future-proofing)

The Pre-Flight step computes **coverage** = share of translatable strings
containing ≥1 known glossary term:

- **High coverage** → proceed normally.
- **Slightly low + many candidates** → *"New content (DLC?) — review 41
  candidate terms before translating?"* (journey ⑤ lite, inside the wizard).
- **Very low** → hard warning: *"This input doesn't look like Rogue Trader.
  This glossary will force wrong terms. Create a new game profile?"*

**Game profiles** (later, not v1): a profile bundles glossary + system prompt +
tag rules. Today `tradutor.py`'s SYSTEM_PROMPT hardcodes W40K/Owlcat; the plan
is to externalize it into the profile so the same engine can serve other
Owlcat-format games (e.g. Dark Heresy-style JSON). v1 only *names* the profile
in project.json so the migration path exists.

---

## 6. What we keep from the current GUI

- PySide6 desktop app (familiar, no new runtime; `launch_gui.bat/ps1` flow).
- Keyring API-key storage.
- Live-wiki glossary fetch.
- Grimdark theme (optional toggle; readability first).

## 7. Explicitly out of scope (v1)

- Full game-profile editor (only the `rogue_trader` profile; prompt still
  hardcoded in the engine).
- Multi-project window (v1: one project open at a time, switchable).
- Cloud anything.

## 8. Implementation phases

| Phase | Delivers | Depends on |
|---|---|---|
| **P1** ✅ (2026-07-25) | Project scaffold + `project.json` + Home dashboard + **Adopt existing files** | — |
| **P2** ✅ (2026-07-25) | ① New Translation wizard w/ Pre-Flight + cost estimate | P1 |
| **P3** ✅ (2026-07-25) | Fullize + mod-page zip (release mechanics) | P2 |
| **P4** ✅ (2026-07-25) | ② Fix & Audit journey + **audit gate on release** (reorders flow to ①→②→③) | P2 |
| **P5** ✅ (2026-07-25) | ④ Patch Day (delta → translate → auto-merge) | P4 |
| **P6** ✅ (2026-07-25) | ⑤ Glossary space (term table + auto-build) + Settings | P1 |

P6 shipped in two drops. **⚙ Settings** — `SettingsDialog`
(Provedores / Modelos / Geral) on the dashboard ⚙ button; user overrides
persist outside repo/projects in `%APPDATA%/W40KTranslator/`
(`user_providers.json` + `user_profiles.json`) via the Qt-free
`w40k_settings.py`; `w40k_preflight` resolves models/providers/subprocess
env through the effective layer; model pickers default to the effective
`default_model`. **⑤ Glossário** — `GlossaryDialog` (Termos / Construir)
over the PROJECT glossary (§9.7): sortable/filterable term table with
add/edit/remove (atomic write + once-per-session backup in `backups/`),
auto-build (candidate scan → approve/reject → optional single-batch LLM
PT suggestion with human review → dedupe merge with metadata stamp),
offline wiki seed + live MediaWiki single-term fetch; Qt-free logic in
`w40k_glossary.py`; Pre-Flight candidate hint links to ⑤. No placeholders
remain.
| **P7** | Game profiles (prompt externalization; inclui editor de prompt por perfil) | all |

Each phase ships a usable app; P1 alone already kills the folder chaos.

## 9. Decisions (locked 2025-07-25)

1. **UI language**: PT-BR.
2. **Theme**: keep the grimdark 40k look (dark + gold) as the default.
3. **App name**: **W40K Translator** (placeholder brand; may change later).
   P1 shipped as `w40k_translator.py` + `w40k_project.py` + `launch_translator.bat`.
   P2 added `w40k_preflight.py` (Qt-free Pre-Flight/credentials/progress-parse layer).
   P3 added `w40k_release.py` (Qt-free fullize/release-zip layer).
   P4 added `w40k_audit.py` (Qt-free audit/retry/merge/gate layer).
   P5 added `w40k_patch.py` (Qt-free patch-diff/delta/merge-hygiene layer).
   P6 Settings (2026-07-25) added `w40k_settings.py` (Qt-free user-override
   layer over `model_profiles.py`, persisted in
   `%APPDATA%/W40KTranslator/`, redirectable via `W40K_CONFIG_DIR`) and
   `key_store_delete` in `w40k_preflight.py`.
   P6 bug-fix round (2026-07-25): engine `tradutor.py` — `-w` agora default
   `None` (explícito é literal; auto-bump só quando omitido/<=0) e cliente
   OpenAI com `max_retries=1` (sem retry duplo sob rate-limit);
   `w40k_preflight.py` ganhou `key_store_set_ex` (diagnóstico do cofre),
   `test_connection` (probe /models → fallback chat completions) e
   `write_prescan_cache` (reuso do Pre-Scan via `--prescan-cache` no
   wizard); builders de audit/patch (`w40k_audit._profile_run_flags`)
   passam `-w`/`--save-every` do perfil EFETIVO; falha de gravação no
   cofre agora gera aviso visível (root cause do relato: pacote `keyring`
   não estava instalado no Python do usuário).
   P6 ⑤ Glossário (2026-07-25): `w40k_glossary.py` (Qt-free: load/save
   atômico + backup, CRUD com validação, filtro, scan de candidatos com
   contexto, guess de categoria, merge com dedupe, prompt/parser da
   sugestão LLM em lote, semente wiki offline via `wiki_sync` e fetch ao
   vivo MediaWiki portado da GUI antiga) + `GlossaryDialog`.
   P6 prep (2026-07-25, no phase row): `Project.reconcile()`/`cleanup_stale()`
   + ReconcileDialog (§9.6); per-project glossary with extended additive
   `metadata` (§9.7) — `import_glossary`/`create_empty_glossary`,
   GlossaryChoiceDialog, project-first glossary resolution in
   `w40k_preflight.resolve_glossary_path`; repo `glossary.json` gained
   additive metadata (terms untouched, engine-verified).
   Versioned-name refactor (2026-07-25, §2/§9.6 revised): registration is
   in place — the app never copies/renames user files; `project.json`
   tracks exact paths (`input.file`, `tracks.<track>.file`) resolved via
   `Project.track_path()`/`track_target()` across P2–P5 flows; renames
   only on explicit version bump (`rename_files_to_version`; Patch Day
   post-merge, "editar versão" confirm); `known_files` sha registry
   prevents re-prompts for replaced/archived dumps.
4. **Flow order (locked 2026-07-25)**: ① translate → ② audit & fix → ③ package;
   release is gated on a clean-or-explicitly-confirmed audit (§4.3).
5. **Glossary auto-build (locked 2026-07-25)**: candidate scan → approve →
   manual or LLM-suggested PT terms → merge; lives in journey ⑤ (§4.5).
6. **State reconciliation (locked 2026-07-25, revised same day)**: the app
   detects known files dropped by hand into `input/`/`output/` and offers to
   register them into `project.json` **in place** — it never renames or copies
   the user's files, and once registered a file must never re-trigger the
   dialog. Tracks and input follow the versioned-name convention (§2).
7. **Per-project glossary (locked 2026-07-25)**: each project owns its
   glossary file (imported from the community RT glossary, from another
   project, or empty — never from scratch unless wanted). Glossary JSON
   `metadata` declares: `name`, `game`, `game_version`, `kind`
   (`base_game` | `mod`), `mod_name`, `parent`. A mod project imports the RT
   glossary then adds/removes terms locally (§4.5 auto-build).
8. **Prompt editor (roadmap, P7)**: game profiles bundle glossary + system
   prompt + tag rules; the profile's prompt is editable in the app so
   far-future non-W40K projects reuse the tool without code edits.
