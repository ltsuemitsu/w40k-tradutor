# Warhammer 40K: Rogue Trader — Kit de Traducao v3.0

Arquitetura limpa: 4 ferramentas especializadas para traduzir o jogo do ingles para portugues brasileiro.

---

## Ferramentas

### 1. `tradutor.py` — Traducao
Unica ferramenta de traducao. Faz tudo: protege tags, usa glossario, paralelismo, resume.

**Primeira traducao:**
```bash
python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --resume
```

**Modo completo (100% portugues):**
```bash
python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --mode complete --resume
```

**Modo preservacao (mantem nomes de mecanicas em ingles):**
```bash
python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --mode preserve --resume
```

**Escolhendo o que preservar:**
```bash
python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json \
    --mode preserve --preserve-cats weapon,talent,skill
```

**Parametros:**
- `-i` / `--input` — Arquivo JSON original (enGB.json)
- `-o` / `--output` — Arquivo JSON de saida (ptBR.json)
- `-g` / `--glossary` — Glossario JSON (opcional, mas recomendado)
- `--mode` — `complete` (padrao) ou `preserve`
- `--preserve-cats` — Categorias a preservar (modo preserve): `weapon,talent,ability,archetype,origin,homeworld,armour,helmet,gloves,boots,cloak,necklace,accessory,consumable,pet_protocol,conviction`
- `--resume` — Continua de onde parou
- `--dry-run` — Testa sem chamar API
- `-b` / `--batch-size` — Itens por batch (padrao: 10)
- `-w` / `--workers` — Workers paralelos (padrao: 3)
- `--temperature` — Temperatura do LLM (padrao: 0.15)
- `--debug` — Modo verbose

---

### 2. `wiki_sync.py` — Glossario da Wiki
Popula o glossario com 2694 nomes extraidos da WH40K Rogue Trader Wiki (https://roguetrader.wh40k.wiki/).

**Sincronizar:**
```bash
python wiki_sync.py --glossary glossary.json --sync
```

**Com revisao interativa:**
```bash
python wiki_sync.py --glossary glossary.json --sync --review
```

**Estatisticas:**
```bash
python wiki_sync.py --glossary glossary.json --stats
```

**Exportar CSV:**
```bash
python wiki_sync.py --glossary glossary.json --export-csv terms.csv
```

Categorias:
- `talent` (1029), `weapon` (554), `ability` (229), `accessory` (148)
- `armour` (143), `helmet` (85), `consumable` (84), `necklace` (81)
- `gloves` (74), `cloak` (73), `boots` (68), `pet_protocol` (65)
- `conviction` (30), `archetype` (14), `homeworld` (9), `origin` (8)

Todo termo vem com `"preserve": true`.

---

### 3. `diff_tool.py` — Analise e Diff
Tres cenarios em uma ferramenta.

**Cenario 1 — Auditoria (textos ainda em ingles):**
```bash
python diff_tool.py -i enGB.json -t ptBR.json --audit --glossary glossary.json
```
Detecta: nao traduzidos, parcialmente em ingles, tags quebradas.

**Cenario 2 — Atualizacao do jogo:**
```bash
python diff_tool.py -i enNOVO.json -i_antigo enVELHO.json -t ptBR.json --update -o retraduzir.json
```
Detecta UUIDs novos, modificados e removidos.

**Cenario 3 — Preservacao inteligente:**
```bash
python diff_tool.py -i enGB.json -t ptBR.json --smart-diff --glossary glossary.json -o retraduzir.json
```
Detecta textos que citam termos do glossario e geram instrucoes de preservacao parcial.

---

### 4. `merge.py` — Mesclagem
Aplica correcoes manuais de volta ao arquivo traduzido.

```bash
python merge.py -i ptBR.json -f correcoes.json -o ptBR_corrigido.json
```

---

### 5. `glossary_manager.py` — Edicao do Glossario
Edicao manual interativa do glossario.

```bash
python glossary_manager.py --glossary glossary.json
```

---

## Requisitos

```bash
pip install openai tqdm
```

Variavel de ambiente:
```bash
export DEEPSEEK_API_KEY="sua-chave-aqui"
# opcional:
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
```

---

## Fluxos de Trabalho

### Primeira Traducao Completa
```bash
# 1. Criar glossario com dados da wiki
python wiki_sync.py --glossary glossary.json --sync

# 2. Traduzir tudo (modo preserve = mantem mecanicas em ingles)
python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --mode preserve --resume

# 3. Auditar resultados
python diff_tool.py -i enGB.json -t ptBR.json --audit --glossary glossary.json

# 4. Corrigir problemas manualmente e mesclar
python merge.py -i ptBR.json -f correcoes.json -o ptBR_final.json
```

### Atualizacao do Jogo
```bash
# 1. Detectar o que mudou
python diff_tool.py -i enNOVO.json -i_antigo enVELHO.json -t ptBR.json --update -o retraduzir.json

# 2. Traduzir apenas o novo
python tradutor.py -i retraduzir.json -o ptBR_novo.json --glossary glossary.json --mode preserve

# 3. Auditar
python diff_tool.py -i enNOVO.json -t ptBR_novo.json --audit --glossary glossary.json
```

### Validacao Final
```bash
python diff_tool.py -i enGB.json -t ptBR.json --audit --glossary glossary.json
```

---

## Formato do Glossario

```json
{
  "metadata": {
    "version": "2.0",
    "updated_at": "2026-06-14T01:15:22",
    "total_terms": 2694
  },
  "terms": [
    {
      "term_english": "Plasma Gun",
      "term_translated": "Plasma Gun",
      "category": "weapon",
      "context": "WH40K Wiki — weapon",
      "confidence": "high",
      "first_seen_batch": 0,
      "usage_count": 1,
      "created_at": "2026-06-14T01:15:22",
      "preserve": true
    }
  ]
}
```

Campos:
- `term_english` — Termo original
- `term_translated` — Traducao (igual ao ingles quando preserve=true)
- `category` — talent, weapon, ability, accessory, armour, helmet, consumable, necklace, gloves, cloak, boots, pet_protocol, conviction, archetype, homeworld, origin
- `preserve` — Se true, o tradutor mantem em ingles no modo preserve
- `confidence` — high/medium/low
- `usage_count` — Frequencia de uso

---

## Arquitetura

```
+-------------+     +-------------+     +-------------+
| wiki_sync   | --> |  tradutor   | --> |  diff_tool  |
| (glossario) |     | (traducao)  |     | (auditoria) |
+-------------+     +-------------+     +-------------+
       ^                                       |
       |                                       v
+-------------+     +-------------+     +-------------+
| glossary_   |     |   merge     | <-- |  correcoes  |
| manager     |     | (mesclagem) |     |  manuais    |
+-------------+     +-------------+     +-------------+
```
