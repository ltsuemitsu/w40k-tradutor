"""w40k_patch.py — Dia de Patch (Fase 5 do GUI_REDESIGN.md, §4.4).

Camada Qt-free da jornada ④: diff EN antigo × EN novo (via diff_tool,
sem modificar o engine), construção do delta pago, detecção de strings
movidas/esvaziadas e merge nos masters com backup e higiene de metadados.

Conclusões do delta-audit implementadas aqui:
  1. UUIDs removidos nunca saíam dos masters → limpeza OPCIONAL no merge
     (desmarcada por padrão na UI), sempre com backup.
  2. Strings movidas (UUID re-keyed, texto idêntico) custavam em dobro →
     content-matching: o PT existente viaja GRÁTIS para o UUID novo e a
     string NÃO entra no delta pago.
  3. Strings esvaziadas pelo patch (texto novo em branco) eram invisíveis
     ao detect_update → detectadas aqui e tratadas como remoções na
     limpeza.
  4. Higiene: chaves de metadado de delta (_status/_old_text/_issue…)
     NUNCA são gravadas nos masters.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import diff_tool

import w40k_audit as au
import w40k_preflight as pf
import w40k_project as wp

# Chaves de metadado de arquivos de delta/validação que não podem vazar
# para os masters (fix 4). Flags legítimas do engine (_failed, _preserved,
# _skipped) NÃO estão aqui.
STRIP_KEYS = ("_status", "_old_text", "_issue", "_issues")

STATUS_NEW = "new"
STATUS_MODIFIED = "modified"


# ─────────────────────────────────────────────────────────────────────────────
# Diff e categorias (grátis)
# ─────────────────────────────────────────────────────────────────────────────

def categorize_patch(old_data: Dict[str, Any],
                     new_data: Dict[str, Any],
                     pt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Classifica o impacto do patch a partir do detect_update do engine.

    Retorna dict com listas:
      new:      [(uuid, texto_novo)]
      modified: [(uuid, texto_novo, texto_antigo)]
      moved:    [(uuid_antigo, uuid_novo, texto_en, texto_pt_ou_vazio)]
      removed:  [(uuid, texto_antigo)]
      emptied:  [(uuid, texto_antigo)]
    e contagens total_new_dump / changed / unchanged.
    """
    old_s = old_data.get("strings", {})
    new_s = new_data.get("strings", {})
    pt_s = pt_data.get("strings", {})

    diff = diff_tool.detect_update(new_data, old_data, pt_data)

    # Esvaziadas: texto novo em branco + antigo não — o detect_update pula
    # textos em branco, então estas strings seriam invisíveis (fix 3).
    emptied: List[Tuple[str, str]] = []
    for key, nitem in new_s.items():
        if not isinstance(nitem, dict):
            continue
        if str(nitem.get("Text", "")).strip():
            continue
        old_text = str((old_s.get(key) or {}).get("Text", ""))
        if old_text.strip():
            emptied.append((key, old_text))

    # Movidas: UUID removido cujo texto EN aparece intacto entre as novas
    # (re-key do jogo) → PT existente é reaproveitado GRÁTIS (fix 2).
    text_to_new_uuid: Dict[str, str] = {}
    for key, nitem in diff["new_keys"]:
        text_to_new_uuid.setdefault(str(nitem.get("Text", "")), key)

    moved: List[Tuple[str, str, str, str]] = []
    removed: List[Tuple[str, str]] = []
    consumed_new: set = set()
    for key in diff["removed_keys"]:
        old_text = str((old_s.get(key) or {}).get("Text", ""))
        target = (text_to_new_uuid.get(old_text)
                  if old_text.strip() else None)
        if target is not None and target not in consumed_new:
            pt_text = str((pt_s.get(key) or {}).get("Text", ""))
            moved.append((key, target, old_text, pt_text))
            consumed_new.add(target)
        else:
            removed.append((key, old_text))

    new_list = [(key, str(nitem.get("Text", "")))
                for key, nitem in diff["new_keys"]
                if key not in consumed_new]
    modified = [(key, str(nitem.get("Text", "")), str(old_text))
                for key, nitem, old_text in diff["modified_keys"]]

    changed = (len(new_list) + len(modified) + len(moved)
               + len(removed) + len(emptied))
    return {
        "total_new_dump": len(new_s),
        "changed": changed,
        "new": new_list,
        "modified": modified,
        "moved": moved,
        "removed": removed,
        "emptied": emptied,
        "unchanged": len(diff["unchanged_keys"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Delta pago (novas + modificadas — movidas NÃO entram)
# ─────────────────────────────────────────────────────────────────────────────

def build_delta(preview: Dict[str, Any],
                new_data: Dict[str, Any]) -> Dict[str, Any]:
    """Arquivo de input para o engine: só novas + modificadas, com
    _status/_old_text (stripped no merge — nunca chegam aos masters)."""
    new_s = new_data.get("strings", {})
    strings: Dict[str, Any] = {}
    for uuid, text in preview["new"]:
        strings[uuid] = {
            "Offset": (new_s.get(uuid) or {}).get("Offset", 0),
            "Text": text,
            "_status": STATUS_NEW,
        }
    for uuid, new_text, old_text in preview["modified"]:
        strings[uuid] = {
            "Offset": (new_s.get(uuid) or {}).get("Offset", 0),
            "Text": new_text,
            "_status": STATUS_MODIFIED,
            "_old_text": old_text,
        }
    return {"strings": strings}


def _atomic_write_json(data: Any, path: Path) -> None:
    """Escrita atômica (tmp + move), como o atomic_save do engine."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        shutil.move(str(tmp), str(path))
    except OSError as exc:
        raise wp.ProjectError(f"Falha ao gravar {path.name}: {exc}")


def delta_path(project: wp.Project, day: Optional[date] = None) -> Path:
    day = day or date.today()
    return project.root / "patches" / f"{day.isoformat()}_delta.json"


def delta_pt_path(project: wp.Project, day: Optional[date] = None) -> Path:
    day = day or date.today()
    return project.root / "patches" / f"{day.isoformat()}_delta_pt.json"


def write_delta(project: wp.Project, delta: Dict[str, Any],
                day: Optional[date] = None) -> Path:
    """Grava patches/<data>_delta.json (atômico)."""
    path = delta_path(project, day)
    try:
        path.parent.mkdir(exist_ok=True)
    except OSError as exc:
        raise wp.ProjectError(f"Não foi possível criar patches/: {exc}")
    _atomic_write_json(delta, path)
    return path


def build_delta_args(tradutor_py: Path, project: wp.Project,
                     delta_in: Path, delta_out: Path, model: str,
                     glossary_path: Optional[Path]) -> List[str]:
    """Comando do engine para traduzir SÓ o delta (modo preserve, com o
    preserve-map da trilha Preservada quando ela existe)."""
    args = [
        str(tradutor_py),
        "-i", str(delta_in),
        "-o", str(delta_out),
        "--mode", "preserve",
        "--resume",
        "--model", model,
    ]
    args += au._profile_run_flags(model)
    if project.track_path(wp.TRACK_PRESERVED) is not None:
        args += ["--preserve-map",
                 str(project.root / "patches" / "preserve_map.json")]
    if glossary_path is not None:
        args += ["-g", str(glossary_path)]
    return args


# ─────────────────────────────────────────────────────────────────────────────
# Novo input: registra o dump novo NO LUGAR (nome versionado preservado)
# ─────────────────────────────────────────────────────────────────────────────

def register_new_input(project: wp.Project,
                       source: Path | str) -> Dict[str, Any]:
    """Registra o dump pós-patch como o novo input do projeto.

    Convenção §2: se o arquivo já está em input/, registra no lugar; se
    veio de fora, é copiado como input/enGB_<versão>.json (versão do nome
    do arquivo; fallback: data). NUNCA renomeia para um nome canônico.
    O input ANTERIOR é o lado "velho" do diff — sem ele, bloqueia.
    """
    if not project.has_input():
        raise wp.ProjectError(
            "Nenhum EN anterior registrado no projeto. O Dia de Patch "
            "compara o dump novo com o dump já registrado — conclua "
            "① Nova Tradução (ou adote uma tradução existente) primeiro.")
    source = Path(source)
    if not source.is_file():
        raise wp.ProjectError(f"Arquivo não encontrado: {source.name}")

    version = wp.extract_game_version(source.name)
    if project._is_inside_project(source):
        target = source  # já está no lugar: registra sem copiar
    else:
        archive_name = (f"enGB_{version}.json" if version
                        else f"enGB_{date.today().isoformat()}.json")
        target = project.root / "input" / archive_name
        try:
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(source, target)
        except OSError as exc:
            raise wp.ProjectError(f"Falha ao arquivar o dump novo: {exc}")

    # Registro + metadados (contagem, sha256, caminho exato).
    registered = project.set_input(target)
    # A versão detectada SUBSTITUI a anterior (o jogo avançou).
    if version:
        project.set_game_version(version)
    return {"archive": registered, "registered": registered,
            "version": version or None}


# ─────────────────────────────────────────────────────────────────────────────
# Merge no master Preservada (backup + higiene + limpeza opcional)
# ─────────────────────────────────────────────────────────────────────────────

def merge_patch(project: wp.Project, track: str,
                delta_pt: Path | str,
                preview: Dict[str, Any],
                cleanup: bool = False) -> Dict[str, Any]:
    """Mescla o patch no master da trilha, nesta ordem:

      1. Movidas: o PT do UUID antigo viaja GRÁTIS para o UUID novo
         (o UUID antigo sai do master — foi re-keyed pelo jogo).
      2. Delta traduzido: upsert das novas+modificadas (semântica do
         merge.py: textos vazios são ignorados).
      3. Limpeza OPCIONAL (cleanup=True): removidas + esvaziadas saem
         do master.
      4. Higiene: _status/_old_text/_issue… jamais ficam no master.

    Sempre com backup timestamped em backups/ antes de mexer no arquivo.
    """
    output = project.track_path(track)
    if output is None or not output.is_file():
        raise wp.ProjectError(
            f"Output não encontrado para a trilha {track}.")
    master = wp.load_localization(output)
    strings = master["strings"]
    backup = au.backup_output(project, output)
    stats = {"backup": backup, "moved": 0, "upserted": 0,
             "skipped_empty": 0, "cleaned": 0, "stripped": 0}

    def strip_meta(entry: Dict[str, Any]) -> int:
        removed = 0
        for key in STRIP_KEYS:
            if key in entry:
                del entry[key]
                removed += 1
        return removed

    # 1. Movidas — reaproveitamento grátis do PT existente.
    for old_uuid, new_uuid, _en_text, pt_hint in preview["moved"]:
        old_entry = strings.get(old_uuid)
        carried = str((old_entry or {}).get("Text", "") or pt_hint or "")
        if not carried.strip():
            continue  # sem PT para carregar — não inventa tradução
        new_entry = (dict(old_entry) if isinstance(old_entry, dict)
                     else {"Text": carried})
        stats["stripped"] += strip_meta(new_entry)
        strings[new_uuid] = new_entry
        strings.pop(old_uuid, None)
        stats["moved"] += 1

    # 2. Delta traduzido — upsert (ignora vazios, como o merge.py).
    delta = wp.load_localization(delta_pt)
    for uuid, entry in delta.get("strings", {}).items():
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("Text", "")).strip():
            stats["skipped_empty"] += 1
            continue
        clean = dict(entry)
        stats["stripped"] += strip_meta(clean)
        strings[uuid] = clean
        stats["upserted"] += 1

    # 3. Limpeza opcional — removidas + esvaziadas (fix 1 e 3).
    if cleanup:
        for uuid, _old in list(preview["removed"]) + list(preview["emptied"]):
            if uuid in strings:
                del strings[uuid]
                stats["cleaned"] += 1

    # 4. Higiene global — nenhum metadado de delta sobrevive no master.
    for entry in strings.values():
        if isinstance(entry, dict):
            stats["stripped"] += strip_meta(entry)

    _atomic_write_json(master, output)
    return stats


def update_project_after_patch(project: wp.Project,
                               version: Optional[str],
                               preview: Dict[str, Any],
                               merged_tracks: List[str]) -> None:
    """Atualiza project.json após o merge: bump de versão nos masters
    (ÚNICO rename do app, §2), contagens das trilhas e patches[]."""
    if version:
        # Masters mesclados passam a carregar a versão nova no nome
        # (os anteriores já estão seguros em backups/).
        project.rename_files_to_version(version)
    for track in merged_tracks:
        path = project.track_path(track)
        if path is None:
            continue
        counts = pf.summarize_output(path)
        project.update_track(track, wp.TRACK_STATUS_DONE,
                             translated=counts["translated"],
                             skipped_free=counts["skipped_free"])
    patches = project.state.setdefault("patches", [])
    patches.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "version": version or None,
        "new": len(preview["new"]),
        "modified": len(preview["modified"]),
        "moved": len(preview["moved"]),
        "removed": len(preview["removed"]),
        "emptied": len(preview["emptied"]),
    })
    project.save()
