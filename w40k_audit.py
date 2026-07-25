"""W40K Translator — Corrigir & Auditar + gate de release (Fase 4, sem Qt).

Lógica da jornada ② (auditoria) e do gate da jornada ③ (§4.2/§4.3):

  - audit_output: classifica o output em Falhas / Idênticas / Suspeitas
    reusando scripts/audit_translation.py (import direto) + varredura
    extra de placeholders vazados ($TERM4$, §TAGn§, [[W40KTn]], {mf|...})
  - run_audit: grava o relatório em audit/ e atualiza project.json.last_audit
  - write_retry_uuids / build_retry_args: export de UUIDs e comando do
    engine (--retranslate-map) para retraduzir só os selecionados
  - mark_for_retry / merge_with_backup: backup em backups/ + escrita
    atômica, seguindo a semântica do merge.py
  - release_gate_decision: função pura do gate de publicação
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import w40k_project as wp
import w40k_settings as _settings

REPO_ROOT = Path(__file__).resolve().parent

CATEGORIES = ("failed", "identical", "suspect")
CATEGORY_NAMES_PT = {
    "failed": "Falhas (erros de API)",
    "identical": "Idênticas (EN = PT)",
    "suspect": "Suspeitas (placeholders/tags/meio-tradução)",
}


def _profile_run_flags(model: str) -> List[str]:
    """-w/--save-every do perfil EFETIVO (overrides das Configurações).

    Sem flags explícitas o engine auto-resolve pelos padrões de CÓDIGO de
    model_profiles e ignora os overrides do usuário em w40k_settings.
    """
    _rid, prof = _settings.resolve_effective_profile(model)
    workers = int(prof.get("workers") or 3)
    save_every = max(1, int(prof.get("save_every") or 5))
    return ["-w", str(workers), "--save-every", str(save_every)]

# Placeholders/artefatos que NUNCA deveriam aparecer no PT final.
_LEAK_RES = [
    re.compile(r"§TAG\d+§"),
    re.compile(r"\$TERM\d+\$"),
    re.compile(r"\[\[W40KT\d+\]\]"),
    re.compile(r"\{mf\|[^}]*\}"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Import do script de auditoria do engine (sem modificá-lo)
# ─────────────────────────────────────────────────────────────────────────────

def _load_audit_script():
    """Importa scripts/audit_translation.py pelo caminho (scripts/ não é
    pacote). None se indisponível."""
    script = REPO_ROOT / "scripts" / "audit_translation.py"
    if not script.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "w40k_audit_translation", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Auditoria
# ─────────────────────────────────────────────────────────────────────────────

def audit_output(output_path: Path, input_path: Path) -> Dict[str, Any]:
    """Audita um output contra o input EN.

    Retorna {"rows": [{uuid, category, reason, en, pt}], "counts":
    {failed, identical, suspect}, "total": N}. Levanta ProjectError
    (PT-BR) quando os arquivos faltam ou o script de auditoria falha.
    """
    output_path = Path(output_path)
    input_path = Path(input_path)
    if not output_path.is_file():
        raise wp.ProjectError(f"Output não encontrado: {output_path.name}")
    if not input_path.is_file():
        raise wp.ProjectError(
            "O input/enGB.json é necessário para comparar EN × PT na "
            "auditoria.")

    pt_data = wp.load_localization(output_path)
    en_data = wp.load_localization(input_path)
    pt_strings = pt_data["strings"]
    en_strings = en_data["strings"]

    module = _load_audit_script()
    if module is None:
        raise wp.ProjectError(
            "scripts/audit_translation.py não pôde ser carregado.")
    raw = module.audit_strings(pt_data, en_data)

    rows: List[Dict[str, Any]] = []
    flagged = set()

    def _texts(uuid: str) -> Tuple[str, str]:
        en = (en_strings.get(uuid) or {}).get("Text", "")
        pt = (pt_strings.get(uuid) or {}).get("Text", "")
        return en, pt

    # O script agrupa "identical_to_en" dentro de "failed" — separar aqui
    # nas três categorias do design (Falhas / Idênticas / Suspeitas).
    for item in raw.get("failed", []):
        uuid = item["uuid"]
        en, pt = _texts(uuid)
        if item.get("reason") == "identical_to_en":
            category = "identical"
        else:
            category = "failed"
        rows.append({"uuid": uuid, "category": category,
                     "reason": item.get("reason", ""), "en": en, "pt": pt})
        flagged.add(uuid)

    for item in raw.get("suspect", []):
        uuid = item["uuid"]
        if uuid in flagged:
            continue
        en, pt = _texts(uuid)
        rows.append({"uuid": uuid, "category": "suspect",
                     "reason": item.get("reason", ""), "en": en, "pt": pt})
        flagged.add(uuid)

    # Varredura extra do design: placeholders/tags vazados no PT final.
    for uuid, entry in pt_strings.items():
        if uuid in flagged or not isinstance(entry, dict):
            continue
        if entry.get("_skipped") or entry.get("_preserved"):
            continue
        pt = (entry.get("Text") or "")
        if not pt.strip():
            continue
        leaks = [rx.pattern for rx in _LEAK_RES if rx.search(pt)]
        if leaks:
            en, _ = _texts(uuid)
            rows.append({"uuid": uuid, "category": "suspect",
                         "reason": "placeholder_vazou", "en": en, "pt": pt})
            flagged.add(uuid)

    counts = {cat: sum(1 for r in rows if r["category"] == cat)
              for cat in CATEGORIES}
    return {"rows": rows, "counts": counts, "total": len(pt_strings)}


def run_audit(project: wp.Project, track: str) -> Dict[str, Any]:
    """Audita a trilha, grava audit/<data>_audit_<trilha>.json e atualiza
    project.json.last_audit ({date, failed, identical, suspect})."""
    input_path = project.input_path()
    if input_path is None:
        raise wp.ProjectError("Nenhum input registrado no projeto.")
    output = project.track_path(track)
    if output is None:
        raise wp.ProjectError(
            f"Nenhum master registrado para a trilha {track}.")
    report = audit_output(output, input_path)
    report["track"] = track
    report["date"] = datetime.now().isoformat(timespec="milliseconds")

    audit_dir = project.root / "audit"
    try:
        audit_dir.mkdir(exist_ok=True)
        report_path = audit_dir / f"{date.today().isoformat()}_audit_{track}.json"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise wp.ProjectError(f"Não foi possível gravar o relatório: {exc}")

    project.state["last_audit"] = {
        "date": report["date"],
        "failed": report["counts"]["failed"],
        "identical": report["counts"]["identical"],
        "suspect": report["counts"]["suspect"],
    }
    project.save()
    report["report_path"] = report_path
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Retradução dos selecionados
# ─────────────────────────────────────────────────────────────────────────────

def write_retry_uuids(project: wp.Project, uuids: List[str]) -> Path:
    """Grava audit/<data>_retry_uuids.json (lista simples de UUIDs — formato
    aceito pelo --retranslate-map do engine)."""
    if not uuids:
        raise wp.ProjectError("Nenhum UUID selecionado para retraduzir.")
    audit_dir = project.root / "audit"
    try:
        audit_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise wp.ProjectError(f"Não foi possível criar audit/: {exc}")
    path = audit_dir / f"{date.today().isoformat()}_retry_uuids.json"
    if path.exists():
        path = audit_dir / (
            f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_retry_uuids.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sorted(uuids), fh, indent=2)
    except OSError as exc:
        raise wp.ProjectError(f"Não foi possível gravar os UUIDs: {exc}")
    return path


def build_retry_args(tradutor_py: Path, project: wp.Project, track: str,
                     retry_file: Path, model: str,
                     glossary_path: Optional[Path]) -> List[str]:
    """Comando do engine para retraduzir SÓ os UUIDs exportados.

    --mode preserve na trilha Preservada; --mode complete na Completa
    (100% PT). --resume mantém o resto do output intacto.
    """
    mode = "preserve" if track == wp.TRACK_PRESERVED else "complete"
    args = [
        str(tradutor_py),
        "-i", str(project.input_path()),
        "-o", str(project.track_target(track)),
        "--mode", mode,
        "--resume",
        "--retranslate-map", str(retry_file),
        "--model", model,
    ]
    args += _profile_run_flags(model)
    if track == wp.TRACK_PRESERVED:
        args += ["--preserve-map",
                 str(project.root / "patches" / "preserve_map.json")]
    if glossary_path is not None:
        args += ["-g", str(glossary_path)]
    return args


# ─────────────────────────────────────────────────────────────────────────────
# Merge com backup (semântica do merge.py, backups/ do projeto)
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write_json(data: Any, path: Path) -> None:
    """Escrita atômica (tmp + move), como o atomic_save do engine."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        shutil.move(str(tmp), str(path))
    except OSError as exc:
        raise wp.ProjectError(f"Falha ao gravar {path.name}: {exc}")


