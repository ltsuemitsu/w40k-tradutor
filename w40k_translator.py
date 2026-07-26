"""W40K Translator — nova GUI (Fase 1 do GUI_REDESIGN.md).

App PySide6 (a GUI legada foi removida na v2.0). UI em PT-BR, tema
grimdark (fundo #0a0a12, dourado #c9a84c), centrado em PROJETOS:

  - Tela de boas-vindas: Novo Projeto / Adotar Tradução Existente / Abrir.
  - Dashboard Home (§4.0): cards de INPUT, TRILHAS, AUDITORIA, GLOSSÁRIO
    e os 5 botões de jornada com lógica de habilitar/desabilitar.
  - Toda a lógica de projeto vive em `w40k_project.py` (sem Qt).

Fases futuras (P2+) substituem os placeholders "Em breve" das jornadas.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import (
    QProcess,
    QProcessEnvironment,
    QSettings,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import w40k_audit as au
import w40k_glossary as gl
import w40k_patch as pch
import w40k_preflight as pf
import w40k_project as wp
import w40k_release as rl
import w40k_settings as st

APP_NAME = "W40K Translator"
SETTINGS_ORG = "W40KTranslator"
SETTINGS_APP = "W40KTranslator"
SETTINGS_LAST_PROJECT = "lastProject"
REPO_ROOT = Path(__file__).resolve().parent

# ─────────────────────────────────────────────────────────────────────────────
# TEMA GRIMDARK 40K
# ─────────────────────────────────────────────────────────────────────────────

GRIMDARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0a0a12;
    color: #e8d9b0;
}
QWidget {
    background-color: #0a0a12;
    color: #e8d9b0;
    font-family: "Segoe UI", "Consolas", sans-serif;
    font-size: 10pt;
}
QGroupBox {
    border: 1px solid #3a2a1f;
    margin-top: 8px;
    padding-top: 12px;
    font-weight: bold;
    color: #c9a84c;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #1f1810;
    color: #c9a84c;
    border: 1px solid #5c4630;
    padding: 8px 16px;
    border-radius: 3px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #2a2118;
    border-color: #c9a84c;
}
QPushButton:pressed {
    background-color: #3a2a1f;
}
QPushButton:disabled {
    background-color: #12100c;
    color: #554a3a;
    border-color: #2a2118;
}
QPushButton#primary {
    background-color: #3a2a1f;
    color: #f0d9a0;
    border-color: #c9a84c;
    font-weight: bold;
}
QPushButton#journey {
    padding: 18px 10px;
    font-size: 11pt;
    font-weight: bold;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0f0e14;
    border: 1px solid #3a2a1f;
    color: #e8d9b0;
    padding: 4px;
    selection-background-color: #4a3a2a;
}
QComboBox {
    background-color: #0f0e14;
    border: 1px solid #3a2a1f;
    color: #e8d9b0;
    padding: 3px;
}
QComboBox QAbstractItemView {
    background-color: #14131a;
    color: #e8d9b0;
    selection-background-color: #3a2a1f;
}
QTableWidget {
    background-color: #0f0e14;
    border: 1px solid #3a2a1f;
    gridline-color: #2a2118;
    color: #e8d9b0;
    alternate-background-color: #14131a;
}
QTableWidget::item:selected {
    background-color: #3a2a1f;
    color: #f0d9a0;
}
QHeaderView::section {
    background-color: #1a1610;
    color: #c9a84c;
    border: 1px solid #3a2a1f;
    padding: 5px;
    font-weight: bold;
}
QLabel#title {
    color: #c9a84c;
    font-size: 16pt;
    font-weight: bold;
}
QLabel#subtitle {
    color: #8a7560;
    font-size: 9pt;
}
QLabel#cardTitle {
    color: #c9a84c;
    font-size: 10pt;
    font-weight: bold;
}
QLabel#cardBody {
    color: #e8d9b0;
}
QLabel#ok {
    color: #9ac98a;
}
QLabel#warn {
    color: #e8b45c;
}
QLabel#err {
    color: #ff9a8a;
}
QFrame#card {
    background-color: #111118;
    border: 1px solid #3a2a1f;
    border-radius: 4px;
}
QToolTip {
    background-color: #1a1610;
    color: #e8d9b0;
    border: 1px solid #c9a84c;
    padding: 4px;
}
"""

ROLE_LABELS = {
    wp.ROLE_EN_INPUT: "EN (entrada)",
    wp.ROLE_PRESERVED: "Preservada",
    wp.ROLE_FULL: "Completa (Full)",
    wp.ROLE_IGNORE: "Ignorar",
}
LABEL_TO_ROLE = {v: k for k, v in ROLE_LABELS.items()}

# Todas as 5 jornadas + ⚙ Configurações entregues (P1–P6) — sem placeholders.


