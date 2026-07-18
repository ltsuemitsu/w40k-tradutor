# W40K Rogue Trader Translator (EN → PT-BR)

![tests](https://github.com/ltsuemitsu/w40k-tradutor/actions/workflows/tests.yml/badge.svg)

A fan-made toolkit to translate *Warhammer 40,000: Rogue Trader* (Owlcat Games)
localization files from English to Brazilian Portuguese, using LLM APIs
(DeepSeek by default; also Zhipu GLM or any OpenAI-compatible endpoint).

It combines a cost-aware translation engine, a 2,600+ term lore glossary built
from the community wiki, patch-diff tooling for game updates, and a PySide6
desktop GUI ("Grimdark Edition").

> **Not affiliated with Owlcat Games or Games Workshop.** Fan project for
> personal/educational use. No game files are included in this repository —
> you must legally own the game and extract the localization files yourself.

---

## Features

- **Glossary-aware translation** — lore terms (talents, abilities, weapons,
  factions, homeworlds…) are preserved or translated consistently, driven by a
  curated JSON glossary with per-term `preserve` flags.
- **Cost control** — free pre-scan classifies all ~77k strings *before* any API
  call (EULA / placeholders / already-translated / preserved), plus a budget
  estimator, blacklists, and length-tiered batching.
- **Crash-safe** — atomic save after every batch; `--resume` continues exactly
  where a run stopped.
- **Game-update workflow** — free EN↔EN patch diff produces a delta file with
  only new/changed strings, so a game patch never costs a full retranslation.
- **Tag protection** — game markup (`{g|…}`, `<color>`, `<sprite>`, `<link>`…)
  is shielded with placeholders before the LLM call and restored after.
- **Desktop GUI** — 4 tabs (Translate / Glossary / Update / Wiki), project
  files (`.w40k`), prescan + blacklist builder, AI glossary population.

## Repository layout

| File | Role |
|---|---|
| `tradutor.py` | Core translation engine + CLI (all translation happens here) |
| `tradutor_desktop.py` | PySide6 desktop GUI (drives the CLIs) |
| `diff_tool.py` | Audit translations, diff game patches, smart glossary-aware diff |
| `merge.py` | Merge correction/retranslation files into the main output (backup + dry-run) |
| `glossary_manager.py` | Interactive CLI glossary editor |
| `wiki_sync.py` | Glossary seeder: ~2,694 wiki terms in 16 categories |
| `glossary.json` | Community glossary (~2,694 terms, EN→PT-BR) — ready to use |
| `data/glossaries/glossary_seed.json` | Hand-written seed terms |
| `launch_gui.bat` / `launch_gui.ps1` | Windows launchers (auto-setup venv + deps) |
| `SCENARIOS.md` | Design contract: the 4 core workflows |
| `GUI_ROADMAP.md` | GUI status & development roadmap |
| `README_v3.md` | Original v3.0 user manual (PT-BR) |

## Requirements

- Python **3.12+** (recommended; see note below)
- `pip install -r requirements-gui.txt` (`openai`, `tqdm`, `PySide6`)
- An API key for DeepSeek (default) or another OpenAI-compatible provider

> Note: `wiki_sync.py` currently uses f-string syntax that requires Python
> ≥ 3.12. The CLIs `tradutor.py`, `diff_tool.py`, `merge.py` run on 3.10+.

## Configuration

```bash
# DeepSeek (default provider)
set DEEPSEEK_API_KEY=sk-...          # Windows
export DEEPSEEK_API_KEY=sk-...       # Linux/macOS

# Optional: override endpoint / model
set DEEPSEEK_BASE_URL=https://api.deepseek.com
```

The GUI also lets you paste keys per-provider in the Settings dialog. (Note:
"Save locally" currently stores keys unencrypted via QSettings — use env vars
if you prefer.)

## Quick start

**1. Get the game files.** From your legally owned game installation, copy the
localization JSON into `data/en/` (see `data/en/README.txt`). These files are
**not** in this repo and must never be committed.

**2. (First time) Seed/refresh the glossary:**

```bash
python wiki_sync.py --sync        # populate glossary with wiki terms
```

**3. Translate (CLI):**

```bash
# Full translation
python tradutor.py data/en/enGB.json data/pt/ptBR.json --mode complete

# Recommended: preserve lore terms per the glossary flags
python tradutor.py data/en/enGB.json data/pt/ptBR.json --mode preserve

# Dry run to see what would be sent to the API (free)
python tradutor.py data/en/enGB.json data/pt/ptBR.json --dry-run
```

**4. Or use the GUI:**

```bash
launch_gui.bat        # Windows (auto-creates venv on first run)
python tradutor_desktop.py
```

**5. After a game patch (free diff, then translate only the delta):**

```bash
python diff_tool.py update data/en/enGB_old.json data/en/enGB_new.json --out delta.json
python tradutor.py delta.json data/pt/ptBR_patch.json --mode preserve
python merge.py data/pt/ptBR.json data/pt/ptBR_patch.json
```

**6. Audit quality:**

```bash
python diff_tool.py audit data/en/enGB.json data/pt/ptBR.json
```

See `README_v3.md` (PT-BR) and `SCENARIOS.md` for the full workflows.

## Roadmap

Tracked in `GUI_ROADMAP.md`. Highlights: direct function integration in the
GUI (replacing subprocess calls), interactive string reviewer, secure key
storage via `keyring`, PyInstaller packaging, cost dashboard, tests.

## Development

Run the test suite (stdlib `unittest` only — no pytest needed):

```bash
pip install openai tqdm
python -m unittest discover -s tests -v
```

Tests use tiny synthetic fixtures — no network, no API keys, no LLM calls.
CI runs a compile-all syntax gate plus the suite on Ubuntu and Windows ×
Python 3.10/3.12 (see `.github/workflows/tests.yml`).

## Contributing

Issues and PRs are welcome. Please **never** commit game localization files,
caches (`prescan_cache.json`, `preserve_map.json`), or your personal `.w40k`
project files — see `.gitignore`.

## License

MIT — see [LICENSE](LICENSE). Game content belongs to Owlcat Games / Games
Workshop; this repo contains only tooling and a community glossary.
