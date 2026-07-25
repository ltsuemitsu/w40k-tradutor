"""W40K Translator — Finalizar & Publicar (Fase 3, sem Qt).

Lógica da jornada ②, importável sem PySide6:

  - build_fullize_args / parse_fullize_line: comando e saída do
    `tradutor.py --fullize` (trilha Completa derivada GRÁTIS da Preservada)
  - needs_refullize: Preservada mais nova que a Completa
  - export_release: zip `traducao_<TRACK>_<versão>.zip` na pasta release/
    com enGB.json + LEIA-ME_INSTALACAO.txt + CHANGELOG.txt, snapshot
    `_src.json` para o diff da próxima release e registro no project.json
  - count_changed_strings: diff simples de Text entre dois dumps
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import w40k_project as wp

# Rótulos do nome do zip — convenção do usuário:
# traducao_FULL_1.6.1.514.zip / traducao_PRESERVED_1.6.1.514.zip
TRACK_ZIP_LABELS = {
    wp.TRACK_FULL: "FULL",
    wp.TRACK_PRESERVED: "PRESERVED",
}
TRACK_NAMES_PT = {
    wp.TRACK_FULL: "Completa (100% PT-BR)",
    wp.TRACK_PRESERVED: "Preservada (mecânica/wiki em inglês)",
}

GAME_LOCALIZATION_HINT = "...\\WH40KRT_Data\\StreamingAssets\\Localization\\"

_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


# ─────────────────────────────────────────────────────────────────────────────
# Fullize (grátis)
# ─────────────────────────────────────────────────────────────────────────────

def build_fullize_args(tradutor_py: Path, project: wp.Project,
                       glossary_path: Path) -> List[str]:
    """Comando do engine: tradutor.py --fullize -i preservada -o full -g gloss.

    Lê o master Preservada registrado (track_path) e escreve a Completa
    no caminho alvo (track_target — versionado quando há game_version).
    """
    return [
        str(tradutor_py),
        "--fullize",
        "-i", str(project.track_path(wp.TRACK_PRESERVED)),
        "-o", str(project.track_target(wp.TRACK_FULL)),
        "-g", str(glossary_path),
    ]


_FULLIZE_RE = re.compile(
    r"Fullize:\s*(\d+)\s+strings altered.*glossary pairs=(\d+)")


def parse_fullize_line(line: str) -> Optional[Dict[str, int]]:
    """'Fullize: 1234 strings altered | out=... | glossary pairs=2694'."""
    match = _FULLIZE_RE.search(line or "")
    if not match:
        return None
    return {"changed": int(match.group(1)), "pairs": int(match.group(2))}


def needs_refullize(project: wp.Project) -> bool:
    """True se a Preservada existe e é mais nova que a Completa (ou a
    Completa não existe)."""
    preserved = project.track_path(wp.TRACK_PRESERVED)
    full = project.track_path(wp.TRACK_FULL)
    if preserved is None or not preserved.is_file():
        return False
    if full is None or not full.is_file():
        return True
    return preserved.stat().st_mtime > full.stat().st_mtime


# ─────────────────────────────────────────────────────────────────────────────
# Validação e nomes
# ─────────────────────────────────────────────────────────────────────────────

def validate_release_version(version: str) -> str:
    """Validação frouxa (dígitos+pontos), mesma regra da versão do jogo."""
    version = (version or "").strip()
    if not version:
        raise wp.ProjectError(
            "Informe a versão do pacote (ex.: 1.6.1.514).")
    if not _VERSION_RE.match(version):
        raise wp.ProjectError(
            "Versão inválida — use apenas números e pontos "
            "(ex.: 1.6.1.514).")
    return version


def release_zip_name(track: str, version: str) -> str:
    if track not in TRACK_ZIP_LABELS:
        raise wp.ProjectError(f"Trilha desconhecida: {track}")
    return f"traducao_{TRACK_ZIP_LABELS[track]}_{version}.zip"


def src_snapshot_name(track: str, version: str) -> str:
    """Snapshot do output exportado, guardado ao lado do zip para o diff
    da próxima release."""
    return f"traducao_{TRACK_ZIP_LABELS[track]}_{version}_src.json"


# ─────────────────────────────────────────────────────────────────────────────
# Textos do pacote
# ─────────────────────────────────────────────────────────────────────────────

def build_readme(track: str, version: str, date_str: str) -> str:
    """LEIA-ME_INSTALACAO.txt em PT-BR."""
    track_name = TRACK_NAMES_PT.get(track, track)
    return f"""W40K TRANSLATOR — Tradução PT-BR de Warhammer 40K: Rogue Trader
====================================================================

Pacote:  tradução {track_name}
Versão:  {version}
Gerado:  {date_str}

Esta é uma TRADUÇÃO DE FÃ, sem qualquer vínculo com a Owlcat Games
ou a Games Workshop.

INSTALAÇÃO
----------
1. FAÇA BACKUP do arquivo original enGB.json do jogo.
2. Copie o enGB.json deste pacote para a pasta de localização do jogo:

     {GAME_LOCALIZATION_HINT}

   (dentro da instalação do Warhammer 40K: Rogue Trader — substitua o
   arquivo existente; o jogo exige exatamente o nome "enGB.json")
3. Inicie o jogo. Para voltar ao inglês, restaure o backup do passo 1.

SOBRE ESTA TRILHA
-----------------
{_track_explanation(track)}