def _fmt_audit_date(iso: str) -> str:
    """'2026-07-25T14:30:00' ou '2026-07-25' → '25/07'."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso)[:19]).strftime("%d/%m")
    except ValueError:
        return str(iso or "?")


def apply_grimdark(app: QApplication) -> None:
    app.setStyleSheet(GRIMDARK_STYLESHEET)
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#0a0a12"))
    palette.setColor(QPalette.WindowText, QColor("#e8d9b0"))
    palette.setColor(QPalette.Base, QColor("#0f0e14"))
    palette.setColor(QPalette.Text, QColor("#e8d9b0"))
    app.setPalette(palette)


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGOS AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

class _ConnectionTestThread(QThread):
    """Wrapper não-bloqueante de pf.test_connection (urllib, stdlib):
    GET /models com Authorization → fallback probe de chat completions."""

    result = Signal(bool, str)

    def __init__(self, base_url: str, api_key: str, model: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self):  # pragma: no cover - exercitado no smoke offscreen
        ok, msg = pf.test_connection(self.base_url, self.api_key,
                                     model=self.model)
        self.result.emit(ok, msg)


class _AddModelDialog(QDialog):
    """Formulário para adicionar um modelo (perfil completo do usuário)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar modelo")
        self.setMinimumWidth(480)
        self.model_id = ""
        self.profile: Dict = {}

        grid = QGridLayout(self)
        row = 0
        grid.addWidget(QLabel("ID do modelo:"), row, 0)
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("ex.: glm-4.7-coding")
        grid.addWidget(self.id_edit, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Provedor:"), row, 0)
        self.provider_combo = QComboBox()
        self.provider_combo.setEditable(True)
        for name in st.effective_providers():
            self.provider_combo.addItem(name)
        grid.addWidget(self.provider_combo, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Rótulo:"), row, 0)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("nome amigável exibido nos pickers")
        grid.addWidget(self.label_edit, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Base URL (opcional):"), row, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("vazio = usa a base URL do provedor")
        grid.addWidget(self.url_edit, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Workers:"), row, 0)
        self.workers_edit = QLineEdit("3")
        grid.addWidget(self.workers_edit, row, 1)
        grid.addWidget(QLabel("Salvar a cada N lotes:"), row, 2)
        row += 1
        self.save_every_edit = QLineEdit("5")
        grid.addWidget(QLabel("Lotes curto/médio/longo/xlongo:"), row, 0)
        self.batches_edit = QLineEdit("50/30/12/5")
        grid.addWidget(self.batches_edit, row, 1)
        grid.addWidget(self.save_every_edit, row, 2)
        row += 1

        grid.addWidget(QLabel("Máx. tokens/lote:"), row, 0)
        self.max_tokens_edit = QLineEdit("12500")
        grid.addWidget(self.max_tokens_edit, row, 1)
        grid.addWidget(QLabel("Papel:"), row, 2)
        row += 1
        self.role_combo = QComboBox()
        self.role_combo.addItems(["bulk", "quality"])
        grid.addWidget(self.role_combo, row, 2)
        row += 1

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, row, 0, 1, 3)

    def _accept(self):
        mid = self.id_edit.text().strip()
        if not mid:
            QMessageBox.warning(self, "Adicionar modelo",
                                "Informe o ID do modelo.")
            return
        if mid in st.effective_profiles():
            QMessageBox.warning(
                self, "Adicionar modelo",
                f"“{mid}” já existe — edite a linha na tabela.")
            return
        provider = self.provider_combo.currentText().strip()
        if not provider:
            QMessageBox.warning(self, "Adicionar modelo",
                                "Informe o provedor.")
            return
        try:
            workers = int(self.workers_edit.text())
            save_every = int(self.save_every_edit.text())
            max_tokens = int(self.max_tokens_edit.text())
            batches = _parse_batches(self.batches_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Adicionar modelo", str(exc))
            return
        profile = {
            "provider": provider,
            "label": self.label_edit.text().strip() or mid,
            "batches": batches,
            "workers": workers,
            "save_every": save_every,
            "max_tokens_batch": max_tokens,
            "role": self.role_combo.currentText(),
        }
        url = self.url_edit.text().strip()
        if url:
            profile["url"] = url
        self.model_id = mid
        self.profile = profile
        self.accept()


def _parse_batches(text: str) -> tuple:
    """'50/30/12/5' (ou vírgulas/espaços) → (50, 30, 12, 5)."""
    parts = [p for p in re.split(r"[/,; ]+", text.strip()) if p]
    if len(parts) != 4:
        raise ValueError(
            "Lotes devem ser 4 números (curto/médio/longo/xlongo), "
            "ex.: 50/30/12/5.")
    values = tuple(int(p) for p in parts)
    if any(v <= 0 for v in values):
        raise ValueError("Lotes devem ser números positivos.")
    return values


class SettingsDialog(QDialog):
    """⚙ Configurações (P6): Provedores / Modelos / Geral.

    Overrides persistem fora do repositório e dos projetos, em
    %APPDATA%/W40KTranslator (ver w40k_settings.py). Todas as edições
    são aplicadas na hora e lidas em tempo de execução pelos fluxos —
    não é preciso reiniciar o app.
    """

    # coluna → campo do perfil (colunas 0/1/9 são somente leitura)
    _MODEL_COL_FIELDS = {
        2: "label", 3: "url", 4: "workers", 5: "batches",
        6: "save_every", 7: "max_tokens_batch", 8: "role",
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Configurações")
        self.setMinimumSize(860, 600)
        self._test_threads: list = []
        self._loading = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Preferências salvas fora do projeto, em "
            f"<code>{st.config_dir()}</code> — nunca no repositório nem "
            "nos projetos. Valem para os próximos runs, sem reiniciar."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._providers_tab_widget(), "Provedores")
        self.tabs.addTab(self._models_tab_widget(), "Modelos")
        self.tabs.addTab(self._general_tab_widget(), "Geral")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Aba Provedores ────────────────────────────────────────────────

    def _providers_tab_widget(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(10)

        for name, code_url in st.code_providers().items():
            v.addWidget(self._provider_group(name, code_url, custom=None))
        for name, info in st.custom_providers().items():
            v.addWidget(self._provider_group(name, "", custom=info))

        add_box = QGroupBox("Adicionar provedor (OpenAI-compatível)")
        grid = QGridLayout(add_box)
        grid.addWidget(QLabel("Nome:"), 0, 0)
        self._new_prov_name = QLineEdit()
        self._new_prov_name.setPlaceholderText("ex.: Meu Proxy GLM")
        grid.addWidget(self._new_prov_name, 0, 1)
        grid.addWidget(QLabel("Base URL:"), 1, 0)
        self._new_prov_url = QLineEdit()
        self._new_prov_url.setPlaceholderText("https://…")
        grid.addWidget(self._new_prov_url, 1, 1)
        btn_add = QPushButton("Adicionar provedor")
        btn_add.clicked.connect(self._add_custom_provider)
        grid.addWidget(btn_add, 1, 2)
        v.addWidget(add_box)
        v.addStretch(1)

        scroll.setWidget(body)
        return scroll

    def _provider_group(self, name: str, code_url: str,
                        custom: Optional[Dict]) -> QGroupBox:
        group = QGroupBox(name)
        g = QGridLayout(group)

        g.addWidget(QLabel("Base URL:"), 0, 0)
        url_edit = QLineEdit(st.provider_base_url(name))
        if code_url:
            url_edit.setPlaceholderText(f"padrão: {code_url}")
        g.addWidget(url_edit, 0, 1)
        btn_save_url = QPushButton("Salvar URL")
        btn_save_url.clicked.connect(
            lambda _=False, n=name, e=url_edit, c=code_url:
            self._save_provider_url(n, e, c))
        g.addWidget(btn_save_url, 0, 2)

        row = 1
        if code_url:
            btn_reset = QPushButton("Restaurar padrão")
            btn_reset.setEnabled(name in st.provider_overrides())
            btn_reset.clicked.connect(
                lambda _=False, n=name, e=url_edit, c=code_url, b=btn_reset:
                self._reset_provider_url(n, e, c, b))
            g.addWidget(btn_reset, row, 1, 1, 2, Qt.AlignRight)
            row += 1

        g.addWidget(QLabel("Chave de API:"), row, 0)
        key_edit = QLineEdit()
        key_edit.setEchoMode(QLineEdit.Password)
        key_edit.setPlaceholderText("cole a chave para salvar no cofre")
        g.addWidget(key_edit, row, 1)
        key_row = QHBoxLayout()
        btn_save_key = QPushButton("Salvar no cofre")
        btn_clear_key = QPushButton("Limpar")
        key_row.addWidget(btn_save_key)
        key_row.addWidget(btn_clear_key)
        g.addLayout(key_row, row, 2)
        row += 1

        status = QLabel("")
        status.setObjectName("subtitle")
        g.addWidget(status, row, 1, 1, 2)
        row += 1
        btn_save_key.clicked.connect(
            lambda _=False, n=name, e=key_edit, s=status:
            self._save_provider_key(n, e, s))
        btn_clear_key.clicked.connect(
            lambda _=False, n=name, e=key_edit, s=status:
            self._clear_provider_key(n, e, s))

        btn_test = QPushButton("Testar conexão")
        g.addWidget(btn_test, row, 0)
        test_label = QLabel("")
        test_label.setObjectName("subtitle")
        test_label.setWordWrap(True)
        g.addWidget(test_label, row, 1, 1, 2)
        btn_test.clicked.connect(
            lambda _=False, n=name, e=url_edit, b=btn_test, l=test_label:
            self._test_connection(n, e, b, l))
        row += 1

        if custom is not None:
            btn_remove = QPushButton("Remover provedor")
            btn_remove.clicked.connect(
                lambda _=False, n=name: self._remove_custom_provider(n))
            g.addWidget(btn_remove, row, 1, 1, 2, Qt.AlignRight)
            row += 1

        self._refresh_key_status(name, status)
        return group

    def _refresh_key_status(self, provider: str, label: QLabel):
        _key, source = pf.resolve_api_key(provider)
        text = f"Chave atual: {source}." if source else \
            "Chave atual: nenhuma encontrada."
        if not pf.keyring_available():
            text += " (cofre do Windows indisponível neste ambiente)"
        label.setText(text)

    def _save_provider_url(self, name: str, edit: QLineEdit, code_url: str):
        url = edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Configurações",
                                "A base URL não pode ficar vazia.")
            return
        try:
            if name in st.custom_providers():
                kind = st.custom_providers()[name].get("kind", "openai")
                st.add_custom_provider(name, url, kind)
            elif url == code_url:
                st.set_provider_base_url(name, "")  # limpa override
            else:
                st.set_provider_base_url(name, url)
        except ValueError as exc:
            QMessageBox.warning(self, "Configurações", str(exc))
            return
        self._rebuild_providers_tab()

    def _reset_provider_url(self, name: str, edit: QLineEdit,
                            code_url: str, btn: QPushButton):
        st.set_provider_base_url(name, "")
        edit.setText(code_url)
        btn.setEnabled(False)

    def _save_provider_key(self, name: str, edit: QLineEdit,
                           status: QLabel):
        value = edit.text().strip()
        if not value:
            QMessageBox.warning(self, "Configurações",
                                "Cole a chave no campo antes de salvar.")
            return
        ok, detail = pf.key_store_set_ex(name, value)
        if ok:
            edit.clear()
            status.setText("✔ Chave salva no cofre do Windows.")
        else:
            # Falha VISÍVEL — antes a gravação falhava em silêncio e o
            # usuário só descobria quando a próxima jornada pedia a chave.
            status.setText(f"⚠ {detail}")
            QMessageBox.warning(
                self, "Cofre do Windows indisponível",
                f"A chave NÃO foi salva: {detail}.\n\n"
                "Sem o cofre, cada jornada vai pedir a chave de novo.")

    def _clear_provider_key(self, name: str, edit: QLineEdit,
                            status: QLabel):
        edit.clear()
        if pf.key_store_delete(name):
            status.setText("Chave removida do cofre do Windows.")
        else:
            status.setText("Nenhuma chave deste provedor no cofre.")
        self._refresh_key_status(name, status)

    def _test_connection(self, name: str, url_edit: QLineEdit,
                         btn: QPushButton, label: QLabel):
        url = url_edit.text().strip()
        if not url:
            label.setText("✖ Informe uma base URL primeiro.")
            return
        key, _source = pf.resolve_api_key(name)
        probe_model = st.probe_model_for_provider(name)
        btn.setEnabled(False)
        label.setText("Testando…")
        thread = _ConnectionTestThread(url, key, probe_model, self)
        self._test_threads.append(thread)

        def _done(ok: bool, msg: str, b=btn, l=label, t=thread):
            l.setText(msg)
            b.setEnabled(True)
            if t in self._test_threads:
                self._test_threads.remove(t)

        thread.result.connect(_done)
        thread.start()

    def _add_custom_provider(self):
        name = self._new_prov_name.text().strip()
        url = self._new_prov_url.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "Configurações",
                                "Informe nome e base URL do provedor.")
            return
        if name in st.effective_providers():
            QMessageBox.warning(self, "Configurações",
                                f"“{name}” já existe.")
            return
        st.add_custom_provider(name, url)
        self._rebuild_providers_tab()

    def _remove_custom_provider(self, name: str):
        st.remove_custom_provider(name)
        self._rebuild_providers_tab()

    def _rebuild_providers_tab(self):
        self.tabs.removeTab(0)
        self.tabs.insertTab(0, self._providers_tab_widget(), "Provedores")
        self.tabs.setCurrentIndex(0)

    # ── Aba Modelos ───────────────────────────────────────────────────

    def _models_tab_widget(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        hint = QLabel(
            "Edite as células diretamente. Linhas de <b>código</b> aceitam "
            "overrides campo a campo (e “Restaurar padrão”); linhas de "
            "<b>usuário</b> podem ser editadas livremente ou removidas."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.models_table = QTableWidget()
        self.models_table.setColumnCount(10)
        self.models_table.setHorizontalHeaderLabels([
            "Modelo", "Provedor", "Rótulo", "Base URL", "Workers",
            "Lotes c/m/l/xl", "Salvar a cada", "Máx. tok/lote",
            "Papel", "Origem",
        ])
        self.models_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.models_table.itemChanged.connect(self._on_model_cell_changed)
        v.addWidget(self.models_table, 1)
        self._reload_models_table()

        row = QHBoxLayout()
        btn_add = QPushButton("Adicionar modelo…")
        btn_add.clicked.connect(self._add_model)
        row.addWidget(btn_add)
        btn_remove = QPushButton("Remover (usuário)")
        btn_remove.clicked.connect(self._remove_selected_model)
        row.addWidget(btn_remove)
        btn_reset = QPushButton("Restaurar padrão (código)")
        btn_reset.clicked.connect(self._reset_selected_model)
        row.addWidget(btn_reset)
        row.addStretch(1)
        v.addLayout(row)
        return tab

    def _reload_models_table(self):
        self._loading = True
        try:
            profiles = st.effective_profiles()
            overrides = st.user_profile_overrides()
            added = st.user_added_profiles()
            self.models_table.setRowCount(len(profiles))
            ro = Qt.ItemIsEditable
            for r, (mid, prof) in enumerate(profiles.items()):
                if mid in added:
                    origem = "usuário"
                elif mid in overrides:
                    origem = "modificado"
                else:
                    origem = "código"
                batches = prof.get("batches") or (50, 30, 12, 5)
                values = [
                    mid,
                    str(prof.get("provider") or ""),
                    str(prof.get("label") or mid),
                    str(prof.get("url") or ""),
                    str(prof.get("workers") or 3),
                    "/".join(str(x) for x in batches),
                    str(prof.get("save_every") or 5),
                    str(prof.get("max_tokens_batch") or 12500),
                    str(prof.get("role") or "bulk"),
                    origem,
                ]
                for c, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    if c in (0, 1, 9):
                        item.setFlags(item.flags() & ~ro)
                    self.models_table.setItem(r, c, item)
        finally:
            self._loading = False

    def _on_model_cell_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        col = item.column()
        field = self._MODEL_COL_FIELDS.get(col)
        if field is None:
            return
        mid_item = self.models_table.item(item.row(), 0)
        if mid_item is None:
            return
        mid = mid_item.text()
        text = item.text().strip()
        try:
            if field in ("workers", "save_every", "max_tokens_batch"):
                value = int(text)
                if value <= 0:
                    raise ValueError("deve ser um número positivo")
            elif field == "batches":
                value = _parse_batches(text)
            else:
                value = text
        except ValueError:
            QMessageBox.warning(
                self, "Configurações",
                f"Valor inválido para “{field}”: “{text}”.")
            self._reload_models_table()
            return

        if st.is_user_profile(mid):
            current = dict(st.user_added_profiles().get(mid) or {})
            if not current:
                current = dict(st.effective_profiles().get(mid) or {})
            if field == "url" and not value:
                current.pop("url", None)
            else:
                current[field] = value
            try:
                st.add_user_profile(mid, current)
            except ValueError as exc:
                QMessageBox.warning(self, "Configurações", str(exc))
        else:
            if field == "url" and not value:
                # limpar url digitada não remove override algum; ignora
                self._reload_models_table()
                return
            st.set_profile_override(mid, {field: value})
        self._reload_models_table()

    def _selected_model_id(self) -> str:
        row = self.models_table.currentRow()
        if row < 0:
            return ""
        item = self.models_table.item(row, 0)
        return item.text() if item else ""

    def _add_model(self):
        dlg = _AddModelDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.model_id:
            try:
                st.add_user_profile(dlg.model_id, dlg.profile)
            except ValueError as exc:
                QMessageBox.warning(self, "Configurações", str(exc))
                return
            self._reload_models_table()

    def _remove_selected_model(self):
        mid = self._selected_model_id()
        if not mid:
            return
        if not st.is_user_profile(mid):
            QMessageBox.information(
                self, "Configurações",
                f"“{mid}” é uma linha de código — use “Restaurar padrão” "
                "para desfazer overrides, não dá para removê-la.")
            return
        st.remove_user_profile(mid)
        if st.default_model() == mid:
            st.set_default_model("")
        self._reload_models_table()
        self._reload_general_tab()

    def _reset_selected_model(self):
        mid = self._selected_model_id()
        if not mid:
            return
        st.reset_profile_overrides(mid)
        self._reload_models_table()

    # ── Aba Geral ─────────────────────────────────────────────────────

    def _general_tab_widget(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.addWidget(QLabel("Modelo padrão dos assistentes:"), 0, 0)
        self.default_model_combo = QComboBox()
        for mid, label, _provider in pf.list_models():
            self.default_model_combo.addItem(f"{mid} — {label}", mid)
        current = st.default_model()
        idx = self.default_model_combo.findData(current)
        if idx >= 0:
            self.default_model_combo.setCurrentIndex(idx)
        self.default_model_combo.currentIndexChanged.connect(
            lambda _i: st.set_default_model(
                self.default_model_combo.currentData() or ""))
        grid.addWidget(self.default_model_combo, 0, 1, 1, 2)

        grid.addWidget(QLabel("Pasta de configuração:"), 1, 0)
        path_edit = QLineEdit(str(st.config_dir()))
        path_edit.setReadOnly(True)
        grid.addWidget(path_edit, 1, 1)
        btn_open = QPushButton("Abrir pasta")
        btn_open.clicked.connect(self._open_config_folder)
        grid.addWidget(btn_open, 1, 2)

        vault = "disponível" if pf.keyring_available() else \
            "indisponível neste ambiente"
        note = QLabel(
            f"Cofre do Windows (keyring): {vault}. As chaves ficam no "
            "cofre do sistema — nunca em arquivos. Arquivos de "
            "configuração: user_providers.json e user_profiles.json."
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        grid.addWidget(note, 2, 0, 1, 3)
        grid.setRowStretch(3, 1)
        return tab

    def _reload_general_tab(self):
        self.tabs.removeTab(2)
        self.tabs.insertTab(2, self._general_tab_widget(), "Geral")

    def _open_config_folder(self):
        st.config_dir().mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(st.config_dir())))


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ GLOSSÁRIO (§4.5) — Termos / Construir (auto-build) / Semente wiki
# ─────────────────────────────────────────────────────────────────────────────

class _CandidateScanThread(QThread):
    """Scan de candidatos fora da UI (input grande demais p/ bloquear)."""

    result = Signal(list)
    error = Signal(str)

    def __init__(self, project: wp.Project, glossary_path: Path,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.glossary_path = glossary_path

    def run(self):  # pragma: no cover - exercitado no smoke offscreen
        try:
            rows = gl.scan_project_candidates(self.project,
                                              self.glossary_path)
            self.result.emit(rows)
        except Exception as exc:
            self.error.emit(str(exc))


class _LlmSuggestThread(QThread):
    """UMA chamada em lote sugerindo PT para os termos aprovados."""

    result = Signal(dict)
    error = Signal(str)

    def __init__(self, terms: list, model: str, api_key: str, base_url: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.terms = terms
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def run(self):  # pragma: no cover - exercitado no smoke offscreen
        try:
            out = gl.suggest_translations_llm(
                self.terms, self.model, self.api_key, self.base_url)
            self.result.emit(out)
        except Exception as exc:
            self.error.emit(str(exc))


class _WikiLiveThread(QThread):
    """Busca 1 termo na wiki ao vivo sem congelar a UI."""

    result = Signal(dict)
    error = Signal(str)

    def __init__(self, term: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.term = term

    def run(self):  # pragma: no cover - rede real, não exercitado
        try:
            self.result.emit(gl.wiki_fetch_live(self.term))
        except Exception as exc:
            self.error.emit(str(exc))


class _TermEditDialog(QDialog):
    """Adicionar/editar termo (categoria: combo das existentes + livre)."""

    def __init__(self, categories: list, entry: Optional[Dict] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Editar termo" if entry else "Adicionar termo")
        self.setMinimumWidth(480)
        self.entry: Dict = {}

        grid = QGridLayout(self)
        row = 0
        grid.addWidget(QLabel("Termo EN:"), row, 0)
        self.en_edit = QLineEdit((entry or {}).get("term_english", ""))
        grid.addWidget(self.en_edit, row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Tradução PT:"), row, 0)
        self.pt_edit = QLineEdit((entry or {}).get("term_translated", ""))
        self.pt_edit.setPlaceholderText("vazio = mantém o EN (preserve)")
        grid.addWidget(self.pt_edit, row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Categoria:"), row, 0)
        self.cat_combo = QComboBox()
        self.cat_combo.setEditable(True)
        self.cat_combo.addItems(categories)
        current_cat = (entry or {}).get("category", "")
        if current_cat:
            self.cat_combo.setCurrentText(current_cat)
        grid.addWidget(self.cat_combo, row, 1)
        grid.addWidget(QLabel("Confiança:"), row, 2)
        row += 1
        self.conf_combo = QComboBox()
        self.conf_combo.addItems(list(gl.CONFIDENCES))
        self.conf_combo.setCurrentText(
            (entry or {}).get("confidence", "medium"))
        grid.addWidget(self.conf_combo, row, 2)
        self.preserve_cb = QCheckBox("Preserve (manter EN no texto)")
        self.preserve_cb.setChecked(bool((entry or {}).get("preserve", True)))
        grid.addWidget(self.preserve_cb, row, 0, 1, 2)
        self.inline_cb = QCheckBox("Inline (travar o termo dentro da frase)")
        self.inline_cb.setChecked(bool((entry or {}).get("inline", False)))
        grid.addWidget(self.inline_cb, row, 2)
        row += 1
        grid.addWidget(QLabel("Contexto:"), row, 0)
        self.context_edit = QLineEdit((entry or {}).get("context", ""))
        grid.addWidget(self.context_edit, row, 1, 1, 2)
        row += 1

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, row, 0, 1, 3)

    def _accept(self):
        entry = {
            "term_english": self.en_edit.text().strip(),
            "term_translated": self.pt_edit.text().strip(),
            "category": self.cat_combo.currentText().strip(),
            "preserve": self.preserve_cb.isChecked(),
            "inline": self.inline_cb.isChecked(),
            "context": self.context_edit.text().strip(),
            "confidence": self.conf_combo.currentText(),
            "source": gl.SOURCE_MANUAL,
        }
        errors = gl.validate_entry(entry)
        if errors:
            QMessageBox.warning(self, "Termo inválido", " ".join(errors))
            return
        self.entry = entry
        self.accept()


class GlossaryDialog(QDialog):
    """⑤ Glossário (§4.5): manutenção + auto-build do glossário DO PROJETO.

    Edições gravam em <projeto>/glossary.json (atômico + backup único por
    sessão em backups/) e atualizam o card GLOSSÁRIO do dashboard.
    """

    _CAND_COLS = ("✓", "Termo EN", "Ocorr.", "Contexto (amostra)",
                  "PT sugerida", "Categoria", "Preserve", "Inline")

    def __init__(self, project: wp.Project, main: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.main = main
        self.setWindowTitle("⑤ Glossário")
        self.setMinimumSize(980, 640)
        self._backup_done = False
        self._threads: list = []
        self._candidate_rows: list[Dict] = []
        self.data = gl.load_glossary(project.glossary_path())

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Glossário do projeto: <code>{project.glossary_path()}</code> "
            "— nunca o do app. Na primeira edição da sessão um backup vai "
            "para <code>backups/</code>."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._terms_tab_widget(), "Termos")
        self.tabs.addTab(self._build_tab_widget(), "Construir (auto-build)")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── persistência comum ────────────────────────────────────────────

    def _ensure_backup(self):
        if self._backup_done:
            return
        gl.backup_glossary(self.project)
        self._backup_done = True

    def _persist(self):
        gl.save_project_glossary(self.project, self.data)
        if self.main.project is not None:
            self.main.dashboard.refresh(self.main.project)

    # ── Aba Termos ────────────────────────────────────────────────────

    def _terms_tab_widget(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)

        filt = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar em EN / PT / contexto…")
        filt.addWidget(self.search_edit, 2)
        self.cat_filter = QComboBox()
        filt.addWidget(self.cat_filter, 1)
        self.preserve_filter = QComboBox()
        self.preserve_filter.addItems(
            ["Preserve: todos", "Só preserve", "Sem preserve"])
        filt.addWidget(self.preserve_filter)
        self.inline_filter = QComboBox()
        self.inline_filter.addItems(
            ["Inline: todos", "Só inline", "Sem inline"])
        filt.addWidget(self.inline_filter)
        v.addLayout(filt)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._reload_terms_table)
        self.search_edit.textChanged.connect(
            lambda _t: self._search_timer.start())
        self.cat_filter.currentIndexChanged.connect(
            lambda _i: self._reload_terms_table())
        self.preserve_filter.currentIndexChanged.connect(
            lambda _i: self._reload_terms_table())
        self.inline_filter.currentIndexChanged.connect(
            lambda _i: self._reload_terms_table())

        self.terms_table = QTableWidget()
        self.terms_table.setColumnCount(7)
        self.terms_table.setHorizontalHeaderLabels([
            "Termo EN", "Tradução PT", "Categoria", "Preserve", "Inline",
            "Fonte", "Uso",
        ])
        self.terms_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.terms_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.terms_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.terms_table.itemDoubleClicked.connect(
            lambda _item: self._edit_selected_term())
        v.addWidget(self.terms_table, 1)

        self.terms_count = QLabel("")
        self.terms_count.setObjectName("subtitle")
        v.addWidget(self.terms_count)

        row = QHBoxLayout()
        for text, slot in (
                ("Adicionar…", self._add_term),
                ("Editar…", self._edit_selected_term),
                ("Remover", self._remove_selected_term),
                ("Semente wiki (offline)…", self._wiki_seed_offline),
                ("Buscar wiki ao vivo…", self._wiki_live)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        v.addLayout(row)

        self._reload_terms_table()
        return tab

    def _reload_terms_table(self):
        # Reconstrói o combo de categorias mantendo a seleção.
        current_cat = self.cat_filter.currentText()
        cats = gl.categories_of(self.data["terms"])
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("Todas as categorias")
        self.cat_filter.addItems(cats)
        idx = self.cat_filter.findText(current_cat)
        self.cat_filter.setCurrentIndex(max(0, idx))
        self.cat_filter.blockSignals(False)

        cat = self.cat_filter.currentText()
        if cat == "Todas as categorias":
            cat = ""
        preserve = {0: None, 1: True, 2: False}[
            self.preserve_filter.currentIndex()]
        inline = {0: None, 1: True, 2: False}[
            self.inline_filter.currentIndex()]
        shown = gl.filter_terms(self.data["terms"], self.search_edit.text(),
                                cat, preserve, inline)

        self.terms_table.setSortingEnabled(False)
        self.terms_table.setRowCount(len(shown))
        for r, t in enumerate(shown):
            values = [
                str(t.get("term_english") or ""),
                str(t.get("term_translated") or ""),
                str(t.get("category") or ""),
                "✓" if t.get("preserve") else "—",
                "✓" if t.get("inline") else "—",
                str(t.get("source") or ""),
            ]
            for c, text in enumerate(values):
                self.terms_table.setItem(r, c, QTableWidgetItem(text))
            usage = QTableWidgetItem()
            usage.setData(Qt.DisplayRole, int(t.get("usage_count") or 0))
            self.terms_table.setItem(r, 6, usage)
        self.terms_table.setSortingEnabled(True)

        total = len(self.data["terms"])
        def pt_br(n: int) -> str:
            return f"{n:,}".replace(",", ".")
        suffix = (f" · filtrados: {pt_br(len(shown))}"
                  if len(shown) != total else "")
        self.terms_count.setText(f"{pt_br(total)} termos{suffix}")

    def _selected_term_en(self) -> str:
        row = self.terms_table.currentRow()
        if row < 0:
            return ""
        item = self.terms_table.item(row, 0)
        return item.text() if item else ""

    def _add_term(self):
        dlg = _TermEditDialog(gl.categories_of(self.data["terms"]),
                              parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            gl.add_term(self.data, dlg.entry)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível adicionar", str(exc))
            return
        self._ensure_backup()
        self._persist()
        self._reload_terms_table()

    def _edit_selected_term(self):
        en = self._selected_term_en()
        if not en:
            return
        idx = gl.find_term(self.data["terms"], en)
        if idx < 0:
            return
        dlg = _TermEditDialog(gl.categories_of(self.data["terms"]),
                              entry=dict(self.data["terms"][idx]),
                              parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            gl.update_term(self.data, en, dlg.entry)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível editar", str(exc))
            return
        self._ensure_backup()
        self._persist()
        self._reload_terms_table()

    def _remove_selected_term(self):
        en = self._selected_term_en()
        if not en:
            return
        answer = QMessageBox.question(
            self, "Remover termo",
            f"Remover “{en}” do glossário do projeto?")
        if answer != QMessageBox.Yes:
            return
        if gl.remove_term(self.data, en):
            self._ensure_backup()
            self._persist()
            self._reload_terms_table()

    # ── Semente wiki ──────────────────────────────────────────────────

    def _wiki_seed_offline(self):
        try:
            entries = gl.wiki_seed_entries()
        except Exception as exc:
            QMessageBox.warning(self, "Semente wiki", str(exc))
            return
        added, skipped = gl.merge_terms(self.data, entries)
        if added == 0:
            QMessageBox.information(
                self, "Semente wiki",
                f"Nada novo — todos os {skipped} termos da semente já "
                "estão no glossário.")
            return
        self._ensure_backup()
        self._persist()
        self._reload_terms_table()
        QMessageBox.information(
            self, "Semente wiki",
            f"{added} termos adicionados da semente offline da wiki "
            f"({skipped} já existiam) · glossário agora tem "
            f"{len(self.data['terms'])} termos.")

    def _wiki_live(self):
        term, ok = QInputDialog.getText(
            self, "Buscar wiki ao vivo",
            "Termo para buscar na wiki do Rogue Trader\n"
            "(roguetrader.wh40k.wiki, via MediaWiki API):")
        if not ok or not term.strip():
            return
        thread = _WikiLiveThread(term.strip(), self)
        self._threads.append(thread)

        def _done(entry: dict, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            added, _skipped = gl.merge_terms(self.data, [entry])
            if added:
                self._ensure_backup()
                self._persist()
                self._reload_terms_table()
                QMessageBox.information(
                    self, "Wiki ao vivo",
                    f"“{entry['term_english']}” adicionado "
                    f"[{entry['category']}].\n\n{entry['context']}")
            else:
                QMessageBox.information(
                    self, "Wiki ao vivo",
                    f"“{entry['term_english']}” já está no glossário.")

        def _err(msg: str, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            QMessageBox.warning(
                self, "Wiki ao vivo",
                f"Não foi possível buscar: {msg}\n\n"
                "Você pode adicionar manualmente em “Adicionar…”.")

        thread.result.connect(_done)
        thread.error.connect(_err)
        thread.start()

    # ── Aba Construir (auto-build) ────────────────────────────────────

    def _build_tab_widget(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)

        top = QHBoxLayout()
        self.btn_scan = QPushButton("Escanear candidatos")
        self.btn_scan.clicked.connect(self._scan_candidates)
        top.addWidget(self.btn_scan)
        self.scan_status = QLabel(
            "Escaneia o input do projeto atrás de termos EN repetidos "
            "que ainda não estão no glossário.")
        self.scan_status.setObjectName("subtitle")
        self.scan_status.setWordWrap(True)
        top.addWidget(self.scan_status, 1)
        v.addLayout(top)

        self.cand_table = QTableWidget()
        self.cand_table.setColumnCount(len(self._CAND_COLS))
        self.cand_table.setHorizontalHeaderLabels(list(self._CAND_COLS))
        self.cand_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        v.addWidget(self.cand_table, 1)

        row = QHBoxLayout()
        btn_all = QPushButton("Marcar todos")
        btn_all.clicked.connect(lambda: self._set_all_approved(True))
        row.addWidget(btn_all)
        btn_none = QPushButton("Desmarcar todos")
        btn_none.clicked.connect(lambda: self._set_all_approved(False))
        row.addWidget(btn_none)
        btn_reject = QPushButton("Rejeitar selecionados")
        btn_reject.setToolTip("Remove da lista as linhas desmarcadas.")
        btn_reject.clicked.connect(self._reject_unapproved)
        row.addWidget(btn_reject)
        row.addStretch(1)
        self.btn_llm = QPushButton("Sugerir via LLM")
        self.btn_llm.clicked.connect(self._suggest_llm)
        row.addWidget(self.btn_llm)
        self.btn_merge = QPushButton("Mesclar no glossário")
        self.btn_merge.clicked.connect(self._merge_candidates)
        row.addWidget(self.btn_merge)
        v.addLayout(row)

        self.merge_status = QLabel("")
        self.merge_status.setObjectName("subtitle")
        self.merge_status.setWordWrap(True)
        v.addWidget(self.merge_status)
        return tab

    def _scan_candidates(self):
        if not self.project.has_input():
            QMessageBox.warning(self, "Escanear candidatos",
                                "O projeto ainda não tem input registrado.")
            return
        self.btn_scan.setEnabled(False)
        self.scan_status.setText("Escaneando o input…")
        thread = _CandidateScanThread(
            self.project, self.project.glossary_path(), self)
        self._threads.append(thread)

        def _done(rows: list, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            self.btn_scan.setEnabled(True)
            self._candidate_rows = rows
            self._reload_cand_table()
            self.scan_status.setText(
                f"{len(rows)} candidatos rankeados por frequência."
                if rows else
                "Nenhum candidato repetido encontrado no input.")

        def _err(msg: str, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            self.btn_scan.setEnabled(True)
            self.scan_status.setText(f"Falha no scan: {msg}")

        thread.result.connect(_done)
        thread.error.connect(_err)
        thread.start()

    @staticmethod
    def _check_item(checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem("")
        item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        return item

    def _reload_cand_table(self):
        self.cand_table.setRowCount(len(self._candidate_rows))
        for r, row in enumerate(self._candidate_rows):
            self.cand_table.setItem(
                r, 0, self._check_item(bool(row.get("approved", True))))
            for c, key in ((1, "term"), (3, "context")):
                item = QTableWidgetItem(str(row.get(key) or ""))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.cand_table.setItem(r, c, item)
            count = QTableWidgetItem()
            count.setData(Qt.DisplayRole, int(row.get("count") or 0))
            count.setFlags(count.flags() & ~Qt.ItemIsEditable)
            self.cand_table.setItem(r, 2, count)
            self.cand_table.setItem(
                r, 4, QTableWidgetItem(str(row.get("pt") or "")))
            self.cand_table.setItem(
                r, 5, QTableWidgetItem(str(row.get("category") or "")))
            self.cand_table.setItem(
                r, 6, self._check_item(bool(row.get("preserve", True))))
            self.cand_table.setItem(
                r, 7, self._check_item(bool(row.get("inline", False))))

    def _sync_candidate_rows(self):
        """Tabela → self._candidate_rows (checkboxes e células editáveis)."""
        for r in range(self.cand_table.rowCount()):
            if r >= len(self._candidate_rows):
                break
            row = self._candidate_rows[r]
            row["approved"] = (
                self.cand_table.item(r, 0).checkState() == Qt.Checked)
            row["pt"] = (self.cand_table.item(r, 4).text()
                         if self.cand_table.item(r, 4) else "").strip()
            row["category"] = (self.cand_table.item(r, 5).text()
                               if self.cand_table.item(r, 5) else "").strip()
            row["preserve"] = (
                self.cand_table.item(r, 6).checkState() == Qt.Checked)
            row["inline"] = (
                self.cand_table.item(r, 7).checkState() == Qt.Checked)

    def _set_all_approved(self, value: bool):
        state = Qt.Checked if value else Qt.Unchecked
        for r in range(self.cand_table.rowCount()):
            item = self.cand_table.item(r, 0)
            if item is not None:
                item.setCheckState(state)

    def _reject_unapproved(self):
        self._sync_candidate_rows()
        kept = [row for row in self._candidate_rows if row.get("approved")]
        rejected = len(self._candidate_rows) - len(kept)
        self._candidate_rows = kept
        self._reload_cand_table()
        self.merge_status.setText(
            f"{rejected} candidatos rejeitados (fora da lista).")

    def _suggest_llm(self):
        self._sync_candidate_rows()
        approved = [row for row in self._candidate_rows
                    if row.get("approved")]
        if not approved:
            QMessageBox.information(self, "Sugerir via LLM",
                                    "Nenhum candidato aprovado.")
            return
        # Só preenche PT vazio — nunca sobrescreve digitação manual.
        terms = [row["term"] for row in approved if not row.get("pt")]
        if not terms:
            QMessageBox.information(
                self, "Sugerir via LLM",
                "Todos os aprovados já têm PT preenchido.")
            return

        model = st.default_model()
        provider = pf.provider_for_model(model)
        key, _source = pf.resolve_api_key(provider, "")
        if not key:
            QMessageBox.warning(
                self, "Sugerir via LLM",
                "Nenhuma chave de API disponível — configure em "
                "⚙ Configurações.")
            return
        _rid, prof = st.resolve_effective_profile(model)
        base_url = str(prof.get("url") or "")

        answer = QMessageBox.question(
            self, "Sugerir via LLM",
            f"1 chamada · {len(terms)} termos · modelo {model}.\n"
            "As sugestões entram como confiança BAIXA — revise antes de "
            "mesclar. Continuar?")
        if answer != QMessageBox.Yes:
            return

        self.btn_llm.setEnabled(False)
        self.merge_status.setText("Consultando o LLM…")
        thread = _LlmSuggestThread(terms, model, key, base_url, self)
        self._threads.append(thread)

        def _done(suggestions: dict, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            self.btn_llm.setEnabled(True)
            filled = 0
            for r, row in enumerate(self._candidate_rows):
                pt = suggestions.get(row["term"])
                if pt and not row.get("pt"):
                    row["pt"] = pt
                    row["source"] = gl.SOURCE_AUTO_BUILD_LLM
                    filled += 1
            self._reload_cand_table()
            self.merge_status.setText(
                f"{filled}/{len(terms)} termos com PT sugerido pelo LLM "
                "— revise a coluna PT antes de mesclar.")

        def _err(msg: str, t=thread):
            if t in self._threads:
                self._threads.remove(t)
            self.btn_llm.setEnabled(True)
            self.merge_status.setText(f"Falha na sugestão LLM: {msg}")

        thread.result.connect(_done)
        thread.error.connect(_err)
        thread.start()

    def _merge_candidates(self):
        self._sync_candidate_rows()
        approved = [row for row in self._candidate_rows
                    if row.get("approved")]
        if not approved:
            QMessageBox.information(self, "Mesclar no glossário",
                                    "Nenhum candidato aprovado para mesclar.")
            return
        entries = gl.entries_from_candidate_rows(approved)
        before = len(self.data["terms"])
        added, skipped = gl.merge_terms(self.data, entries)
        if added == 0:
            QMessageBox.information(
                self, "Mesclar no glossário",
                f"Nada novo — {skipped} já existiam (dedupe por EN).")
            return
        self._ensure_backup()
        self._persist()
        self._reload_terms_table()
        # Linhas aprovadas saem da lista (adicionadas ou duplicadas —
        # ambas já estão no glossário); as desmarcadas ficam para revisão.
        self._candidate_rows = [
            row for row in self._candidate_rows if not row.get("approved")
        ]
        self._reload_cand_table()
        note = f" · {skipped} pulados (já existiam)" if skipped else ""
        self.merge_status.setText(
            f"✔ {added} termos adicionados{note} · glossário agora tem "
            f"{len(self.data['terms'])} termos (antes: {before}).")


class AdoptDialog(QDialog):
    """'Adotar Tradução Existente' (§3): escaneia, classifica e copia."""

    def __init__(self, project: wp.Project,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Adotar Tradução Existente")
        self.setMinimumSize(760, 480)
        self._rows: list[Dict] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Aponte uma pasta ou arquivos soltos. O app detecta quais são "
            "o dump em inglês e as traduções (Preservada / Completa), e "
            "<b>copia</b> — nunca move — os arquivos para dentro do projeto."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        pick_row = QHBoxLayout()
        btn_folder = QPushButton("Escolher pasta…")
        btn_folder.clicked.connect(self._pick_folder)
        btn_files = QPushButton("Escolher arquivos…")
        btn_files.clicked.connect(self._pick_files)
        pick_row.addWidget(btn_folder)
        pick_row.addWidget(btn_files)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Arquivo", "Strings", "Detecção", "Papel no projeto"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.summary = QLabel("Nenhum arquivo analisado ainda.")
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Importar selecionados")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._import)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self._ok_button.setEnabled(False)
        layout.addWidget(buttons)

    # ── seleção e varredura ─────────────────────────────────────────────

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Escolha a pasta com os arquivos de tradução")
        if folder:
            self._scan([Path(folder)])

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Escolha os arquivos JSON", "", "JSON (*.json)")
        if files:
            self._scan([Path(f) for f in files])

    def _scan(self, paths: list[Path]) -> None:
        try:
            results = wp.scan_candidates(paths)
        except Exception as exc:  # varredura nunca deve derrubar o diálogo
            QMessageBox.warning(self, "Erro na varredura",
                                f"Não foi possível analisar: {exc}")
            return
        if not results:
            self.summary.setText("Nenhum arquivo .json encontrado.")
            return

        self._rows = results
        self.table.setRowCount(0)
        for info in results:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(info["name"]))
            strings = (str(info["strings"])
                       if info["strings"] is not None else "—")
            self.table.setItem(row, 1, QTableWidgetItem(strings))

            if not info["valid"]:
                det = QLabel(f"✗ {info['error']}")
                det.setObjectName("err")
            else:
                lang = {"en": "inglês", "pt": "português",
                        "unknown": "idioma?"}[info["language"]]
                det = QLabel(f"Válido · {lang}")
                det.setObjectName("ok")
            det.setWordWrap(True)
            self.table.setCellWidget(row, 2, det)

            combo = QComboBox()
            combo.addItems(list(ROLE_LABELS.values()))
            combo.setCurrentText(ROLE_LABELS[info["role"]])
            if not info["valid"]:
                combo.setCurrentText(ROLE_LABELS[wp.ROLE_IGNORE])
            self.table.setCellWidget(row, 3, combo)

        valid = sum(1 for r in results if r["valid"])
        self.summary.setText(
            f"{len(results)} arquivo(s) analisado(s) · {valid} válido(s). "
            "Confira a coluna 'Papel no projeto' e ajuste se necessário."
        )
        self._ok_button.setEnabled(valid > 0)

    # ── importação ──────────────────────────────────────────────────────

    def _selected_roles(self) -> Dict[str, Path]:
        roles: Dict[str, Path] = {}
        for row, info in enumerate(self._rows):
            combo = self.table.cellWidget(row, 3)
            role = LABEL_TO_ROLE.get(combo.currentText(), wp.ROLE_IGNORE)
            if role == wp.ROLE_IGNORE or not info["valid"]:
                continue
            if role in roles:
                QMessageBox.warning(
                    self, "Papel duplicado",
                    f"Mais de um arquivo marcado como "
                    f"'{ROLE_LABELS[role]}'. Escolha apenas um por papel.")
                return {}
            roles[role] = info["path"]
        return roles

    def _import(self) -> None:
        roles = self._selected_roles()
        if not roles:
            QMessageBox.information(
                self, "Nada para importar",
                "Marque ao menos um arquivo com um papel válido.")
            return
        try:
            result = self.project.adopt_files(roles)
        except wp.ProjectError as exc:
            QMessageBox.critical(self, "Erro na importação", str(exc))
            return

        lines = []
        for item in result["imported"]:
            lines.append(
                f"✓ {item['source']} → {item['dest']} "
                f"({item['strings']:,} strings)".replace(",", "."))
        for err in result["errors"]:
            lines.append(f"✗ {err}")
        if result["imported"]:
            lines.append("\nOs arquivos originais foram mantidos intactos; "
                         "o projeto agora gerencia as cópias.")
        QMessageBox.information(self, "Resumo da adoção", "\n".join(lines))
        if result["imported"]:
            self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# RECONCILIAÇÃO DE ESTADO (§9.6) — arquivos soltos em input//output/
# ─────────────────────────────────────────────────────────────────────────────

class ReconcileDialog(QDialog):
    """Lista arquivos de localização encontrados em input//output/ que o
    project.json ainda não conhece; o usuário confirma/ajusta o papel de
    cada um (mesma UX da adoção) e o registro backfill o estado."""

    def __init__(self, project: wp.Project, untracked: list[Dict],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self._rows = untracked
        self.setWindowTitle("Reconhecer arquivos soltos")
        self.setMinimumSize(760, 420)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Encontrei arquivos de tradução em <b>input/</b> ou "
            "<b>output/</b> que o projeto ainda não conhece — talvez você "
            "tenha copiado algo manualmente. Confira o papel de cada um: "
            "o registro copia os versionados para os nomes canônicos "
            "(os originais ficam) e atualiza o project.json."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Arquivo", "Strings", "Detecção", "Papel no projeto"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        for info in untracked:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(info["name"]))
            self.table.setItem(
                row, 1, QTableWidgetItem(str(info.get("strings") or "—")))
            lang = {"en": "inglês", "pt": "português",
                    "unknown": "idioma?"}[info["language"]]
            det = QLabel(f"Válido · {lang}")
            det.setObjectName("ok")
            self.table.setCellWidget(row, 2, det)
            combo = QComboBox()
            combo.addItems(list(ROLE_LABELS.values()))
            combo.setCurrentText(ROLE_LABELS[info["role"]])
            self.table.setCellWidget(row, 3, combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Registrar selecionados")
        buttons.button(QDialogButtonBox.Cancel).setText("Agora não")
        buttons.accepted.connect(self._register)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _selected_roles(self) -> Dict[str, Path]:
        roles: Dict[str, Path] = {}
        for row, info in enumerate(self._rows):
            combo = self.table.cellWidget(row, 3)
            role = LABEL_TO_ROLE.get(combo.currentText(), wp.ROLE_IGNORE)
            if role == wp.ROLE_IGNORE:
                continue
            if role in roles:
                QMessageBox.warning(
                    self, "Papel duplicado",
                    f"Mais de um arquivo marcado como "
                    f"'{ROLE_LABELS[role]}'. Escolha apenas um por papel.")
                return {}
            roles[role] = info["path"]
        return roles

    def _register(self) -> None:
        roles = self._selected_roles()
        if not roles:
            QMessageBox.information(
                self, "Nada para registrar",
                "Marque ao menos um arquivo com um papel válido.")
            return
        try:
            result = self.project.adopt_files(roles)
        except wp.ProjectError as exc:
            QMessageBox.critical(self, "Erro no registro", str(exc))
            return
        lines = [
            f"✓ {item['source']} → {item['dest']} "
            f"({item['strings']:,} strings)".replace(",", ".")
            for item in result["imported"]
        ]
        lines += [f"✗ {err}" for err in result["errors"]]
        if result["imported"]:
            lines.append("\nOs originais foram mantidos; o projeto agora "
                         "reconhece esses arquivos.")
            self.accept()
        QMessageBox.information(self, "Resumo do registro", "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# GLOSSÁRIO DO PROJETO (§9.7) — escolha na criação / troca
# ─────────────────────────────────────────────────────────────────────────────

class GlossaryChoiceDialog(QDialog):
    """Escolha do glossário do projeto: ① Rogue Trader (recomendado),
    ② outro arquivo (jogo base ou mod), ③ começar vazio (avançado)."""

    CHOICE_RT = "rt"
    CHOICE_FILE = "file"
    CHOICE_EMPTY = "empty"

    def __init__(self, repo_glossary: Path,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.repo_glossary = Path(repo_glossary)
        self.choice = self.CHOICE_RT
        self.file_path: Optional[Path] = None
        self.kind = wp.GLOSSARY_KIND_BASE
        self.mod_name = ""
        self.setWindowTitle("Glossário do projeto")
        self.setMinimumWidth(560)

        try:
            terms = wp.count_glossary_terms(self.repo_glossary)
            rt_label = (f"① Importar glossário Rogue Trader "
                        f"({terms:,} termos — recomendado)"
                        .replace(",", "."))
        except wp.ProjectError:
            rt_label = "① Importar glossário Rogue Trader (recomendado)"

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Cada projeto tem seu próprio glossário — mods podem partir "
            "do glossário do jogo base e evoluir separado. A escolha "
            "padrão cobre Rogue Trader inteiro."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.radio_rt = QRadioButton(rt_label)
        self.radio_rt.setChecked(True)
        self.radio_file = QRadioButton("② Importar de outro projeto/arquivo…")
        self.radio_empty = QRadioButton("③ Começar vazio (avançado)")
        layout.addWidget(self.radio_rt)
        layout.addWidget(self.radio_file)

        self.file_row = QWidget()
        file_layout = QGridLayout(self.file_row)
        file_layout.setContentsMargins(24, 0, 0, 0)
        btn_pick = QPushButton("Escolher glossary.json…")
        btn_pick.clicked.connect(self._pick_file)
        file_layout.addWidget(btn_pick, 0, 0)
        self.file_label = QLabel("nenhum arquivo escolhido")
        self.file_label.setObjectName("subtitle")
        file_layout.addWidget(self.file_label, 0, 1)
        file_layout.addWidget(QLabel("Tipo:"), 1, 0)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Jogo base", wp.GLOSSARY_KIND_BASE)
        self.kind_combo.addItem("Mod (derivado de outro glossário)",
                                wp.GLOSSARY_KIND_MOD)
        self.kind_combo.currentIndexChanged.connect(self._toggle_mod_name)
        file_layout.addWidget(self.kind_combo, 1, 1)
        self.mod_name_edit = QLineEdit()
        self.mod_name_edit.setPlaceholderText(
            "nome do mod (ex.: Dark Heresy)")
        self.mod_name_edit.setVisible(False)
        file_layout.addWidget(self.mod_name_edit, 2, 1)
        layout.addWidget(self.file_row)
        layout.addWidget(self.radio_empty)

        self.radio_file.toggled.connect(
            lambda on: self._sync_file_row())

        empty_hint = QLabel(
            "Vazio = sem preservação de termos nem fullize até você "
            "construir o glossário na jornada ⑤.")
        empty_hint.setObjectName("subtitle")
        empty_hint.setWordWrap(True)
        layout.addWidget(empty_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_file_row()

    def _sync_file_row(self) -> None:
        self.file_row.setVisible(self.radio_file.isChecked())

    def _toggle_mod_name(self) -> None:
        self.mod_name_edit.setVisible(
            self.kind_combo.currentData() == wp.GLOSSARY_KIND_MOD)

    def _pick_file(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Escolha o glossary.json", "", "JSON (*.json)")
        if file:
            self.file_path = Path(file)
            self.file_label.setText(self.file_path.name)

    def _accept(self) -> None:
        if self.radio_file.isChecked():
            if self.file_path is None:
                QMessageBox.information(
                    self, "Escolha o arquivo",
                    "Aponte o glossary.json a importar — ou escolha outra "
                    "opção.")
                return
            self.choice = self.CHOICE_FILE
            self.kind = self.kind_combo.currentData()
            self.mod_name = self.mod_name_edit.text().strip()
        elif self.radio_empty.isChecked():
            self.choice = self.CHOICE_EMPTY
        else:
            self.choice = self.CHOICE_RT
        self.accept()

    def apply_to(self, project: wp.Project) -> Dict:
        """Aplica a escolha ao projeto (import/cópia/vazio + metadata)."""
        if self.choice == self.CHOICE_FILE:
            return project.import_glossary(
                self.file_path, kind=self.kind,
                mod_name=self.mod_name or None)
        if self.choice == self.CHOICE_EMPTY:
            return project.create_empty_glossary()
        return project.import_glossary(self.repo_glossary)


# ─────────────────────────────────────────────────────────────────────────────
# TELA DE BOAS-VINDAS
# ─────────────────────────────────────────────────────────────────────────────

class WelcomePage(QWidget):
    """Primeira execução / sem projeto aberto."""

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 50, 60, 50)
        layout.setSpacing(18)

        title = QLabel("W40K TRANSLATOR")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Tradução PT-BR de Warhammer 40K: Rogue Trader\n"
            "Organize tudo em um projeto — o app lembra onde você parou."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        btn_new = QPushButton("🗡  Novo Projeto")
        btn_new.setObjectName("journey")
        btn_new.setToolTip("Cria a estrutura de pastas e o project.json "
                           "em uma pasta que você escolher.")
        btn_new.clicked.connect(self._new_project)
        layout.addWidget(btn_new)

        btn_adopt = QPushButton("⚜  Adotar Tradução Existente")
        btn_adopt.setObjectName("journey")
        btn_adopt.setToolTip("Já tem arquivos traduzidos soltos? O app copia "
                             "e organiza tudo em um projeto novo.")
        btn_adopt.clicked.connect(self._adopt_flow)
        layout.addWidget(btn_adopt)

        btn_open = QPushButton("📖  Abrir Projeto")
        btn_open.setObjectName("journey")
        btn_open.setToolTip("Abre uma pasta que já contém project.json.")
        btn_open.clicked.connect(self._open_project)
        layout.addWidget(btn_open)

        layout.addStretch(1)

    # ── ações ───────────────────────────────────────────────────────────

    def _new_project(self) -> Optional[wp.Project]:
        folder = QFileDialog.getExistingDirectory(
            self, "Escolha (ou crie) a pasta do novo projeto")
        if not folder:
            return None
        try:
            project = wp.Project.create(
                Path(folder), glossary_path=REPO_ROOT / "glossary.json")
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível criar o projeto",
                                str(exc))
            return None

        self._glossary_step(project)

        answer = QMessageBox.question(
            self, "Adicionar enGB.json?",
            "Projeto criado ✓\n\nDeseja adicionar agora o arquivo de "
            "localização do jogo (enGB.json) na pasta input/?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            src, _ = QFileDialog.getOpenFileName(
                self, "Escolha o enGB.json do jogo", "",
                "JSON (*.json)")
            if src:
                try:
                    project.set_input(Path(src))
                except (wp.ProjectError, wp.LocalizationFormatError) as exc:
                    QMessageBox.warning(
                        self, "Arquivo não adicionado",
                        f"{exc}\n\nVocê pode adicionar depois pela jornada "
                        "① Nova Tradução.")
        # BUG 1 fix: projeto criado vai direto para o dashboard, igual ao
        # 'Abrir Projeto' (persiste lastProject via MainWindow.open_project).
        self.main.open_project(project)
        return project

    def _adopt_flow(self) -> None:
        project = self._new_project_silent()
        if project is None:
            return
        self._glossary_step(project)
        dialog = AdoptDialog(project, self)
        if dialog.exec() == QDialog.Accepted:
            # Mesmo destino do 'Abrir Projeto': persiste lastProject e
            # troca para o dashboard.
            self.main.open_project(project)
        # Se cancelar, o scaffold vazio fica lá — o usuário pode abri-lo
        # depois por 'Abrir Projeto'.

    def _glossary_step(self, project: wp.Project) -> None:
        """§9.7: todo projeto novo escolhe seu glossário (padrão ① RT).
        Cancelar aplica o recomendado — glossário vazio só se escolhido."""
        dialog = GlossaryChoiceDialog(REPO_ROOT / "glossary.json", self)
        if dialog.exec() != QDialog.Accepted:
            dialog.choice = GlossaryChoiceDialog.CHOICE_RT
        try:
            dialog.apply_to(project)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Glossário não importado",
                                f"{exc}\n\nVocê pode importar depois pelo "
                                "botão 'Trocar/reimportar…' no card "
                                "GLOSSÁRIO.")

    def _new_project_silent(self) -> Optional[wp.Project]:
        folder = QFileDialog.getExistingDirectory(
            self, "Escolha (ou crie) a pasta do projeto que vai adotar os arquivos")
        if not folder:
            return None
        try:
            return wp.Project.create(
                Path(folder), glossary_path=REPO_ROOT / "glossary.json")
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível criar o projeto",
                                str(exc))
            return None

    def _open_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Escolha a pasta do projeto (com project.json)")
        if not folder:
            return
        try:
            project = wp.Project.open(Path(folder))
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível abrir o projeto",
                                str(exc))
            return
        self.main.open_project(project)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD (§4.0)
# ─────────────────────────────────────────────────────────────────────────────

class DashboardPage(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(14)

        # Cabeçalho
        header = QHBoxLayout()
        self.title = QLabel("ROGUE TRADER PT-BR")
        self.title.setObjectName("title")
        header.addWidget(self.title)
        header.addStretch(1)
        btn_switch = QPushButton("Trocar de projeto")
        btn_switch.clicked.connect(self.main.close_project)
        header.addWidget(btn_switch)
        btn_settings = QPushButton("⚙ Configurações")
        btn_settings.clicked.connect(
            lambda: SettingsDialog(self).exec())
        header.addWidget(btn_settings)
        layout.addLayout(header)

        self.project_label = QLabel("")
        self.project_label.setObjectName("subtitle")
        layout.addWidget(self.project_label)

        # Cards de status
        cards = QGridLayout()
        cards.setSpacing(12)
        self.card_input = self._make_card("INPUT")
        self.card_tracks = self._make_card("TRILHAS")
        self.card_audit = self._make_card("AUDITORIA")
        self.card_glossary = self._make_card("GLOSSÁRIO")
        cards.addWidget(self.card_input[0], 0, 0)
        cards.addWidget(self.card_tracks[0], 0, 1)
        cards.addWidget(self.card_audit[0], 1, 0)
        cards.addWidget(self.card_glossary[0], 1, 1)
        layout.addLayout(cards)

        # Botão discreto no card INPUT para corrigir a versão do jogo
        # quando a detecção automática pelo nome do arquivo falha.
        btn_edit_version = QPushButton("editar versão")
        btn_edit_version.setToolTip(
            "A versão do jogo é detectada pelo nome do arquivo "
            "(ex.: enGB_1.6.1.514.json). Corrija aqui se necessário — "
            "ela é usada nos pacotes de release.")
        btn_edit_version.clicked.connect(self._edit_game_version)
        input_layout = self.card_input[0].layout()
        input_layout.addWidget(btn_edit_version, 0,
                               alignment=Qt.AlignLeft)

        # §9.6: reconhecer arquivos soltos em input//output/ manualmente
        btn_reconcile = QPushButton("Reconhecer arquivos")
        btn_reconcile.setToolTip(
            "Procura em input/ e output/ arquivos de tradução que você "
            "soltou lá manualmente (ex.: ptBR_full_1.6.1.514.json) e "
            "registra no project.json.")
        btn_reconcile.clicked.connect(self._reconcile_now)
        tracks_layout = self.card_tracks[0].layout()
        tracks_layout.addWidget(btn_reconcile, 0, alignment=Qt.AlignLeft)

        # §9.7: trocar/reimportar o glossário do projeto
        btn_swap_gloss = QPushButton("Trocar/reimportar…")
        btn_swap_gloss.setToolTip(
            "Importa outro glossário para este projeto (Rogue Trader, "
            "outro arquivo, ou começar vazio).")
        btn_swap_gloss.clicked.connect(self._swap_glossary)
        gloss_layout = self.card_glossary[0].layout()
        gloss_layout.addWidget(btn_swap_gloss, 0, alignment=Qt.AlignLeft)

        # Jornadas
        flow_hint = QLabel("Fluxo: ① traduzir → ② auditar → ③ publicar")
        flow_hint.setObjectName("subtitle")
        layout.addWidget(flow_hint)

        journeys = QGridLayout()
        journeys.setSpacing(10)
        self.journey_buttons: Dict[int, QPushButton] = {}
        labels = {
            1: "① Nova Tradução",
            2: "② Corrigir && Auditar",
            3: "③ Finalizar && Publicar",
            4: "④ Dia de Patch",
            5: "⑤ Glossário",
        }
        positions = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)]
        for num, (row, col) in zip(labels, positions):
            btn = QPushButton(labels[num])
            btn.setObjectName("journey")
            btn.clicked.connect(lambda _=False, n=num: self._open_journey(n))
            journeys.addWidget(btn, row, col)
            self.journey_buttons[num] = btn
        journeys.setColumnStretch(0, 1)
        journeys.setColumnStretch(1, 1)
        journeys.setColumnStretch(2, 1)
        journeys.setColumnStretch(3, 1)
        layout.addLayout(journeys)
        layout.addStretch(1)

    @staticmethod
    def _make_card(title: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("card")
        inner = QVBoxLayout(frame)
        head = QLabel(title)
        head.setObjectName("cardTitle")
        inner.addWidget(head)
        body = QLabel("—")
        body.setObjectName("cardBody")
        body.setWordWrap(True)
        inner.addWidget(body)
        inner.addStretch(1)
        return frame, body

    # ── atualização de estado ───────────────────────────────────────────

    def refresh(self, project: wp.Project) -> None:
        self.project_label.setText(f"Projeto: {project.root}")

        # INPUT
        if project.has_input():
            info = project.state["input"]
            canonical = Path(info["file"]).name
            lines = [
                f"✓ {canonical} · "
                f"{info['strings']:,} strings".replace(",", ".")
            ]
            original = info.get("original_name")
            if original and original != canonical:
                lines.append(f"origem: {original}")
            version = project.state.get("game_version")
            lines.append(f"jogo v{version}" if version
                         else "versão desconhecida")
            self.card_input[1].setText("\n".join(lines))
        else:
            self.card_input[1].setText(
                "✗ Nenhum enGB.json em input/\n"
                "Adicione pela jornada ① ou adote arquivos existentes.")

        # TRILHAS
        track_lines = []
        for track, label in ((wp.TRACK_PRESERVED, "Preservada"),
                             (wp.TRACK_FULL, "Completa")):
            entry = project.track_status(track)
            progress = project.track_progress(track)
            if entry.get("status") == wp.TRACK_STATUS_DONE:
                pct = "" if progress is None else f" {progress * 100:.0f}%"
                track_lines.append(f"{label} ✓{pct}")
            else:
                track_lines.append(f"{label} · pendente")
        self.card_tracks[1].setText("\n".join(track_lines))

        # AUDITORIA
        audit = project.state.get("last_audit")
        if audit:
            failed = audit.get("failed", 0)
            suspect = audit.get("suspect", 0)
            identical = audit.get("identical", 0)
            when = _fmt_audit_date(audit.get("date", ""))
            if failed or suspect:
                self.card_audit[1].setText(
                    f"⚠ {failed} falhas · {suspect} suspeitas · "
                    f"{identical} idênticas\nem {when}")
            else:
                extra = (f" ({identical} idênticas legítimas)"
                         if identical else "")
                self.card_audit[1].setText(f"✓ limpa em {when}{extra}")
        else:
            self.card_audit[1].setText("Nunca executada.")

        # GLOSSÁRIO (glossary.json na raiz do repo)
        self.card_glossary[1].setText(self._glossary_summary(project))

        # JORNADAS — lógica de habilitar/desabilitar
        self._update_journeys(project)

    @staticmethod
    def _glossary_summary(project: wp.Project) -> str:
        """Card GLOSSÁRIO: nome + contagem + tipo a partir da metadata do
        glossário do projeto (§9.7); legado sem metadata cai no stamp."""
        path = pf.resolve_glossary_path(project, repo_root=REPO_ROOT)
        if path is None:
            return "Glossário não encontrado\n(importe pelo botão abaixo)."
        try:
            terms = wp.count_glossary_terms(path)
        except wp.ProjectError:
            return "Glossário ilegível\n(troque pelo botão abaixo)."
        meta = wp.read_glossary_metadata(path)
        stamp = project.state.get("glossary_stamp", {})
        name = meta.get("name") or stamp.get("name")
        kind = meta.get("kind") or stamp.get("kind")
        parent = meta.get("parent") or stamp.get("parent")
        count = f"{terms:,} termos".replace(",", ".")
        if name and kind == wp.GLOSSARY_KIND_MOD:
            base = f" (base: {parent})" if parent else ""
            return f"{name} · {count} · mod{base}"
        if name:
            suffix = " · jogo base" if kind == wp.GLOSSARY_KIND_BASE else ""
            return f"{name} · {count}{suffix}"
        # Glossário legado (sem metadata estendida): comportamento antigo.
        built_for = stamp.get("built_for", wp.GAME_PROFILE)
        profile = ("Rogue Trader" if built_for == "rogue_trader"
                   else built_for)
        return f"{profile} · {count} ✓"

    def _reconcile_now(self, silent: bool = False) -> None:
        """§9.6: procura arquivos soltos em input//output/. Silencioso
        quando não há nada novo (abertura de projeto); o botão manual
        sempre responde."""
        project = self.main.project
        if project is None:
            return
        untracked = project.reconcile()["untracked"]
        if not untracked:
            if not silent:
                QMessageBox.information(
                    self, "Tudo em dia",
                    "Nenhum arquivo novo em input/ ou output/ — o "
                    "project.json já reconhece tudo.")
            return
        dialog = ReconcileDialog(project, untracked, self)
        dialog.exec()
        if self.main.project is not None:
            self.refresh(self.main.project)

    def _swap_glossary(self) -> None:
        project = self.main.project
        if project is None:
            return
        dialog = GlossaryChoiceDialog(REPO_ROOT / "glossary.json", self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            dialog.apply_to(project)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Glossário não importado", str(exc))
            return
        self.refresh(project)

    def _update_journeys(self, project: wp.Project) -> None:
        has_output = project.has_any_output()
        preserved_done = (project.track_status(wp.TRACK_PRESERVED)
                          .get("status") == wp.TRACK_STATUS_DONE)

        rules = {
            1: (True, ""),  # o Passo 1 do wizard ensina a adicionar o input
            2: (has_output,
                "Por quê? Não existe tradução para auditar.\n"
                "Corrigir & Auditar trabalha sobre os arquivos em output/."),
            3: (preserved_done,
                "Por quê? A trilha Preservada ainda não está concluída.\n"
                "Finalize ① Nova Tradução primeiro — ou adote uma "
                "tradução existente."),
            4: (has_output and project.has_input(),
                "Por quê? O Dia de Patch precisa de um EN arquivado e de "
                "uma tradução existente.\nConclua ① Nova Tradução primeiro "
                "— ou adote uma tradução existente."),
            5: (True, ""),
        }
        for num, (enabled, reason) in rules.items():
            btn = self.journey_buttons[num]
            btn.setEnabled(enabled)
            btn.setToolTip("" if enabled else reason)

    def _open_journey(self, num: int) -> None:
        if num == 1:
            project = self.main.project
            if project is None:
                return
            wizard = TranslationWizard(project, self.main, self)
            wizard.exec()
            # Reflete no dashboard: input adicionado no Passo 1 ou trilha
            # concluída no Passo 3.
            if self.main.project is not None:
                self.refresh(self.main.project)
            return
        if num == 2:
            project = self.main.project
            if project is None:
                return
            dialog = AuditDialog(project, self.main, self)
            dialog.exec()
            if self.main.project is not None:
                self.refresh(self.main.project)
            return
        if num == 3:
            project = self.main.project
            if project is None:
                return
            dialog = ReleaseDialog(project, self.main, self)
            dialog.exec()
            if self.main.project is not None:
                self.refresh(self.main.project)
            return
        if num == 4:
            project = self.main.project
            if project is None:
                return
            dialog = PatchDayDialog(project, self.main, self)
            dialog.exec()
            if self.main.project is not None:
                self.refresh(self.main.project)
            return
        if num == 5:
            project = self.main.project
            if project is None:
                return
            dialog = GlossaryDialog(project, self.main, self)
            dialog.exec()
            if self.main.project is not None:
                self.refresh(self.main.project)
            return

    def _edit_game_version(self) -> None:
        """Edição manual da versão do jogo (validação frouxa: dígitos+pontos)."""
        project = self.main.project
        if project is None:
            return
        current = project.state.get("game_version") or ""
        text, ok = QInputDialog.getText(
            self, "Versão do jogo",
            "Versão do jogo (ex.: 1.6.1.514).\n"
            "Usada nos nomes dos pacotes de release:",
            text=current)
        if not ok:
            return
        try:
            project.set_game_version(text)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Versão inválida", str(exc))
            return
        # §2: versão nova → oferece renomear os arquivos acompanhados
        # (ÚNICO rename do app; silencioso quando não há o que renomear).
        version = project.state.get("game_version")
        if version:
            has_files = any(
                p is not None and p.is_file() and not p.stem.endswith(
                    f"_{version}")
                for p in [project.input_path(),
                          project.track_path(wp.TRACK_PRESERVED),
                          project.track_path(wp.TRACK_FULL)])
            if has_files:
                answer = QMessageBox.question(
                    self, "Renomear arquivos para a nova versão?",
                    f"Renomear os arquivos acompanhados para a versão "
                    f"{version}?\n\n"
                    f"ex.: ptBR_preserved_…json → ptBR_preserved_"
                    f"{version}.json\n"
                    "Os nomes atuais continuam funcionando se você "
                    "preferir manter.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if answer == QMessageBox.Yes:
                    try:
                        renamed = project.rename_files_to_version(
                            version, include_input=True)
                    except wp.ProjectError as exc:
                        QMessageBox.warning(
                            self, "Não foi possível renomear", str(exc))
                        renamed = []
                    if renamed:
                        lines = [f"{old} → {new}" for old, new in renamed]
                        QMessageBox.information(
                            self, "Arquivos renomeados ✓", "\n".join(lines))
        self.refresh(project)


# ─────────────────────────────────────────────────────────────────────────────
# JORNADA ① NOVA TRADUÇÃO — wizard de 3 passos (§4.1, Fase 2)
# ─────────────────────────────────────────────────────────────────────────────

class PreflightWorker(QThread):
    """Roda o Pré-Voo (grátis) fora da thread da UI."""
    finished_ok = Signal(object)   # pf.PreflightResult
    failed = Signal(str)

    def __init__(self, input_path: Path, glossary_path: Optional[Path],
                 model: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._input = input_path
        self._glossary = glossary_path
        self._model = model

    def run(self) -> None:
        try:
            result = pf.run_preflight(self._input, self._glossary,
                                      model=self._model)
        except Exception as exc:  # nunca derrubar a UI por análise
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


class TranslationWizard(QDialog):
    """① Nova Tradução: Entrada → Pré-Voo (grátis) → Executar."""

    def __init__(self, project: wp.Project, main: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.main = main
        self.completed_run = False
        self.preflight: Optional[pf.PreflightResult] = None
        self._worker: Optional[PreflightWorker] = None
        self._proc: Optional[QProcess] = None
        self._buffer = ""
        self._stopped_by_user = False

        self.setWindowTitle("① Nova Tradução")
        self.setMinimumSize(860, 620)

        root = QVBoxLayout(self)
        self.steps = QStackedWidget()
        self.steps.addWidget(self._build_step_input())
        self.steps.addWidget(self._build_step_preflight())
        self.steps.addWidget(self._build_step_run())
        root.addWidget(self.steps, 1)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("← Voltar")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_next = QPushButton("Avançar →")
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self._on_close)
        self.btn_close.setVisible(False)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_close)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)

        self._refresh_input_status()
        self._update_nav()

    # ── Passo 1: Entrada ────────────────────────────────────────────────

    def _build_step_input(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        title = QLabel("Passo 1 de 3 — Entrada")
        title.setObjectName("title")
        layout.addWidget(title)

        self.input_status = QLabel("—")
        self.input_status.setObjectName("cardBody")
        self.input_status.setWordWrap(True)
        layout.addWidget(self.input_status)

        self.btn_add_input = QPushButton("Adicionar enGB.json…")
        self.btn_add_input.setToolTip(
            "Copia o arquivo de localização do jogo para input/ do projeto. "
            "Encontre-o em …\\WH40KRT_Data\\StreamingAssets\\Localization")
        self.btn_add_input.clicked.connect(self._pick_input)
        layout.addWidget(self.btn_add_input, 0, Qt.AlignLeft)

        box = QGroupBox("Trilha")
        box_layout = QVBoxLayout(box)
        radio_pres = QRadioButton(
            "Preservada (recomendada) — nomes de mecânica e da wiki "
            "(armas, talentos, atributos) ficam em inglês; a narrativa é "
            "traduzida.")
        radio_pres.setChecked(True)
        radio_full = QRadioButton("Completa (Full)")
        radio_full.setEnabled(False)
        radio_full.setToolTip(
            "A trilha Completa é derivada GRATUITAMENTE da Preservada.")
        note = QLabel(
            "A trilha Completa (100% PT) é gerada DE GRAÇA a partir da "
            "Preservada na jornada ③ Finalizar & Publicar — sem custo de API.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        box_layout.addWidget(radio_pres)
        box_layout.addWidget(radio_full)
        box_layout.addWidget(note)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _refresh_input_status(self) -> None:
        if self.project.has_input():
            info = self.project.state["input"]
            version = self.project.state.get("game_version")
            lines = [
                f"✓ {Path(info['file']).name} · "
                f"{info['strings']:,} strings".replace(",", ".")
            ]
            if version:
                lines.append(f"jogo v{version}")
            self.input_status.setText("\n".join(lines))
            self.btn_add_input.setText("Substituir enGB.json…")
        else:
            self.input_status.setText(
                "✗ Nenhum arquivo de entrada.\n"
                "Clique em 'Adicionar enGB.json…' e escolha o arquivo de "
                "localização do jogo (ele será COPIADO para input/).")
        self._update_nav()

    def _pick_input(self) -> None:
        src, _ = QFileDialog.getOpenFileName(
            self, "Escolha o enGB.json do jogo", "", "JSON (*.json)")
        if not src:
            return
        try:
            self.project.set_input(Path(src))
        except (wp.ProjectError, wp.LocalizationFormatError) as exc:
            QMessageBox.warning(self, "Arquivo não adicionado", str(exc))
            return
        self._refresh_input_status()

    # ── Passo 2: Pré-Voo ────────────────────────────────────────────────

    def _build_step_preflight(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        title = QLabel("Passo 2 de 3 — Pré-Voo (grátis)")
        title.setObjectName("title")
        layout.addWidget(title)
        hint = QLabel("Análise local do arquivo — nenhuma chamada de API, "
                      "nenhum custo.")
        hint.setObjectName("subtitle")
        layout.addWidget(hint)

        self.btn_preflight = QPushButton("Rodar Pré-Voo")
        self.btn_preflight.setObjectName("primary")
        self.btn_preflight.clicked.connect(self._run_preflight)
        layout.addWidget(self.btn_preflight, 0, Qt.AlignLeft)

        self.pf_summary = QLabel("Pré-Voo ainda não executado.")
        self.pf_summary.setObjectName("cardBody")
        self.pf_summary.setWordWrap(True)
        layout.addWidget(self.pf_summary)

        self.pf_coverage = QLabel("")
        self.pf_coverage.setWordWrap(True)
        layout.addWidget(self.pf_coverage)

        cand_box = QGroupBox("Termos candidatos (não estão no glossário — "
                             "revisão na jornada ⑤)")
        cand_layout = QVBoxLayout(cand_box)
        self.candidates_list = QListWidget()
        self.candidates_list.setMaximumHeight(110)
        cand_layout.addWidget(self.candidates_list)
        layout.addWidget(cand_box)

        model_box = QGroupBox("Modelo e estimativa")
        model_layout = QGridLayout(model_box)
        model_layout.addWidget(QLabel("Modelo:"), 0, 0)
        self.model_combo = QComboBox()
        for mid, label, provider in pf.list_models():
            self.model_combo.addItem(f"{mid} — {label}", mid)
        default_idx = self.model_combo.findData(
            st.default_model() or "deepseek-v4-flash")
        if default_idx >= 0:
            self.model_combo.setCurrentIndex(default_idx)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_layout.addWidget(self.model_combo, 0, 1, 1, 2)
        self.est_label = QLabel("—")
        self.est_label.setObjectName("cardBody")
        self.est_label.setWordWrap(True)
        model_layout.addWidget(self.est_label, 1, 0, 1, 3)
        layout.addWidget(model_box)

        key_box = QGroupBox("Chave de API (necessária para o Passo 3)")
        key_layout = QGridLayout(key_box)
        self.key_status = QLabel("—")
        self.key_status.setWordWrap(True)
        key_layout.addWidget(self.key_status, 0, 0, 1, 2)
        key_layout.addWidget(QLabel("Chave:"), 1, 0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText(
            "Cole a chave, ou deixe vazio para usar ambiente/cofre")
        self.key_edit.textChanged.connect(self._update_nav)
        key_layout.addWidget(self.key_edit, 1, 1)
        self.save_key_cb = QCheckBox("Salvar no cofre do Windows")
        self.save_key_cb.setEnabled(pf.keyring_available())
        if not pf.keyring_available():
            self.save_key_cb.setToolTip(
                "Cofre indisponível (pacote 'keyring' não instalado) — a "
                "chave ficará apenas nesta sessão, sem ser gravada em disco.")
        key_layout.addWidget(self.save_key_cb, 2, 0, 1, 2)
        layout.addWidget(key_box)
        layout.addStretch(1)
        return page

    def _current_model(self) -> str:
        return self.model_combo.currentData() or "deepseek-v4-flash"

    def _run_preflight(self) -> None:
        input_path = self.project.input_path()
        if input_path is None:
            return
        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        self.btn_preflight.setEnabled(False)
        self.btn_preflight.setText("Analisando…")
        self._worker = PreflightWorker(input_path, glossary,
                                       self._current_model(), self)
        self._worker.finished_ok.connect(self._fill_preflight)
        self._worker.failed.connect(self._on_preflight_error)
        self._worker.start()

    def _fill_preflight(self, result: pf.PreflightResult) -> None:
        """Preenche a UI com o resultado (método separado para o smoke test)."""
        self.preflight = result
        self.btn_preflight.setEnabled(True)
        self.btn_preflight.setText("Rodar Pré-Voo novamente")

        self.pf_summary.setText(
            f"{result.total:,} strings no total · "
            f"{result.free_total:,} grátis "
            f"({result.skip_placeholder} placeholders, {result.skip_eula} "
            f"EULA, {result.exact_preserved} termos exatos mantidos em EN) · "
            f"{result.inline_locked} com termos travados inline · "
            f"{result.api_bound:,} vão para a API".replace(",", "."))

        if result.coverage is None:
            self.pf_coverage.setText("Cobertura do glossário: —")
            self.pf_coverage.setObjectName("")
        elif result.coverage >= pf.COVERAGE_OK:
            self.pf_coverage.setText(
                f"✓ Cobertura do glossário: {result.coverage * 100:.0f}% "
                f"das strings da API contêm termos conhecidos")
            self.pf_coverage.setObjectName("ok")
        elif result.coverage >= pf.COVERAGE_LOW:
            self.pf_coverage.setText(
                f"⚠ Cobertura do glossário: {result.coverage * 100:.0f}% — "
                "um pouco baixa. Conteúdo novo (DLC)? Revise os termos "
                "candidatos abaixo antes de traduzir.")
            self.pf_coverage.setObjectName("warn")
        else:
            self.pf_coverage.setText(
                f"⚠ Cobertura do glossário: {result.coverage * 100:.0f}% — "
                "MUITO baixa. Este input não parece ser do Rogue Trader; o "
                "glossário pode forçar termos errados. Confira o arquivo.")
            self.pf_coverage.setObjectName("err")
        self.pf_coverage.style().unpolish(self.pf_coverage)
        self.pf_coverage.style().polish(self.pf_coverage)

        self.candidates_list.clear()
        if result.candidates:
            for term, count in result.candidates:
                self.candidates_list.addItem(f"{term}  ·  {count}×")
            self.candidates_list.addItem(
                f"— {len(result.candidates)} termos novos encontrados · "
                "revise em ⑤ Glossário")
        else:
            self.candidates_list.addItem("Nenhum candidato repetido encontrado.")

        self._refresh_estimate()
        self._update_key_status()
        self._update_nav()

    def _on_preflight_error(self, message: str) -> None:
        self.btn_preflight.setEnabled(True)
        self.btn_preflight.setText("Rodar Pré-Voo")
        QMessageBox.warning(self, "Falha no Pré-Voo",
                            f"Não foi possível analisar o arquivo:\n{message}")

    def _on_model_changed(self) -> None:
        if self.preflight is not None:
            pf.recalc_estimate(self.preflight, self._current_model())
            self._refresh_estimate()
        self._update_key_status()
        self._update_nav()

    def _refresh_estimate(self) -> None:
        r = self.preflight
        if r is None:
            return
        self.est_label.setText(
            f"~{r.input_tokens_est:,} tokens de entrada / "
            f"~{r.output_tokens_est:,} de saída estimados".replace(",", ".") +
            "  (heurística: ~4 caracteres por token)\n"
            f"≈ {r.batches_est} lotes · {r.workers} workers em paralelo · "
            f"{r.duration_hint}\n"
            f"Custo: {r.cost_hint}")

    def _update_key_status(self) -> None:
        provider = pf.provider_for_model(self._current_model())
        typed = self.key_edit.text().strip()
        if typed:
            self.key_status.setText(
                f"✓ Chave digitada (provedor {provider or 'desconhecido'})")
            self.key_status.setObjectName("ok")
        elif pf.env_api_key():
            self.key_status.setText(
                "✓ Chave encontrada nas variáveis de ambiente")
            self.key_status.setObjectName("ok")
        elif pf.key_store_get(provider):
            self.key_status.setText(
                f"✓ Chave salva no cofre do Windows ({provider})")
            self.key_status.setObjectName("ok")
        else:
            self.key_status.setText(
                "✗ Nenhuma chave encontrada — cole a chave do provedor "
                f"{provider or 'escolhido'} ou configure uma variável de "
                "ambiente (DEEPSEEK_API_KEY etc.).")
            self.key_status.setObjectName("err")
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)

    def _key_ready(self) -> bool:
        provider = pf.provider_for_model(self._current_model())
        key, _source = pf.resolve_api_key(provider, self.key_edit.text())
        return bool(key)

    # ── Passo 3: Executar ───────────────────────────────────────────────

    def _build_step_run(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        title = QLabel("Passo 3 de 3 — Executar")
        title.setObjectName("title")
        layout.addWidget(title)

        self.cmd_preview = QLabel("")
        self.cmd_preview.setObjectName("subtitle")
        self.cmd_preview.setWordWrap(True)
        layout.addWidget(self.cmd_preview)

        honesty = QLabel("O progresso é salvo a cada lote — parar e "
                         "continuar retoma de onde parou (--resume).")
        honesty.setObjectName("subtitle")
        honesty.setWordWrap(True)
        layout.addWidget(honesty)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        counters = QHBoxLayout()
        self.cnt_done = QLabel("traduzidas: 0")
        self.cnt_free = QLabel("grátis: —")
        self.cnt_fail = QLabel("falhas: —")
        self.cnt_eta = QLabel("ETA: —")
        for lbl in (self.cnt_done, self.cnt_free, self.cnt_fail,
                    self.cnt_eta):
            lbl.setObjectName("cardBody")
            counters.addWidget(lbl)
        counters.addStretch(1)
        layout.addLayout(counters)

        self.log_box = QGroupBox("Log detalhado")
        self.log_box.setCheckable(True)
        self.log_box.setChecked(False)
        log_layout = QVBoxLayout(self.log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setVisible(False)
        log_layout.addWidget(self.log_view)
        self.log_box.toggled.connect(self.log_view.setVisible)
        layout.addWidget(self.log_box, 1)

        run_buttons = QHBoxLayout()
        self.btn_start = QPushButton("▶ Iniciar tradução")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self._start_run)
        self.btn_stop = QPushButton("⏸ Parar (salva o progresso)")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_run)
        self.btn_continue = QPushButton("⏵ Continuar de onde parou")
        self.btn_continue.setObjectName("primary")
        self.btn_continue.setVisible(False)
        self.btn_continue.clicked.connect(self._start_run)
        run_buttons.addWidget(self.btn_start)
        run_buttons.addWidget(self.btn_stop)
        run_buttons.addWidget(self.btn_continue)
        run_buttons.addStretch(1)
        layout.addLayout(run_buttons)
        return page

    def _prepare_run_page(self) -> None:
        model = self._current_model()
        output = self.project.track_target(wp.TRACK_PRESERVED)
        self.cmd_preview.setText(
            f"tradutor.py --mode preserve --resume --model {model}\n"
            f"entrada: {self.project.input_path()}\n"
            f"saída:   {output}")

    def _build_command(self) -> tuple[list[str], dict[str, str]]:
        model = self._current_model()
        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        args = [
            str(REPO_ROOT / "tradutor.py"),
            "-i", str(self.project.input_path()),
            "-o", str(self.project.track_target(wp.TRACK_PRESERVED)),
            "--mode", "preserve",
            "--resume",
            "--preserve-map",
            str(self.project.root / "patches" / "preserve_map.json"),
            "--model", model,
        ]
        # Workers/save_every do perfil EFETIVO (overrides das Configurações);
        # sem flags o engine auto-resolveria só pelos padrões de código.
        args += au._profile_run_flags(model)
        if glossary is not None:
            args += ["-g", str(glossary)]
        # Pre-Scan cache: pula a re-classificação de preservados/skips/EULA
        # no engine (padrão da GUI antiga; stale/modo divergente = ignorado).
        try:
            pf.write_prescan_cache(
                self.project.input_path(), glossary,
                self.project.root / "prescan_cache.json", mode="preserve")
            args += ["--prescan-cache",
                     str(self.project.root / "prescan_cache.json")]
        except Exception:
            pass  # cache é otimização; falha não impede o run
        provider = pf.provider_for_model(model)
        key, _source = pf.resolve_api_key(provider, self.key_edit.text())
        env = pf.subprocess_env(model, key)
        return args, env

    def _start_run(self) -> None:
        if self._proc is not None:
            return
        provider = pf.provider_for_model(self._current_model())
        key, _source = pf.resolve_api_key(provider, self.key_edit.text())
        if not key:
            QMessageBox.warning(
                self, "Chave de API ausente",
                "Nenhuma chave de API disponível (campo, ambiente ou cofre). "
                "Volte ao Passo 2 e configure a chave.")
            return
        # Persiste no cofre se o usuário pediu (nunca em plaintext).
        if self.save_key_cb.isChecked() and self.key_edit.text().strip():
            ok, detail = pf.key_store_set_ex(provider, key)
            if ok:
                self._append_log("🔐 Chave salva no cofre do Windows.")
            else:
                self._append_log(f"⚠ Chave NÃO persistida ({detail}) — "
                                 "usada só nesta sessão.")

        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        if glossary is None:
            QMessageBox.warning(
                self, "Glossário não encontrado",
                "glossary.json não foi encontrado na pasta do app nem do "
                "projeto. A tradução sem glossário não é recomendada.")
            return

        args, env = self._build_command()
        self._stopped_by_user = False
        self._buffer = ""
        self.btn_start.setVisible(False)
        self.btn_continue.setVisible(False)
        self.btn_stop.setEnabled(True)
        self.cnt_done.setText("traduzidas: 0")
        self.cnt_fail.setText("falhas: —")
        self.cnt_eta.setText("ETA: —")
        self.progress.setValue(0)

        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)

        self._proc = QProcess(self)
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(args)
        self._proc.setWorkingDirectory(str(REPO_ROOT))
        self._proc.setProcessEnvironment(qenv)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_proc_output)
        self._proc.finished.connect(self._on_proc_finished)
        self._append_log("$ " + " ".join(args[:2]) + " …")
        self._proc.start()

    def _stop_run(self) -> None:
        if self._proc is None:
            return
        self._stopped_by_user = True
        self._append_log("⏸ Parando — o progresso já salvo será mantido.")
        self._proc.terminate()
        QTimer.singleShot(3000, self._kill_if_running)
        self.btn_stop.setEnabled(False)

    def _kill_if_running(self) -> None:
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def _on_proc_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buffer += chunk
        parts = self._buffer.replace("\r", "\n").split("\n")
        self._buffer = parts.pop()
        for line in parts:
            self._handle_engine_line(line)

    def _handle_engine_line(self, line: str) -> None:
        if not line.strip():
            return
        self._append_log(line)
        parsed = pf.parse_engine_line(line)
        if not parsed:
            return
        if parsed["kind"] == "plan":
            self.progress.setRange(0, max(1, parsed["pending"]))
            self.cnt_free.setText(
                f"grátis: {parsed['exact'] + parsed['skipped']}")
        elif parsed["kind"] == "progress":
            if parsed["total"] != self.progress.maximum():
                self.progress.setRange(0, max(1, parsed["total"]))
            self.progress.setValue(parsed["done"])
            self.cnt_done.setText(f"traduzidas: {parsed['done']}")
            if parsed["eta"]:
                self.cnt_eta.setText(f"ETA: {parsed['eta']}")
        elif parsed["kind"] == "final":
            self.cnt_done.setText(f"traduzidas: {parsed['success']}")
            self.cnt_fail.setText(f"falhas: {parsed['failed']}")

    def _on_proc_finished(self, exit_code: int, _status) -> None:
        # Processa o resto do buffer antes de concluir.
        if self._buffer.strip():
            self._handle_engine_line(self._buffer)
        self._buffer = ""
        self._proc = None
        self.btn_stop.setEnabled(False)

        if self._stopped_by_user:
            self.btn_continue.setVisible(True)
            self._append_log("⏸ Parado pelo usuário. Use 'Continuar' para "
                             "retomar de onde parou.")
            return

        if exit_code == 0:
            self._finish_success()
        else:
            self.btn_start.setVisible(True)
            tail = self._log_tail()
            QMessageBox.critical(
                self, "A tradução falhou",
                f"O motor encerrou com código {exit_code}.\n"
                f"O projeto não foi alterado.\n\nÚltimas linhas do log:\n{tail}")

    def _finish_success(self) -> None:
        output = self.project.track_target(wp.TRACK_PRESERVED)
        try:
            summary = pf.summarize_output(output)
            # Registra o caminho exato do master (convenção versionada §2).
            self.project.set_track_file(wp.TRACK_PRESERVED, output)
            self.project.update_track(
                wp.TRACK_PRESERVED, wp.TRACK_STATUS_DONE,
                translated=summary["translated"],
                skipped_free=summary["skipped_free"])
        except (wp.ProjectError, wp.LocalizationFormatError) as exc:
            QMessageBox.warning(
                self, "Tradução concluída, mas…",
                f"O motor terminou, porém não foi possível atualizar o "
                f"projeto:\n{exc}")
            return
        self.completed_run = True
        self.progress.setValue(self.progress.maximum())
        QMessageBox.information(
            self, "Trilha Preservada concluída ✓",
            f"{summary['translated']:,} strings traduzidas · "
            f"{summary['skipped_free']:,} grátis · "
            f"{summary['failed']} falhas".replace(",", ".") +
            "\n\nPróximo passo: jornada ② Corrigir & Auditar — revise "
            "falhas e suspeitas antes de publicar (a release exige auditoria).")

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _log_tail(self, max_chars: int = 2000) -> str:
        text = self.log_view.toPlainText()
        return text[-max_chars:] if len(text) > max_chars else text

    # ── Navegação ───────────────────────────────────────────────────────

    def _go_back(self) -> None:
        idx = self.steps.currentIndex()
        if idx > 0:
            self.steps.setCurrentIndex(idx - 1)
        self._update_nav()

    def _go_next(self) -> None:
        idx = self.steps.currentIndex()
        if idx == 1 and self.preflight is None:
            self._run_preflight()
            return
        if idx < 2:
            self.steps.setCurrentIndex(idx + 1)
            if self.steps.currentIndex() == 2:
                self._prepare_run_page()
        self._update_nav()

    def _update_nav(self) -> None:
        idx = self.steps.currentIndex()
        self.btn_back.setEnabled(idx > 0)
        running = self._proc is not None
        self.btn_close.setVisible(idx == 2 and not running)
        self.btn_next.setVisible(idx < 2)

        if idx == 0:
            ok = self.project.has_input()
            self.btn_next.setEnabled(ok)
            self.btn_next.setToolTip(
                "" if ok else "Por quê? Adicione o enGB.json do jogo primeiro.")
        elif idx == 1:
            ok = self.preflight is not None and self._key_ready()
            self.btn_next.setEnabled(ok)
            reasons = []
            if self.preflight is None:
                reasons.append("rode o Pré-Voo")
            if not self._key_ready():
                reasons.append("configure a chave de API")
            self.btn_next.setToolTip(
                "" if ok else "Por quê? Falta: " + " e ".join(reasons) + ".")

    def _on_close(self) -> None:
        if self._proc is not None:
            answer = QMessageBox.question(
                self, "Tradução em andamento",
                "A tradução está rodando. Parar agora?\n"
                "O progresso salvo será mantido.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._stop_run()
            QTimer.singleShot(500, self.accept)
            return
        self.accept()

    def closeEvent(self, event) -> None:
        if self._proc is not None:
            event.ignore()
            self._on_close()
            return
        event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# JORNADA ② CORRIGIR & AUDITAR — auditoria + retradução + edição (§4.2, Fase 4)
# ─────────────────────────────────────────────────────────────────────────────

class AuditWorker(QThread):
    """Roda a auditoria (grátis, import direto) fora da thread da UI."""
    finished_ok = Signal(object)   # report dict do au.run_audit
    failed = Signal(str)

    def __init__(self, project: wp.Project, track: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._project = project
        self._track = track

    def run(self) -> None:
        try:
            report = au.run_audit(self._project, self._track)
        except Exception as exc:  # nunca derrubar a UI
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(report)


class EditStringDialog(QDialog):
    """Edição manual de uma string (EN somente leitura, PT editável)."""

    def __init__(self, uuid: str, en: str, pt: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Editar string — {uuid[:12]}…")
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Original (EN):"))
        en_view = QPlainTextEdit(en)
        en_view.setReadOnly(True)
        layout.addWidget(en_view)
        layout.addWidget(QLabel("Tradução (PT) — edite:"))
        self.pt_edit = QPlainTextEdit(pt)
        layout.addWidget(self.pt_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Salvar (com backup)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def new_text(self) -> str:
        return self.pt_edit.toPlainText()


class AuditDialog(QDialog):
    """② Corrigir & Auditar: auditoria grátis, tabela EN×PT, retradução
    dos selecionados e edição manual — tudo com backup."""

    def __init__(self, project: wp.Project, main: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.main = main
        self.report: Optional[dict] = None
        self._worker: Optional[AuditWorker] = None
        self._proc: Optional[QProcess] = None
        self._buffer = ""

        self.setWindowTitle("② Corrigir & Auditar")
        self.setMinimumSize(900, 640)

        layout = QVBoxLayout(self)
        title = QLabel("Corrigir & Auditar")
        title.setObjectName("title")
        layout.addWidget(title)
        hint = QLabel(
            "A auditoria é grátis e local. A release (③) só sai com auditoria "
            "em dia — falhas e suspeitas pendentes exigem confirmação.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Linha de controle
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Trilha:"))
        self.track_combo = QComboBox()
        for track in (wp.TRACK_PRESERVED, wp.TRACK_FULL):
            tp = project.track_path(track)
            if tp is not None and tp.is_file():
                self.track_combo.addItem(rl.TRACK_NAMES_PT[track], track)
        controls.addWidget(self.track_combo)
        self.btn_audit = QPushButton("🔍 Rodar auditoria (grátis)")
        self.btn_audit.setObjectName("primary")
        self.btn_audit.clicked.connect(self._run_audit)
        controls.addWidget(self.btn_audit)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.counts_label = QLabel("Auditoria ainda não executada nesta sessão.")
        self.counts_label.setObjectName("cardBody")
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)

        # Filtro + seleção
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Mostrar:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Todas as categorias", None)
        for cat in au.CATEGORIES:
            self.filter_combo.addItem(au.CATEGORY_NAMES_PT[cat], cat)
        self.filter_combo.currentIndexChanged.connect(self._fill_table)
        filter_row.addWidget(self.filter_combo)
        btn_all = QPushButton("Selecionar visíveis")
        btn_all.clicked.connect(lambda: self._set_visible_check(True))
        btn_none = QPushButton("Limpar seleção")
        btn_none.clicked.connect(lambda: self._set_visible_check(False))
        filter_row.addWidget(btn_all)
        filter_row.addWidget(btn_none)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        # Tabela EN × PT
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["✓", "UUID", "EN (original)", "PT (atual)", "Motivo"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._edit_row)
        layout.addWidget(self.table, 1)

        # Retradução (API)
        retry_box = QGroupBox("Retraduzir selecionados (usa API — só os "
                              "UUIDs escolhidos)")
        retry_layout = QGridLayout(retry_box)
        retry_layout.addWidget(QLabel("Modelo:"), 0, 0)
        self.model_combo = QComboBox()
        for mid, label, _provider in pf.list_models():
            self.model_combo.addItem(f"{mid} — {label}", mid)
        idx = self.model_combo.findData(
            st.default_model() or "deepseek-v4-flash")
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        retry_layout.addWidget(self.model_combo, 0, 1)
        retry_layout.addWidget(QLabel("Chave:"), 0, 2)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("vazio = ambiente/cofre")
        retry_layout.addWidget(self.key_edit, 0, 3)

        self.retry_progress = QProgressBar()
        self.retry_progress.setRange(0, 100)
        self.retry_progress.setValue(0)
        retry_layout.addWidget(self.retry_progress, 1, 0, 1, 4)

        self.btn_retry = QPushButton("🔁 Retraduzir selecionados")
        self.btn_retry.setObjectName("primary")
        self.btn_retry.clicked.connect(self._retry_selected)
        retry_layout.addWidget(self.btn_retry, 2, 0, 1, 2)
        self.retry_status = QLabel(
            "O progresso é salvo a cada lote; ao concluir, a auditoria roda "
            "de novo para você ver a melhora.")
        self.retry_status.setObjectName("subtitle")
        self.retry_status.setWordWrap(True)
        retry_layout.addWidget(self.retry_status, 2, 2, 1, 2)

        self.retry_log = QPlainTextEdit()
        self.retry_log.setObjectName("log")
        self.retry_log.setReadOnly(True)
        self.retry_log.setMaximumHeight(90)
        self.retry_log.setVisible(False)
        retry_layout.addWidget(self.retry_log, 3, 0, 1, 4)
        layout.addWidget(retry_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self._on_close)
        layout.addWidget(buttons)

        if self.track_combo.count() == 0:
            self.btn_audit.setEnabled(False)
            self.counts_label.setText(
                "Nenhum output em output/ — conclua ① Nova Tradução primeiro.")

    # ── auditoria ───────────────────────────────────────────────────────

    def _current_track(self) -> str:
        return self.track_combo.currentData() or wp.TRACK_PRESERVED

    def _run_audit(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_audit.setEnabled(False)
        self.btn_audit.setText("Auditando…")
        self._worker = AuditWorker(self.project, self._current_track(), self)
        self._worker.finished_ok.connect(self._fill_report)
        self._worker.failed.connect(self._on_audit_error)
        self._worker.start()

    def _fill_report(self, report: dict) -> None:
        """Preenche contagens + tabela (método separado para o smoke test)."""
        self.report = report
        self.btn_audit.setEnabled(True)
        self.btn_audit.setText("🔍 Rodar auditoria novamente")
        c = report["counts"]
        self.counts_label.setText(
            f"{report['total']:,} strings analisadas · "
            f"{c['failed']} falhas · {c['identical']} idênticas · "
            f"{c['suspect']} suspeitas".replace(",", ".") +
            "\nDuplo-clique numa linha para editar manualmente (com backup).")
        self._fill_table()
        self.main.dashboard.refresh(self.project)

    def _on_audit_error(self, message: str) -> None:
        self.btn_audit.setEnabled(True)
        self.btn_audit.setText("🔍 Rodar auditoria (grátis)")
        QMessageBox.warning(self, "Falha na auditoria", message)

    def _fill_table(self) -> None:
        if self.report is None:
            return
        current_filter = self.filter_combo.currentData()
        rows = [r for r in self.report["rows"]
                if current_filter is None or r["category"] == current_filter]
        self.table.setRowCount(0)
        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, row_data["uuid"])
            self.table.setItem(row, 0, check)

            self.table.setItem(row, 1, QTableWidgetItem(row_data["uuid"][:13]))
            en_item = QTableWidgetItem(row_data["en"][:300])
            en_item.setToolTip(row_data["en"])
            self.table.setItem(row, 2, en_item)
            pt_item = QTableWidgetItem(row_data["pt"][:300])
            pt_item.setToolTip(row_data["pt"])
            self.table.setItem(row, 3, pt_item)
            cat = au.CATEGORY_NAMES_PT[row_data["category"]].split(" (")[0]
            self.table.setItem(
                row, 4, QTableWidgetItem(f"{cat} · {row_data['reason']}"))

    def _set_visible_check(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def _selected_uuids(self) -> list[str]:
        uuids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                uuids.append(item.data(Qt.UserRole))
        return uuids

    # ── edição manual ───────────────────────────────────────────────────

    def _edit_row(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self.report is None:
            return
        uuid = self.table.item(row, 0).data(Qt.UserRole)
        row_data = next((r for r in self.report["rows"] if r["uuid"] == uuid),
                        None)
        if row_data is None:
            return
        dialog = EditStringDialog(uuid, row_data["en"], row_data["pt"], self)
        if dialog.exec() != QDialog.Accepted:
            return
        new_text = dialog.new_text()
        if new_text == row_data["pt"]:
            return
        try:
            result = au.merge_with_backup(
                self.project, self._current_track(), {uuid: new_text})
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível salvar a edição",
                                str(exc))
            return
        # Atualiza a linha na tabela e remove-a do relatório (corrigida).
        self.table.item(row, 3).setText(new_text[:300])
        self.table.item(row, 3).setToolTip(new_text)
        self.report["rows"] = [r for r in self.report["rows"]
                               if r["uuid"] != uuid]
        self.report["counts"][row_data["category"]] -= 1
        c = self.report["counts"]
        self.counts_label.setText(
            f"✓ Edição salva (backup em backups/). "
            f"Restam: {c['failed']} falhas · {c['identical']} idênticas · "
            f"{c['suspect']} suspeitas — rode a auditoria de novo para "
            "atualizar o gate da release.")
        self.main.dashboard.refresh(self.project)

    # ── retradução ──────────────────────────────────────────────────────

    def _retry_selected(self) -> None:
        if self._proc is not None:
            return
        uuids = self._selected_uuids()
        if not uuids:
            QMessageBox.information(
                self, "Nada selecionado",
                "Marque ao menos uma linha com ✓ para retraduzir.")
            return
        model = self.model_combo.currentData() or "deepseek-v4-flash"
        provider = pf.provider_for_model(model)
        key, _source = pf.resolve_api_key(provider, self.key_edit.text())
        if not key:
            QMessageBox.warning(
                self, "Chave de API ausente",
                "Configure a chave (campo, variável de ambiente ou cofre do "
                "Windows) para retraduzir.")
            return
        try:
            retry_file = au.write_retry_uuids(self.project, uuids)
            mark = au.mark_for_retry(self.project, self._current_track(),
                                     uuids)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível preparar a "
                                "retradução", str(exc))
            return
        self._append_retry_log(
            f"💾 Backup: {mark['backup'].name} · "
            f"{mark['marked']} UUIDs marcados para retradução")

        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        args = au.build_retry_args(REPO_ROOT / "tradutor.py", self.project,
                                   self._current_track(), retry_file, model,
                                   glossary)
        env = pf.subprocess_env(model, key)
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)

        self._buffer = ""
        self.retry_progress.setValue(0)
        self.btn_retry.setEnabled(False)
        self.retry_log.setVisible(True)
        self._proc = QProcess(self)
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(args)
        self._proc.setWorkingDirectory(str(REPO_ROOT))
        self._proc.setProcessEnvironment(qenv)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_retry_output)
        self._proc.finished.connect(self._on_retry_finished)
        self._append_retry_log("$ tradutor.py --retranslate-map …")
        self._proc.start()

    def _on_retry_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buffer += chunk
        parts = self._buffer.replace("\r", "\n").split("\n")
        self._buffer = parts.pop()
        for line in parts:
            if not line.strip():
                continue
            self._append_retry_log(line)
            parsed = pf.parse_engine_line(line)
            if parsed and parsed["kind"] == "plan":
                self.retry_progress.setRange(0, max(1, parsed["pending"]))
            elif parsed and parsed["kind"] == "progress":
                self.retry_progress.setRange(0, max(1, parsed["total"]))
                self.retry_progress.setValue(parsed["done"])

    def _on_retry_finished(self, exit_code: int, _status) -> None:
        if self._buffer.strip():
            self._append_retry_log(self._buffer)
        self._buffer = ""
        self._proc = None
        self.btn_retry.setEnabled(True)
        if exit_code != 0:
            tail = self.retry_log.toPlainText()[-1500:]
            QMessageBox.critical(
                self, "A retradução falhou",
                f"O motor encerrou com código {exit_code}. O backup está em "
                f"backups/.\n\nÚltimas linhas do log:\n{tail}")
            return
        self.retry_progress.setValue(self.retry_progress.maximum())
        QMessageBox.information(
            self, "Retradução concluída ✓",
            "Os UUIDs selecionados foram retraduzidos e mesclados.\n"
            "Rodando a auditoria novamente para atualizar os números…")
        self._run_audit()

    def _append_retry_log(self, text: str) -> None:
        self.retry_log.appendPlainText(text)

    def _on_close(self) -> None:
        if self._proc is not None:
            answer = QMessageBox.question(
                self, "Retradução em andamento",
                "A retradução está rodando. Parar agora? O progresso salvo "
                "será mantido.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._proc.terminate()
        self.reject()


# ─────────────────────────────────────────────────────────────────────────────
# JORNADA ③ FINALIZAR & PUBLICAR — fullize grátis + pacote de mod (§4.3)
# ─────────────────────────────────────────────────────────────────────────────

class ReleaseDialog(QDialog):
    """③ Finalizar & Publicar: fullize (grátis) e export do pacote de mod."""

    def __init__(self, project: wp.Project, main: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.main = main
        self._proc: Optional[QProcess] = None
        self._buffer = ""

        self.setWindowTitle("③ Finalizar & Publicar")
        self.setMinimumSize(780, 560)

        layout = QVBoxLayout(self)
        title = QLabel("Finalizar & Publicar")
        title.setObjectName("title")
        layout.addWidget(title)

        layout.addWidget(self._build_fullize_card())
        layout.addWidget(self._build_package_card())
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self._on_close)
        layout.addWidget(buttons)

        self._refresh_state()

    # ── Card 1: Fullizar (grátis) ───────────────────────────────────────

    def _build_fullize_card(self) -> QGroupBox:
        box = QGroupBox("Fullizar — trilha Completa 100% PT (GRÁTIS, sem API)")
        layout = QVBoxLayout(box)

        expl = QLabel(
            "Transforma a trilha Preservada em 100% português substituindo "
            "os termos de mecânica pelos equivalentes do glossário. "
            "Nenhuma chamada de API, nenhum custo.")
        expl.setObjectName("subtitle")
        expl.setWordWrap(True)
        layout.addWidget(expl)

        self.fullize_status = QLabel("—")
        self.fullize_status.setObjectName("cardBody")
        self.fullize_status.setWordWrap(True)
        layout.addWidget(self.fullize_status)

        row = QHBoxLayout()
        self.btn_fullize = QPushButton("⚡ Fullizar agora (grátis)")
        self.btn_fullize.setObjectName("primary")
        self.btn_fullize.clicked.connect(self._run_fullize)
        row.addWidget(self.btn_fullize)
        row.addStretch(1)
        layout.addLayout(row)

        self.fullize_log_box = QGroupBox("Log do fullize")
        self.fullize_log_box.setCheckable(True)
        self.fullize_log_box.setChecked(False)
        log_layout = QVBoxLayout(self.fullize_log_box)
        self.fullize_log = QPlainTextEdit()
        self.fullize_log.setObjectName("log")
        self.fullize_log.setReadOnly(True)
        self.fullize_log.setMaximumHeight(120)
        self.fullize_log.setVisible(False)
        log_layout.addWidget(self.fullize_log)
        self.fullize_log_box.toggled.connect(self.fullize_log.setVisible)
        layout.addWidget(self.fullize_log_box)
        return box

    def _run_fullize(self) -> None:
        if self._proc is not None:
            return
        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        if glossary is None:
            QMessageBox.warning(
                self, "Glossário não encontrado",
                "glossary.json não foi encontrado — o fullize precisa dele "
                "para substituir os termos.")
            return
        args = rl.build_fullize_args(REPO_ROOT / "tradutor.py",
                                     self.project, glossary)
        self._buffer = ""
        self.btn_fullize.setEnabled(False)
        self.btn_fullize.setText("Fullizando…")
        self.fullize_log.clear()

        self._proc = QProcess(self)
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(args)
        self._proc.setWorkingDirectory(str(REPO_ROOT))
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_fullize_output)
        self._proc.finished.connect(self._on_fullize_finished)
        self.fullize_log.appendPlainText("$ tradutor.py --fullize …")
        self._proc.start()

    def _on_fullize_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buffer += chunk
        parts = self._buffer.replace("\r", "\n").split("\n")
        self._buffer = parts.pop()
        for line in parts:
            if line.strip():
                self.fullize_log.appendPlainText(line)

    def _on_fullize_finished(self, exit_code: int, _status) -> None:
        if self._buffer.strip():
            self.fullize_log.appendPlainText(self._buffer)
        self._buffer = ""
        self._proc = None
        self.btn_fullize.setText("⚡ Fullizar agora (grátis)")

        if exit_code != 0:
            tail = self.fullize_log.toPlainText()[-1500:]
            QMessageBox.critical(
                self, "Fullize falhou",
                f"O motor encerrou com código {exit_code}.\n\n"
                f"Últimas linhas do log:\n{tail}")
            self._refresh_state()
            return

        log_text = self.fullize_log.toPlainText()
        parsed = rl.parse_fullize_line(log_text)
        full_output = self.project.track_target(wp.TRACK_FULL)
        try:
            strings = wp.count_strings(full_output)
            # Registra o caminho exato do master Completa (convenção §2).
            self.project.set_track_file(wp.TRACK_FULL, full_output)
            self.project.update_track(wp.TRACK_FULL, wp.TRACK_STATUS_DONE,
                                      translated=strings, skipped_free=0)
        except (wp.ProjectError, wp.LocalizationFormatError) as exc:
            QMessageBox.warning(
                self, "Fullize concluído, mas…",
                f"Não foi possível atualizar o projeto:\n{exc}")
            self._refresh_state()
            return

        changed = parsed["changed"] if parsed else None
        detalhe = (f"{changed:,} termos de mecânica traduzidos pelo "
                   "glossário".replace(",", ".")
                   if changed is not None else "trilha Completa gerada")
        QMessageBox.information(
            self, "Trilha Completa pronta ✓",
            f"{detalhe}.\n\noutput/{full_output.name} agora tem {strings:,} "
            "strings 100% em português.".replace(",", "."))
        self._refresh_state()
        self.main.dashboard.refresh(self.project)

    # ── Card 2: Pacote para a página de mod ─────────────────────────────

    def _build_package_card(self) -> QGroupBox:
        box = QGroupBox("Pacote para a página de mod")
        layout = QGridLayout(box)

        layout.addWidget(QLabel("Trilha:"), 0, 0)
        self.track_combo = QComboBox()
        for track in (wp.TRACK_PRESERVED, wp.TRACK_FULL):
            self.track_combo.addItem(rl.TRACK_NAMES_PT[track], track)
        self.track_combo.currentIndexChanged.connect(self._refresh_diff_hint)
        layout.addWidget(self.track_combo, 0, 1)

        layout.addWidget(QLabel("Versão:"), 1, 0)
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("ex.: 1.6.1.514")
        self.version_edit.textChanged.connect(self._refresh_state)
        layout.addWidget(self.version_edit, 1, 1)

        self.diff_hint = QLabel("—")
        self.diff_hint.setObjectName("subtitle")
        self.diff_hint.setWordWrap(True)
        layout.addWidget(self.diff_hint, 2, 0, 1, 2)

        self.zip_preview = QLabel("—")
        self.zip_preview.setObjectName("subtitle")
        self.zip_preview.setWordWrap(True)
        layout.addWidget(self.zip_preview, 3, 0, 1, 2)

        # Gate de auditoria (§4.3)
        self.gate_label = QLabel("—")
        self.gate_label.setObjectName("subtitle")
        self.gate_label.setWordWrap(True)
        layout.addWidget(self.gate_label, 4, 0, 1, 2)
        self.btn_goto_audit = QPushButton("Ir para ② Corrigir && Auditar")
        self.btn_goto_audit.clicked.connect(self._goto_audit)
        layout.addWidget(self.btn_goto_audit, 5, 0, 1, 2)

        self.btn_export = QPushButton("📦 Exportar pacote (.zip)")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._export)
        layout.addWidget(self.btn_export, 6, 0, 1, 2)
        return box

    def _selected_track(self) -> str:
        return self.track_combo.currentData() or wp.TRACK_PRESERVED

    def _refresh_state(self) -> None:
        """Atualiza gating e textos dos dois cards conforme o projeto."""
        # Fullize
        preserved_path = self.project.track_path(wp.TRACK_PRESERVED)
        full_path = self.project.track_path(wp.TRACK_FULL)
        has_preserved = preserved_path is not None and preserved_path.is_file()
        has_full = full_path is not None and full_path.is_file()
        full_status = self.project.track_status(wp.TRACK_FULL)
        lines = []
        if has_full:
            lines.append(
                f"✓ Completa gerada ({full_status.get('updated', '?')})")
        else:
            lines.append("Completa ainda não gerada.")
        if has_preserved and rl.needs_refullize(self.project):
            lines.append("⚠ Preservada mudou — re-fullize para atualizar "
                         "a Completa.")
        self.fullize_status.setText("\n".join(lines))
        running = self._proc is not None
        self.btn_fullize.setEnabled(has_preserved and not running)
        self.btn_fullize.setToolTip(
            "" if has_preserved
            else "Por quê? A trilha Preservada ainda não existe — "
                 "conclua ① Nova Tradução primeiro.")

        # Pacote — trilhas disponíveis
        for idx in range(self.track_combo.count()):
            track = self.track_combo.itemData(idx)
            tp = self.project.track_path(track)
            exists = tp is not None and tp.is_file()
            model = self.track_combo.model()
            item = model.item(idx)
            if item is not None:
                item.setEnabled(exists)
        # Se a trilha atual não existe, pula para uma que exista.
        _cur = self.project.track_path(self._selected_track())
        if _cur is None or not _cur.is_file():
            for idx in range(self.track_combo.count()):
                tp = self.project.track_path(self.track_combo.itemData(idx))
                if tp is not None and tp.is_file():
                    self.track_combo.setCurrentIndex(idx)
                    break

        if not self.version_edit.text().strip():
            self.version_edit.setText(
                self.project.state.get("game_version") or "")

        self._refresh_diff_hint()

    def _gate_decision(self) -> tuple[str, str]:
        """Gate de auditoria (§4.3) para a trilha selecionada."""
        track = self._selected_track()
        output = self.project.track_path(track)
        mtimes = ([output.stat().st_mtime]
                  if output is not None and output.is_file() else [])
        return au.release_gate_decision(
            self.project.state.get("last_audit"), mtimes)

    def _refresh_diff_hint(self) -> None:
        track = self._selected_track()
        _tp = self.project.track_path(track)
        exists = _tp is not None and _tp.is_file()
        version = self.version_edit.text().strip()

        diff = rl.diff_since_last_release(self.project, track)
        if diff is not None:
            count, prev = diff
            self.diff_hint.setText(
                f"{count:,} strings alteradas desde a última release "
                f"(v{prev})".replace(",", "."))
        else:
            self.diff_hint.setText("Primeira release desta trilha.")

        try:
            name = rl.release_zip_name(track, version) if version else "—"
        except wp.ProjectError:
            name = "—"
        self.zip_preview.setText(f"Arquivo: release/{name}")

        valid = bool(version)
        try:
            if version:
                rl.validate_release_version(version)
        except wp.ProjectError:
            valid = False

        # ── Gate de auditoria ──
        gate, gate_reason = self._gate_decision() if exists else \
            (au.GATE_BLOCKED, "")
        if not exists:
            self.gate_label.setText("")
            self.btn_goto_audit.setVisible(False)
        elif gate == au.GATE_BLOCKED:
            self.gate_label.setText(f"⛔ {gate_reason}")
            self.gate_label.setObjectName("err")
            self.btn_goto_audit.setVisible(True)
        elif gate == au.GATE_WARN:
            self.gate_label.setText(f"⚠ {gate_reason}")
            self.gate_label.setObjectName("warn")
            self.btn_goto_audit.setVisible(True)
        else:
            self.gate_label.setText(f"✓ {gate_reason}")
            self.gate_label.setObjectName("ok")
            self.btn_goto_audit.setVisible(False)
        self.gate_label.style().unpolish(self.gate_label)
        self.gate_label.style().polish(self.gate_label)

        blocked = exists and gate == au.GATE_BLOCKED
        self.btn_export.setEnabled(exists and valid and not blocked)
        tooltip = []
        if not exists:
            tooltip.append("a trilha escolhida ainda não existe")
        if not valid:
            tooltip.append("versão inválida (use números e pontos)")
        if blocked:
            tooltip.append("rode a auditoria antes de publicar")
        self.btn_export.setToolTip(
            "" if not tooltip else "Por quê? " + " e ".join(tooltip) + ".")

    def _goto_audit(self) -> None:
        dialog = AuditDialog(self.project, self.main, self)
        dialog.exec()
        self._refresh_state()
        self.main.dashboard.refresh(self.project)

    def _export(self) -> None:
        track = self._selected_track()
        version = self.version_edit.text().strip()

        # Gate de auditoria: warn exige confirmação explícita (§4.3).
        gate, gate_reason = self._gate_decision()
        if gate == au.GATE_BLOCKED:
            QMessageBox.warning(
                self, "Auditoria pendente",
                "Rode a auditoria antes de publicar — a release precisa "
                "sair 100% auditada.\n\n" + gate_reason)
            return
        if gate == au.GATE_WARN:
            box = QMessageBox(self)
            box.setWindowTitle("Auditoria com pendências")
            box.setIcon(QMessageBox.Warning)
            box.setText(
                f"{gate_reason}\n\nAlgumas marcações podem ser falsos "
                "positivos, mas o caminho recomendado é corrigir em ② "
                "Corrigir & Auditar. Exportar mesmo assim?")
            override = box.addButton("Exportar mesmo assim",
                                     QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is not override:
                return
        try:
            result = rl.export_release(self.project, track, version)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível exportar", str(exc))
            return

        # Guarda a versão usada como versão do jogo se estava vazia.
        if not self.project.state.get("game_version"):
            try:
                self.project.set_game_version(version)
            except wp.ProjectError:
                pass

        box = QMessageBox(self)
        box.setWindowTitle("Pacote exportado ✓")
        diff = result["diff_count"]
        detalhe = (f"\n{diff:,} strings alteradas desde "
                   f"v{result['prev_version']}.".replace(",", ".")
                   if diff is not None else "")
        box.setText(
            f"Pacote pronto para a página de mod:{detalhe}\n\n"
            f"{result['zip']}\n\n"
            "Conteúdo: enGB.json (renomeado para o jogo) + "
            "LEIA-ME_INSTALACAO.txt + CHANGELOG.txt")
        open_btn = box.addButton("Abrir pasta", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(result["zip"].parent)))

        self._refresh_state()
        self.main.dashboard.refresh(self.project)

    # ── fechamento ──────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._proc is not None:
            answer = QMessageBox.question(
                self, "Fullize em andamento",
                "O fullize está rodando. Cancelar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._proc.terminate()
        self.reject()


# ─────────────────────────────────────────────────────────────────────────────
# JORNADA ④ DIA DE PATCH — diff grátis + delta + auto-merge (§4.4, Fase 5)
# ─────────────────────────────────────────────────────────────────────────────

class PatchPreviewWorker(QThread):
    """Roda o diff (grátis) + delta + pré-voo do delta fora da UI."""
    finished_ok = Signal(object)   # {"preview", "delta", "delta_path", "cost"}
    failed = Signal(str)

    def __init__(self, project: wp.Project, new_path: Path,
                 model: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._project = project
        self._new_path = new_path
        self._model = model

    def run(self) -> None:
        try:
            old_data = wp.load_localization(self._project.input_path())
            new_data = wp.load_localization(self._new_path)
            pt_path = self._project.track_path(wp.TRACK_PRESERVED)
            pt_data = (wp.load_localization(pt_path)
                       if pt_path is not None and pt_path.is_file()
                       else {"strings": {}})
            preview = pch.categorize_patch(old_data, new_data, pt_data)
            delta = pch.build_delta(preview, new_data)
            delta_file = pch.write_delta(self._project, delta)
            glossary = pf.resolve_glossary_path(self._project,
                                                repo_root=REPO_ROOT)
            cost = pf.run_preflight(delta_file, glossary, model=self._model)
        except Exception as exc:  # nunca derrubar a UI por análise
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit({"preview": preview, "delta": delta,
                               "delta_path": delta_file, "cost": cost})


class PatchDayDialog(QDialog):
    """④ Dia de Patch: Novo EN → Prévia do diff (grátis) → Executar → Fim."""

    def __init__(self, project: wp.Project, main: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.main = main
        self.new_path: Optional[Path] = None
        self.preview: Optional[dict] = None
        self.cost: Optional[pf.PreflightResult] = None
        self._worker: Optional[PatchPreviewWorker] = None
        self._proc: Optional[QProcess] = None
        self._buffer = ""
        self._stopped_by_user = False
        self._merge_stats: Optional[dict] = None

        self.setWindowTitle("④ Dia de Patch")
        self.setMinimumSize(900, 640)

        layout = QVBoxLayout(self)
        title = QLabel("Dia de Patch")
        title.setObjectName("title")
        layout.addWidget(title)
        hint = QLabel(
            "O jogo atualizou? Traga o enGB.json NOVO. O diff é grátis e "
            "você só paga pela diferença — strings movidas de lugar têm o "
            "PT reaproveitado de graça.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.steps = QStackedWidget()
        self.steps.addWidget(self._build_step_input())    # 0
        self.steps.addWidget(self._build_step_preview())  # 1
        self.steps.addWidget(self._build_step_run())      # 2
        self.steps.addWidget(self._build_step_done())     # 3
        layout.addWidget(self.steps, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self._on_close)
        layout.addWidget(self.buttons)

    # ── Passo 1: Novo EN ────────────────────────────────────────────────

    def _build_step_input(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        if not self.project.has_input():
            blocked = QLabel(
                "⛔ Nenhum EN anterior registrado no projeto.\n\n"
                "O Dia de Patch compara o dump novo com o enGB.json já "
                "arquivado no projeto. Conclua ① Nova Tradução primeiro — "
                "ou adote uma tradução existente na tela de boas-vindas.")
            blocked.setObjectName("err")
            blocked.setWordWrap(True)
            layout.addWidget(blocked)
            layout.addStretch(1)
            return page

        if self.project.track_path(wp.TRACK_PRESERVED) is None:
            blocked = QLabel(
                "⛔ A trilha Preservada não existe neste projeto.\n\n"
                "Ela é a base do merge do Dia de Patch (a Completa é "
                "regenerada grátis a partir dela). Conclua ① Nova Tradução "
                "primeiro.")
            blocked.setObjectName("err")
            blocked.setWordWrap(True)
            layout.addWidget(blocked)
            layout.addStretch(1)
            return page

        current = self.project.input_path()
        info = QLabel(
            f"EN atual arquivado: {current.name} · "
            f"{self.project.state['input'].get('strings', 0):,} strings"
            .replace(",", "."))
        info.setObjectName("cardBody")
        layout.addWidget(info)

        pick_row = QHBoxLayout()
        self.btn_pick = QPushButton("📂 Escolher o enGB.json NOVO…")
        self.btn_pick.setObjectName("primary")
        self.btn_pick.clicked.connect(self._pick_new_input)
        pick_row.addWidget(self.btn_pick)
        self.pick_label = QLabel("Nenhum arquivo escolhido.")
        self.pick_label.setObjectName("subtitle")
        self.pick_label.setWordWrap(True)
        pick_row.addWidget(self.pick_label, 1)
        layout.addLayout(pick_row)

        expl = QLabel(
            "O arquivo é registrado com o nome que tem — se veio de fora "
            "do projeto, é copiado como input/enGB_<versão>.json (a versão "
            "vem do nome; sem versão, usa a data de hoje). O dump antigo "
            "permanece arquivado — nada é renomeado nem destruído.")
        expl.setObjectName("subtitle")
        expl.setWordWrap(True)
        layout.addWidget(expl)
        layout.addStretch(1)

        nav = QHBoxLayout()
        self.btn_to_preview = QPushButton("Avançar: prévia do diff (grátis) →")
        self.btn_to_preview.setObjectName("primary")
        self.btn_to_preview.setEnabled(False)
        self.btn_to_preview.clicked.connect(self._compute_preview)
        nav.addStretch(1)
        nav.addWidget(self.btn_to_preview)
        layout.addLayout(nav)
        return page

    def _pick_new_input(self) -> None:
        start = str(self.project.input_path().parent)
        file, _ = QFileDialog.getOpenFileName(
            self, "Escolha o enGB.json NOVO (pós-patch)", start,
            "Localização EN (*.json)")
        if not file:
            return
        self.new_path = Path(file)
        version = wp.extract_game_version(self.new_path.name)
        stamp = (f"versão detectada: {version}" if version
                 else "sem versão no nome — arquivo será datado")
        self.pick_label.setText(f"✓ {self.new_path.name} ({stamp})")
        self.btn_to_preview.setEnabled(True)

    # ── Passo 2: Prévia do diff (grátis) ────────────────────────────────

    def _build_step_preview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.headline = QLabel("Calculando o diff…")
        self.headline.setObjectName("cardTitle")
        layout.addWidget(self.headline)

        self.counts_grid = QGridLayout()
        self.cat_labels: Dict[str, QLabel] = {}
        cats = [
            ("new", "🆕 Novas"), ("modified", "📝 Modificadas"),
            ("moved", "🔀 Movidas (PT grátis)"),
            ("removed", "🗑️ Removidas"), ("emptied", "💧 Esvaziadas"),
            ("unchanged", "✅ Intactas"),
        ]
        for i, (key, label) in enumerate(cats):
            name = QLabel(label)
            name.setObjectName("cardBody")
            value = QLabel("—")
            value.setObjectName("cardTitle")
            self.counts_grid.addWidget(name, i // 3, (i % 3) * 2)
            self.counts_grid.addWidget(value, i // 3, (i % 3) * 2 + 1)
            self.cat_labels[key] = value
        layout.addLayout(self.counts_grid)

        details = QGroupBox("Detalhes do diff (antigo × novo lado a lado)")
        details.setCheckable(True)
        details.setChecked(False)
        det_layout = QVBoxLayout(details)
        self.diff_table = QTableWidget(0, 4)
        self.diff_table.setHorizontalHeaderLabels(
            ["Categoria", "UUID", "EN antigo", "EN novo / detalhe"])
        self.diff_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.diff_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.diff_table.setAlternatingRowColors(True)
        self.diff_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.setVisible(False)
        det_layout.addWidget(self.diff_table)
        details.toggled.connect(self.diff_table.setVisible)
        layout.addWidget(details, 1)

        cost_box = QGroupBox("Custo — SÓ o delta (novas + modificadas)")
        cost_layout = QGridLayout(cost_box)
        cost_layout.addWidget(QLabel("Modelo:"), 0, 0)
        self.model_combo = QComboBox()
        for mid, label, _provider in pf.list_models():
            self.model_combo.addItem(f"{mid} — {label}", mid)
        idx = self.model_combo.findData(
            st.default_model() or "deepseek-v4-flash")
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.currentIndexChanged.connect(self._recalc_cost)
        cost_layout.addWidget(self.model_combo, 0, 1)
        cost_layout.addWidget(QLabel("Chave:"), 0, 2)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("vazio = ambiente/cofre")
        cost_layout.addWidget(self.key_edit, 0, 3)
        self.cost_label = QLabel("—")
        self.cost_label.setObjectName("cardBody")
        self.cost_label.setWordWrap(True)
        cost_layout.addWidget(self.cost_label, 1, 0, 1, 4)
        layout.addWidget(cost_box)

        self.cleanup_cb = QCheckBox(
            "🗑️ Limpar strings removidas/esvaziadas dos masters")
        cleanup_expl = QLabel(
            "Desmarcado por segurança: strings removidas pelo jogo não "
            "atrapalham o mod — limpar só enxuga o arquivo. Backup é "
            "sempre criado em backups/ antes de qualquer mudança.")
        cleanup_expl.setObjectName("subtitle")
        cleanup_expl.setWordWrap(True)
        layout.addWidget(self.cleanup_cb)
        layout.addWidget(cleanup_expl)

        nav = QHBoxLayout()
        btn_back = QPushButton("← Voltar")
        btn_back.clicked.connect(lambda: self.steps.setCurrentIndex(0))
        self.btn_execute = QPushButton("▶ Executar (traduzir delta + merge)")
        self.btn_execute.setObjectName("primary")
        self.btn_execute.setEnabled(False)
        self.btn_execute.clicked.connect(self._start_execution)
        nav.addWidget(btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_execute)
        layout.addLayout(nav)
        return page

    def _compute_preview(self) -> None:
        if self.new_path is None or self._worker is not None:
            return
        self.steps.setCurrentIndex(1)
        self.headline.setText("Calculando o diff…")
        self.btn_execute.setEnabled(False)
        self._worker = PatchPreviewWorker(
            self.project, self.new_path,
            self.model_combo.currentData() or "deepseek-v4-flash", self)
        self._worker.finished_ok.connect(self._fill_preview)
        self._worker.failed.connect(self._on_preview_error)
        self._worker.start()

    def _fill_preview(self, bundle: dict) -> None:
        """Preenche contagens + tabela + custo (separado p/ o smoke test)."""
        self._worker = None
        self.preview = bundle["preview"]
        self.cost = bundle["cost"]
        p = self.preview
        self.headline.setText(
            f"O patch mudou {p['changed']:,} de "
            f"{p['total_new_dump']:,} strings".replace(",", "."))
        for key, lbl in self.cat_labels.items():
            value = (p["unchanged"] if key == "unchanged"
                     else len(p[key]))
            lbl.setText(f"{value:,}".replace(",", "."))

        cat_names = {
            "new": "🆕 nova", "modified": "📝 modificada",
            "moved": "🔀 movida", "removed": "🗑️ removida",
            "emptied": "💧 esvaziada",
        }
        rows = []
        for uuid, text in p["new"]:
            rows.append((cat_names["new"], uuid, "—", text))
        for uuid, new_text, old_text in p["modified"]:
            rows.append((cat_names["modified"], uuid, old_text, new_text))
        for old_uuid, new_uuid, text, pt in p["moved"]:
            note = f"{text}\n→ novo UUID {new_uuid} · PT reaproveitado grátis"
            rows.append((cat_names["moved"], old_uuid, text, note))
        for uuid, old_text in p["removed"]:
            rows.append((cat_names["removed"], uuid, old_text,
                         "ausente do jogo novo"))
        for uuid, old_text in p["emptied"]:
            rows.append((cat_names["emptied"], uuid, old_text,
                         "texto esvaziado pelo patch"))
        self.diff_table.setRowCount(len(rows))
        for row, (cat, uuid, old, new) in enumerate(rows):
            for col, text in enumerate((cat, uuid, old, new)):
                item = QTableWidgetItem(text)
                if col in (2, 3):
                    item.setToolTip(text)
                self.diff_table.setItem(row, col, item)

        removed_n = len(p["removed"]) + len(p["emptied"])
        self.cleanup_cb.setText(
            f"🗑️ Limpar strings removidas/esvaziadas dos masters "
            f"({removed_n} strings)")
        self._recalc_cost()
        self.btn_execute.setEnabled(True)

    def _on_preview_error(self, message: str) -> None:
        self._worker = None
        self.headline.setText("⚠ Não foi possível calcular o diff.")
        QMessageBox.warning(self, "Prévia falhou", message)

    def _recalc_cost(self) -> None:
        if self.cost is None:
            return
        model = self.model_combo.currentData() or "deepseek-v4-flash"
        self.cost = pf.recalc_estimate(self.cost, model)
        c = self.cost
        paid = (len(self.preview["new"]) + len(self.preview["modified"])
                if self.preview else 0)
        if paid == 0:
            self.cost_label.setText(
                "Nada a traduzir — o patch só moveu/removeu strings. "
                "Custo: R$ 0 ✓")
            return
        self.cost_label.setText(
            f"{paid} strings pagas (🆕+📝) · ~{c.input_tokens_est:,} tokens "
            f"· {c.batches_est} lotes · {c.duration_hint} · {c.cost_hint}"
            .replace(",", ".") +
            f"\n🔀 {len(self.preview['moved'])} movidas reaproveitam o PT "
            "existente de graça.")

    # ── Passo 3: Executar ───────────────────────────────────────────────

    def _build_step_run(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.run_status = QLabel("Preparando…")
        self.run_status.setObjectName("cardTitle")
        self.run_status.setWordWrap(True)
        layout.addWidget(self.run_status)

        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 100)
        self.run_progress.setValue(0)
        layout.addWidget(self.run_progress)

        counters = QHBoxLayout()
        self.cnt_done = QLabel("traduzidas: 0")
        self.cnt_eta = QLabel("ETA: —")
        for lbl in (self.cnt_done, self.cnt_eta):
            lbl.setObjectName("cardBody")
            counters.addWidget(lbl)
        counters.addStretch(1)
        layout.addLayout(counters)

        self.run_log = QPlainTextEdit()
        self.run_log.setObjectName("log")
        self.run_log.setReadOnly(True)
        layout.addWidget(self.run_log, 1)

        nav = QHBoxLayout()
        self.btn_stop = QPushButton("⏸ Parar (o progresso é salvo)")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_run)
        nav.addWidget(self.btn_stop)
        nav.addStretch(1)
        layout.addLayout(nav)
        return page

    def _append_log(self, text: str) -> None:
        self.run_log.appendPlainText(text)

    def _start_execution(self) -> None:
        """Arquiva o EN novo e dispara a tradução do delta (ou vai direto
        para o merge quando não há nada pago)."""
        if self.preview is None or self.new_path is None:
            return
        model = self.model_combo.currentData() or "deepseek-v4-flash"
        provider = pf.provider_for_model(model)
        key, _source = pf.resolve_api_key(provider, self.key_edit.text())
        paid = len(self.preview["new"]) + len(self.preview["modified"])
        if paid and not key:
            QMessageBox.warning(
                self, "Chave de API ausente",
                "Nenhuma chave de API disponível (campo, ambiente ou cofre).")
            return

        try:
            info = pch.register_new_input(self.project, self.new_path)
        except wp.ProjectError as exc:
            QMessageBox.warning(self, "Não foi possível registrar o EN novo",
                                str(exc))
            return
        self._new_version = info["version"]
        self.steps.setCurrentIndex(2)
        self._append_log(f"📦 EN novo arquivado: {info['archive'].name}"
                         + (f" (versão {info['version']})"
                            if info["version"] else ""))

        if not paid:
            self._append_log("Nada a traduzir — indo direto para o merge.")
            self.run_progress.setRange(0, 1)
            self.run_progress.setValue(0)
            self._do_merge()
            return

        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        args = pch.build_delta_args(
            REPO_ROOT / "tradutor.py", self.project,
            pch.delta_path(self.project), pch.delta_pt_path(self.project),
            model, glossary)
        env = pf.subprocess_env(model, key)
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)

        self._stopped_by_user = False
        self._buffer = ""
        self.run_status.setText("Traduzindo o delta (só o que mudou)…")
        self.btn_stop.setEnabled(True)
        self._proc = QProcess(self)
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(args)
        self._proc.setWorkingDirectory(str(REPO_ROOT))
        self._proc.setProcessEnvironment(qenv)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_proc_output)
        self._proc.finished.connect(self._on_delta_finished)
        self._append_log("$ tradutor.py (delta) --mode preserve --resume …")
        self._proc.start()

    def _stop_run(self) -> None:
        if self._proc is None:
            return
        self._stopped_by_user = True
        self._append_log("⏸ Parando — o progresso já salvo será mantido. "
                         "Rode o Dia de Patch de novo para continuar.")
        self._proc.terminate()
        QTimer.singleShot(3000, self._kill_if_running)
        self.btn_stop.setEnabled(False)

    def _kill_if_running(self) -> None:
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def _on_proc_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buffer += chunk
        parts = self._buffer.replace("\r", "\n").split("\n")
        self._buffer = parts.pop()
        for line in parts:
            if not line.strip():
                continue
            self._append_log(line)
            parsed = pf.parse_engine_line(line)
            if parsed and parsed["kind"] == "plan":
                self.run_progress.setRange(0, max(1, parsed["pending"]))
            elif parsed and parsed["kind"] == "progress":
                self.run_progress.setRange(0, max(1, parsed["total"]))
                self.run_progress.setValue(parsed["done"])
                self.cnt_done.setText(f"traduzidas: {parsed['done']}")

    def _on_delta_finished(self, exit_code: int, _status) -> None:
        if self._buffer.strip():
            self._append_log(self._buffer)
        self._buffer = ""
        self._proc = None
        self.btn_stop.setEnabled(False)
        if exit_code != 0:
            tail = self.run_log.toPlainText()[-1500:]
            self.run_status.setText("⚠ A tradução do delta falhou.")
            QMessageBox.critical(
                self, "A tradução do delta falhou",
                f"O motor encerrou com código {exit_code}. Nada foi mesclado"
                " — os masters estão intactos.\n\nÚltimas linhas do log:\n"
                f"{tail}")
            return
        self.run_progress.setValue(self.run_progress.maximum())
        self._do_merge()

    # ── merge + fullize + estado ────────────────────────────────────────

    def _do_merge(self) -> None:
        """Merge no master Preservada (separado p/ o smoke test)."""
        self.run_status.setText("Mesclando no master Preservada…")
        delta_pt = pch.delta_pt_path(self.project)
        paid = (len(self.preview["new"]) + len(self.preview["modified"])
                if self.preview else 0)
        if paid and not delta_pt.is_file():
            self.run_status.setText("⚠ delta_pt.json não foi gerado.")
            QMessageBox.critical(
                self, "Merge abortado",
                "A tradução do delta não gerou o arquivo esperado. "
                "Os masters estão intactos.")
            return
        if not paid:
            # Nada pago: delta vazio sintético só para o merge das movidas.
            delta_pt = pch.write_delta(self.project, {"strings": {}})

        try:
            stats = pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                                    delta_pt, self.preview,
                                    cleanup=self.cleanup_cb.isChecked())
        except wp.ProjectError as exc:
            self.run_status.setText("⚠ O merge falhou.")
            QMessageBox.critical(self, "O merge falhou", str(exc))
            return
        self._merge_stats = stats
        self._append_log(
            f"💾 Backup: {stats['backup'].name} · "
            f"🔀 {stats['moved']} movidas grátis · "
            f"⬆ {stats['upserted']} aplicadas · "
            f"🗑️ {stats['cleaned']} limpas")

        if self.project.track_path(wp.TRACK_FULL) is not None:
            self._run_fullize()
        else:
            self._finish_patch([wp.TRACK_PRESERVED])

    def _run_fullize(self) -> None:
        """Regenera a Completa (grátis) a partir da Preservada mesclada."""
        glossary = pf.resolve_glossary_path(self.project, repo_root=REPO_ROOT)
        if glossary is None:
            self._append_log("⚠ Glossário não encontrado — a Completa NÃO "
                             "foi regenerada. Fullize em ③ depois.")
            self._finish_patch([wp.TRACK_PRESERVED])
            return
        self.run_status.setText("Regenerando a trilha Completa (grátis)…")
        self.run_progress.setRange(0, 0)  # indeterminado
        args = rl.build_fullize_args(REPO_ROOT / "tradutor.py",
                                     self.project, glossary)
        self._buffer = ""
        self._proc = QProcess(self)
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(args)
        self._proc.setWorkingDirectory(str(REPO_ROOT))
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_fullize_output)
        self._proc.finished.connect(self._on_fullize_finished)
        self._append_log("$ tradutor.py --fullize …")
        self._proc.start()

    def _on_fullize_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._buffer += chunk
        parts = self._buffer.replace("\r", "\n").split("\n")
        self._buffer = parts.pop()
        for line in parts:
            if line.strip():
                self._append_log(line)

    def _on_fullize_finished(self, exit_code: int, _status) -> None:
        if self._buffer.strip():
            self._append_log(self._buffer)
        self._buffer = ""
        self._proc = None
        if exit_code != 0:
            self._append_log("⚠ Fullize falhou — a Preservada está "
                             "atualizada; regenere a Completa em ③.")
            self._finish_patch([wp.TRACK_PRESERVED])
            return
        self._finish_patch([wp.TRACK_PRESERVED, wp.TRACK_FULL])

    def _finish_patch(self, merged_tracks: list) -> None:
        pch.update_project_after_patch(
            self.project, getattr(self, "_new_version", None),
            self.preview, merged_tracks)
        self.run_progress.setRange(0, 1)
        self.run_progress.setValue(1)
        self._fill_done(merged_tracks)
        self.steps.setCurrentIndex(3)
        self.main.dashboard.refresh(self.project)

    # ── Passo 4: Fim ────────────────────────────────────────────────────

    def _build_step_done(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.done_title = QLabel("Sua tradução está atualizada ✓")
        self.done_title.setObjectName("title")
        layout.addWidget(self.done_title)
        self.done_summary = QLabel("")
        self.done_summary.setObjectName("cardBody")
        self.done_summary.setWordWrap(True)
        layout.addWidget(self.done_summary)

        note = QLabel(
            "Próximos passos: rode ② Corrigir & Auditar (a release ③ só "
            "sai com auditoria em dia) e depois publique o pacote novo.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        nav = QHBoxLayout()
        btn_audit = QPushButton("② Auditar agora")
        btn_audit.setObjectName("primary")
        btn_audit.clicked.connect(self._goto_audit)
        btn_release = QPushButton("③ Publicar")
        btn_release.clicked.connect(self._goto_release)
        nav.addStretch(1)
        nav.addWidget(btn_audit)
        nav.addWidget(btn_release)
        layout.addLayout(nav)
        return page

    def _fill_done(self, merged_tracks: list) -> None:
        p = self.preview or {}
        stats = self._merge_stats or {}
        tracks_pt = " e ".join(rl.TRACK_NAMES_PT[t] for t in merged_tracks)
        lines = [
            f"O patch mudou {p.get('changed', 0):,} strings.".replace(",", "."),
            f"🔀 {stats.get('moved', 0)} movidas reaproveitaram o PT de graça",
            f"⬆ {stats.get('upserted', 0)} novas/modificadas traduzidas e mescladas",
        ]
        if stats.get("cleaned"):
            lines.append(f"🗑️ {stats['cleaned']} removidas/esvaziadas limpas")
        lines.append(f"💾 Backup em backups/ · trilhas atualizadas: {tracks_pt}")
        self.done_summary.setText("\n".join(lines))

    def _goto_audit(self) -> None:
        AuditDialog(self.project, self.main, self).exec()
        self.main.dashboard.refresh(self.project)

    def _goto_release(self) -> None:
        ReleaseDialog(self.project, self.main, self).exec()
        self.main.dashboard.refresh(self.project)

    # ── fechamento ──────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._proc is not None:
            answer = QMessageBox.question(
                self, "Trabalho em andamento",
                "O Dia de Patch está rodando. Parar agora? O progresso "
                "salvo será mantido e NADA será mesclado pela metade — o "
                "merge só acontece depois da tradução completa.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._proc.terminate()
        self.reject()


# ─────────────────────────────────────────────────────────────────────────────
# JANELA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(920, 640)
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.project: Optional[wp.Project] = None

        self.stack = QStackedWidget()
        self.welcome = WelcomePage(self)
        self.dashboard = DashboardPage(self)
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.dashboard)
        self.setCentralWidget(self.stack)

        self._restore_last_project()

    # ── ciclo de vida do projeto ────────────────────────────────────────

    def _restore_last_project(self) -> None:
        last = self.settings.value(SETTINGS_LAST_PROJECT, "")
        if not last:
            self.stack.setCurrentWidget(self.welcome)
            return
        try:
            project = wp.Project.open(Path(last))
        except wp.ProjectError:
            # Projeto sumiu/está inválido: cai na boas-vindas sem drama.
            self.settings.remove(SETTINGS_LAST_PROJECT)
            self.stack.setCurrentWidget(self.welcome)
            return
        self.open_project(project)

    def open_project(self, project: wp.Project) -> None:
        self.project = project
        self.settings.setValue(SETTINGS_LAST_PROJECT, str(project.root))
        # §9.6: limpeza silenciosa de estado velho (arquivo sumiu do disco
        # → pendente de novo) antes de qualquer leitura dos cards.
        for line in project.cleanup_stale():
            print(f"[reconcile] {line}")
        self.dashboard.refresh(project)
        self.stack.setCurrentWidget(self.dashboard)
        # §9.6: arquivos soltos manualmente em input//output/ → oferece
        # registro; silencioso quando não há nada novo.
        self.dashboard._reconcile_now(silent=True)

    def close_project(self) -> None:
        self.project = None
        self.settings.remove(SETTINGS_LAST_PROJECT)
        self.stack.setCurrentWidget(self.welcome)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(SETTINGS_ORG)
    apply_grimdark(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
