#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Merge de Traducao — Mescla itens re-traduzidos de volta ao arquivo principal
============================================================================

Fluxo correto:
    1. validador.py gera ainda_em_ingles.json
    2. tradutor_game_json.py traduz ainda_em_ingles.json → fix.json
    3. merge.py mescla fix.json no ptBR.json

Uso:
    # Mescla correcoes (re-traduzidas) no arquivo principal
    python merge.py -b ptBR.json -c fix.json -o ptBR.json

    # Com backup automatico
    python merge.py -b ptBR.json -c fix.json -o ptBR.json --backup

    # Preview
    python merge.py -b ptBR.json -c fix.json -o ptBR.json --dry-run

    # Se o arquivo de correcoes veio direto do validador (sem retraduzir),
    # o merge vai AVISAR e sugerir o comando correto.
"""

import json
import argparse
import shutil
import os
import sys
from datetime import datetime
from typing import Dict, Any


def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: dict, path: str):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_from_validator(item: dict) -> bool:
    """Detecta se um item veio do arquivo de saida do validador."""
    return "_current_translation" in item or "_issue" in item


def is_untranslated_validator_item(item: dict) -> bool:
    """
    Verifica se o item do validador ainda nao foi re-traduzido.
    Retorna True se Text == _current_translation (ainda em ingles).
    """
    text = item.get("Text", "")
    current = item.get("_current_translation", "")
    return bool(current and text == current)


def main():
    parser = argparse.ArgumentParser(description="Mescla itens re-traduzidos no arquivo principal")
    parser.add_argument("-b", "--base", required=True, help="Arquivo base (traducao principal)")
    parser.add_argument("-c", "--correcoes", required=True, help="Arquivo com correcoes (pos-traducao)")
    parser.add_argument("-o", "--output", required=True, help="Arquivo de saida")
    parser.add_argument("--backup", action="store_true", help="Faz backup do arquivo base antes de sobrescrever")
    parser.add_argument("--dry-run", action="store_true", help="So mostra o que seria alterado, nao altera")
    args = parser.parse_args()

    base = load_json(args.base)
    correcoes = load_json(args.correcoes)

    base_strings = base.get("strings", {})
    corr_strings = correcoes.get("strings", {})

    if not corr_strings:
        print("❌ Arquivo de correcoes vazio ou sem chave 'strings'")
        return 1

    # ─── DETECTA ARQUIVO DO VALIDADOR NAO RE-TRADUZIDO ───
    validator_untranslated = 0
    validator_total = 0
    for item in corr_strings.values():
        if is_from_validator(item):
            validator_total += 1
            if is_untranslated_validator_item(item):
                validator_untranslated += 1

    if validator_total > 0 and validator_untranslated == validator_total:
        print("\n" + "!" * 60)
        print("  ⚠️  ARQUIVO DO VALIDADOR DETECTADO — NAO FOI RE-TRADUZIDO!")
        print("!" * 60)
        print(f"\n  O arquivo '{args.correcoes}' parece ser saida do validador.")
        print(f"  Todos os {validator_total} itens ainda estao em ingles.")
        print("\n  ❌ O merge NAO pode ser feito direto.")
        print("\n  ✅ Fluxo correto:")
        print("     1. python validador.py -i en.json -t pt.json -o problemas.json")
        print("     2. python tradutor_game_json.py -i problemas.json -o fix.json --glossary g.json --extract-every 0")
        print("     3. python merge.py -b pt.json -c fix.json -o pt.json")
        print("\n" + "!" * 60)
        return 1

    if validator_total > 0 and validator_untranslated > 0:
        print(f"\n⚠️  Aviso: {validator_untranslated}/{validator_total} itens do validador parecem nao ter sido re-traduzidos.")
        print("    Estes itens serao ignorados no merge.")
        print()

    # ─── MERGE ───
    alterados = 0
    adicionados = 0
    inalterados = 0
    ignorados = 0
    detalhes = []

    for key, corr_item in corr_strings.items():
        corr_text = corr_item.get("Text", "")

        # Pula itens vazios (erro de traducao)
        if not corr_text or not corr_text.strip():
            detalhes.append(f"  ⚠️  {key[:8]}...: correcao VAZIA, pulando")
            inalterados += 1
            continue

        # Pula itens do validador que nao foram re-traduzidos
        if is_from_validator(corr_item) and is_untranslated_validator_item(corr_item):
            ignorados += 1
            detalhes.append(f"  ⏭️  {key[:8]}...: nao re-traduzido, ignorado")
            continue

        if key in base_strings:
            base_text = base_strings[key].get("Text", "")

            # So altera se a correcao e diferente do que ja esta no base
            if corr_text == base_text:
                inalterados += 1
                continue

            if not args.dry_run:
                base_strings[key]["Text"] = corr_text
                # Remove metadados de debug se existirem
                base_strings[key].pop("_current_translation", None)
                base_strings[key].pop("_issue", None)

            alterados += 1
            issue = corr_item.get("_issue", "correcao")
            detalhes.append(f"  ✅ {key[:8]}... [{issue}]")
            detalhes.append(f"     ANT: {base_text[:70]}")
            detalhes.append(f"     NOV: {corr_text[:70]}")
        else:
            # Key nao existia no base — adiciona
            if not args.dry_run:
                base_strings[key] = {
                    "Offset": corr_item.get("Offset", 0),
                    "Text": corr_text
                }
            adicionados += 1
            detalhes.append(f"  ➕ {key[:8]}...: novo item adicionado")

    # ─── RELATORIO ───
    print(f"\n{'='*60}")
    print(f"  MERGE {'(PREVIEW)' if args.dry_run else ''}")
    print(f"{'='*60}")
    print(f"  Base:        {args.base}")
    print(f"  Correcoes:   {args.correcoes}")
    print(f"  Saida:       {args.output}")
    print(f"{'='*60}")
    print(f"  Alterados:   {alterados}")
    print(f"  Adicionados: {adicionados}")
    print(f"  Inalterados: {inalterados}")
    if ignorados > 0:
        print(f"  Ignorados:   {ignorados} (nao re-traduzidos)")
    print(f"  Total corr.: {len(corr_strings)}")
    print(f"{'='*60}")

    if detalhes:
        print("\n  Detalhes:")
        for d in detalhes:
            print(d)

    if args.dry_run:
        print(f"\n⚠️  DRY-RUN — nenhum arquivo foi alterado.")
        return 0

    # Backup
    if args.backup and os.path.exists(args.base):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{args.base}.{ts}.backup"
        shutil.copy2(args.base, backup_path)
        print(f"\n💾 Backup: {backup_path}")

    # Salva
    base["strings"] = base_strings
    save_json(base, args.output)
    print(f"\n✅ Arquivo salvo: {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
