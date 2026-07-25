#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diff Tool — Ferramenta ÚNICA de análise e diff
===============================================

Cenário 1 — Primeira tradução (auditoria):
    python diff_tool.py -i en.json -t pt.json --audit --glossary glossary.json

Cenário 2 — Atualização do jogo:
    python diff_tool.py -i enNOVO.json -i_antigo enVELHO.json -t pt.json --update -o novo.json

Cenário 3 — Preservação inteligente:
    python diff_tool.py -i en.json -t pt.json --smart-diff --glossary glossary.json -o retraduzir.json

Modos combináveis:
    --audit        → Valida tradução existente
    --update       → Detecta mudanças no jogo (novos/alterados/removidos UUIDs)
    --smart-diff   → Preserva termos do glossário no contexto
    -o arquivo    → Gera arquivo de saída
    --preview      → Só mostra, não cria arquivo
"""

import json
import re
import os
import sys
import argparse
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict


def load_json(path: str) -> Optional[dict]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None


def save_json(data: dict, path: str):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── DETECÇÃO DE IDIOMA ───

EN_INDICATORS = {"the","and","for","are","but","not","you","all","can","had","her","was","one","our","out","day","get","has","him","his","how","man","new","now","old","see","two","way","who","boy","did","its","let","put","say","she","too","use","with","have","this","will","your","from","they","know","want","been","good","much","some","time","very","when","come","here","just","like","long","make","many","over","such","take","than","them","well","were","what","would","there","about","after","back","other","before","right","through","where","being","every","great","might","shall","still","those","under","while","without","should","these","each","which","their","then","grants","deals","causes","adds","increases","decreases","reduces","removes","gives","allows","enables","requires","damage","bonus","skill","weapon","attack","critical","hit","dodge","block","armor","armour","health","enemy","item","character","level","points","turn","round","critical","melee","ranged","energy","fire","plasma","bolt","power","chain","las","melta","fusion","shuriken","splinter","dark","bright","heat","force","shock","arc","needle","webber","acid","stub","revolver","carbine","sniper","hunting","marksman","autogun","shotgun","combat","scoped","full-auto","shredder","double-barreled","fragmentary","sorcerous","witchcraft","troubling","inopportune","retrieve","particular","import","vox-broadcasts","accompanied","chambers","elevator","resorted","traitor"}

SKIP_TEXTS = {"placeholder","tbd","todo","n/a","wip","dummy","test","temp","temporary","stub","none","null","blank","empty","missing","notext","no text","new text","string","template","sample text","lorem ipsum","fixme","fix me","deprecated","obsolete","removed","deleted","hidden","unused","reserved","..."}


def strip_tags(text: str) -> str:
    result = re.sub(r'\{g\|[^}]+\}', '', text)
    result = re.sub(r'\{/g\}', '', result)
    result = re.sub(r'\{n\}', ' ', result)
    result = re.sub(r'\{/n\}', ' ', result)
    result = re.sub(r'\{i\}', ' ', result)
    result = re.sub(r'\{/i\}', ' ', result)
    result = re.sub(r'\{b\}', ' ', result)
    result = re.sub(r'\{/b\}', ' ', result)
    result = re.sub(r'<[^>]+>', ' ', result)
    result = re.sub(r'§TAG\d+§', ' ', result)
    result = result.replace('\\"', '"')
    return result.strip()


def count_english_words(text: str) -> Tuple[int, List[str]]:
    visible = strip_tags(text)
    words = re.findall(r"[a-zA-Z']{3,}", visible)
    found = []
    for w in words:
        wl = w.lower()
        if wl in EN_INDICATORS:
            found.append(w)
    return len(found), found


def is_placeholder(text: str) -> bool:
    clean = text.strip().lower()
    clean = re.sub(r'^[\[\{<\(]+|[\]\}>\)]+$', '', clean)
    return clean in SKIP_TEXTS


def get_glossary_terms(glossary: dict) -> Dict[str, dict]:
    """Retorna mapa term_lower → entry."""
    result = {}
    for t in glossary.get("terms", []):
        en = t.get("term_english", "").lower()
        if en:
            result[en] = t
    return result


# ─── ANÁLISE ───

def audit_translation(orig: dict, trans: dict, glossary: dict) -> dict:
    """Cenário 1: Auditoria da tradução existente."""
    orig_s = orig.get("strings", {})
    trans_s = trans.get("strings", {})
    gterms = get_glossary_terms(glossary) if glossary else {}
    
    categories = {
        "identical": [],       # Idêntico ao original (não traduzido)
        "partial_english": [], # Traduzido parcialmente (ainda tem inglês)
        "placeholder": [],     # Placeholder/marcador
        "glossary_preserved": [], # Termo do glossário (OK ficar em EN)
        "tag_broken": [],      # Tags quebradas
        "ok": [],              # Traduzido corretamente
    }
    
    for key, oitem in orig_s.items():
        otext = oitem.get("Text", "")
        if not otext.strip():
            continue
        
        titem = trans_s.get(key, {})
        ttext = titem.get("Text", "") if titem else ""
        
        # Placeholder?
        if is_placeholder(otext):
            categories["placeholder"].append((key, otext, "placeholder"))
            continue
        
        # Glossário → preservar?
        if otext.strip().lower() in gterms:
            categories["glossary_preserved"].append((key, otext, "glossario"))
            continue
        
        # Idêntico?
        if otext == ttext:
            categories["identical"].append((key, otext, "nao traduzido"))
            continue
        
        # Tags quebradas?
        orig_tags = len(re.findall(r'\{g\|[^}]+\}', otext))
        trans_tags = len(re.findall(r'\{g\|[^}]+\}', ttext))
        if orig_tags != trans_tags:
            categories["tag_broken"].append((key, otext, f"tags: {orig_tags}→{trans_tags}"))
            continue
        
        remaining_ph = re.findall(r'§TAG\d+§', ttext)
        if remaining_ph:
            categories["tag_broken"].append((key, otext, f"placeholders: {remaining_ph}"))
            continue
        
        # Ainda tem inglês?
        en_count, en_words = count_english_words(ttext)
        if en_count >= 2:
            categories["partial_english"].append((key, otext, f"{en_count} EN: {en_words[:5]}"))
            continue
        
        # OK
        categories["ok"].append((key, otext, "OK"))
    
    return categories


def detect_update(en_new: dict, en_old: dict, pt_current: dict) -> dict:
    """Cenário 2: Detecta mudanças no jogo."""
    new_s = en_new.get("strings", {})
    old_s = en_old.get("strings", {})
    pt_s = pt_current.get("strings", {})
    
    result = {
        "new_keys": [],      # UUID novo no jogo
        "modified_keys": [], # Texto mudou no jogo
        "removed_keys": [],  # UUID removido do jogo
        "unchanged_keys": [], # Sem mudança
    }
    
    for key, nitem in new_s.items():
        ntext = nitem.get("Text", "")
        if not ntext.strip():
            continue
        
        if key not in old_s:
            result["new_keys"].append((key, nitem))
        elif old_s[key].get("Text", "") != ntext:
            result["modified_keys"].append((key, nitem, old_s[key].get("Text", "")))
        else:
            result["unchanged_keys"].append(key)
    
    for key in old_s:
        if key not in new_s:
            result["removed_keys"].append(key)
    
    return result


def smart_diff(orig: dict, trans: dict, glossary: dict) -> Tuple[dict, List[Tuple]]:
    """Cenário 3: Diff inteligente que preserva termos do glossário no contexto."""
    orig_s = orig.get("strings", {})
    trans_s = trans.get("strings", {})
    gterms = get_glossary_terms(glossary) if glossary else {}
    
    needs_work = []  # Precisa retraduzir
    preserved_in_context = []  # Tem termos do glossário no meio
    ok = []
    
    for key, oitem in orig_s.items():
        otext = oitem.get("Text", "")
        if not otext.strip():
            continue
        
        ttext = trans_s.get(key, {}).get("Text", "") if trans_s.get(key) else ""
        
        # Placeholder?
        if is_placeholder(otext):
            continue
        
        # Nome de mecânica puro (só o nome)?
        o_clean = strip_tags(otext).strip()
        if o_clean.lower() in gterms and gterms[o_clean.lower()].get("category") in ("weapon","talent","skill","ability","attribute"):
            # É só o nome → OK preservar
            ok.append((key, otext, "nome puro"))
            continue
        
        # Já traduzido corretamente?
        if otext != ttext and ttext.strip():
            en_count, _ = count_english_words(ttext)
            if en_count < 2:
                # Verifica se contém termos do glossário no meio
                found_terms = []
                for tkey, tentry in gterms.items():
                    if tentry.get("category") not in ("weapon","talent","skill","ability","attribute","lore"):
                        continue
                    pattern = r'\b' + re.escape(tkey) + r'\b'
                    if re.search(pattern, otext.lower()):
                        found_terms.append(tentry["term_english"])
                
                if found_terms:
                    preserved_in_context.append((key, otext, ttext, found_terms))
                else:
                    ok.append((key, otext, "OK"))
                continue
        
        # Precisa retraduzir
        found_terms = []
        for tkey, tentry in gterms.items():
            if tentry.get("category") not in ("weapon","talent","skill","ability","attribute","lore"):
                continue
            pattern = r'\b' + re.escape(tkey) + r'\b'
            if re.search(pattern, otext.lower()):
                found_terms.append(tentry["term_english"])
        
        needs_work.append((key, oitem, ttext, found_terms))
    
    return {"needs_work": needs_work, "preserved": preserved_in_context, "ok": ok}, needs_work


# ─── RELATÓRIO ───

def print_report(categories: dict, title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    
    for cat, label, icon in [
        ("identical", "NÃO TRADUZIDO (idêntico ao EN)", "🔴"),
        ("partial_english", "PARCIAL (ainda tem inglês)", "🟡"),
        ("tag_broken", "TAGS QUEBRADAS", "🔴"),
        ("placeholder", "Placeholder (ignorado)", "⚪"),
        ("glossary_preserved", "Glossário preservado (OK)", "🟢"),
        ("ok", "OK (traduzido corretamente)", "🟢"),
    ]:
        items = categories.get(cat, [])
        print(f"\n{icon} {label}: {len(items)}")
        if cat in ("identical", "partial_english", "tag_broken") and items:
            for key, text, detail in items[:5]:
                print(f"   [{key[:8]}...] {detail}")
                print(f"      {text[:70]}...")
            if len(items) > 5:
                print(f"   ... e mais {len(items)-5}")


def print_update_report(result: dict):
    print(f"\n{'='*60}")
    print("  ATUALIZAÇÃO DO JOGO DETECTADA")
    print(f"{'='*60}")
    print(f"\n🆕 NOVOS UUIDs: {len(result['new_keys'])}")
    print(f"📝 MODIFICADOS: {len(result['modified_keys'])}")
    print(f"🗑️ REMOVIDOS: {len(result['removed_keys'])}")
    print(f"[OK] INALTERADOS: {len(result['unchanged_keys'])}")


def print_smart_report(result: dict, needs_work: list):
    print(f"\n{'='*60}")
    print("  PRESERVAÇÃO INTELIGENTE")
    print(f"{'='*60}")
    print(f"\n🟢 OK: {len(result['ok'])}")
    print(f"🔵 Preservados no contexto: {len(result['preserved'])}")
    print(f"🔴 Precisam retraduzir: {len(needs_work)}")
    
    if result['preserved']:
        print(f"\n  Exemplos de preservação no contexto:")
        for key, otext, ttext, terms in result['preserved'][:5]:
            print(f"    EN: {otext[:60]}...")
            print(f"    PT: {ttext[:60]}...")
            print(f"    Termos: {terms[:3]}")
            print()
    
    if needs_work:
        print(f"\n  Exemplos para retraduzir:")
        for key, oitem, ttext, terms in needs_work[:5]:
            otext = oitem.get("Text", "")
            terms_str = f" (contém: {terms[:3]})" if terms else ""
            print(f"    [{key[:8]}...]{terms_str}")
            print(f"    EN: {otext[:60]}...")


# ─── MAIN ───

# Flags that take a value (for positional-subcommand argv expansion)
_VALUE_FLAGS = {"-o", "--out", "-g", "--glossary", "-t", "--translated", "--min-english"}


def _expand_positional_subcommand(argv: List[str]) -> List[str]:
    """Support the documented positional forms by translating them to flag style:
      diff_tool.py update <old_en> <new_en> --out <delta.json>
      diff_tool.py audit <en> <pt> [--out <problems.json>]
    Flag-style invocation is returned unchanged.
    """
    if len(argv) < 2 or argv[1] not in ("update", "audit"):
        return argv
    mode = argv[1]
    positional: List[str] = []
    passthrough: List[str] = []
    i = 2
    while i < len(argv):
        tok = argv[i]
        if tok == "--out":
            passthrough += ["-o", argv[i + 1] if i + 1 < len(argv) else ""]
            i += 2
        elif tok in _VALUE_FLAGS:
            passthrough += [tok, argv[i + 1] if i + 1 < len(argv) else ""]
            i += 2
        elif tok.startswith("-"):
            passthrough.append(tok)  # boolean flag
            i += 1
        else:
            positional.append(tok)
            i += 1
    if mode == "update" and len(positional) >= 2:
        old, new = positional[0], positional[1]  # README order: old first, new second
        return [argv[0], "-i", new, "-i_antigo", old, "--update"] + passthrough
    if mode == "audit" and len(positional) >= 2:
        en, pt = positional[0], positional[1]
        return [argv[0], "-i", en, "-t", pt, "--audit"] + passthrough
    return argv


def main():
    parser = argparse.ArgumentParser(description="Diff Tool — Análise inteligente de tradução")
    parser.add_argument("-i", "--input", required=True, help="Arquivo original (atual) do jogo")
    parser.add_argument("-i_antigo", help="Arquivo anterior do jogo (para detectar update)")
    parser.add_argument("-t", "--translated", help="Arquivo traduzido (ptBR)")
    parser.add_argument("-g", "--glossary", help="Glossário JSON")
    parser.add_argument("-o", "--output", help="Arquivo de saída (JSON para retraduzir)")
    parser.add_argument("--audit", action="store_true", help="Cenário 1: Auditoria")
    parser.add_argument("--update", action="store_true", help="Cenário 2: Detecção de update")
    parser.add_argument("--smart-diff", action="store_true", help="Cenário 3: Preservação inteligente")
    parser.add_argument("--preview", action="store_true", help="Só mostra, não salva")
    parser.add_argument("--min-english", type=int, default=2)
    args = parser.parse_args(_expand_positional_subcommand(sys.argv)[1:])

    orig = load_json(args.input)
    if not orig:
        print("[ERR] Arquivo de entrada inválido"); return 1
    
    glossary = load_json(args.glossary) if args.glossary else None
    trans = load_json(args.translated) if args.translated else None
    en_old = load_json(args.i_antigo) if args.i_antigo else None

    output_data = {"strings": {}}

    # ── Cenário 2: Update ──
    if args.update and en_old:
        # pt_current is optional (kept for backward compat; unused by detect_update)
        result = detect_update(orig, en_old, trans or {})
        print_update_report(result)
        
        # Gera arquivo apenas com UUIDs novos + modificados
        for key, item in result["new_keys"]:
            output_data["strings"][key] = {
                "Offset": item.get("Offset", 0),
                "Text": item.get("Text", ""),
                "_status": "new"
            }
        for key, item, old_text in result["modified_keys"]:
            output_data["strings"][key] = {
                "Offset": item.get("Offset", 0),
                "Text": item.get("Text", ""),
                "_status": "modified",
                "_old_text": old_text
            }
        
        total = len(output_data["strings"])
        print(f"\n📦 Total para traduzir: {total}")

    # ── Cenário 1: Audit ──
    elif args.audit and trans:
        categories = audit_translation(orig, trans, glossary)
        print_report(categories, "AUDITORIA DA TRADUÇÃO")
        
        # Gera arquivo com problemas
        for cat in ("identical", "partial_english", "tag_broken"):
            for key, text, detail in categories.get(cat, []):
                ttext = trans.get("strings", {}).get(key, {}).get("Text", "")
                output_data["strings"][key] = {
                    "Offset": orig["strings"][key].get("Offset", 0),
                    "Text": text,
                    "_current_translation": ttext,
                    "_issue": detail
                }

    # ── Cenário 3: Smart Diff ──
    elif args.smart_diff and trans and glossary:
        result, needs_work = smart_diff(orig, trans, glossary)
        print_smart_report(result, needs_work)
        
        for key, oitem, ttext, terms in needs_work:
            entry = {
                "Offset": oitem.get("Offset", 0),
                "Text": oitem.get("Text", ""),
                "_current_translation": ttext,
                "_issue": "retradução necessária"
            }
            if terms:
                entry["_preserve_terms"] = terms
            output_data["strings"][key] = entry

    else:
        print("[ERR] Modo não reconhecido. Use --audit, --update ou --smart-diff")
        print("   --audit: precisa de -t (traduzido)")
        print("   --update: precisa de -i_antigo (-t opcional)")
        print("   --smart-diff: precisa de -t e -g (glossário)")
        return 1

    # ── Salva ──
    if output_data["strings"] and args.output and not args.preview:
        save_json(output_data, args.output)
        print(f"\n📁 Salvo: {args.output} ({len(output_data['strings'])} itens)")
    
    if args.preview:
        print(f"\n👁️ Preview: {len(output_data['strings'])} itens (não salvo)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