def backup_output(project: wp.Project, output_path: Path) -> Path:
    """Copia o output para backups/<datahora>_pre-merge_<nome>.json."""
    backups_dir = project.root / "backups"
    try:
        backups_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        dest = backups_dir / f"{stamp}_pre-merge_{output_path.name}"
        shutil.copy2(output_path, dest)
        return dest
    except OSError as exc:
        raise wp.ProjectError(f"Falha ao criar backup: {exc}")


def merge_with_backup(project: wp.Project, track: str,
                      updates: Dict[str, str]) -> Dict[str, Any]:
    """Aplica textos novos no output da trilha, com backup antes.

    Semântica do merge.py: ignora textos vazios, só grava se mudou, limpa
    a flag _failed das entradas corrigidas. Retorna {backup, changed}.
    """
    output_path = project.track_path(track)
    if output_path is None or not output_path.is_file():
        raise wp.ProjectError(
            f"Output não encontrado para a trilha {track}.")
    data = wp.load_localization(output_path)
    strings = data["strings"]

    todo = {k: v for k, v in updates.items()
            if k in strings and v and v.strip()}
    if not todo:
        raise wp.ProjectError("Nada para mesclar (textos vazios ou UUIDs "
                              "ausentes do output).")

    backup = backup_output(project, output_path)
    changed = 0
    for uuid, text in todo.items():
        entry = strings[uuid]
        if entry.get("Text") != text:
            entry["Text"] = text
            entry.pop("_failed", None)
            changed += 1
    if changed:
        _atomic_write_json(data, output_path)
    return {"backup": backup, "changed": changed}