Gerado pelo projeto W40K Translator (ferramenta de fã, código aberto).
"""


def _track_explanation(track: str) -> str:
    if track == wp.TRACK_FULL:
        return ("Trilha COMPLETA: todo o texto em português, incluindo nomes\n"
                "de mecânica (armas, talentos, atributos).")
    return ("Trilha PRESERVADA: a narrativa está em português, mas nomes de\n"
            "mecânica e da wiki (armas, talentos, atributos) permanecem em\n"
            "inglês, como os jogadores de Rogue Trader esperam.")


def build_changelog(version: str, date_str: str,
                    diff_count: Optional[int] = None,
                    prev_version: Optional[str] = None) -> str:
    """CHANGELOG.txt — stub com contagem de alterações quando há release
    anterior com snapshot."""
    lines = [
        "CHANGELOG — W40K Translator (tradução de fã PT-BR)",
        "=" * 52,
        "",
        f"v{version} — {date_str}",
    ]
    if diff_count is not None and prev_version:
        lines.append(
            f"  · {diff_count:,} strings alteradas desde v{prev_version}"
            .replace(",", "."))
    else:
        lines.append("  · Primeira release registrada deste projeto.")
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Diff de strings
# ─────────────────────────────────────────────────────────────────────────────

def count_changed_strings(old_path: Path, new_path: Path) -> int:
    """Quantas strings têm Text diferente entre dois dumps (união de UUIDs;
    strings novas contam como alteradas)."""
    old = wp.load_localization(old_path)["strings"]
    new = wp.load_localization(new_path)["strings"]
    changed = 0
    for key in set(old) | set(new):
        old_text = (old.get(key) or {}).get("Text")
        new_text = (new.get(key) or {}).get("Text")
        if old_text != new_text:
            changed += 1
    return changed


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

def latest_release(project: wp.Project,
                   track: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Release mais recente registrada (opcionalmente de uma trilha)."""
    releases = project.state.get("releases") or []
    if track is not None:
        releases = [r for r in releases if r.get("track") == track]
    return releases[-1] if releases else None


def find_previous_snapshot(project: wp.Project, track: str,
                           exclude_version: Optional[str] = None
                           ) -> Optional[tuple[Path, str]]:
    """(caminho do _src.json, versão) da release anterior da mesma trilha,
    para o diff 'strings alteradas desde vX'. None se não houver."""
    releases = [r for r in (project.state.get("releases") or [])
                if r.get("track") == track]
    for rel in reversed(releases):
        version = rel.get("version") or ""
        if exclude_version and version == exclude_version:
            continue
        snap = project.root / "release" / src_snapshot_name(track, version)
        if snap.is_file():
            return snap, version
    return None


def diff_since_last_release(project: wp.Project,
                            track: str) -> Optional[tuple[int, str]]:
    """(n_alteradas, versão_anterior) comparando o output atual com o
    snapshot da última release da trilha. None se não houver base."""
    output = project.track_path(track)
    if output is None or not output.is_file():
        return None
    found = find_previous_snapshot(project, track)
    if found is None:
        return None
    snap, prev_version = found
    try:
        return count_changed_strings(snap, output), prev_version
    except wp.LocalizationFormatError:
        return None


def export_release(project: wp.Project, track: str,
                   version: str) -> Dict[str, Any]:
    """Monta o zip da release na pasta release/ e registra no project.json.

    Conteúdo do zip: enGB.json (output renomeado — o jogo exige esse nome),
    LEIA-ME_INSTALACAO.txt e CHANGELOG.txt. Ao lado do zip fica o snapshot
    traducao_<TRACK>_<versão>_src.json para o diff da próxima release.

    Levanta ProjectError (PT-BR) quando os pré-requisitos faltam.
    """
    version = validate_release_version(version)
    if track not in TRACK_ZIP_LABELS:
        raise wp.ProjectError(f"Trilha desconhecida: {track}")

    output = project.track_path(track)
    if output is None or not output.is_file():
        raise wp.ProjectError(
            f"Não existe tradução da trilha {TRACK_NAMES_PT[track]} em "
            "output/. Conclua a tradução/fullize primeiro.")

    # Gate: full só faz sentido depois da Preservada.
    if track == wp.TRACK_FULL and \
            project.track_path(wp.TRACK_PRESERVED) is None:
        raise wp.ProjectError(
            "A trilha Completa deriva da Preservada — rode o fullize "
            "primeiro (ele é grátis).")

    release_dir = project.root / "release"
    try:
        release_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise wp.ProjectError(f"Não foi possível criar release/: {exc}")

    today = date.today().isoformat()

    # Diff contra a release anterior (se houver snapshot).
    diff = diff_since_last_release(project, track)
    diff_count, prev_version = diff if diff else (None, None)

    zip_path = release_dir / release_zip_name(track, version)
    readme = build_readme(track, version, today)
    changelog = build_changelog(version, today, diff_count, prev_version)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(output, "enGB.json")
            zf.writestr("LEIA-ME_INSTALACAO.txt", readme)
            zf.writestr("CHANGELOG.txt", changelog)
        # Snapshot para o diff da próxima release.
        snapshot = release_dir / src_snapshot_name(track, version)
        snapshot.write_bytes(output.read_bytes())
    except OSError as exc:
        raise wp.ProjectError(f"Falha ao montar o pacote: {exc}")

    project.record_release(version=version, track=track,
                           file=f"release/{zip_path.name}")
    return {
        "zip": zip_path,
        "zip_name": zip_path.name,
        "version": version,
        "track": track,
        "diff_count": diff_count,
        "prev_version": prev_version,
    }
