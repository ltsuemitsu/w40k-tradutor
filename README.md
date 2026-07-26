# W40K Rogue Trader Translator (EN → PT-BR)

![tests](https://github.com/ltsuemitsu/w40k-tradutor/actions/workflows/tests.yml/badge.svg)

Toolkit de fã para traduzir os arquivos de localização de
**Warhammer 40,000: Rogue Trader** (Owlcat Games) do inglês para
**português brasileiro**, usando APIs de LLM (DeepSeek por padrão; também
Zhipu GLM, Kimi/Moonshot ou qualquer endpoint compatível com OpenAI).

Inclui motor com controle de custo, glossário de lore/mecânica, proteção de
tags técnicas do jogo, fluxo **dual-track** (Preservada + Completa), diff de
patch e a GUI desktop **W40K Translator v2** (PySide6, centrada em projetos).

> **Não afiliado** à Owlcat Games nem à Games Workshop.  
> Projeto de fã para uso pessoal / comunitário / educacional.  
> **Nenhum arquivo de jogo** entra neste repositório — você precisa possuir o
> jogo legalmente e extrair os JSONs de localização você mesmo.

---

## O que este repo é (e o que não é)

| É | Não é |
|---|---|
| Ferramenta para **gerar** tradução PT-BR | Um mod pronto para instalar no Nexus |
| Pipeline + glossário **do Rogue Trader** | Localização oficial da Owlcat |
| Código open-source (MIT) | Pacote com `enGB.json` do jogo (copyright) |

Os zips de tradução para jogadores ficam em páginas de mod (ex.: Nexus), não
aqui. Aqui está o **como fazer** e o **glossário RT** para a comunidade
reproduzir, auditar e melhorar.

---

## Glossário = Rogue Trader (importante)

O `glossary.json` e os seeds em `data/glossaries/` foram montados para
**Warhammer 40,000: Rogue Trader** (termos de talents, armas, archetypes,
lore do Koronus Expanse, etc. — milhares de entradas EN→PT-BR).

### Quer usar em outro jogo (ex.: Dark Heresy)?

O **motor** (tags Owlcat-like, batches, preserve, fullize, GUI) pode servir de
base se o formato de localização for parecido.

O **glossário não serve “de carona”**:

1. **Não reutilize cegamente** o `glossary.json` do Rogue Trader em outro título.
   Muitos termos mudam de sentido, não existem, ou têm outro nome canônico.
2. **Atualize** o glossário (edite, apague categorias irrelevantes, marque
   `preserve` / `inline` com calma), **ou**
3. **Crie do zero** com as ferramentas do repo:
   - jornada **⑤ Glossário** da GUI (por projeto: tabela, auto-build com
     sugestão LLM em 1 chamada, semente wiki offline + ao vivo)
   - `wiki_sync.py` (semente a partir de listas/wiki)
   - `glossary_manager.py` (edição CLI)
4. Rode **Pré-Voo / dry-run** e audite um lote pequeno **antes** de gastar API
   no jogo inteiro.

Resumo: **mesmo universo 40k ≠ mesmo glossário**. RT e Dark Heresy pedem
listas próprias (ou uma derivada com revisão humana pesada).

---

## Dual-track: Preservada vs Completa (Full)

Fluxo recomendado — **duas saídas** a partir do mesmo inglês:

| Saída | O que é | Para quem |
|---|---|---|
| **Preservada** (`ptBR_preserved…`) | Narrativa/UI em PT; nomes de mecânica/wiki ficam em **EN** quando o glossário manda (exact skip + lock inline) | Quem usa builds, guias e wiki em inglês |
| **Completa / Full** (`ptBR_full…`) | Parte da Preservada e aplica **Fullize** (replace EN→PT do glossário, **sem** nova chamada cara de IA) | Quem quer imersão 100% em português |

### O que cada string faz no modo Preserve

| Tipo | Ação | Custo |
|---|---|---|
| vazia / placeholder | copia / skip | grátis |
| EULA / legal enorme | skip (blacklist) | grátis |
| termo wiki **exato** (string inteira) | mantém EN | grátis |
| termo **dentro** da frase | traduz a frase, trava o termo (`§TERM§`) | API |
| narrativa limpa | traduz normal | API |

Tags técnicas do jogo (`{g\|…}`, Encyclopedia, `{name}`, binds, sprites, cores,
indent…) são **blindadas** e não devem ir “cruas” para o modelo.

---

## A GUI — W40K Translator v2

A forma mais fácil de usar o toolkit. App PySide6 em PT-BR, tema grimdark,
**centrado em projetos** (um projeto = um par EN→PT versionado, ex.:
`enGB_1.6.1.514.json` → `ptBR_full_1.6.1.514.json`, com `project.json`
rastreando o estado).

```text
launch_translator.bat
# ou: py -3 w40k_translator.py
```

Na primeira abertura, a tela de boas-vindas oferece **Novo Projeto**,
**Adotar Tradução Existente** (aponta seus arquivos atuais) ou **Abrir**.
Dali você cai no Dashboard, com cards de **INPUT · TRILHAS · AUDITORIA ·
GLOSSÁRIO** e as jornadas:

| Jornada | O que faz |
|---|---|
| **① Nova Tradução** | Wizard: **Pré-Voo grátis** (classificação de strings, cobertura do glossário, estimativa de custo, candidatos a termo) → run com progresso/ETA. Chave fica no cofre do Windows, nunca em plaintext. |
| **② Auditoria** | Lista falhas / idênticas / suspeitas do output, edição inline e **retradução** cirúrgica (`--retranslate-map`, com backup). |
| **③ Empacotar** | Portão de auditoria, **Fullize grátis** e geração de zips `traducao_<TRACK>_<versão>.zip` com `enGB.json` dentro, prontos para publicar. |
| **④ Patch do Jogo** | Diff EN velho × novo, traduz **só o delta**, merge com backups. Strings movidas de lugar são reaproveitadas de graça. |
| **⑤ Glossário** | Glossário **do projeto**: tabela editável, auto-build com sugestão PT via LLM em uma chamada, semente wiki offline + ao vivo. |
| **⚙ Configurações** | Provedores com base URL editável e overrides em `%APPDATA%/W40KTranslator/`, editor de modelos, chaves no cofre via keyring, teste de conexão. |

Toda a lógica das jornadas vive em módulos sem Qt (`w40k_preflight.py`,
`w40k_audit.py`, `w40k_release.py`, `w40k_patch.py`, `w40k_settings.py`,
`w40k_glossary.py`, `w40k_project.py`) — testável com stdlib puro.

A GUI antiga (abas, sem projetos) foi **removida na v2.0**. O CLI continua
intacto e cobre os mesmos fluxos (ver abaixo).

---

## Requisitos

- Python **3.10+** (3.12 testado no CI)
- Chave de API (DeepSeek recomendado para volume; outros provedores ok)
- Cópia legal do jogo para obter o JSON de localização

```bash
pip install -r requirements-gui.txt
# openai, tqdm, PySide6, keyring (obrigatório para o cofre de chaves)
```

### Chaves de API (nunca commitar)

```bash
# Windows (cmd)
set DEEPSEEK_API_KEY=sk-...

# Windows (PowerShell)
$env:DEEPSEEK_API_KEY="sk-..."

# Linux / macOS
export DEEPSEEK_API_KEY=sk-...
```

Na GUI: cole a chave em **⚙ Configurações** e ela vai para o **cofre do
Windows** (Windows Credential Manager via `keyring`).  
**Não** coloque chaves em arquivos do projeto, no `glossary.json`, nem em issues.

Variáveis úteis: `DEEPSEEK_API_KEY`, `ZHIPU_API_KEY`, `KIMI_API_KEY`,
`OPENAI_API_KEY` (custom), opcionalmente `DEEPSEEK_BASE_URL`.

### Modelos e cache (barato vs premium)

Perfis em `model_profiles.py` — o motor escolhe **batch size / workers /
save_every** pelo nome do modelo:

| Uso | Modelo sugerido | Notas |
|---|---|---|
| **Bulk barato (recomendado)** | `deepseek-v4-flash` | ~4h / poucos $ no full game; workers 8 |
| Premium voz | `glm-5.2` | Output caro; use só se quiser o estilo |
| Zhipu barato | `glm-4.7-flash` / `glm-4.5-flash` | Free/cheap no plano Zhipu |
| Kimi coding | `kimi-for-coding` | URL `https://api.kimi.com/coding/v1` |

**Prompt cache:** system + glossário ficam **estáveis** (ordem alfabética).
Só a lista de strings do batch muda → o provedor cobra prefixo como
*cached input* (muito mais barato no DeepSeek e no GLM).

```bash
# Bulk default (profile aplica workers/batches)
python tradutor.py -i data/en/enGB.json -o data/pt/ptBR_preserved.json \
  -g glossary.json --mode preserve --resume --model deepseek-v4-flash

# Forçar workers manuais (-w N explícito é literal; -w 0/omitido = auto)
python tradutor.py ... --model glm-5.2 -w 3 --save-every 5
```

---

## Início rápido

### 1. Pegue os arquivos do jogo

Na instalação Steam do Rogue Trader, localize algo como:

```text
...\Warhammer 40,000 Rogue Trader\WH40KRT_Data\StreamingAssets\Localization\enGB.json
```

Copie o `enGB.json` (ou o dump da versão que for traduzir) para:

```text
data/en/enGB.json
```

(ver `data/en/README.txt`). Esses JSONs estão no `.gitignore` de propósito.

### 2. (Opcional) Atualizar semente de wiki / glossário

```bash
python wiki_sync.py --glossary glossary.json --sync
```

### 3. Traduzir — GUI (mais fácil)

```text
launch_translator.bat
```

Crie um projeto (Novo Projeto ou Adotar Tradução Existente) e siga a
jornada **① Nova Tradução**:

1. **Pré-Voo** (grátis) — classificação, cobertura do glossário, custo estimado
2. Preserve ON → iniciar a tradução (progresso/ETA na tela)
3. **③ Empacotar** → Fullize grátis + zips das duas trilhas
4. Instale no jogo só **uma** das saídas, renomeando para `enGB.json` na pasta
   Localization (faça backup do original).

### 4. Traduzir — CLI

```bash
# 1) Master Preservada (usa API)
python tradutor.py -i data/en/enGB.json -o data/pt/ptBR_preserved.json \
  -g glossary.json --mode preserve --resume --preserve-map preserve_map.json

# 2) Master Completa (GRÁTIS — sem API)
python tradutor.py --fullize \
  -i data/pt/ptBR_preserved.json -o data/pt/ptBR_full.json -g glossary.json

# Só classificar / proteger (sem gastar API)
python tradutor.py -i data/en/enGB.json -o data/pt/_dry.json \
  -g glossary.json --mode preserve --dry-run
```

`--resume` continua de onde parou (save atômico por batch).
`--prescan-cache` reaproveita a classificação entre runs.

---

## Depois de um patch do jogo

Não re-traduza 70k strings. A jornada **④ Patch do Jogo** da GUI faz diff
EN→EN e traduz só o delta. Equivalente em CLI:

```bash
python diff_tool.py update data/en/enGB_old.json data/en/enGB_new.json --out delta.json
python tradutor.py -i delta.json -o data/pt/delta_preserved.json -g glossary.json --mode preserve
python tradutor.py --fullize -i data/pt/delta_preserved.json -o data/pt/delta_full.json -g glossary.json
python merge.py -b data/pt/ptBR_preserved.json data/pt/delta_preserved.json -o data/pt/ptBR_preserved.json --backup
python merge.py -b data/pt/ptBR_full.json data/pt/delta_full.json -o data/pt/ptBR_full.json --backup
```

Auditoria:

```bash
python diff_tool.py audit data/en/enGB.json data/pt/ptBR_preserved.json
```

Detalhes de desenho: [`SCENARIOS.md`](SCENARIOS.md) e
[`GUI_REDESIGN.md`](GUI_REDESIGN.md) (spec do redesign v2).

---

## Layout do repositório

| Caminho | Função |
|---|---|
| `tradutor.py` | Motor + CLI (`--mode preserve`, `--fullize`, batches, resume) |
| `w40k_translator.py` | GUI PySide6 v2 (app centrado em projetos) |
| `w40k_project.py` | Projetos: criar/adotar/abrir, `project.json`, trilhas |
| `w40k_preflight.py` | Jornada ①: Pré-Voo, estimativas, cofre de chaves, subprocess |
| `w40k_audit.py` | Jornada ②: auditoria de output + retradução cirúrgica |
| `w40k_release.py` | Jornada ③: fullize, portão de auditoria, zips de release |
| `w40k_patch.py` | Jornada ④: diff de patch, delta, merge com backups |
| `w40k_glossary.py` | Jornada ⑤: glossário do projeto, auto-build, wiki ao vivo |
| `w40k_settings.py` | ⚙: provedores, overrides, editor de modelos |
| `model_profiles.py` | Perfis de modelos (workers/batch/save_every) |
| `diff_tool.py` | Diff de update, audit, smart-diff |
| `merge.py` | Mescla correções / deltas no master PT |
| `glossary_manager.py` | Editor CLI do glossário |
| `wiki_sync.py` | Semente / sync de termos (wiki offline + live) |
| `scripts/` | Utilitários de manutenção de tradução |
| `glossary.json` | Glossário comunitário **Rogue Trader** EN→PT-BR |
| `data/glossaries/` | Seeds / `wiki_terms.json` (RT) |
| `data/blacklists/` | UUIDs EULA etc. (amostras) |
| `data/en/`, `data/pt/` | Seus dumps locais (**não versionados**) |
| `tests/` | Unittest sem rede / sem API |
| `GUI_REDESIGN.md` | Spec do redesign v2 (jornadas, projetos, tema) |
| `launch_translator.bat` / `.ps1` | Atalhos Windows da GUI v2 |

---

## Desenvolvimento e testes

```bash
pip install openai tqdm
python -m unittest discover -s tests
```

**267 testes**, stdlib puro (`unittest`), sem rede e sem chaves.  
CI (GitHub Actions): Ubuntu + Windows × Python 3.10/3.12 — `compileall` +
unittest. Testes usam fixtures sintéticas: **sem** arquivos do jogo.

---

## Segurança e boa prática ao contribuir

- **Nunca** commite: `enGB.json`, saídas PT, zips de mod, `.w40k`,
  `prescan_cache.json`, `preserve_map.json`, `.env`, backups com path local.
- **Nunca** cole API keys em issues, PRs ou screenshots do README.
- Chaves: variável de ambiente ou cofre do Windows (keyring) via GUI.
- Pull requests são bem-vindos (glossário, bugs de tag, docs).  
  Não envie dumps completos de localização do jogo.

---

## Roadmap

- **P7 — perfis de jogo / editor de prompt**: suporte declarativo a outros
  jogos com formato Owlcat-like (o `project.json` já registra o perfil para
  preparar a migração). Ver `GUI_REDESIGN.md`.

---

## Tradução assistida por IA × tradução humana

Este toolkit **acelera** cobertura e consistência de glossário.  
Tradução revisada por humanos continua sendo o padrão ouro de qualidade
literária. Se for publicar um mod gerado daqui, deixe isso claro na página e
valorize também os projetos PT-BR feitos à mão pela comunidade.

---

## Aviso legal

- Conteúdo de *Warhammer 40,000: Rogue Trader* © Owlcat Games / Games Workshop.
- Este repositório contém **apenas** ferramentas e glossário comunitário.
- MIT — ver [LICENSE](LICENSE). O jogo e suas strings **não** são redistribuídos
  por este projeto.

---

## Créditos

- Owlcat / GW pelo jogo e universo.
- Comunidade PT-BR de Rogue Trader (traduções, guias, feedback de tom).
- Contribuidores de termos no glossário e quem reporta tags quebradas.

**O Imperador protege — e o Pré-Voo também.**