def mark_for_retry(project: wp.Project, track: str,
                   uuids: List[str]) -> Dict[str, Any]:
    """Marca UUIDs como _failed (com backup) para que o engine os retraduza
    mesmo com --resume (a checagem de 'já feito' pula entradas com texto
    que NÃO estão _failed)."""
    output_path = project.track_path(track)
    if output_path is None or not output_path.is_file():
        raise wp.ProjectError(
            f"Output não encontrado para a trilha {track}.")
    data = wp.load_localization(output_path)
    strings = data["strings"]
    targets = [u for u in uuids if u in strings]
    if not targets:
        raise wp.ProjectError("Nenhum dos UUIDs selecionados existe no "
                              "output da trilha.")
    backup = backup_output(project, output_path)
    for uuid in targets:
        strings[uuid]["_failed"] = True
    _atomic_write_json(data, output_path)
    return {"backup": backup, "marked": len(targets)}


# ─────────────────────────────────────────────────────────────────────────────
# Gate de release (§4.3) — função pura
# ─────────────────────────────────────────────────────────────────────────────

GATE_OK = "ok"
GATE_WARN = "warn"
GATE_BLOCKED = "blocked"


def _audit_timestamp(audit_date: str) -> float:
    """ISO datetime → timestamp; date-only (schema antigo) → fim do dia,
    para não marcar como desatualizado quem auditou no mesmo dia."""
    text = str(audit_date).strip()
    try:
        if "T" not in text and " " not in text:
            # date-only: considera o fim do dia
            day = date.fromisoformat(text[:10])
            return datetime.combine(day, time(23, 59, 59)).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def release_gate_decision(last_audit: Optional[Dict[str, Any]],
                          output_mtimes: List[float]
                          ) -> Tuple[str, str]:
    """Decide se a release pode sair.

    Entradas: project.json.last_audit (ou None) e mtimes dos outputs que
    serão exportados. Retorna (decisão, motivo PT-BR):
      - "blocked": sem auditoria ou outputs mais novos que a auditoria
      - "warn":    auditoria em dia, mas com falhas/suspeitas pendentes
      - "ok":      auditoria em dia e limpa (idênticas não bloqueiam)
    """
    if not last_audit or not last_audit.get("date"):
        return (GATE_BLOCKED,
                "Auditoria nunca executada. Rode a auditoria antes de "
                "publicar — a release precisa sair 100% auditada.")

    audit_ts = _audit_timestamp(str(last_audit["date"]))
    # Tolerância de 1s: mtimes do filesystem e o relógio do ISO podem
    # divergir por frações de segundo dentro da mesma execução.
    if any(m > audit_ts + 1.0 for m in output_mtimes):
        return (GATE_BLOCKED,
                "Os outputs mudaram desde a última auditoria. Rode a "
                "auditoria novamente antes de publicar — a release precisa "
                "sair 100% auditada.")

    failed = int(last_audit.get("failed") or 0)
    suspect = int(last_audit.get("suspect") or 0)
    identical = int(last_audit.get("identical") or 0)
    if failed > 0 or suspect > 0:
        partes = []
        if failed:
            partes.append(f"{failed} falhas")
        if suspect:
            partes.append(f"{suspect} suspeitas")
        if identical:
            partes.append(f"{identical} idênticas (nomes próprios são "
                          "legítimos)")
        return (GATE_WARN,
                "A última auditoria encontrou " + " · ".join(partes) + ".")
    if identical > 0:
        return (GATE_OK,
                f"Auditoria limpa — {identical} idênticas (legítimas).")
    return (GATE_OK, "Auditoria limpa ✓")
