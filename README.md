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

- **Dual-track output** — **Preserved** (EN mechanics + PT narrative) and **Full**
  (100% PT via free glossary replace / Fullize).
- **Smart preserve** — exact whole-string wiki terms stay EN; terms *inside*
  phrases are hard-locked (`§TERM§`) while the sentence still translates.
- **Hard tech protect** — Encyclopedia, `{g|…}`, `{mf|…}`, `{name}`, binds,
  sprites, indent… never reach the LLM.
- **Cost control** — free pre-scan, empty/placeholder/EULA skip, budget
  estimator, blacklists, length-tiered batching (short×50 … xlong×5).
- **Crash-safe** — atomic save after every batch; `--resume` continues exactly
  where a run stopped.
- **Game-update workflow** — free EN↔EN patch diff produces a delta file with
  only new/changed strings.
- **Desktop GUI** — guided dual-track buttons, glossary editor, update + merge.

## Dual-track recipe (recommended)

### GUI
1. Open `launch_gui.bat` → Translate tab  
2. **Pre-Scan** (free)  
3. Paths: Input EN · Output Preserved · Output Full · Glossary  
4. Preserve ON → **1) Start Preserve Translation**  
5. **2) Fullize → 100% PT (FREE)**

### CLI
```bash
# 1) Preserved master (API)
python tradutor.py -i data/en/enGB_new.json -o data/pt/ptBR_preserved.json \
  -g glossary.json --mode preserve --resume --preserve-map preserve_map.json

# 2) Full master (FREE — no API)
python tradutor.py --fullize \
  -i data/pt/ptBR_preserved.json -o data/pt/ptBR_full.json -g glossary.json

# Dry-run classify + protect only
python tradutor.py -i data/en/enGB_new.json -o data/pt/_dry.json \
  -g glossary.json --mode preserve --dry-run
```

### What each string does in Preserve mode
| Kind | Action |
|---|---|
| empty / placeholder | skip (free) |
| EULA / huge legal | skip (free) |
| exact wiki term | copy EN (free) |
| term inside phrase | translate + hard-lock term |
| clean narrative | normal PT translate |

## Repository layout

| File | Role |
|---|---|
| `tradutor.py` | Core engine + CLI (`--mode preserve`, `--fullize`, smart batches) |
| `tradutor_desktop.py` | PySide6 GUI (drives the CLIs) |
| `diff_tool.py` | Audit translations, diff game patches |
| `merge.py` | Merge correction/retranslation files into a base PT |
| `glossary_manager.py` | Interactive CLI glossary editor |
| `wiki_sync.py` | Glossary seeder (loads offline wiki term lists) |
| `data/glossaries/wiki_terms.json` | Offline wiki terms (~2,694 in 16 categories) |
| `glossary.json` | Community glossary (~2,694 terms, EN→PT-BR) |
| `launch_gui.bat` / `launch_gui.ps1` | Windows launchers |
| `SCENARIOS.md` | Design contract: core workflows |

## Requirements

- Python **3.10+** (3.12 tested in CI)
- `pip install -r requirements-gui.txt` (`openai`, `tqdm`, `PySide6`, `keyring`)
- An API key for DeepSeek (default) or another OpenAI-compatible provider

## Configuration

```bash
# DeepSeek (default provider)
set DEEPSEEK_API_KEY=sk-...          # Windows
export DEEPSEEK_API_KEY=sk-...       # Linux/macOS

# Optional: override endpoint / model
set DEEPSEEK_BASE_URL=https://api.deepseek.com
```

The GUI also lets you paste keys per-provider. Prefer **Save to keychain**
(OS Credential Manager via `keyring`).

## Quick start

**1. Get the game files.** From your legally owned game installation, copy the
localization JSON into `data/en/` (see `data/en/README.txt`). These files are
**not** in this repo and must never be committed.

**2. (First time) Seed/refresh the glossary:**

```bash
python wiki_sync.py --glossary glossary.json --sync
```

**3. Dual-track translate** — see recipe above (GUI or CLI).

**4. After a game patch (free diff, then translate only the delta):**

```bash
python diff_tool.py update data/en/enGB_old.json data/en/enGB_new.json --out delta.json
python tradutor.py -i delta.json -o data/pt/delta_preserved.json -g glossary.json --mode preserve
python tradutor.py --fullize -i data/pt/delta_preserved.json -o data/pt/delta_full.json -g glossary.json
python merge.py -b data/pt/ptBR_preserved.json data/pt/delta_preserved.json -o data/pt/ptBR_preserved.json --backup
python merge.py -b data/pt/ptBR_full.json data/pt/delta_full.json -o data/pt/ptBR_full.json --backup
```

**5. Audit quality:**

```bash
python diff_tool.py audit data/en/enGB.json data/pt/ptBR_preserved.json
```

See `SCENARIOS.md` for broader workflow notes.

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
