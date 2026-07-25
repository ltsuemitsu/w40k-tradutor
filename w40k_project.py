"""W40K Translator — camada de projeto (sem Qt).

Este módulo contém TODA a lógica de projeto da nova GUI (Fase 1 do
GUI_REDESIGN.md) e é propositalmente livre de PySide6 para que os testes
rodem com `python -m unittest discover -s tests` em qualquer ambiente.

Responsabilidades:
  - Scaffold de pastas do projeto (§2 do GUI_REDESIGN.md)
  - Leitura/gravação/validação de `project.json`
  - Helpers de sha256 e contagem de strings em JSONs de localização
  - Heurísticas de classificação para "Adotar Tradução Existente" (§3)
  - Cópia (nunca movimentação) de arquivos adotados + backfill do estado
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

APP_VERSION = "2.0"
PROJECT_FILE = "project.json"
GAME_PROFILE = "rogue_trader"
SUBDIRS = ("input", "output", "patches", "audit", "release", "backups")

INPUT_EN_NAME = "enGB.json"
OUTPUT_PRESERVED_NAME = "ptBR_preserved.json"
OUTPUT_FULL_NAME = "ptBR_full.json"

# Papéis detectáveis na adoção (§3). Os rótulos PT-BR ficam na GUI.
ROLE_EN_INPUT = "en_input"
ROLE_PRESERVED = "preserved"
ROLE_FULL = "full"
ROLE_IGNORE = "ignore"
ROLES = (ROLE_EN_INPUT, ROLE_PRESERVED, ROLE_FULL, ROLE_IGNORE)

TRACK_PRESERVED = "preserved"
TRACK_FULL = "full"
TRACK_STATUS_PENDING = "pending"
TRACK_STATUS_DONE = "done"


class ProjectError(Exception):
    """Erro de alto nível da camada de projeto (mensagens amigáveis na GUI)."""


class ProjectValidationError(ProjectError):
    """project.json ausente, inválido ou fora do esquema esperado."""


class LocalizationFormatError(ProjectError):
    """Arquivo não segue o esquema de localização {strings: {uuid: {Text}}}."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de arquivo de localização
# ─────────────────────────────────────────────────────────────────────────────

