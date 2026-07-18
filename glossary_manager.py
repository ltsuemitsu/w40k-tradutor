#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciador de Glossário — Ferramenta Interativa
=================================================
Permite visualizar, editar, adicionar e remover termos do glossário evolutivo.
Útil para "corrigir retroactivamente" decisões de tradução entre batches.

Uso:
    python glossary_manager.py glossary.json                    # Modo interativo
    python glossary_manager.py glossary.json --list             # Lista todos os termos
    python glossary_manager.py glossary.json --add              # Adiciona termo interativo
    python glossary_manager.py glossary.json --import terms.csv # Importa de CSV
    python glossary_manager.py glossary.json --export terms.csv # Exporta para CSV
    python glossary_manager.py glossary.json --search "weapon"  # Busca termos
    python glossary_manager.py glossary.json --edit "INT"       # Edita termo específico
    python glossary_manager.py glossary.json --remove "INT"     # Remove termo
"""

import json
import os
import sys
import csv
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict


@dataclass
class GlossaryEntry:
    term_english: str
    term_translated: str
    category: str
    context: str = ""
    confidence: str = "high"
    first_seen_batch: int = 0
    usage_count: int = 1
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "GlossaryEntry":
        return cls(**d)
    
    def display(self, index: int = 0) -> str:
        lines = [
            f"  [{index}] \"{self.term_english}\" → \"{self.term_traduzido}\"",
            f"      Categoria: {self.category} | Confiança: {self.confidence} | Usos: {self.usage_count}",
        ]
        if self.context:
            lines.append(f"      Contexto: {self.context}")
        return "\n".join(lines)


def load_glossary(path: str) -> dict:
    """Carrega ou inicializa glossário."""
    if not os.path.exists(path):
        return {"metadata": {"version": "1.0", "updated_at": datetime.now().isoformat(), "total_terms": 0}, "terms": []}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_glossary(path: str, data: dict):
    """Salva glossário."""
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total_terms"] = len(data.get("terms", []))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Glossário salvo: {path} ({data['metadata']['total_terms']} termos)")


def list_terms(data: dict, category: str = None):
    """Lista todos os termos, opcionalmente filtrado por categoria."""
    terms = data.get("terms", [])
    if category:
        terms = [t for t in terms if t.get("category", "").lower() == category.lower()]
    
    if not terms:
        print("Nenhum termo encontrado.")
        return
    
    # Agrupa por categoria
    by_cat = defaultdict(list)
    for t in terms:
        by_cat[t.get("category", "sem_categoria")].append(t)
    
    print(f"\n📖 Glossário: {len(terms)} termos\n{'='*60}")
    for cat in sorted(by_cat.keys()):
        print(f"\n  [{cat.upper()}] ({len(by_cat[cat])} termos)")
        print(f"  {'-'*50}")
        for i, term in enumerate(by_cat[cat], 1):
            ctx = f" | ctx: {term.get('context', '')}" if term.get('context') else ""
            print(f"  {i:3d}. \"{term['term_english']}\" → \"{term['term_translated']}\" "
                  f"[conf: {term.get('confidence', '?')}, usos: {term.get('usage_count', 0)}]{ctx}")
    print()


def add_term_interactive(data: dict):
    """Adiciona um novo termo interativamente."""
    print("\n➕ Adicionar novo termo ao glossário")
    print("-" * 40)
    
    english = input("Termo em inglês: ").strip()
    if not english:
        print("❌ Cancelado.")
        return
    
    # Verifica se já existe
    existing = next((t for t in data["terms"] if t["term_english"].lower() == english.lower()), None)
    if existing:
        print(f"⚠️ Termo já existe: \"{existing['term_english']}\" → \"{existing['term_translated']}\"")
        overwrite = input("Sobrescrever? (s/N): ").strip().lower()
        if overwrite != 's':
            print("❌ Mantido termo existente.")
            return
        data["terms"].remove(existing)
    
    translated = input("Tradução: ").strip()
    
    print("\nCategorias disponíveis:")
    cats = ["atributo", "skill", "mecanica", "formula", "lore", "item", "outro"]
    for i, c in enumerate(cats, 1):
        print(f"  {i}. {c}")
    cat_input = input("Categoria (número ou nome): ").strip()
    try:
        category = cats[int(cat_input) - 1]
    except (ValueError, IndexError):
        category = cat_input if cat_input else "outro"
    
    context = input("Contexto/Notas (opcional): ").strip()
    
    entry = {
        "term_english": english,
        "term_translated": translated,
        "category": category,
        "context": context,
        "confidence": "high",
        "first_seen_batch": 0,
        "usage_count": 1,
        "created_at": datetime.now().isoformat()
    }
    data["terms"].append(entry)
    print(f"✅ Adicionado: \"{english}\" → \"{translated}\" [{category}]")


def search_terms(data: dict, query: str):
    """Busca termos por substring."""
    query_lower = query.lower()
    results = []
    for t in data.get("terms", []):
        if (query_lower in t.get("term_english", "").lower() or 
            query_lower in t.get("term_translated", "").lower() or
            query_lower in t.get("context", "").lower()):
            results.append(t)
    
    print(f"\n🔍 Busca por \"{query}\": {len(results)} resultados")
    for i, t in enumerate(results, 1):
        ctx = f" | {t.get('context', '')}" if t.get('context') else ""
        print(f"  {i}. \"{t['term_english']}\" → \"{t['term_translated']}\" [{t.get('category', '?')}]{ctx}")
    print()


def edit_term(data: dict, term_english: str):
    """Edita um termo existente."""
    term = next((t for t in data["terms"] if t["term_english"].lower() == term_english.lower()), None)
    if not term:
        print(f"❌ Termo \"{term_english}\" não encontrado.")
        # Sugere busca
        matches = [t for t in data["terms"] if term_english.lower() in t["term_english"].lower()]
        if matches:
            print("Você quis dizer:")
            for m in matches[:5]:
                print(f"  - \"{m['term_english']}\"")
        return
    
    print(f"\n✏️ Editando: \"{term['term_english']}\"")
    print(f"   Tradução atual: \"{term['term_translated']}\"")
    print(f"   Categoria: {term.get('category', '')}")
    print(f"   Contexto: {term.get('context', '')}")
    print("   (Deixe em branco para manter o valor atual)")
    
    new_trans = input("Nova tradução: ").strip()
    if new_trans:
        term["term_translated"] = new_trans
    
    new_cat = input("Nova categoria: ").strip()
    if new_cat:
        term["category"] = new_cat
    
    new_ctx = input("Novo contexto: ").strip()
    if new_ctx:
        term["context"] = new_ctx
    
    term["confidence"] = "high"  # Editado manualmente = alta confiança
    print(f"✅ Atualizado: \"{term['term_english']}\" → \"{term['term_translated']}\"")


def remove_term(data: dict, term_english: str):
    """Remove um termo do glossário."""
    original_len = len(data["terms"])
    data["terms"] = [t for t in data["terms"] if t["term_english"].lower() != term_english.lower()]
    removed = original_len - len(data["terms"])
    if removed:
        print(f"✅ Removido \"{term_english}\".")
    else:
        print(f"❌ Termo \"{term_english}\" não encontrado.")


def export_csv(data: dict, path: str):
    """Exporta glossário para CSV."""
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["term_english", "term_translated", "category", "context", "confidence", "usage_count"])
        for t in data.get("terms", []):
            writer.writerow([
                t.get("term_english", ""),
                t.get("term_translated", ""),
                t.get("category", ""),
                t.get("context", ""),
                t.get("confidence", ""),
                t.get("usage_count", 0)
            ])
    print(f"✅ Exportado: {path} ({len(data.get('terms', []))} termos)")


def import_csv(data: dict, path: str, merge: bool = True):
    """Importa termos de CSV."""
    if not os.path.exists(path):
        print(f"❌ Arquivo não encontrado: {path}")
        return
    
    imported = 0
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {
                "term_english": row.get("term_english", "").strip(),
                "term_translated": row.get("term_translated", "").strip(),
                "category": row.get("category", "outro").strip(),
                "context": row.get("context", "").strip(),
                "confidence": row.get("confidence", "high").strip(),
                "first_seen_batch": 0,
                "usage_count": int(row.get("usage_count", 1)) if row.get("usage_count") else 1,
                "created_at": datetime.now().isoformat()
            }
            if not entry["term_english"] or not entry["term_translated"]:
                continue
            
            # Verifica duplicata
            existing = next((t for t in data["terms"] if t["term_english"].lower() == entry["term_english"].lower()), None)
            if existing:
                if not merge:
                    continue
                # Atualiza
                existing.update(entry)
            else:
                data["terms"].append(entry)
            imported += 1
    
    print(f"✅ Importado: {imported} termos de {path}")


def interactive_mode(data: dict, path: str):
    """Modo interativo contínuo."""
    print("\n" + "="*60)
    print("  GERENCIADOR DE GLOSSÁRIO — Modo Interativo")
    print("="*60)
    print(f"Arquivo: {path} | Termos atuais: {len(data.get('terms', []))}")
    print("\nComandos: list | add | search | edit | remove | export | import | save | quit")
    
    while True:
        try:
            cmd = input("\n> ").strip().lower()
            parts = cmd.split(None, 1)
            action = parts[0] if parts else ""
            arg = parts[1] if len(parts) > 1 else ""
            
            if action in ("quit", "q", "exit"):
                save_glossary(path, data)
                print("👋 Até logo!")
                break
            elif action == "list" or action == "ls":
                list_terms(data, arg if arg else None)
            elif action == "add" or action == "a":
                add_term_interactive(data)
            elif action == "search" or action == "s" or action == "find":
                search_terms(data, arg if arg else input("Buscar: "))
            elif action == "edit" or action == "e":
                edit_term(data, arg if arg else input("Termo a editar: "))
            elif action == "remove" or action == "rm" or action == "del":
                remove_term(data, arg if arg else input("Termo a remover: "))
            elif action == "export":
                export_path = arg if arg else input("Arquivo CSV de saída: ")
                export_csv(data, export_path)
            elif action == "import":
                import_path = arg if arg else input("Arquivo CSV de entrada: ")
                import_csv(data, import_path)
            elif action == "save":
                save_glossary(path, data)
            elif action == "help" or action == "h" or action == "?":
                print("Comandos: list [categoria] | add | search <query> | edit <termo> | remove <termo> | export <arquivo.csv> | import <arquivo.csv> | save | quit")
            else:
                print(f"❓ Comando desconhecido: '{action}'. Digite 'help' para ajuda.")
        
        except KeyboardInterrupt:
            print("\n\n💾 Salvando antes de sair...")
            save_glossary(path, data)
            break
        except Exception as e:
            print(f"❌ Erro: {e}")


def main():
    parser = argparse.ArgumentParser(description="Gerenciador de Glossário de Tradução de Jogos")
    parser.add_argument("glossary_file", help="Arquivo JSON do glossário")
    parser.add_argument("--list", action="store_true", help="Lista todos os termos")
    parser.add_argument("--category", help="Filtra por categoria ao listar")
    parser.add_argument("--add", action="store_true", help="Adiciona termo interativamente")
    parser.add_argument("--search", help="Busca termos por substring")
    parser.add_argument("--edit", help="Edita termo específico")
    parser.add_argument("--remove", help="Remove termo específico")
    parser.add_argument("--export", metavar="CSV", help="Exporta para CSV")
    parser.add_argument("--import-csv", metavar="CSV", help="Importa de CSV")
    
    args = parser.parse_args()
    
    data = load_glossary(args.glossary_file)
    
    if args.list:
        list_terms(data, args.category)
    elif args.add:
        add_term_interactive(data)
        save_glossary(args.glossary_file, data)
    elif args.search:
        search_terms(data, args.search)
    elif args.edit:
        edit_term(data, args.edit)
        save_glossary(args.glossary_file, data)
    elif args.remove:
        remove_term(data, args.remove)
        save_glossary(args.glossary_file, data)
    elif args.export:
        export_csv(data, args.export)
    elif args.import_csv:
        import_csv(data, args.import_csv)
        save_glossary(args.glossary_file, data)
    else:
        interactive_mode(data, args.glossary_file)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