def sha256_of_file(path: Path | str) -> str:
    """SHA-256 hex do arquivo, lido em blocos (seguro para JSONs grandes)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_localization(path: Path | str) -> Dict[str, Any]:
    """Carrega e valida um JSON de localização.

    Retorna o dict completo. Levanta LocalizationFormatError com mensagem
    em PT-BR quando o arquivo não é JSON válido ou não segue o esquema
    {"strings": {"<uuid>": {"Text": str, ...}}}.
    """
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise LocalizationFormatError(f"Arquivo não encontrado: {path.name}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LocalizationFormatError(
            f"JSON inválido em {path.name}: {exc}"
        )
    _validate_schema(data, path.name)
    return data


def _validate_schema(data: Any, name: str = "arquivo") -> None:
    if not isinstance(data, dict) or not isinstance(data.get("strings"), dict):
        raise LocalizationFormatError(
            f"{name}: esquema de localização não reconhecido "
            "(esperado objeto com chave 'strings')."
        )
    # Amostra: basta um punhado de entradas bem-formadas para confiar.
    sample = list(data["strings"].values())[:25]
    if not sample:
        return  # strings vazio ainda é um dump válido (ex.: delta zerado)
    ok = sum(
        1 for entry in sample
        if isinstance(entry, dict) and isinstance(entry.get("Text"), str)
    )
    if ok < max(1, len(sample) // 2):
        raise LocalizationFormatError(
            f"{name}: entradas sem campo 'Text' — não parece um dump de "
            "localização do jogo."
        )


def is_localization_json(path: Path | str) -> bool:
    """True se o arquivo segue o esquema de localização."""
    try:
        load_localization(path)
        return True
    except LocalizationFormatError:
        return False


def count_strings(path: Path | str) -> int:
    """Número de strings de um JSON de localização validado."""
    return len(load_localization(path)["strings"])


# ─────────────────────────────────────────────────────────────────────────────
# Heurísticas de classificação (adoção — §3)
# ─────────────────────────────────────────────────────────────────────────────

_PT_STOPWORDS = (
    " de ", " que ", " não ", " você ", " para ", " com ", " uma ", " um ",
    " seu ", " sua ", " são ", " está ", " pode ", " isso ", " esta ",
    " este ", " foi ", " por ", " dos ", " das ", " mais ", " como ",
)
_EN_STOPWORDS = (
    " the ", " and ", " you ", " of ", " to ", " with ", " your ", " is ",
    " are ", " for ", " that ", " this ", " have ", " not ", " will ",
)
_PT_ACCENTS_RE = re.compile(r"[ãõçáéíóúâêôàü]", re.IGNORECASE)

# Versão de jogo embutida em nomes de arquivo (ex.: enGB_1.6.1.514.json).
# 3 ou 4 grupos numéricos separados por ponto; 2 grupos (1.6) não bastam.
_GAME_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\.\d+)?)")
# Validação frouxa para edição manual da versão (só dígitos e pontos).
_GAME_VERSION_EDIT_RE = re.compile(r"^\d+(\.\d+)*$")


def extract_game_version(filename: str) -> str:
    """Extrai a versão do jogo de um nome de arquivo.

    Reconhece convenções como enGB_1.6.1.514.json, ptBR_full_1.3.2.json e
    traducao_FULL_1.6.1.514.zip. Retorna "" quando não há versão (3–4
    grupos numéricos são exigidos; '1.6' sozinho não é versão de build).
    """
    match = _GAME_VERSION_RE.search(Path(filename).name)
    return match.group(1) if match else ""

LANG_EN = "en"
LANG_PT = "pt"
LANG_UNKNOWN = "unknown"


def _sample_texts(data: Dict[str, Any], limit: int = 200) -> List[str]:
    texts: List[str] = []
    for entry in data.get("strings", {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("Text"), str):
            text = entry["Text"].strip()
            if text:
                texts.append(text)
        if len(texts) >= limit:
            break
    return texts


def guess_language(path: Path | str, sample: int = 200) -> str:
    """Adivinha EN vs PT-BR a partir de stopwords e acentos.

    Retorna "en", "pt" ou "unknown". Arquivos inválidos retornam "unknown".
    """
    try:
        data = load_localization(path)
    except LocalizationFormatError:
        return LANG_UNKNOWN
    texts = _sample_texts(data, sample)
    if not texts:
        return LANG_UNKNOWN

    pt_hits = 0
    en_hits = 0
    accented = 0
    for text in texts:
        low = f" {text.lower()} "
        pt_hits += sum(1 for w in _PT_STOPWORDS if w in low)
        en_hits += sum(1 for w in _EN_STOPWORDS if w in low)
        if _PT_ACCENTS_RE.search(text):
            accented += 1

    # Acentos PT em volume são o sinal mais forte de PT-BR.
    accent_ratio = accented / len(texts)
    if accent_ratio >= 0.08 and pt_hits >= en_hits:
        return LANG_PT
    if pt_hits >= 3 and pt_hits >= en_hits * 2:
        return LANG_PT
    if en_hits >= 3 and en_hits >= pt_hits * 2 and accent_ratio < 0.03:
        return LANG_EN
    if pt_hits == 0 and en_hits == 0:
        return LANG_UNKNOWN
    return LANG_PT if pt_hits > en_hits else LANG_EN


def _looks_like_mechanic_term(text: str) -> bool:
    """String curta, ASCII, sem acento — típica de termo de mecânica
    mantido em inglês na trilha Preservada (ex.: 'Plasma Gun')."""
    stripped = text.strip()
    if not (2 <= len(stripped) <= 40):
        return False
    if len(stripped.split()) > 4:
        return False
    if _PT_ACCENTS_RE.search(stripped):
        return False
    try:
        stripped.encode("ascii")
    except UnicodeEncodeError:
        return False
    # Precisa ter ao menos uma letra e parecer rótulo (não frase pontuada).
    if not any(c.isalpha() for c in stripped):
        return False
    return not stripped.endswith((".", "!", "?", "…"))


def _has_preserve_markers(data: Dict[str, Any]) -> bool:
    """Entradas marcadas como preservadas pelo engine (_preserved)."""
    for entry in list(data.get("strings", {}).values())[:500]:
        if isinstance(entry, dict) and entry.get("_preserved"):
            return True
    return False


def guess_track_hint(path: Path | str) -> str:
    """Para um arquivo PT-BR válido, sugere trilha 'preserved' ou 'full'.

    Sinais: preserve_map.json vizinho, marcadores _preserved nas entradas,
    ou fração relevante de termos de mecânica mantidos em inglês.
    """
    data = load_localization(path)
    path = Path(path)
    if (path.parent / "preserve_map.json").is_file():
        return ROLE_PRESERVED
    if _has_preserve_markers(data):
        return ROLE_PRESERVED
    texts = _sample_texts(data, 300)
    if not texts:
        return ROLE_FULL
    mechanic = sum(1 for t in texts if _looks_like_mechanic_term(t))
    if mechanic / len(texts) >= 0.06:
        return ROLE_PRESERVED
    return ROLE_FULL


def classify_file(path: Path | str) -> Dict[str, Any]:
    """Classifica um arquivo candidato à adoção.

    Retorna dict com: path, name, valid, error, strings, language, role.
    Nunca levanta exceção — erros viram mensagens PT-BR por arquivo.
    """
    path = Path(path)
    info: Dict[str, Any] = {
        "path": path,
        "name": path.name,
        "valid": False,
        "error": None,
        "strings": None,
        "language": LANG_UNKNOWN,
        "role": ROLE_IGNORE,
    }
    try:
        data = load_localization(path)
    except LocalizationFormatError as exc:
        info["error"] = str(exc)
        return info

    info["valid"] = True
    info["strings"] = len(data["strings"])
    info["language"] = guess_language(path)

    if info["language"] == LANG_EN:
        info["role"] = ROLE_EN_INPUT
    elif info["language"] == LANG_PT:
        info["role"] = guess_track_hint(path)
    else:
        info["role"] = ROLE_IGNORE
        info["error"] = (
            "Idioma não identificado — confirme manualmente ou ignore."
        )
    return info


def scan_candidates(paths: Iterable[Path | str]) -> List[Dict[str, Any]]:
    """Varre arquivos/pastas e classifica cada .json candidato.

    Pastas são varridas apenas no nível imediato (sem recursão) para manter
    a adoção previsível. Arquivos duplicados são reportados uma única vez.
    """
    files: List[Path] = []
    seen = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            candidates = sorted(p.glob("*.json"))
        else:
            candidates = [p]
        for c in candidates:
            if c.suffix.lower() != ".json":
                continue
            key = str(c.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(c)
    return [classify_file(f) for f in files]


# ─────────────────────────────────────────────────────────────────────────────
# Estado do projeto
# ─────────────────────────────────────────────────────────────────────────────

def default_state(glossary_path: Optional[str] = None,
                  glossary_terms: int = 0) -> Dict[str, Any]:
    """Estado inicial de project.json conforme §2 do GUI_REDESIGN.md."""
    return {
        "app_version": APP_VERSION,
        "game_profile": GAME_PROFILE,
        "game_version": None,
        "glossary": glossary_path or "glossary.json",
        "glossary_stamp": {"terms": glossary_terms, "built_for": GAME_PROFILE,
                           "name": None, "kind": None,
                           "mod_name": None, "parent": None},
        "input": {"file": None, "original_name": None,
                  "sha256": None, "strings": 0},
        "tracks": {
            TRACK_PRESERVED: {
                "status": TRACK_STATUS_PENDING,
                "updated": None,
                "translated": 0,
                "skipped_free": 0,
                "file": None,
            },
            TRACK_FULL: {
                "status": TRACK_STATUS_PENDING,
                "updated": None,
                "translated": 0,
                "skipped_free": 0,
                "file": None,
            },
        },
        "last_audit": None,
        "releases": [],
        "known_files": [],
    }


def count_glossary_terms(glossary_path: Path | str) -> int:
    """Número de termos de um glossary.json (formato {metadata, terms})."""
    try:
        with open(glossary_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProjectError(
            f"Não foi possível ler o glossário: {exc}"
        )
    terms = data.get("terms")
    if not isinstance(terms, list):
        raise ProjectError("Glossário sem lista 'terms' válida.")
    return len(terms)


# Tipos de glossário (§9.7): jogo base ou mod (com pai).
GLOSSARY_KIND_BASE = "base_game"
GLOSSARY_KIND_MOD = "mod"
GLOSSARY_KINDS = (GLOSSARY_KIND_BASE, GLOSSARY_KIND_MOD)


def read_glossary_metadata(glossary_path: Path | str) -> Dict[str, Any]:
    """Lê o bloco 'metadata' de um glossary.json ({} se ausente/ilegível).

    O engine lê apenas 'terms' — chaves extras de metadata são seguras.
    """
    try:
        with open(glossary_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    meta = data.get("metadata")
    return dict(meta) if isinstance(meta, dict) else {}


class Project:
    """Um projeto de tradução = uma pasta gerenciada pelo app (§2)."""

    def __init__(self, root: Path | str, state: Dict[str, Any]):
        self.root = Path(root)
        self.state = state

    # ── construção ──────────────────────────────────────────────────────

    @classmethod
    def create(cls, folder: Path | str,
               glossary_path: Optional[Path | str] = None) -> "Project":
        """Cria o scaffold do projeto na pasta-alvo.

        A pasta pode existir e não estar vazia; apenas não pode já conter
        um project.json (isso seria 'Abrir Projeto', não 'Novo Projeto').
        """
        folder = Path(folder)
        if (folder / PROJECT_FILE).is_file():
            raise ProjectError(
                "Esta pasta já contém um projeto (project.json). "
                "Use 'Abrir Projeto'."
            )
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for sub in SUBDIRS:
                (folder / sub).mkdir(exist_ok=True)
        except OSError as exc:
            raise ProjectError(f"Não foi possível criar as pastas: {exc}")

        glossary_rel = "glossary.json"
        terms = 0
        if glossary_path is not None:
            try:
                terms = count_glossary_terms(glossary_path)
            except ProjectError:
                terms = 0  # glossário ilegível não impede criar o projeto

        project = cls(folder, default_state(glossary_rel, terms))
        project.save()
        return project

    @classmethod
    def open(cls, folder: Path | str) -> "Project":
        """Abre projeto existente: valida project.json e repara subpastas."""
        folder = Path(folder)
        pfile = folder / PROJECT_FILE
        if not pfile.is_file():
            raise ProjectValidationError(
                "Nenhum project.json encontrado nesta pasta."
            )
        try:
            with open(pfile, "r", encoding="utf-8-sig") as fh:
                state = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise ProjectValidationError(f"project.json inválido: {exc}")
        if not isinstance(state, dict) or "tracks" not in state \
                or "input" not in state:
            raise ProjectValidationError(
                "project.json não segue o esquema esperado do app."
            )

        # Reparo silencioso de subpastas e campos novos ausentes.
        try:
            for sub in SUBDIRS:
                (folder / sub).mkdir(exist_ok=True)
        except OSError as exc:
            raise ProjectError(f"Não foi possível reparar as pastas: {exc}")

        merged = default_state(state.get("glossary"), 0)
        merged.update({k: v for k, v in state.items()
                       if k not in ("tracks", "input", "glossary_stamp")})
        if isinstance(state.get("input"), dict):
            merged["input"].update(state["input"])
        for track in (TRACK_PRESERVED, TRACK_FULL):
            if isinstance(state.get("tracks", {}).get(track), dict):
                merged["tracks"][track].update(state["tracks"][track])
        if isinstance(state.get("glossary_stamp"), dict):
            merged["glossary_stamp"].update(state["glossary_stamp"])

        project = cls(folder, merged)
        project.save()  # persiste reparo/migração de campos
        return project

    # ── persistência ────────────────────────────────────────────────────

    @property
    def file(self) -> Path:
        return self.root / PROJECT_FILE

    def save(self) -> None:
        try:
            with open(self.file, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        except OSError as exc:
            raise ProjectError(f"Não foi possível salvar project.json: {exc}")

    # ── atualizações de estado ──────────────────────────────────────────

    def _is_inside_project(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
            return True
        except ValueError:
            return False

    def set_input(self, source: Path | str) -> Path:
        """Registra o dump EN de entrada NO LUGAR, com o nome que tem
        (§2 convenção de nomes versionados — nunca renomeia).

        Se o arquivo está fora do projeto, é copiado para
        `input/<nome original>` (o nome é sempre preservado). Detecta a
        versão do jogo pelo nome (convenção enGB_<versão>.json).
        """
        source = Path(source)
        if not source.is_file():
            raise ProjectError(f"Arquivo não encontrado: {source.name}")
        if self._is_inside_project(source):
            dest = source  # já está no lugar: registra sem copiar
        else:
            dest = self.root / "input" / source.name
            self._copy_into(source, dest)
        strings = count_strings(dest)
        # Substituição: o sha do input anterior vira "conhecido" — dumps
        # antigos arquivados em input/ nunca re-disparam a reconciliação.
        self._remember_known_file(self.state.get("input", {}))
        self.state["input"] = {
            "file": str(dest.relative_to(self.root)).replace("\\", "/"),
            "original_name": source.name,
            "sha256": sha256_of_file(dest),
            "strings": strings,
        }
        self._detect_game_version(source.name)
        self.save()
        return dest

    def _remember_known_file(self, entry: Dict[str, Any]) -> None:
        """Anota o sha de um arquivo substituído (input/trilha anterior)
        em known_files — artefatos antigos não são novidade (§9.6)."""
        digest = entry.get("sha256")
        if not digest:
            path = entry.get("file")
            if path and (self.root / path).is_file():
                try:
                    digest = sha256_of_file(self.root / path)
                except OSError:
                    digest = None
        if digest:
            known = self.state.setdefault("known_files", [])
            if digest not in known:
                known.append(digest)

    def set_game_version(self, version: str) -> None:
        """Define a versão do jogo manualmente (validação frouxa).

        Aceita apenas dígitos e pontos (ex.: 1.6.1.514). String vazia
        limpa a versão (volta a 'desconhecida').
        """
        version = (version or "").strip()
        if version and not _GAME_VERSION_EDIT_RE.match(version):
            raise ProjectError(
                "Versão inválida — use apenas números e pontos "
                "(ex.: 1.6.1.514)."
            )
        self.state["game_version"] = version or None
        self.save()

    def _detect_game_version(self, *candidate_names: str) -> None:
        """Preenche game_version a partir de nomes de arquivo, sem
        sobrescrever um valor já conhecido."""
        if self.state.get("game_version"):
            return
        for name in candidate_names:
            version = extract_game_version(name)
            if version:
                self.state["game_version"] = version
                return

    def update_track(self, track: str, status: str,
                     translated: Optional[int] = None,
                     skipped_free: Optional[int] = None) -> None:
        if track not in self.state["tracks"]:
            raise ProjectError(f"Trilha desconhecida: {track}")
        entry = self.state["tracks"][track]
        entry["status"] = status
        entry["updated"] = date.today().isoformat()
        if translated is not None:
            entry["translated"] = translated
        if skipped_free is not None:
            entry["skipped_free"] = skipped_free
        self.save()

    def record_release(self, version: str, track: str, file: str) -> None:
        """Registra uma release exportada ({version, date, track, file})."""
        releases = self.state.setdefault("releases", [])
        releases.append({
            "version": version,
            "date": date.today().isoformat(),
            "track": track,
            "file": file,
        })
        self.save()

    # ── consultas ───────────────────────────────────────────────────────

    def input_path(self) -> Optional[Path]:
        rel = self.state.get("input", {}).get("file")
        return (self.root / rel) if rel else None

    def has_input(self) -> bool:
        p = self.input_path()
        return bool(p and p.is_file())

    def output_path(self, track: str) -> Path:
        """Caminho CANÔNICO legado (ptBR_<track>.json) — usado só como
        fallback de migração e varredura. Fluxos devem usar track_path()
        / track_target()."""
        name = (OUTPUT_PRESERVED_NAME if track == TRACK_PRESERVED
                else OUTPUT_FULL_NAME)
        return self.root / "output" / name

    def track_path(self, track: str) -> Optional[Path]:
        """Caminho absoluto do master da trilha conforme project.json
        (tracks.<track>.file). Fallback de migração: o nome canônico
        legado, se existir em disco. None quando não há master."""
        rel = self.state.get("tracks", {}).get(track, {}).get("file")
        if rel:
            return self.root / rel
        legacy = self.output_path(track)
        return legacy if legacy.is_file() else None

    def track_target(self, track: str) -> Path:
        """Onde a trilha deve ser ESCRITA: o caminho registrado (ou o
        legado existente); para uma trilha nova, o nome versionado pela
        game_version (ptBR_<track>_<versão>.json; plano se sem versão)."""
        current = self.track_path(track)
        if current is not None:
            return current
        base = (OUTPUT_PRESERVED_NAME if track == TRACK_PRESERVED
                else OUTPUT_FULL_NAME)
        version = self.state.get("game_version")
        if version:
            base = base.replace(".json", f"_{version}.json")
        return self.root / "output" / base

    def set_track_file(self, track: str, path: Path | str) -> None:
        """Registra em tracks.<track>.file o caminho (relativo) do master."""
        if track not in self.state["tracks"]:
            raise ProjectError(f"Trilha desconhecida: {track}")
        path = Path(path)
        try:
            rel = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            raise ProjectError(
                f"O master da trilha precisa estar dentro do projeto: "
                f"{path.name}")
        self.state["tracks"][track]["file"] = str(rel).replace("\\", "/")
        self.save()

    def has_any_output(self) -> bool:
        return any(self.track_path(t) is not None
                   for t in (TRACK_PRESERVED, TRACK_FULL))

    def rename_files_to_version(self, version: str,
                                include_input: bool = False
                                ) -> List[tuple[str, str]]:
        """Renomeia os masters (e opcionalmente o input) para o nome
        versionado — ÚNICO caso em que o app renomeia arquivos (§2:
        bump explícito de versão). Retorna [(nome_antigo, nome_novo)].

        Arquivos ausentes são pulados silenciosamente; renomear para o
        nome atual é no-op. Alvos existentes são substituídos (o master
        novo acabou de sair do merge).
        """
        if not version or not _GAME_VERSION_EDIT_RE.match(version):
            raise ProjectError(
                "Versão inválida — use apenas números e pontos "
                "(ex.: 1.6.1.514).")
        plan: List[tuple[Path, str]] = []
        for track, stem in ((TRACK_PRESERVED, "ptBR_preserved"),
                            (TRACK_FULL, "ptBR_full")):
            current = self.track_path(track)
            if current is not None and current.is_file():
                plan.append((current, f"{stem}_{version}.json"))
        if include_input:
            current_in = self.input_path()
            if current_in is not None and current_in.is_file():
                plan.append((current_in, f"enGB_{version}.json"))

        renamed: List[tuple[str, str]] = []
        for src, new_name in plan:
            if src.name == new_name:
                continue
            dest = src.with_name(new_name)
            try:
                os.replace(src, dest)
            except OSError as exc:
                raise ProjectError(
                    f"Não foi possível renomear {src.name}: {exc}")
            rel = str(dest.relative_to(self.root)).replace("\\", "/")
            if src.parent.name == "output":
                track = (TRACK_PRESERVED if "preserved" in src.name
                         else TRACK_FULL)
                self.state["tracks"][track]["file"] = rel
            else:
                self.state["input"]["file"] = rel
            renamed.append((src.name, new_name))
        if renamed:
            self.save()
        return renamed

    def track_status(self, track: str) -> Dict[str, Any]:
        return self.state.get("tracks", {}).get(track, {})

    def track_progress(self, track: str) -> Optional[float]:
        """Fração 0..1 de strings cobertas pela trilha (None sem input)."""
        entry = self.track_status(track)
        total = self.state.get("input", {}).get("strings") or 0
        if not total:
            return None
        if entry.get("status") != TRACK_STATUS_DONE:
            return 0.0
        covered = (entry.get("translated") or 0) + (entry.get("skipped_free") or 0)
        if covered <= 0:
            return 1.0  # adoção sem contagem detalhada: considera completo
        return min(1.0, covered / total)

    # ── adoção (§3) ─────────────────────────────────────────────────────

    @staticmethod
    def _copy_into(source: Path | str, dest: Path) -> None:
        """Copia (NUNCA move) um arquivo para dentro do projeto."""
        source = Path(source)
        dest = Path(dest)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() == dest.resolve():
                return  # já está no lugar certo
            shutil.copy2(source, dest)
        except OSError as exc:
            raise ProjectError(
                f"Falha ao copiar {source.name}: {exc}"
            )

    def adopt_files(self, roles: Dict[str, Path | str]) -> Dict[str, Any]:
        """Registra arquivos adotados e faz backfill do estado.

        Convenção §2: o arquivo fica ONDE ESTÁ e com o NOME QUE TEM —
        arquivos já dentro do projeto são registrados no lugar; arquivos
        de fora são copiados para input//output/ preservando o nome
        original (nunca renomeados para nomes canônicos).

        `roles` mapeia papel → caminho de origem, usando ROLE_EN_INPUT,
        ROLE_PRESERVED e ROLE_FULL. Retorna resumo {"imported": [...],
        "errors": [...]}. Erros de um arquivo não impedem os demais.
        """
        imported: List[Dict[str, Any]] = []
        errors: List[str] = []

        plan = (
            (ROLE_EN_INPUT, "input"),
            (ROLE_PRESERVED, "output"),
            (ROLE_FULL, "output"),
        )
        for role, subdir in plan:
            source = roles.get(role)
            if not source:
                continue
            source = Path(source)
            if self._is_inside_project(source):
                dest = source  # no lugar: registra sem copiar/renomear
            else:
                dest = self.root / subdir / source.name
            try:
                self._copy_into(source, dest)
                strings = count_strings(dest)
                digest = sha256_of_file(dest)
                rel_dest = str(dest.relative_to(self.root)).replace("\\", "/")
            except (ProjectError, LocalizationFormatError, ValueError) as exc:
                errors.append(f"{source.name}: {exc}")
                continue

            today = date.today().isoformat()
            if role == ROLE_EN_INPUT:
                self._remember_known_file(self.state.get("input", {}))
                self.state["input"] = {
                    "file": rel_dest,
                    "original_name": source.name,
                    "sha256": digest,
                    "strings": strings,
                }
            else:
                track = (TRACK_PRESERVED if role == ROLE_PRESERVED
                         else TRACK_FULL)
                prev = self.track_path(track)
                if prev is not None and prev.is_file() \
                        and prev.resolve() != dest.resolve():
                    self._remember_known_file(
                        {"file": str(prev.relative_to(self.root))
                         .replace("\\", "/")})
                self.state["tracks"][track] = {
                    "status": TRACK_STATUS_DONE,
                    "updated": today,
                    "translated": strings,
                    "skipped_free": 0,
                    "file": rel_dest,
                }
            imported.append({
                "role": role,
                "source": source.name,
                "dest": rel_dest,
                "strings": strings,
            })

        if imported:
            # Detecta a versão do jogo a partir dos nomes originais
            # (enGB_1.6.1.514.json, ptBR_full_1.6.1.514.json, ...).
            self._detect_game_version(*(
                str(roles[role])
                for role in (ROLE_EN_INPUT, ROLE_PRESERVED, ROLE_FULL)
                if roles.get(role)
            ))
            self.save()
        return {"imported": imported, "errors": errors}

    # ── reconciliação de estado (§9.6) ──────────────────────────────────

    def _is_tracked(self, role: str, path: Path) -> bool:
        """True se project.json já conhece ESTE conteúdo (sha + status).

        Compara contra o caminho REGISTRADO (input.file / tracks.file) —
        como o registro é no lugar, o sha bate e o arquivo nunca volta a
        ser oferecido (causa raiz do re-prompt: antes comparava com a
        CÓPIA canônica e o original solto parecia novo).
        """
        digest = sha256_of_file(path)
        if digest in self.state.get("known_files", []):
            return True  # artefato antigo já substituído — nunca re-oferece
        if role == ROLE_EN_INPUT:
            ref = self.input_path()
            return bool(self.state["input"].get("file")) \
                and ref is not None and ref.is_file() \
                and self.state["input"].get("sha256") == digest
        track = TRACK_PRESERVED if role == ROLE_PRESERVED else TRACK_FULL
        entry = self.track_status(track)
        out = self.track_path(track)
        return entry.get("status") == TRACK_STATUS_DONE \
            and out is not None and out.is_file() \
            and sha256_of_file(out) == digest

    def reconcile(self) -> Dict[str, Any]:
        """Varre input/ e output/ atrás de arquivos de localização que o
        project.json ainda não conhece — canonical (enGB.json,
        ptBR_full.json) ou versionados (enGB_1.6.1.514.json,
        ptBR_preserved_1.6.1.514.json).

        Retorna {"untracked": [classify_file(...)+sha256]}. Nada é
        modificado aqui — o registro acontece via adopt_files().
        """
        untracked: List[Dict[str, Any]] = []
        for folder in (self.root / "input", self.root / "output"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json")):
                if path.name == "preserve_map.json":
                    continue  # artefato do engine, não é localização
                try:
                    info = classify_file(path)
                except Exception:
                    continue  # arquivo ilegível nunca derruba a varredura
                if not info["valid"] or info["role"] == ROLE_IGNORE:
                    continue
                if self._is_tracked(info["role"], path):
                    continue
                info["sha256"] = sha256_of_file(path)
                untracked.append(info)
        return {"untracked": untracked}

    def cleanup_stale(self) -> List[str]:
        """project.json diz 'done' mas o arquivo sumiu do disco → volta
        para pendente (limpeza silenciosa; retorna linhas de log PT-BR)."""
        cleaned: List[str] = []
        changed = False
        for track in (TRACK_PRESERVED, TRACK_FULL):
            entry = self.state["tracks"].get(track, {})
            tp = self.track_path(track)
            if entry.get("status") == TRACK_STATUS_DONE \
                    and (tp is None or not tp.is_file()):
                entry.update({"status": TRACK_STATUS_PENDING,
                              "updated": None,
                              "translated": 0, "skipped_free": 0})
                cleaned.append(
                    f"trilha {track}: output sumiu do disco — "
                    "marcada como pendente")
                changed = True
        info = self.state.get("input", {})
        if info.get("file") and not (self.root / info["file"]).is_file():
            self.state["input"] = {"file": None, "original_name": None,
                                   "sha256": None, "strings": 0}
            cleaned.append("input: enGB.json sumiu do disco — "
                           "marcado como pendente")
            changed = True
        if changed:
            self.save()
        return cleaned

    # ── glossário do projeto (§9.7) ─────────────────────────────────────

    def glossary_path(self) -> Path:
        """Caminho do glossário do projeto (project.json 'glossary')."""
        rel = self.state.get("glossary") or "glossary.json"
        return self.root / rel

    def _apply_glossary(self, data: Dict[str, Any], stamp: Dict[str, Any]
                        ) -> Dict[str, Any]:
        """Grava <projeto>/glossary.json e atualiza glossary_stamp."""
        dest = self.glossary_path()
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        except OSError as exc:
            raise ProjectError(f"Não foi possível gravar o glossário: {exc}")
        self.state["glossary"] = "glossary.json"
        self.state["glossary_stamp"] = stamp
        self.save()
        return dict(stamp)

    def import_glossary(self, source: Path | str,
                        kind: str = GLOSSARY_KIND_BASE,
                        mod_name: Optional[str] = None) -> Dict[str, Any]:
        """Copia um glossary.json para dentro do projeto e carimba a
        metadata estendida (§9.7) — ADITIVA: campos existentes (version,
        updated_at, total_terms, ...) e todos os terms são preservados.

        kind 'mod' ganha mod_name e parent (do metadata da origem).
        """
        if kind not in GLOSSARY_KINDS:
            raise ProjectError(f"Tipo de glossário desconhecido: {kind}")
        source = Path(source)
        try:
            with open(source, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProjectError(f"Não foi possível ler o glossário: {exc}")
        terms = data.get("terms")
        if not isinstance(terms, list):
            raise ProjectError("Glossário sem lista 'terms' válida.")
        src_meta = data.get("metadata")
        src_meta = dict(src_meta) if isinstance(src_meta, dict) else {}

        if kind == GLOSSARY_KIND_MOD:
            name = (mod_name or src_meta.get("name") or source.stem)
            parent = src_meta.get("name") or src_meta.get("game") or None
            mod_value: Optional[str] = mod_name or name
        else:
            name = src_meta.get("name") or source.stem
            parent = src_meta.get("parent")
            mod_value = None
        game = src_meta.get("game") or GAME_PROFILE

        metadata = dict(src_meta)  # aditivo: preserva campos legados
        metadata.update({
            "updated_at": datetime.now().isoformat(),
            "total_terms": len(terms),
            "name": name,
            "game": game,
            "game_version": src_meta.get("game_version"),
            "kind": kind,
            "mod_name": mod_value,
            "parent": parent,
        })
        data["metadata"] = metadata
        stamp = {"terms": len(terms), "built_for": game,
                 "name": name, "kind": kind,
                 "mod_name": mod_value, "parent": parent}
        return self._apply_glossary(data, stamp)

    def create_empty_glossary(self, name: str = "Glossário do projeto"
                              ) -> Dict[str, Any]:
        """Cria um glossário vazio no projeto (opção avançada)."""
        data = {
            "metadata": {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "total_terms": 0,
                "name": name,
                "game": GAME_PROFILE,
                "game_version": None,
                "kind": GLOSSARY_KIND_BASE,
                "mod_name": None,
                "parent": None,
            },
            "terms": [],
        }
        stamp = {"terms": 0, "built_for": GAME_PROFILE,
                 "name": name, "kind": GLOSSARY_KIND_BASE,
                 "mod_name": None, "parent": None}
        return self._apply_glossary(data, stamp)
