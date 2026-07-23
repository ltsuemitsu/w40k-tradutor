#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W40K: Rogue Trader Translator — Desktop GUI (Grimdark Edition)

Warhammer 40k inspired desktop application for the translation scenarios.

Run after installing the GUI requirements:
    pip install -r requirements-gui.txt
    python tradutor_desktop.py

This GUI drives the existing core tools (tradutor.py, diff_tool.py, glossary_manager, merge, wiki_sync)
while providing:
- Prominent "Preserve Wiki & Core Mechanics" toggle (Scenarios 1 vs 2)
- Clear flows for full translation, game updates (Scenario 3), and merge (Scenario 4)
- Interactive glossary editor with Preserve flag support
- Multi-provider support surface (DeepSeek + GLM/Zhipu)
- Live log + progress for long operations
"""

import sys
import os
import json
import re
import subprocess
import threading
import shutil
import traceback
from pathlib import Path

# Optional: OS keychain storage for API keys (issue #9). If keyring is not
# installed, the app falls back to QSettings with a logged warning.
try:
    import keyring as _keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _keyring = None
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "W40kTradutor"
from datetime import datetime
from typing import Optional, Dict, Any, List

# Make sure we run from the directory where the script lives.
# This is important when launched via .bat file or double-click.
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# Guard the heavy PySide6 imports so we can give a nice error message
# instead of a confusing traceback when the package is missing.
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QTabWidget, QGroupBox, QLabel, QPushButton, QLineEdit, QCheckBox,
        QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QProgressBar,
        QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
        QMessageBox, QMenuBar, QStatusBar, QSplitter, QFrame, QInputDialog,
        QDialog
    )
    from PySide6.QtCore import Qt, QSettings, Signal, QObject, QThread, QTimer
    from PySide6.QtGui import QFont, QColor, QPalette, QAction
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

if not PYSIDE_AVAILABLE:
    print("=" * 70)
    print("ERROR: PySide6 is not installed.")
    print("=" * 70)
    print()
    print("The desktop GUI requires PySide6 (Qt for Python).")
    print()
    print("Install the GUI requirements with:")
    print("    py -3 -m pip install -r requirements-gui.txt")
    print()
    print("Or manually:")
    print("    py -3 -m pip install PySide6")
    print()
    print("After installing, run the GUI again with:")
    print("    python tradutor_desktop.py")
    print("    (or use the launch_gui.ps1 / launch_gui.bat scripts)")
    print()
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# GRIMDARK 40K THEME
# ─────────────────────────────────────────────────────────────────────────────

GRIMDARK_STYLESHEET = """
QMainWindow {
    background-color: #0a0a12;
    color: #e8d9b0;
}
QWidget {
    background-color: #0a0a12;
    color: #e8d9b0;
    font-family: "Segoe UI", "Consolas", sans-serif;
    font-size: 10pt;
}
QTabWidget::pane {
    border: 1px solid #3a2a1f;
    background: #111118;
}
QTabBar::tab {
    background: #1a1610;
    color: #c9a84c;
    padding: 8px 16px;
    border: 1px solid #3a2a1f;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #2a2118;
    color: #f0d9a0;
    border-bottom: 2px solid #c9a84c;
}
QTabBar::tab:hover {
    background: #221d15;
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
    padding: 6px 14px;
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
QPushButton#primary {
    background-color: #3a2a1f;
    color: #f0d9a0;
    border-color: #c9a84c;
    font-weight: bold;
}
QPushButton#danger {
    color: #ff9a8a;
    border-color: #6b2a2a;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0f0e14;
    border: 1px solid #3a2a1f;
    color: #e8d9b0;
    padding: 4px;
    selection-background-color: #4a3a2a;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #0f0e14;
    border: 1px solid #3a2a1f;
    color: #e8d9b0;
    padding: 3px;
}
QCheckBox {
    color: #e8d9b0;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #5c4630;
    background: #0f0e14;
}
QCheckBox::indicator:checked {
    background: #c9a84c;
    border-color: #c9a84c;
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
QProgressBar {
    border: 1px solid #3a2a1f;
    background: #0f0e14;
    text-align: center;
    color: #c9a84c;
}
QProgressBar::chunk {
    background-color: #6b4e2a;
    border: 1px solid #c9a84c;
}
QLabel#title {
    color: #c9a84c;
    font-size: 14pt;
    font-weight: bold;
    padding: 4px 0;
}
QLabel#subtitle {
    color: #8a7560;
    font-size: 9pt;
}
QLabel#big_toggle_label {
    color: #f0d9a0;
    font-size: 11pt;
    font-weight: bold;
}
QTextEdit#log {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9pt;
    background: #08070c;
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class W40kTranslatorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("W40K: Rogue Trader — Tradutor (Grimdark)")

        # Create settings object early so we can restore window geometry before sizing.
        self.settings = QSettings("W40kTradutor", "DesktopApp")
        self.current_project: Dict[str, Any] = {}
        self.current_project_path: Optional[str] = None
        self.active_worker: Optional[TranslationWorker] = None
        self.recent_projects: List[str] = []

        # For chaining async steps in Populate Glossary
        self._pending_population_source = None
        self._pending_population_glossary = None

        # Debounced auto-save for manual glossary table edits
        self._glossary_save_timer = QTimer(self)
        self._glossary_save_timer.setSingleShot(True)
        # Auto-saves run silently (no modal popup); manual saves still get one. (#5)
        self._glossary_save_timer.timeout.connect(lambda: self._save_glossary_from_table(silent=True))

        # Try to restore the user's previous window size/position first.
        # This respects what they resized it to on *their* screen.
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            # First run (or no saved geometry): calculate a size that is guaranteed
            # to fit the current screen, with margins.
            screen = QApplication.primaryScreen().availableGeometry()

            margin = 80
            max_w = screen.width() - margin
            max_h = screen.height() - margin

            w = min(1180, max_w)
            h = min(820, max_h)

            w = max(700, w)
            h = max(500, h)

            self.resize(w, h)

            # Center on the primary screen (handles multi-monitor correctly).
            self.move(
                screen.x() + (screen.width() - w) // 2,
                screen.y() + (screen.height() - h) // 2
            )

        # Hard lower bound so the UI stays usable.
        self.setMinimumSize(700, 500)

        self._setup_ui()
        self._apply_theme()

        # Defer these so the widget tree is fully live (prevents C++ object deleted crashes).
        QTimer.singleShot(0, self._load_last_paths)
        QTimer.singleShot(0, self._load_recent_projects)
        QTimer.singleShot(0, self._rebuild_recent_menu)

        self._update_status("Ready. Load a glossary and English JSON to begin or open a project.")

    def _apply_theme(self):
        self.setStyleSheet(GRIMDARK_STYLESHEET)
        # Dark palette tweaks
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#0a0a12"))
        palette.setColor(QPalette.WindowText, QColor("#e8d9b0"))
        self.setPalette(palette)

    def _setup_ui(self):
        # Central widget + main layout
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Header
        header = QLabel("⚔️  W40K: ROGUE TRADER — TRADUTOR  ⚔️")
        header.setObjectName("title")
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)

        sub = QLabel("Scenarios 1–4  •  Glossary-driven consistency  •  Preserve wiki mechanics  •  Grimdark tooling")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(sub)

        # Project status bar (new for proper workspace support)
        proj_bar = QHBoxLayout()
        self.project_label = QLabel("No project loaded — use File → New/Open Project")
        self.project_label.setStyleSheet("color: #c9a84c; font-weight: bold; padding: 2px 4px;")
        proj_bar.addWidget(self.project_label)
        proj_bar.addStretch()

        btn_new = QPushButton("New")
        btn_new.clicked.connect(self._new_project)
        proj_bar.addWidget(btn_new)

        btn_open = QPushButton("Open...")
        btn_open.clicked.connect(self._open_project)
        proj_bar.addWidget(btn_open)

        btn_save = QPushButton("Save Project")
        btn_save.clicked.connect(self._save_project)
        proj_bar.addWidget(btn_save)

        proj_widget = QWidget()
        proj_widget.setLayout(proj_bar)
        main_layout.addWidget(proj_widget)

        # Main tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # === TAB 1: TRANSLATE (Scenarios 1 & 2) - ALWAYS CREATE THIS FIRST ===
        self.tab_translate = self._create_translate_tab()
        self.tabs.addTab(self.tab_translate, "Translate (1 & 2)")
        self.tabs.setCurrentIndex(0)
        print("INFO: Translate tab created as first tab")

        # === TAB 2: GAME UPDATE (Scenario 3) ===
        try:
            self.tab_update = self._create_update_tab()
            self.tabs.addTab(self.tab_update, "Game Update (3)")
        except Exception as ex:
            print("WARNING: failed to create Game Update tab:", ex)

        # === TAB 3: GLOSSARY ===
        try:
            self.tab_glossary = self._create_glossary_tab()
            self.tabs.addTab(self.tab_glossary, "Glossary")
        except Exception as ex:
            print("WARNING: failed to create Glossary tab:", ex)

        # === TAB 4: AUDIT & MERGE (Scenario 4 + support) ===
        try:
            self.tab_audit_merge = self._create_audit_merge_tab()
            self.tabs.addTab(self.tab_audit_merge, "Audit & Merge (4)")
        except Exception as ex:
            print("WARNING: failed to create Audit & Merge tab:", ex)

        # Final guarantee: Translate is always tab 0 and selected
        if self.tabs.count() > 0:
            for i in range(self.tabs.count()):
                if "Translate" in self.tabs.tabText(i):
                    if i != 0:
                        w = self.tabs.widget(i)
                        txt = self.tabs.tabText(i)
                        self.tabs.removeTab(i)
                        self.tabs.insertTab(0, w, txt)
                    break
        self.tabs.setCurrentIndex(0)
        print("INFO: Tabs after guarantee:", [self.tabs.tabText(i) for i in range(self.tabs.count())])

        # Force the Translate tab to always be present as the FIRST tab and selected.
        # This protects against any mangled state from previous edits or creation failures.
        translate_found = False
        for i in range(self.tabs.count()):
            if "Translate" in self.tabs.tabText(i):
                self.tabs.setCurrentIndex(i)
                translate_found = True
                break
        if not translate_found:
            try:
                t = self._create_translate_tab()
                self.tabs.insertTab(0, t, "Translate (1 & 2)")
                self.tabs.setCurrentIndex(0)
                print("INFO: Force-inserted the missing Translate tab at position 0")
            except Exception as ex:
                print("ERROR: Could not force-insert the Translate tab:", ex)

        # Extra safety: if still no Translate tab, force create and insert
        has_translate = any("Translate" in self.tabs.tabText(i) for i in range(self.tabs.count()))
        if not has_translate:
            try:
                t = self._create_translate_tab()
                self.tabs.insertTab(0, t, "Translate (1 & 2)")
                self.tabs.setCurrentIndex(0)
                print("INFO: Extra safety net inserted Translate tab")
            except Exception as ex:
                print("ERROR: Extra safety net failed for Translate tab:", ex)
        self.tabs.setCurrentIndex(0)

        # Nuclear option: after everything, if the first tab is still not Translate, recreate and force it
        try:
            if self.tabs.count() == 0 or "Translate" not in self.tabs.tabText(0):
                if hasattr(self, 'tab_translate') and self.tab_translate is not None:
                    # remove old first if any
                    if self.tabs.count() > 0:
                        self.tabs.removeTab(0)
                    self.tabs.insertTab(0, self.tab_translate, "Translate (1 & 2)")
                else:
                    self.tab_translate = self._create_translate_tab()
                    if self.tabs.count() > 0:
                        self.tabs.removeTab(0)
                    self.tabs.insertTab(0, self.tab_translate, "Translate (1 & 2)")
                self.tabs.setCurrentIndex(0)
                print("INFO: Nuclear option forced Translate tab as first")
        except Exception as ex:
            print("ERROR: Nuclear option for Translate tab failed:", ex)
        self.tabs.setCurrentIndex(0)

        # Final guarantee: always make sure Translate is tab 0 and selected
        try:
            translate_index = -1
            for i in range(self.tabs.count()):
                if "Translate" in self.tabs.tabText(i):
                    translate_index = i
                    break
            if translate_index > 0:
                # move it to front
                tab_widget = self.tabs.widget(translate_index)
                tab_label = self.tabs.tabText(translate_index)
                self.tabs.removeTab(translate_index)
                self.tabs.insertTab(0, tab_widget, tab_label)
            if self.tabs.count() > 0:
                self.tabs.setCurrentIndex(0)
            print("INFO: Final guarantee - current tabs:", [self.tabs.tabText(i) for i in range(self.tabs.count())])
        except Exception as ex:
            print("ERROR in final tab guarantee:", ex)

        # Bottom log + progress area
        bottom_box = QGroupBox("Operation Log & Progress")
        bottom_layout = QVBoxLayout(bottom_box)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        bottom_layout.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        bottom_layout.addWidget(self.log)

        main_layout.addWidget(bottom_box)

        # Menu
        self._create_menu()

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # Cancel button in status area (simple)
        self.cancel_btn = QPushButton("Cancel Running Task")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self._cancel_current)
        self.cancel_btn.setEnabled(False)
        self.status.addPermanentWidget(self.cancel_btn)

        # ABSOLUTE FINAL GUARANTEE: The Translate tab MUST be the first tab and selected.
        # If for any reason (mangled previous edits, exception, etc.) it is missing,
        # we recreate and insert it at position 0 right before the window is shown.
        try:
            if self.tabs.count() == 0 or "Translate" not in self.tabs.tabText(0):
                if hasattr(self, 'tab_translate') and self.tab_translate is not None:
                    # remove any non-translate first tab
                    if self.tabs.count() > 0 and "Translate" not in self.tabs.tabText(0):
                        self.tabs.removeTab(0)
                    self.tabs.insertTab(0, self.tab_translate, "Translate (1 & 2)")
                else:
                    self.tab_translate = self._create_translate_tab()
                    if self.tabs.count() > 0 and "Translate" not in self.tabs.tabText(0):
                        self.tabs.removeTab(0)
                    self.tabs.insertTab(0, self.tab_translate, "Translate (1 & 2)")
                self.tabs.setCurrentIndex(0)
                print("INFO: Absolute final guarantee inserted/forced Translate tab as first")
            self.tabs.setCurrentIndex(0)
            print("INFO: Current tabs at end of setup:", [self.tabs.tabText(i) for i in range(self.tabs.count())])
        except Exception as ex:
            print("CRITICAL: failed to guarantee Translate tab at the end:", ex)
            # Last ditch: add a stub tab
            try:
                stub = QWidget()
                l = QVBoxLayout(stub)
                l.addWidget(QLabel("Translate tab creation had a critical error. Check the console output for details."))
                self.tabs.insertTab(0, stub, "Translate (1 & 2) [ERROR]")
                self.tabs.setCurrentIndex(0)
            except:
                pass

    def _create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        new_proj = QAction("New Project", self)
        new_proj.triggered.connect(self._new_project)
        file_menu.addAction(new_proj)

        open_proj = QAction("Open Project...", self)
        open_proj.triggered.connect(self._open_project)
        file_menu.addAction(open_proj)

        save_proj = QAction("Save Project", self)
        save_proj.triggered.connect(self._save_project)
        file_menu.addAction(save_proj)

        # Recent Projects submenu (populated on the fly)
        self.recent_menu = file_menu.addMenu("Recent Projects")
        self._rebuild_recent_menu()

        file_menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        settings_menu = menubar.addMenu("&Settings")
        prov_act = QAction("Manage Providers & Keys...", self)
        prov_act.triggered.connect(self._open_provider_dialog)
        settings_menu.addAction(prov_act)

        help_menu = menubar.addMenu("&Help")
        about = QAction("About / Scenarios", self)
        about.triggered.connect(lambda: QMessageBox.information(
                    self, "W40K Tradutor",
                    "Dual-track EN→PT-BR for Rogue Trader\n\n"
                    "1) Pre-Scan (free)\n"
                    "2) Preserve translation → EN mechanics + PT story\n"
                    "3) Fullize (free) → 100% PT via glossary\n\n"
                    "Exact wiki terms stay EN; terms inside phrases are hard-locked.\n"
                    "Tags / Encyclopedia / {name} / {mf|…} never go to the LLM.\n"
                    "Empty, placeholder, and EULA texts are skipped (no API).\n\n"
                    "Smart batches: short×50 · medium×30 · long×12 · xlong×5.\n"
                    "See README.md for CLI recipes."
                ))
        help_menu.addAction(about)

    # ───────────────────────────────
    # TAB: TRANSLATE (dual-track: Preserved + Full)
    # ───────────────────────────────
    def _create_translate_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        guide = QLabel(
            "<b>Dual-track workflow (recommended)</b><br>"
            "<b>1.</b> Pre-Scan (free) → review EULA/skip counts<br>"
            "<b>2.</b> Preserve ON → <b>Start Translation</b> → <code>ptBR_preserved</code> "
            "(EN mechanics + PT narrative; hard-locks tags &amp; wiki terms inside phrases)<br>"
            "<b>3.</b> <b>Fullize</b> (free, no API) → <code>ptBR_full</code> "
            "(glossary EN→PT replace on the preserved file)<br>"
            "<span style='color:#8a7560'>Exact whole-string wiki terms stay EN in step 2. "
            "Empty/placeholder/EULA never hit the API. Smart batches: short×50 · med×30 · long×12 · xlong×5.</span>"
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "background:#1a1520; border:1px solid #3a3040; border-radius:6px; "
            "padding:10px; color:#e8dcc8;"
        )
        layout.addWidget(guide)

        # Files group
        files_g = QGroupBox("Files")
        fl = QVBoxLayout(files_g)

        self.tr_input = self._file_row(fl, "Input (English JSON)", "data/en/enGB.json", self._pick_input)
        self.tr_output = self._file_row(fl, "Output — Preserved PT (EN terms + PT story)", "data/pt/ptBR_preserved.json", self._pick_output)
        self.tr_full_output = self._file_row(fl, "Output — Full PT (100% PT via Fullize)", "data/pt/ptBR_full.json", self._pick_output)
        self.tr_glossary = self._file_row(fl, "Glossary", "glossary.json", self._pick_glossary)
        self.tr_blacklist = self._file_row(fl, "Blacklist (optional UUIDs)", "data/blacklists/blacklist.json", self._pick_blacklist)
        self.tr_preserve_map = self._file_row(fl, "Preserve Map (auto from Preserve run)", "preserve_map.json", self._pick_preserve_map)
        self.tr_preserve_map.setToolTip(
            "Written on Preserve runs: {uuid: {kind: exact|inline, terms: [...]}}.\n"
            "exact = whole string was a wiki term (kept EN).\n"
            "inline = terms hard-locked inside a translated phrase."
        )

        bl_btn = QPushButton("Interactive Blacklist Builder (scan for EULA, long texts, placeholders...)")
        bl_btn.clicked.connect(self._build_blacklist_interactive)
        fl.addWidget(bl_btn)

        prescan_btn = QPushButton("🔍 Pre-Scan: Classify All UUIDs (FREE — no API cost)")
        prescan_btn.setToolTip(
            "Free classification before spending money:\n"
            "• SKIP — empty / placeholder\n"
            "• EULA — huge legal walls (auto-skipped by engine too)\n"
            "• PRESERVED — exact glossary term (free EN keep)\n"
            "• SHORT / MEDIUM / LONG — length tiers for smart batches\n"
            "Note: inline term locks are applied at translate time (not only exact)."
        )
        prescan_btn.clicked.connect(self._prescan_source)
        fl.addWidget(prescan_btn)

        layout.addWidget(files_g)

        # Big Preserve Toggle
        preserve_box = QGroupBox("Preserve mode")
        preserve_layout = QVBoxLayout(preserve_box)
        self.preserve_toggle = QCheckBox("PRESERVE WIKI & CORE MECHANICS  (recommended — dual-track step 2)")
        self.preserve_toggle.setObjectName("big_toggle_label")
        self.preserve_toggle.setChecked(True)
        self.preserve_toggle.setToolTip(
            "ON (recommended):\n"
            "• EXACT — whole string is a glossary term → keep English, no API\n"
            "• INLINE — term inside a phrase → translate phrase, hard-lock term as §TERM§\n"
            "• CLEAN — normal PT translation\n"
            "• Tags / Encyclopedia / {name} / {mf|…} always hard-protected\n\n"
            "OFF: full narrative translate (no EN term locks). Use Fullize after Preserve for 100% PT."
        )
        preserve_layout.addWidget(self.preserve_toggle)
        layout.addWidget(preserve_box)

        # Provider + params
        params_g = QGroupBox("Translation Settings")
        pl = QHBoxLayout(params_g)

        pl.addWidget(QLabel("Provider:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItems([
            "DeepSeek",
            "Zhipu GLM",
            "Kimi (Coding)",
            "Custom (OpenAI compat)",
        ])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        pl.addWidget(self.provider_combo)

        pl.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Leave empty to use env var")
        self.api_key_edit.textChanged.connect(self._on_api_key_changed)
        pl.addWidget(self.api_key_edit, 1)

        save_key_cb = QCheckBox("Save securely (OS keychain)")
        save_key_cb.setToolTip(
            "OS keychain via keyring. Uncheck to remove. Falls back to plain settings if keyring missing."
        )
        save_key_cb.stateChanged.connect(self._on_save_key_toggled)
        pl.addWidget(save_key_cb)
        self.save_key_cb = save_key_cb

        layout.addWidget(params_g)

        # Model + URL (cache-friendly bulk uses stable system prompt in engine)
        model_g = QGroupBox("Model & endpoint (profile tunes batches/workers)")
        mg = QGridLayout(model_g)
        mg.addWidget(QLabel("Base URL:"), 0, 0)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setText("https://api.deepseek.com")
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com")
        mg.addWidget(self.base_url_edit, 0, 1)
        mg.addWidget(QLabel("Model:"), 1, 0)
        self.model_edit = QComboBox()
        self.model_edit.setEditable(True)
        self.model_edit.addItems([
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
            "glm-5.2",
            "glm-5.1",
            "glm-5",
            "glm-5-turbo",
            "glm-4.7",
            "glm-4.7-flash",
            "glm-4.7-flashx",
            "glm-4.5-flash",
            "glm-4.5-air",
            "glm-4-plus",
            "glm-4-flash",
            "k3",
            "kimi-for-coding",
            "kimi-for-coding-highspeed",
        ])
        self.model_edit.setCurrentText("deepseek-v4-flash")
        self.model_edit.setMinimumWidth(200)
        self.model_edit.currentTextChanged.connect(self._on_model_changed_profile)
        mg.addWidget(self.model_edit, 1, 1)
        self.profile_label = QLabel("")
        self.profile_label.setWordWrap(True)
        self.profile_label.setStyleSheet("color:#8a7560;")
        mg.addWidget(self.profile_label, 2, 0, 1, 2)
        layout.addWidget(model_g)
        QTimer.singleShot(0, self._refresh_profile_label)

        # Advanced params
        adv_g = QGroupBox("Advanced")
        adv = QHBoxLayout(adv_g)

        adv.addWidget(QLabel("Batch size:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 50)
        self.batch_spin.setValue(10)
        adv.addWidget(self.batch_spin)

        adv.addWidget(QLabel("Workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 16)
        self.workers_spin.setValue(0)  # 0 = model profile
        self.workers_spin.setToolTip("0 = auto from model_profiles.py (recommended)")
        adv.addWidget(self.workers_spin)

        adv.addWidget(QLabel("Temperature:"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(0.15)
        adv.addWidget(self.temp_spin)

        self.dry_run_cb = QCheckBox("Dry Run (no API calls — test tag protection)")
        adv.addWidget(self.dry_run_cb)

        self.auto_extract_cb = QCheckBox("Auto-extract terms to glossary during translation (recommended for first pass)")
        self.auto_extract_cb.setToolTip("Every 5 batches the LLM will also suggest new consistent terms to add to your glossary. Great for populating before the real translation.")
        adv.addWidget(self.auto_extract_cb)

        layout.addWidget(adv_g)

        # Actions
        action_layout = QHBoxLayout()
        self.translate_btn = QPushButton("▶ 1) START PRESERVE TRANSLATION")
        self.translate_btn.setObjectName("primary")
        self.translate_btn.setToolTip(
            "Step 2 of dual-track.\n"
            "Preserve ON → EN mechanics + PT story → Output Preserved.\n"
            "Smart batches + EULA/placeholder skip + hard tag protect."
        )
        self.translate_btn.clicked.connect(lambda: self._start_translation(optimized=True))
        action_layout.addWidget(self.translate_btn)

        self.fullize_btn = QPushButton("✨ 2) FULLIZE → 100% PT (FREE)")
        self.fullize_btn.setObjectName("primary")
        self.fullize_btn.setToolTip(
            "Step 3 of dual-track — NO API cost.\n"
            "Reads Output Preserved, replaces glossary EN terms with PT, writes Output Full."
        )
        self.fullize_btn.clicked.connect(self._start_fullize)
        action_layout.addWidget(self.fullize_btn)

        self.dryrun_quick_btn = QPushButton("Dry Run (safe test)")
        self.dryrun_quick_btn.setToolTip("No API calls — classify + protect tags/terms only.")
        self.dryrun_quick_btn.clicked.connect(
            lambda: (self.dry_run_cb.setChecked(True), self._start_translation(optimized=True))
        )
        action_layout.addWidget(self.dryrun_quick_btn)

        self.retranslate_btn = QPushButton("🔁 Advanced: LLM 2nd pass (legacy)")
        self.retranslate_btn.setToolTip(
            "LEGACY / special cases only.\n"
            "Prefer Fullize (free) for the Full track.\n"
            "This re-sends preserved UUIDs to the LLM (costs money)."
        )
        self.retranslate_btn.clicked.connect(self._start_second_pass)
        action_layout.addWidget(self.retranslate_btn)

        layout.addLayout(action_layout)
        layout.addStretch()

        return w

    def _file_row(self, parent_layout, label: str, default_name: str, picker_slot):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        lbl.setMinimumWidth(80)
        row.addWidget(lbl)
        line = QLineEdit()
        line.setText(self.settings.value(f"last_{label[:3]}", default_name))
        line.setMinimumWidth(180)
        row.addWidget(line, 1)
        btn = QPushButton("Browse...")
        btn.setMinimumWidth(80)
        btn.clicked.connect(lambda: picker_slot(line))
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return line

    def _pick_input(self, line: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select English JSON", "", "JSON (*.json)")
        if path:
            line.setText(path)

    def _pick_output(self, line: QLineEdit):
        path, _ = QFileDialog.getSaveFileName(self, "Output PT-BR JSON", "ptBR.json", "JSON (*.json)")
        if path:
            line.setText(path)

    def _pick_glossary(self, line: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Glossary", "", "JSON (*.json)")
        if path:
            line.setText(path)
            # Also load it into the Glossary tab if user wants
            if hasattr(self, "glossary_path_edit"):
                self.glossary_path_edit.setText(path)

    def _pick_blacklist(self, line: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Blacklist JSON", "", "JSON (*.json)")
        if path:
            line.setText(path)

    def _pick_preserve_map(self, line: QLineEdit):
        path, _ = QFileDialog.getSaveFileName(self, "Preserve Map JSON", "preserve_map.json", "JSON (*.json)")
        if path:
            line.setText(path)

    # ───────────────────────────────
    # TAB: GAME UPDATE (Scenario 3)
    # ───────────────────────────────
    def _create_update_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hint = QLabel("Pure English vs English diff (no LLM cost). Generate minimal delta files for re-translation under either preserve mode.")
        hint.setStyleSheet("color: #8a7560;")
        layout.addWidget(hint)

        g = QGroupBox("Game Update Diff")
        gl = QVBoxLayout(g)

        self.up_new = self._file_row(gl, "New English (patch)", "data/en/enGB_new.json", lambda l: self._pick_file(l, "New English"))
        self.up_old = self._file_row(gl, "Previous English (baseline)", "data/en/enGB_old.json", lambda l: self._pick_file(l, "Old English"))
        self.up_current_pt = self._file_row(gl, "Current PT (optional)", "data/pt/ptBR.json", lambda l: self._pick_file(l, "Current PT"))

        layout.addWidget(g)

        btns = QHBoxLayout()
        analyze_btn = QPushButton("Analyze Changes (free)")
        analyze_btn.clicked.connect(self._analyze_update)
        btns.addWidget(analyze_btn)

        self.gen_preserve_delta_btn = QPushButton("Generate Delta — Preserve ON")
        self.gen_preserve_delta_btn.clicked.connect(lambda: self._generate_delta(preserve=True))
        btns.addWidget(self.gen_preserve_delta_btn)

        self.gen_full_delta_btn = QPushButton("Generate Delta — Full Narrative")
        self.gen_full_delta_btn.clicked.connect(lambda: self._generate_delta(preserve=False))
        btns.addWidget(self.gen_full_delta_btn)

        layout.addLayout(btns)

        self.update_results = QTextEdit()
        self.update_results.setReadOnly(True)
        self.update_results.setMaximumHeight(160)
        layout.addWidget(QLabel("Diff Results:"))
        layout.addWidget(self.update_results)

        layout.addStretch()
        return w

    def _pick_file(self, line: QLineEdit, title: str):
        p, _ = QFileDialog.getOpenFileName(self, f"Select {title}", "", "JSON (*.json)")
        if p:
            line.setText(p)

    def _analyze_update(self):
        new_p = self.up_new.text().strip()
        old_p = self.up_old.text().strip()
        if not (new_p and old_p):
            QMessageBox.warning(self, "Missing files", "Need both New English and Previous English.")
            return

        self._append_log("Analyzing English vs English diff (no API calls)...")

        try:
            # Use the diff_tool logic directly for speed (import the functions)
            import diff_tool as dt
            new_data = dt.load_json(new_p)
            old_data = dt.load_json(old_p)
            if not new_data or not old_data:
                raise ValueError("Failed to load one of the files")

            result = dt.detect_update(new_data, old_data, {"strings": {}})
            report = (
                f"NEW UUIDs: {len(result.get('new_keys', []))}\n"
                f"MODIFIED:  {len(result.get('modified_keys', []))}\n"
                f"REMOVED:   {len(result.get('removed_keys', []))}\n"
                f"UNCHANGED: {len(result.get('unchanged_keys', []))}"
            )
            self.update_results.setPlainText(report)
            self._append_log("Diff complete. Use the Generate Delta buttons.")
            self._update_status("Update analysis ready.")
        except Exception as e:
            self._append_log(f"ERROR during diff: {e}")
            QMessageBox.critical(self, "Diff error", str(e))

    def _generate_delta(self, preserve: bool):
        # For demo we generate a minimal delta using the same logic as diff_tool
        # In real use the user would then feed the delta into the Translate tab
        new_p = self.up_new.text().strip()
        old_p = self.up_old.text().strip()
        if not (new_p and old_p):
            QMessageBox.warning(self, "Missing", "Analyze first or provide both English files.")
            return

        try:
            import diff_tool as dt
            new_data = dt.load_json(new_p)
            old_data = dt.load_json(old_p)
            result = dt.detect_update(new_data, old_data, {"strings": {}})

            delta = {"strings": {}}
            for key, item in result.get("new_keys", []):
                delta["strings"][key] = {"Offset": item.get("Offset", 0), "Text": item.get("Text", ""), "_status": "new"}
            for key, item, old_text in result.get("modified_keys", []):
                delta["strings"][key] = {
                    "Offset": item.get("Offset", 0),
                    "Text": item.get("Text", ""),
                    "_status": "modified",
                    "_old_text": old_text
                }

            suffix = "preserve_on" if preserve else "full_narrative"
            default_name = f"delta_{suffix}.json"
            out_path, _ = QFileDialog.getSaveFileName(self, "Save Delta", default_name, "JSON (*.json)")
            if out_path:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(delta, f, indent=2, ensure_ascii=False)
                self._append_log(f"Delta saved: {out_path}  ({len(delta['strings'])} strings)")
                self._append_log("Now go to the Translate tab, load this delta as Input, set the matching Preserve toggle, and translate it.")
                QMessageBox.information(self, "Delta Ready", f"Saved {out_path}\n\nLoad it in the Translate tab and run with the correct preserve setting.")
        except Exception as e:
            QMessageBox.critical(self, "Delta generation failed", str(e))

    # ───────────────────────────────
    # Interactive Blacklist Builder (for huge files with EULA etc.)
    # ───────────────────────────────
    def _build_blacklist_interactive(self):
        self._append_log("[BLACKLIST] Button clicked — starting...")
        input_path = self.tr_input.text().strip()
        self._append_log(f"[BLACKLIST] Input path: '{input_path}'")
        if not input_path or not os.path.exists(input_path):
            self._append_log("[BLACKLIST] No valid input path — aborting.")
            QMessageBox.warning(self, "No input", "Please select a valid Input (English JSON) first.")
            return

        try:
            with open(input_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            strings = data.get("strings", {})
            self._append_log(f"[BLACKLIST] Loaded {len(strings)} strings from source.")
            if not strings:
                self._append_log("[BLACKLIST] Empty strings dict — aborting.")
                QMessageBox.warning(self, "Empty", "No 'strings' found in the input JSON.")
                return
        except Exception as e:
            self._append_log(f"[BLACKLIST] Load failed: {e}")
            QMessageBox.critical(self, "Load failed", str(e))
            return
        candidates = []
        eula_keywords = ["eula", "end user license", "license agreement", "terms of service", "privacy policy", "copyright"]
        empty_count = 0  # track empties separately (not shown in dialog)

        self._append_log("[BLACKLIST] Scanning for candidates...")
        for key, item in strings.items():
            text = item.get("Text", "") or ""
            if not text.strip():
                empty_count += 1
                continue  # skip empties — always safe to blacklist, no review needed
            word_count = len(text.split())
            lower = text.lower()
            reason = ""
            if word_count > 2000:
                reason = f"very long ({word_count} words)"
            elif any(kw in lower for kw in eula_keywords):
                reason = "EULA / legal text"
            elif any(p in lower for p in ["placeholder", "tbd", "todo", "wip", "dummy", "test", "temp", "{", "[[", "lorem"]):
                reason = "placeholder / template"
            if reason:
                preview = text[:100].replace("\n", " ")
                candidates.append((key, word_count, preview, reason))

        self._append_log(f"[BLACKLIST] Empty strings (auto-skipped): {empty_count}")
        self._append_log(f"[BLACKLIST] Review candidates: {len(candidates)}")
        
        if not candidates and empty_count == 0:
            self._append_log("[BLACKLIST] No candidates found at all.")
            QMessageBox.information(self, "No candidates", "No EULA/long/placeholder strings found.")
            return
        
        # ── Generate CSV report for external review ──
        csv_path = "data/blacklists/blacklist_candidates.csv"
        os.makedirs(os.path.dirname(csv_path) if os.path.dirname(csv_path) else ".", exist_ok=True)
        import csv as _csv
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = _csv.writer(csvfile)
            writer.writerow(["UUID", "Words", "Chars", "Reason", "Preview (first 200 chars)"])
            for key, wc, preview, reason in sorted(candidates, key=lambda x: -x[1]):
                text = strings.get(key, {}).get("Text", "") or ""
                writer.writerow([key, wc, len(text), reason, text[:200].replace("\n", " ")])
        
        self._append_log(f"[BLACKLIST] CSV report saved: {csv_path} ({len(candidates)} candidates, sorted by size)")
        
        # ── Simple dialog: quick actions ──
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Blacklist Builder — {len(candidates)} candidates")
        dlg.resize(500, 300)
        lay = QVBoxLayout(dlg)
        
        summary = QLabel(
            f"<h3>Blacklist Candidates</h3>"
            f"<b>{empty_count}</b> empty strings (safe to skip — included automatically)<br>"
            f"<b>{len(candidates)}</b> candidates for review<br><br>"
            f"Full list exported to:<br>"
            f"<code>{os.path.abspath(csv_path)}</code><br><br>"
            f"<i>Open in Excel to review each text before blacklisting.</i>"
        )
        summary.setWordWrap(True)
        lay.addWidget(summary)
        
        # Show top 10 largest
        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setMaximumHeight(120)
        top10 = sorted(candidates, key=lambda x: -x[1])[:10]
        lines = ["Top 10 largest candidates:"]
        for key, wc, preview, reason in top10:
            lines.append(f"  [{reason}] {wc} words — {preview[:80]}...")
        preview_text.setPlainText("\n".join(lines))
        lay.addWidget(preview_text)
        
        btns = QHBoxLayout()
        
        save_all_btn = QPushButton("💾 Blacklist ALL Candidates")
        save_all_btn.setObjectName("primary")
        save_all_btn.setToolTip(f"Saves all {len(candidates)} candidates + {empty_count} empties to blacklist.json")
        def save_all():
            keys = [key for key, _, _, _ in candidates]
            # Also include empties
            for key, item in strings.items():
                text = item.get("Text", "") or ""
                if not text.strip():
                    keys.append(key)
            out_path, _ = QFileDialog.getSaveFileName(dlg, "Save Blacklist", "data/blacklists/blacklist.json", "JSON (*.json)")
            if out_path:
                os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(keys, f, indent=2)
                self.tr_blacklist.setText(out_path)
                self._append_log(f"[BLACKLIST] Saved {len(keys)} UUIDs → {out_path}")
                QMessageBox.information(dlg, "Saved", f"{len(keys)} items blacklisted.\nFile: {out_path}")
                dlg.accept()
        save_all_btn.clicked.connect(save_all)
        btns.addWidget(save_all_btn)
        
        open_csv_btn = QPushButton("📂 Open CSV in Default App")
        def open_csv():
            os.startfile(os.path.abspath(csv_path))
        open_csv_btn.clicked.connect(open_csv)
        btns.addWidget(open_csv_btn)
        
        btns.addStretch()
        close_btn = QPushButton("Close (review CSV first)")
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        
        self._append_log(f"[BLACKLIST] Showing simple dialog...")
        dlg.exec()
        self._append_log(f"[BLACKLIST] Dialog closed.")

    def _set_all_checks(self, table, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            if item:
                item.setCheckState(state)

    def _save_blacklist_from_table(self, table, candidates, dlg):
        selected = []
        for r in range(table.rowCount()):
            chk = table.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                key_item = table.item(r, 1)
                if key_item:
                    selected.append(key_item.text())

        if not selected:
            QMessageBox.information(self, "None selected", "No items checked.")
            return

        out_path, _ = QFileDialog.getSaveFileName(self, "Save Blacklist", "data/blacklists/blacklist_eula.json", "JSON (*.json)")
        if not out_path:
            return

        try:
            os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(selected, f, indent=2)
            self.tr_blacklist.setText(out_path)
            self._append_log(f"Blacklist saved with {len(selected)} UUIDs → {out_path}")
            QMessageBox.information(self, "Blacklist saved", f"{len(selected)} items blacklisted.\nNow select this file in the Blacklist field and start translation (they will be skipped).")
            dlg.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _prescan_source(self):
        """Classify every UUID in the source file into categories BEFORE spending any API money.
        
        Runs in a background thread to keep the GUI responsive on huge files (78k+ lines).
        """
        input_path = self.tr_input.text().strip()
        glossary_path = self.tr_glossary.text().strip()
        
        if not input_path or not os.path.exists(input_path):
            QMessageBox.warning(self, "No source", "Select a valid Input (English JSON) first.")
            return

        self._append_log("=== PRE-SCAN: Launching background scanner (no API cost) ===")
        
        # Check glossary availability now so we can pass it to the worker
        glossary_available = False
        preserve_on = self.preserve_toggle.isChecked()
        if preserve_on and glossary_path and os.path.exists(glossary_path):
            glossary_available = True
        
        model_now = self.model_edit.currentText().strip() or "deepseek-v4-pro"
        
        # Progress dialog (modal but responsive — worker sends signals)
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("Pre-Scan Running...")
        progress_dlg.setMinimumWidth(400)
        progress_layout = QVBoxLayout(progress_dlg)
        progress_label = QLabel(f"Scanning {os.path.basename(input_path)}...\n0 / ? UUIDs classified")
        progress_label.setWordWrap(True)
        progress_layout.addWidget(progress_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # indeterminate until we know count
        progress_layout.addWidget(progress_bar)
        cancel_btn = QPushButton("Cancel")
        progress_layout.addWidget(cancel_btn)
        
        # Worker thread
        class PrescanWorker(QThread):
            progress_signal = Signal(int, int, str)  # current, total, message
            done_signal = Signal(dict)  # buckets dict
            error_signal = Signal(str)
            
            def __init__(self, input_path, glossary_path, glossary_available, preserve_on):
                super().__init__()
                self.input_path = input_path
                self.glossary_path = glossary_path
                self.glossary_available = glossary_available
                self.preserve_on = preserve_on
            
            def run(self):
                try:
                    import json, os, re as _re, hashlib
                    from datetime import datetime
                    
                    with open(self.input_path, "r", encoding="utf-8") as f:
                        src = json.load(f)
                    strings = src.get("strings", {})
                    total = len(strings)
                    
                    self.progress_signal.emit(0, total, f"Loaded {total:,} UUIDs. Classifying...")
                    
                    # Load glossary
                    glossary = None
                    if self.glossary_available:
                        try:
                            from tradutor import SmartGlossary, DEFAULT_PRESERVE_CATS
                            preserve_cats = set(DEFAULT_PRESERVE_CATS)
                            glossary = SmartGlossary(self.glossary_path, "preserve", preserve_cats)
                        except Exception:
                            pass
                    
                    buckets = {
                        "PRESERVED": [],
                        "SKIP": [],
                        "EULA": [],
                        "SHORT": [],
                        "MEDIUM": [],
                        "LONG": [],
                        "PENDING": [],
                    }
                    
                    SKIP_TEXTS = {"placeholder","tbd","todo","n/a","wip","dummy","test","temp",
                                   "temporary","stub","none","null","blank","empty","missing",
                                   "notext","no text","new text","string","template","sample text",
                                   "lorem ipsum","fixme","fix me","deprecated","obsolete","removed",
                                   "deleted","hidden","unused","reserved","..."}
                    
                    eula_keywords = ["eula", "end user license", "license agreement", 
                                    "terms of service", "privacy policy", "copyright",
                                    "registered trademark", "all rights reserved"]
                    
                    total_chars = 0
                    processed = 0
                    report_every = max(1, total // 20)  # report every 5%
                    next_report = report_every
                    
                    for key, item in strings.items():
                        if self.isInterruptionRequested():
                            self.progress_signal.emit(processed, total, "Cancelled")
                            return
                        
                        text = item.get("Text", "") or ""
                        text_clean = text.strip()
                        
                        # 1. SKIP
                        if not text_clean:
                            buckets["SKIP"].append((key, 0, "(empty)"))
                            processed += 1
                            if processed >= next_report:
                                self.progress_signal.emit(processed, total, f"Classifying... {processed}/{total}")
                                next_report += report_every
                            continue
                        
                        clean_lower = text_clean.lower()
                        clean_lower_stripped = _re.sub(r'^[\[{<(]+|[\]}>)]+$', '', clean_lower)
                        if clean_lower_stripped in SKIP_TEXTS:
                            buckets["SKIP"].append((key, len(text_clean), text_clean[:60]))
                            processed += 1
                            if processed >= next_report:
                                self.progress_signal.emit(processed, total, f"Classifying... {processed}/{total}")
                                next_report += report_every
                            continue
                        
                        wc = 0  # lazy: only computed if EULA-suspect
                        char_count = len(text_clean)
                        total_chars += char_count
                        
                        # 2. EULA — only flag 2000+ word texts (true EULA, not narrative)
                        is_eula = False
                        if char_count > 15000:  # definitely 2000+ words
                            is_eula = True
                        elif char_count > 3000:  # borderline: count words
                            wc = len(text_clean.split())
                            if wc > 2000:
                                is_eula = True
                            elif any(kw in text_clean.lower() for kw in eula_keywords) and wc > 500:
                                is_eula = True
                        
                        if is_eula:
                            wc_str = f"{wc} words: " if wc > 0 else ""
                            buckets["EULA"].append((key, char_count, f"{wc_str}{text_clean[:80]}..."))
                            processed += 1
                            if processed >= next_report:
                                self.progress_signal.emit(processed, total, f"Classifying... {processed}/{total}")
                                next_report += report_every
                            continue
                        
                        # 3. PRESERVED — fast O(1) exact match only (no regex contains)
                        # Full contains matching is done during actual translation.
                        # For Pre-Scan classification, exact match is instant and accurate enough.
                        if glossary:
                            text_lower = text_clean.lower()
                            if text_lower in glossary._preserve_index:
                                buckets["PRESERVED"].append((key, char_count, f"exact: {text_clean[:60]}"))
                                processed += 1
                                if processed >= next_report:
                                    self.progress_signal.emit(processed, total, f"Classifying... {processed}/{total}")
                                    next_report += report_every
                                continue
                        
                        # 4. Length classification
                        if char_count <= 50:
                            buckets["SHORT"].append((key, char_count, text_clean[:60]))
                        elif char_count <= 300:
                            buckets["MEDIUM"].append((key, char_count, text_clean[:60]))
                        elif char_count <= 1000:
                            buckets["LONG"].append((key, char_count, text_clean[:60]))
                        else:
                            buckets["PENDING"].append((key, char_count, text_clean[:60]))
                        
                        processed += 1
                        if processed >= next_report:
                            self.progress_signal.emit(processed, total, f"Classifying... {processed}/{total}")
                            next_report += report_every
                    
                    buckets["_total"] = total
                    buckets["_total_chars"] = total_chars
                    buckets["_source_path"] = os.path.abspath(self.input_path)
                    self.progress_signal.emit(processed, total, "Classification complete! Saving cache...")
                    
                    # Save cache for tradutor.py reuse
                    try:
                        cache = {
                            "source_path": os.path.abspath(self.input_path),
                            "source_hash": hashlib.md5(open(self.input_path, "rb").read()).hexdigest(),
                            "preserve_mode": "preserve" if self.preserve_on else "complete",
                            "scanned_at": datetime.now().isoformat(),
                            "total": total,
                            "buckets": {
                                cat: [item[0] for item in items]
                                for cat, items in buckets.items() if not cat.startswith("_")
                            }
                        }
                        with open("prescan_cache.json", "w", encoding="utf-8") as f:
                            json.dump(cache, f, indent=2)
                        self.progress_signal.emit(processed, total, "Cache saved to prescan_cache.json")
                    except Exception:
                        pass  # non-critical
                    
                    self.done_signal.emit(buckets)
                    
                except Exception as e:
                    self.error_signal.emit(str(e))
        
        worker = PrescanWorker(input_path, glossary_path, glossary_available, preserve_on)
        
        def on_progress(current, total, msg):
            progress_label.setText(f"Scanning {os.path.basename(input_path)}...\n{msg}")
            progress_bar.setRange(0, total)
            progress_bar.setValue(current)
        
        def on_done(buckets):
            progress_dlg.accept()
            self._show_prescan_results(buckets, model_now)
        
        def on_error(err):
            progress_dlg.accept()
            self._append_log(f"Pre-Scan error: {err}")
            QMessageBox.critical(self, "Pre-Scan failed", str(err))
        
        worker.progress_signal.connect(on_progress)
        worker.done_signal.connect(on_done)
        worker.error_signal.connect(on_error)
        cancel_btn.clicked.connect(worker.requestInterruption)
        cancel_btn.clicked.connect(progress_dlg.reject)
        
        worker.start()
        progress_dlg.exec()
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
    
    def _show_prescan_results(self, buckets, model_now):
        """Display the Pre-Scan results dialog (called from background thread completion)."""
        total = buckets["_total"]
        total_chars = buckets["_total_chars"]
        preserved_count = len(buckets["PRESERVED"])
        skip_count = len(buckets["SKIP"])
        eula_count = len(buckets["EULA"])
        to_translate = total - preserved_count - skip_count - eula_count
        
        # Cost estimate
        if "flash" in model_now.lower():
            price_in, price_out = 0.00014, 0.00028
        elif "pro" in model_now.lower() or "reasoner" in model_now.lower():
            price_in, price_out = 0.00055, 0.00219
        else:
            price_in, price_out = 0.00027, 0.00110
        
        translate_chars = sum(item[1] for item in 
            buckets["SHORT"] + buckets["MEDIUM"] + buckets["LONG"] + buckets["PENDING"])
        translate_tokens = translate_chars // 4
        est_cost = round((translate_tokens / 1000) * (price_in + price_out), 2)
        
        # Log
        self._append_log(f"Total UUIDs: {total:,}")
        self._append_log(f"  🟢 PRESERVED (free): {preserved_count} ({round(preserved_count/max(total,1)*100)}%)")
        self._append_log(f"  ⚪ SKIP (free): {skip_count}")
        self._append_log(f"  🔴 EULA (blacklist): {eula_count}")
        self._append_log(f"  📝 SHORT (<=50c): {len(buckets['SHORT'])}")
        self._append_log(f"  📝 MEDIUM (51-300c): {len(buckets['MEDIUM'])}")
        self._append_log(f"  📝 LONG (301-1000c): {len(buckets['LONG'])}")
        self._append_log(f"  ❓ PENDING (>1000c): {len(buckets['PENDING'])}")
        self._append_log(f"To translate: {to_translate:,} | Est. cost: ~${est_cost} ({model_now})")
        
        # Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Pre-Scan Results — {total:,} UUIDs classified")
        dlg.resize(800, 600)
        lay = QVBoxLayout(dlg)
        
        summary = QLabel(
            f"<h3>Pre-Scan Complete — No API Cost</h3>"
            f"<b>{total:,}</b> total UUIDs in source<br><br>"
            f"<span style='color:#4a4'><b>{preserved_count}</b> PRESERVED (glossary match — FREE)</span><br>"
            f"<span style='color:#888'><b>{skip_count}</b> SKIP (placeholders/empty — FREE)</span><br>"
            f"<span style='color:#c44'><b>{eula_count}</b> EULA (very long — blacklist candidate)</span><br>"
            f"<b>{to_translate:,}</b> to translate "
            f"({len(buckets['SHORT'])} short, {len(buckets['MEDIUM'])} medium, "
            f"{len(buckets['LONG'])} long, {len(buckets['PENDING'])} pending)<br><br>"
            f"Est. API cost: <b>${est_cost}</b> with {model_now}<br>"
            f"Savings: {preserved_count + skip_count} strings "
            f"({(preserved_count + skip_count)/max(total,1)*100:.0f}%) cost ZERO "
            f"(exact EN + empty/placeholder; EULA also free at translate time)<br>"
            f"<small>PRESERVED here = <b>exact</b> glossary match only. "
            f"At translate time, terms <b>inside phrases</b> are hard-locked (inline), "
            f"not skipped as whole English sentences. "
            f"Engine also auto-skips empty/placeholder/EULA without a blacklist.</small>"
        )
        summary.setWordWrap(True)
        lay.addWidget(summary)
        
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Category", "Count", "Sample"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        
        for cat_name, icon in [("PRESERVED","🟢"),("SKIP","⚪"),("EULA","🔴"),
                                ("SHORT","📝"),("MEDIUM","📝"),("LONG","📝"),("PENDING","❓")]:
            items = buckets[cat_name]
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(f"{icon} {cat_name}"))
            table.setItem(row, 1, QTableWidgetItem(str(len(items))))
            sample = items[0][2][:100] if items else "(none)"
            table.setItem(row, 2, QTableWidgetItem(sample))
        
        lay.addWidget(table)
        
        btn_row = QHBoxLayout()
        if eula_count > 0:
            eula_btn = QPushButton(f"🛑 Auto-Blacklist {eula_count} EULA Texts")
            eula_btn.setObjectName("danger")
            eula_keys_saved = [False]  # mutable flag
            eula_path_saved = [""]
            def auto_blacklist_eula():
                eula_keys = [item[0] for item in buckets["EULA"]]
                out_path = self.tr_blacklist.text().strip() or "data/blacklists/blacklist_eula.json"
                out_path, _ = QFileDialog.getSaveFileName(dlg, "Save EULA Blacklist", out_path, "JSON (*.json)")
                if out_path:
                    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(eula_keys, f, indent=2)
                    self.tr_blacklist.setText(out_path)
                    eula_keys_saved[0] = True
                    eula_path_saved[0] = out_path
                    self._append_log(f"EULA blacklist saved: {len(eula_keys)} UUIDs → {out_path}")
                    QMessageBox.information(dlg, "Blacklist saved", 
                        f"{len(eula_keys)} EULA texts blacklisted.\nFile: {out_path}")
            eula_btn.clicked.connect(auto_blacklist_eula)
            btn_row.addWidget(eula_btn)
        
        # "Start Optimized Translation" button
        start_btn = QPushButton("🚀 Start Optimized Translation")
        start_btn.setObjectName("primary")
        start_btn.setToolTip(
            "Launches translation with:\n"
            "• Pre-Scan cache (skips re-classification)\n"
            "• Smart batching (50/30/12/5 per length tier)\n"
            "• EULA blacklist auto-applied\n"
            "• Your current model/temperature/workers settings"
        )
        def start_optimized():
            dlg.accept()
            # Ensure EULA blacklist is applied if available
            if eula_count > 0 and not eula_keys_saved[0]:
                eula_keys = [item[0] for item in buckets["EULA"]]
                auto_path = "data/blacklists/blacklist_eula.json"
                os.makedirs(os.path.dirname(auto_path) if os.path.dirname(auto_path) else ".", exist_ok=True)
                with open(auto_path, "w", encoding="utf-8") as f:
                    json.dump(eula_keys, f, indent=2)
                self.tr_blacklist.setText(auto_path)
                self._append_log(f"EULA blacklist auto-saved: {len(eula_keys)} UUIDs → {auto_path}")
            self._start_translation(optimized=True)
        start_btn.clicked.connect(start_optimized)
        btn_row.addWidget(start_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        
        dlg.exec()
    # ───────────────────────────────
    # TAB: GLOSSARY (Critical for preserve flags)
    # ───────────────────────────────
    def _create_glossary_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Path + actions
        # File path row
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Glossary file:"))
        self.glossary_path_edit = QLineEdit(self.settings.value("last_glossary", "glossary.json"))
        self.glossary_path_edit.setMinimumWidth(200)
        path_row.addWidget(self.glossary_path_edit, 1)
        load_btn = QPushButton("Load / Reload")
        load_btn.setMinimumWidth(110)
        load_btn.clicked.connect(self._load_glossary_into_table)
        path_row.addWidget(load_btn)
        save_btn = QPushButton("Save Glossary")
        save_btn.setMinimumWidth(110)
        save_btn.clicked.connect(self._save_glossary_from_table)
        path_row.addWidget(save_btn)
        layout.addLayout(path_row)

        # Main action buttons in a grid so long labels don't get crushed
        actions_grid = QGridLayout()
        actions_grid.setSpacing(6)

        wiki_btn = QPushButton("Wiki Sync (offline data)")
        wiki_btn.clicked.connect(self._wiki_sync_glossary)
        actions_grid.addWidget(wiki_btn, 0, 0)

        pop_btn = QPushButton("Populate First (AI term extraction)")
        pop_btn.setToolTip("Populate glossary with AI term extraction from the source file")
        pop_btn.clicked.connect(self._ai_populate_glossary)
        actions_grid.addWidget(pop_btn, 0, 1)

        live_wiki_btn = QPushButton("Live Wiki (scrape / search)")
        live_wiki_btn.clicked.connect(self._live_wiki_scrape_dialog)
        actions_grid.addWidget(live_wiki_btn, 0, 2)

        audit_btn = QPushButton("Audit Glossary")
        audit_btn.clicked.connect(self._audit_glossary)
        actions_grid.addWidget(audit_btn, 0, 3)

        clean_btn = QPushButton("Clean / Reset")
        clean_btn.setToolTip("Clean / reset glossary for a new generation")
        clean_btn.setObjectName("danger")
        clean_btn.clicked.connect(self._clean_glossary_for_new_generation)
        actions_grid.addWidget(clean_btn, 1, 0)

        resume_pop_btn = QPushButton("Resume Population")
        resume_pop_btn.setToolTip("Resume last glossary population if temp file exists")
        resume_pop_btn.clicked.connect(self._resume_last_population)
        actions_grid.addWidget(resume_pop_btn, 1, 1)

        map_btn = QPushButton("Build Preserve Map")
        map_btn.setToolTip("Build preserve map from source for smart partial preservation")
        map_btn.clicked.connect(self._build_preserve_map)
        actions_grid.addWidget(map_btn, 1, 2)

        small_btn = QPushButton("Create Small Input")
        small_btn.setToolTip("Create small English input for mechanics/full pass from preserve_map")
        small_btn.clicked.connect(self._create_small_mechanics_input)
        actions_grid.addWidget(small_btn, 1, 3)

        translate_wiki_btn = QPushButton("Translate Wiki Terms")
        translate_wiki_btn.setToolTip("Populate PT translations for wiki terms (and preserve=true items) in your glossary. The 'preserve' flag itself decides if the EN version stays in the final JSON during Scenario 2 runs.")
        translate_wiki_btn.clicked.connect(self._translate_wiki_terms)
        actions_grid.addWidget(translate_wiki_btn, 2, 0)

        layout.addLayout(actions_grid)

        # Table
        self.glossary_table = QTableWidget(0, 6)
        self.glossary_table.setHorizontalHeaderLabels(["Term (EN)", "Translation (PT)", "Category", "Preserve", "Source", "Context"])
        self.glossary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.glossary_table.setAlternatingRowColors(True)
        self.glossary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.glossary_table.itemChanged.connect(self._on_glossary_table_changed)
        layout.addWidget(self.glossary_table, 1)

        # Row actions
        row_actions = QHBoxLayout()
        add_btn = QPushButton("+ Add Term")
        add_btn.clicked.connect(self._add_glossary_row)
        row_actions.addWidget(add_btn)

        del_btn = QPushButton("Delete Selected")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected_glossary_rows)
        row_actions.addWidget(del_btn)

        search_lbl = QLabel("Filter:")
        row_actions.addWidget(search_lbl)
        self.glossary_filter = QLineEdit()
        self.glossary_filter.textChanged.connect(self._filter_glossary_table)
        row_actions.addWidget(self.glossary_filter)

        row_actions.addStretch()
        layout.addLayout(row_actions)

        return w

    def _on_glossary_table_changed(self, item):
        """Schedule an auto-save 1 second after the user stops editing the glossary table."""
        if item is None:
            return
        self._glossary_save_timer.stop()
        self._glossary_save_timer.start(1000)

    def _load_glossary_into_table(self):
        path = self.glossary_path_edit.text().strip()
        if not path or not os.path.exists(path):
            path, _ = QFileDialog.getOpenFileName(self, "Load Glossary", "", "JSON (*.json)")
            if not path:
                return
            self.glossary_path_edit.setText(path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            terms = data.get("terms", [])
            self.glossary_table.setRowCount(0)

            # Block itemChanged while (re)loading: programmatic inserts are not
            # user edits and must not arm the auto-save debounce. (Fixes #5)
            self.glossary_table.blockSignals(True)
            try:
                for term in terms:
                    row = self.glossary_table.rowCount()
                    self.glossary_table.insertRow(row)

                    self.glossary_table.setItem(row, 0, QTableWidgetItem(term.get("term_english", "")))
                    self.glossary_table.setItem(row, 1, QTableWidgetItem(term.get("term_translated", "")))
                    self.glossary_table.setItem(row, 2, QTableWidgetItem(term.get("category", "")))

                    # Preserve checkbox column
                    preserve_item = QTableWidgetItem()
                    preserve_item.setCheckState(Qt.Checked if term.get("preserve") else Qt.Unchecked)
                    self.glossary_table.setItem(row, 3, preserve_item)

                    self.glossary_table.setItem(row, 4, QTableWidgetItem(term.get("source", "")))
                    self.glossary_table.setItem(row, 5, QTableWidgetItem(term.get("context", "")))
            finally:
                self.glossary_table.blockSignals(False)

            self._append_log(f"Loaded {len(terms)} terms from glossary.")
            self._update_status(f"Glossary: {len(terms)} terms")
            self.settings.setValue("last_glossary", path)
        except Exception as e:
            QMessageBox.critical(self, "Failed to load glossary", str(e))

    def _save_glossary_from_table(self, silent: bool = False):
        path = self.glossary_path_edit.text().strip()
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save Glossary", "glossary.json", "JSON (*.json)")
            if not path:
                return
            self.glossary_path_edit.setText(path)

        try:
            # Load existing data to preserve metadata for unchanged terms
            existing_terms = {}
            existing_metadata = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                    existing_metadata = old_data.get("metadata", {})
                    for t in old_data.get("terms", []):
                        key = t.get("term_english", "").strip().lower()
                        if key:
                            existing_terms[key] = t
                except Exception:
                    pass

            terms = []
            for row in range(self.glossary_table.rowCount()):
                en = self.glossary_table.item(row, 0).text().strip() if self.glossary_table.item(row, 0) else ""
                if not en:
                    continue
                pt = self.glossary_table.item(row, 1).text().strip() if self.glossary_table.item(row, 1) else en
                cat = self.glossary_table.item(row, 2).text().strip() if self.glossary_table.item(row, 2) else "outro"
                preserve = self.glossary_table.item(row, 3).checkState() == Qt.Checked if self.glossary_table.item(row, 3) else False
                src = self.glossary_table.item(row, 4).text().strip() if self.glossary_table.item(row, 4) else "manual"

                # Preserve existing metadata for this term (usage_count, created_at, confidence, etc.)
                en_key = en.strip().lower()
                old_entry = existing_terms.get(en_key, {})
                
                term = {
                    "term_english": en,
                    "term_translated": pt,
                    "category": cat,
                    "preserve": preserve,
                    "source": src or old_entry.get("source", "manual"),
                    "context": (self.glossary_table.item(row, 5).text().strip() if self.glossary_table.item(row, 5) else old_entry.get("context", "")),
                    "confidence": old_entry.get("confidence", "high"),
                    "usage_count": old_entry.get("usage_count", 1),
                    "created_at": old_entry.get("created_at", datetime.now().isoformat()),
                }
                terms.append(term)

            data = {
                "metadata": {
                    "version": "2.1",
                    "updated_at": datetime.now().isoformat(),
                    "total_terms": len(terms)
                },
                "terms": terms
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._append_log(f"Saved glossary with {len(terms)} terms → {path}")
            if silent:
                # Debounced auto-save: status bar only, no modal popup. (#5)
                self._update_status(f"Glossary auto-saved ({len(terms)} terms)")
            else:
                QMessageBox.information(self, "Saved", f"Glossary saved with {len(terms)} terms.")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _add_glossary_row(self):
        row = self.glossary_table.rowCount()
        self.glossary_table.insertRow(row)
        self.glossary_table.setItem(row, 0, QTableWidgetItem("New Term"))
        self.glossary_table.setItem(row, 1, QTableWidgetItem("Nova Tradução"))
        self.glossary_table.setItem(row, 2, QTableWidgetItem("outro"))
        pitem = QTableWidgetItem()
        pitem.setCheckState(Qt.Unchecked)
        self.glossary_table.setItem(row, 3, pitem)
        self.glossary_table.setItem(row, 4, QTableWidgetItem("manual"))
        self.glossary_table.setItem(row, 5, QTableWidgetItem("Added from GUI"))

    def _delete_selected_glossary_rows(self):
        rows = sorted({idx.row() for idx in self.glossary_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.glossary_table.removeRow(r)

    def _filter_glossary_table(self, text: str):
        text = text.lower()
        for row in range(self.glossary_table.rowCount()):
            match = False
            for col in range(6):
                item = self.glossary_table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            self.glossary_table.setRowHidden(row, not match)

    def _wiki_sync_glossary(self):
        # For now we call the wiki_sync script via process so it uses the embedded data
        glossary = self.glossary_path_edit.text().strip()
        if not glossary:
            QMessageBox.warning(self, "No glossary", "Load or specify a glossary file first.")
            return

        cmd = [sys.executable, "wiki_sync.py", "--glossary", glossary, "--sync"]
        self._run_external(cmd, "Wiki Sync")

    def _translate_wiki_terms(self):
        """Translate English wiki terms in the glossary into Portuguese using the LLM.

        Only touches terms where source is 'wiki' or preserve=True and term_translated == term_english
        (i.e. wiki_sync imported them but left them untranslated).
        """
        self._append_log("[WIKI-TRANSLATE] Button clicked.")
        try:
            glossary_path = self.glossary_path_edit.text().strip()
            if not glossary_path or not os.path.exists(glossary_path):
                QMessageBox.warning(self, "No glossary", "Load or specify a glossary file first.")
                return

            abs_glossary = os.path.abspath(glossary_path)
            self._append_log(f"[WIKI-TRANSLATE] Reading glossary from: {abs_glossary}")
            self._append_log(f"[WIKI-TRANSLATE] Glossary tab path: '{glossary_path}'")
            self._append_log(f"[WIKI-TRANSLATE] Translate tab glossary (if set): '{self.tr_glossary.text().strip()}'")

            key = self.api_key_edit.text().strip()
            has_env_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            if not key and not has_env_key:
                QMessageBox.warning(self, "No API key", "Configure an API key before translating wiki terms.")
                return

            with open(glossary_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            terms = data.get("terms", [])
            to_translate = []
            for term in terms:
                src = term.get("source", "").lower()
                en = term.get("term_english", "").strip()
                pt = term.get("term_translated", "").strip()
                preserve = term.get("preserve", False)
                # Match wiki-sourced OR preserve-flagged terms that still have English as translation
                is_wiki_sourced = "wiki" in src or "wh40k" in src
                if (is_wiki_sourced or preserve) and (not pt or pt.lower() == en.lower()):
                    # Snapshot original for change detection
                    term["_orig_pt"] = pt
                    to_translate.append(term)

            if not to_translate:
                QMessageBox.information(self, "Nothing to translate", "No wiki terms need translation (they already have PT translations or there are no wiki terms).")
                return

            model = self.model_edit.currentText().strip()
            wiki_batch = 30  # must match the WikiTranslateWorker batch_size below (#7)
            n_calls = (len(to_translate) + wiki_batch - 1) // wiki_batch
            reply = QMessageBox.question(
                self, "Translate Wiki Terms",
                f"Found {len(to_translate)} wiki/preserve terms without Portuguese translation.\n\n"
                f"This will send {len(to_translate)} terms to the LLM in batches of {wiki_batch}\n"
                f"({n_calls} API calls, up to 3 in parallel) using model: {model}.\n\n"
                f"ESTIMATED COST: ${round(len(to_translate) * 0.001, 2)}–${round(len(to_translate) * 0.005, 2)} USD\n"
                f"(depends on model pricing; flash models are much cheaper)\n\n"
                f"TIP: ALL {len(to_translate)} terms will be translated to Portuguese.\n"
                f"• Uses grimdark WH40k tone throughout\n"
                f"• Model: {model} | Temperature: 0.2 (creative)\n\n"
                f"This ONLY affects the glossary file. Continue?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            glossary_path = self.glossary_path_edit.text().strip()  # re-read for clarity
            abs_glossary = os.path.abspath(glossary_path)
            self._append_log(f"=== Translating {len(to_translate)} wiki terms into Portuguese ===")
            self._append_log(f"[WIKI-TARGET] Will save results to: {abs_glossary}")
            self.progress.setValue(0)

            provider = self.provider_combo.currentText()
            model = self.model_edit.currentText().strip()
            base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            self._append_log(f"[WIKI-TRANSLATE] Using model='{model}'  (detailed raw LLM responses + truncation detection will be logged)")
            self._wiki_worker = WikiTranslateWorker(to_translate, model, key, provider, base_url, batch_size=wiki_batch)
            worker = self._wiki_worker
            worker.log.connect(self._append_log)
            worker.progress.connect(lambda cur, tot, msg: self.progress.setValue(int(cur / max(tot, 1) * 100)))

            def on_finished(success, message):
                self.cancel_btn.setEnabled(False)
                if success:
                    try:
                        # Count actual changes for the user
                        updated = 0
                        unchanged_sample = []
                        for t in to_translate:
                            orig_pt = (t.get("_orig_pt", "") or "").strip().lower()
                            new_pt = (t.get("term_translated", "") or "").strip()
                            if new_pt and new_pt.lower() != orig_pt:
                                updated += 1
                            elif not new_pt:
                                unchanged_sample.append(t.get("term_english", "?"))
                            # clean temp snapshot key
                            if "_orig_pt" in t:
                                del t["_orig_pt"]

                        abs_path = os.path.abspath(glossary_path)
                        file_size_before = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0

                        with open(abs_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)

                        file_size_after = os.path.getsize(abs_path)
                        self._load_glossary_into_table()

                        self._append_log(f"=== {message} ===")
                        self._append_log(f"[WIKI-SAVE] ABSOLUTE PATH: {abs_path}")
                        self._append_log(f"[WIKI-SAVE] File size: {file_size_before:,} → {file_size_after:,} bytes")
                        self._append_log(f"[WIKI-SAVE] {updated} terms received new Portuguese translations")
                        if unchanged_sample:
                            self._append_log(f"[WIKI-SAVE] {len(unchanged_sample)} terms still empty (no translation returned): {unchanged_sample[:5]}")

                        # Extra verification: re-load and show first translated terms
                        try:
                            with open(abs_path, "r", encoding="utf-8") as f:
                                saved = json.load(f)
                            # Show first 3 terms that have a PT translation different from EN
                            translated_sample = []
                            for s in saved.get("terms", []):
                                en = s.get("term_english", "")
                                pt = s.get("term_translated", "")
                                if pt and pt.lower() != en.lower():
                                    translated_sample.append(f"'{en}' -> '{pt}'")
                                    if len(translated_sample) >= 3:
                                        break
                            if translated_sample:
                                self._append_log(f"[WIKI-VERIFY] Sample translations on disk: {', '.join(translated_sample)}")
                            else:
                                self._append_log(f"[WIKI-VERIFY] WARNING: No translated terms found on disk! Something went wrong.")
                                # Fallback: show first 3 terms regardless
                                for s in saved.get("terms", [])[:3]:
                                    self._append_log(f"[WIKI-VERIFY] First term: '{s.get('term_english')}' -> '{s.get('term_translated')}'")
                        except Exception as ve:
                            self._append_log(f"[WIKI-VERIFY] Could not re-check file: {ve}")

                        self._append_log("   → Switch to the Glossary tab. The table was auto-reloaded from disk.")
                        self._append_log("   → Use the Filter field at the bottom of the Glossary tab to find terms.")
                        self._append_log("   Note: 'Translate Wiki Terms' ONLY updates the glossary.json (term_translated field).")
                        self._append_log("         It does NOT change your game JSON files or wiki data. Use the updated glossary in a normal translation run to see effects.")

                        QMessageBox.information(self, "Wiki Terms Translated", 
                            f"{message}\n\nUpdated {updated} terms in the glossary.\nFile: {glossary_path}")
                    except Exception as e:
                        QMessageBox.critical(self, "Save failed", str(e))
                else:
                    self._append_log(f"=== {message} ===")
                    if "cancel" in (message or "").lower():
                        QMessageBox.information(self, "Wiki Translation", message or "Cancelled")
                    else:
                        QMessageBox.warning(self, "Wiki Translation Failed", message)

            worker.finished_signal.connect(on_finished)
            self.cancel_btn.setEnabled(True)
            worker.start()
            self._append_log("[WIKI-TRANSLATE] Worker started. Check the Operation Log pane for raw model output on any failures.")

        except Exception as e:
            self._append_log(f"[WIKI-TRANSLATE] Unexpected error: {e}")
            QMessageBox.critical(self, "Wiki Translation Error", f"Unexpected error: {e}")

    def _ai_populate_glossary(self):
        """Support for user's request: populate glossary first (using IA / term extraction) before full translation.

        This flow now prioritizes the wiki_sync terms. Steps run asynchronously so the GUI stays (more) responsive
        and you can watch live output in the log pane at the bottom.
        """
        glossary = self.glossary_path_edit.text().strip()
        if not glossary:
            glossary, _ = QFileDialog.getSaveFileName(self, "Glossary to populate / create", "glossary_populated.json", "JSON (*.json)")
            if not glossary:
                return
            self.glossary_path_edit.setText(glossary)

        source = self.tr_input.text().strip()
        if not source or not os.path.exists(source):
            source, _ = QFileDialog.getOpenFileName(self, "Select English Source for AI term extraction", "", "JSON (*.json)")
            if not source:
                return

        # Store pending for chaining after wiki step
        self._pending_population_source = source
        self._pending_population_glossary = glossary

        # === Step 1: Wiki sync (if user wants) ===
        reply = QMessageBox.question(
            self, "Include Official Wiki Terms?",
            "Do you want to first add the terms that live in wiki_sync.py\n"
            "(~2694 Rogue Trader wiki terms: talents, weapons, abilities, armour, consumables, etc.)\n"
            "into the glossary with preserve=true?\n\n"
            "This is strongly recommended before any AI extraction or translation.\n\n"
            "IMPORTANT: On very large files the operation can take a long time.\n"
            "The log pane at the bottom will keep updating even if the window feels slow.\n"
            "For a live external console, close this GUI and run:\n"
            "    python tradutor_desktop.py",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._append_log("=== Step 1/2: Running wiki_sync to seed the glossary with official game terms ===")
            self._append_log("Output will appear live in the log below. Please wait...")
            cmd = [sys.executable, "wiki_sync.py", "--glossary", glossary, "--sync"]
            key = self.api_key_edit.text().strip()
            self._save_key_if_checked()
            env = os.environ.copy()
            if key:
                env["DEEPSEEK_API_KEY"] = key
                env["OPENAI_API_KEY"] = key
                if "GLM" in self.provider_combo.currentText() or "Zhipu" in self.provider_combo.currentText():
                    env["DEEPSEEK_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
                else:
                    env["DEEPSEEK_BASE_URL"] = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            self._run_external(cmd, "Wiki Sync (official terms)", custom_env=env if key else None)
            # Chaining → AI extraction happens in _on_worker_finished
        else:
            reply2 = QMessageBox.question(
                self, "AI Term Extraction — COSTS REAL MONEY",
                "This will launch tradutor.py with --extract-every 20 + small batches.\n"
                "The LLM will be called for term extraction every ~20 batches (not translation — dry-run mode).\n\n"
                "On large files (tens of thousands of strings) this costs money in API usage.\n"
                "Example: 50k strings → ~312 extraction calls (~$1-3 with flash, more with pro).\n\n"
                "Only do this if your glossary really needs the extra terms beyond the wiki sync.\n\n"
                "Continue and spend tokens?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply2 == QMessageBox.Yes:
                # Rough estimate
                est = "unknown"
                try:
                    with open(source, "r", encoding="utf-8") as f:
                        sd = json.load(f)
                    n = len(sd.get("strings", {}))
                    est = f"~{n} strings → many batches + extractions"
                except:
                    pass
                # Extra strong guard: require explicit acceptance text
                confirm, ok = QInputDialog.getText(
                    self,
                    "Confirm expensive operation",
                    f"Source size: {est}\n\nType exactly: I ACCEPT THE COST\n(to proceed with AI glossary population):"
                )
                if ok and confirm.strip().upper() == "I ACCEPT THE COST":
                    self._start_ai_extraction_step(source, glossary)
                else:
                    self._append_log("AI glossary population cancelled (cost confirmation not accepted).")
            else:
                self._append_log("AI glossary population cancelled by user.")

    def _start_ai_extraction_step(self, source, glossary):
        """Helper to start the AI extraction (step 2). Called directly or chained after wiki."""
        self._append_log("=== Step 2/2: AI Glossary Population (term extraction) ===")
        self._append_log(f"Source: {source}")
        self._append_log(f"Target glossary: {glossary}")
        self._append_log("Strategy: wiki_sync terms (preserve mechanics) are now in the glossary.")
        self._append_log("Running light AI pass to extract additional terms specific to your data file.")
        self._append_log("WARNING: This makes quite a few LLM calls (extract-every 3). Use only when you really need new terms.")
        self._append_log("This can take a LONG time and cost real money on very large files (78k+ lines).")
        self._append_log("Watch the log pane at the bottom for progress (batches, extracted terms).")
        self._append_log("The GUI may feel slow but the work continues in background.")
        self._append_log("When you see 'finished successfully', then review the glossary and run the real translation.")

        model_for_pop = self.model_edit.currentText().strip() or "deepseek-v4-pro"
        # Use extract_every=20 (was 3) to dramatically reduce API calls.
        # For a 50k string file: 50k/8 = 6250 batches → 6250/20 = ~312 extraction calls (vs ~2083 with every=3)
        cmd = [sys.executable, "tradutor.py", "-i", source, "-o", "glossary_pass_temp.json", "-g", glossary,
               "--extract-every", "20", "--dry-run", "--auto-glossary", "--batch-size", "8",
               "--model", model_for_pop]

        if os.path.exists("glossary_pass_temp.json"):
            cmd += ["--resume"]
            self._append_log("Resuming previous glossary population (glossary_pass_temp.json exists). This avoids re-processing the entire file.")

        # Pass key from GUI field if present (same pattern as real translation)
        key = self.api_key_edit.text().strip()
        provider = self.provider_combo.currentText()
        env = os.environ.copy()
        if key:
            env["DEEPSEEK_API_KEY"] = key
            env["OPENAI_API_KEY"] = key
        if "GLM" in provider or "Zhipu" in provider:
            env["DEEPSEEK_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
        else:
            if "DEEPSEEK_BASE_URL" not in env:
                env["DEEPSEEK_BASE_URL"] = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        self._run_external(cmd, "AI Glossary Population (term extraction)", custom_env=env if key else None)
        # Completion dialog is shown in _on_worker_finished.

    def _live_wiki_scrape_dialog(self):
        """Manual / on-demand wiki connection (user request for live instead of only offline scrape)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Live / Manual Wiki Scrape")
        lay = QVBoxLayout(dlg)

        info = QLabel("Search the live WH40K Rogue Trader Wiki (roguetrader.wh40k.wiki) via its\n"
                      "official MediaWiki API and add the found page to your glossary as a preserve term.\n\n"
                      "For bulk seeding prefer 'Wiki Sync (offline data)'; use this for individual new terms.")
        info.setWordWrap(True)
        lay.addWidget(info)

        form = QHBoxLayout()
        form.addWidget(QLabel("Term or Category to fetch/add:"))
        term_edit = QLineEdit()
        term_edit.setPlaceholderText("e.g. Plasma Gun or talent")
        form.addWidget(term_edit)
        lay.addLayout(form)

        btn_fetch = QPushButton("Search Live Wiki + Add to Current Glossary")
        def do_fetch():
            term = term_edit.text().strip()
            if not term:
                return
            glossary = self.glossary_path_edit.text().strip()
            if not glossary:
                QMessageBox.warning(dlg, "No glossary", "Specify a glossary file first.")
                return
            self._append_log(f"Live wiki search for '{term}' via MediaWiki API...")
            try:
                import urllib.request, urllib.parse

                API = "https://roguetrader.wh40k.wiki/api.php"
                UA = {"User-Agent": "W40kTradutor/1.0 (fan translation tool; github.com/ltsuemitsu/w40k-tradutor)"}

                def wiki_api(params):
                    url = API + "?" + urllib.parse.urlencode(dict(params, format="json"))
                    req = urllib.request.Request(url, headers=UA)
                    with urllib.request.urlopen(req, timeout=15) as r:
                        return json.load(r)

                # 1) search for the best matching page
                s = wiki_api({"action": "query", "list": "search", "srsearch": term, "srlimit": "1"})
                hits = s.get("query", {}).get("search", [])
                if not hits:
                    self._append_log(f"  No wiki results for '{term}'.")
                    QMessageBox.information(dlg, "Not found", f"No wiki page found for '{term}'.")
                    return
                title = hits[0]["title"]

                # 2) fetch page wikitext (follows redirects)
                w = wiki_api({"action": "query", "prop": "revisions", "rvprop": "content",
                              "rvslots": "main", "titles": title, "redirects": "1"})
                page = next(iter(w.get("query", {}).get("pages", {}).values()))
                if "missing" in page or "revisions" not in page:
                    raise RuntimeError(f"page '{title}' has no content")
                resolved = page.get("title", title)
                wikitext = page["revisions"][0]["slots"]["main"]["*"]

                # 3) light parsing: infobox template name + a few descriptive fields
                m = re.search(r"\{\{\s*([A-Za-z][A-Za-z0-9 _-]*)", wikitext)
                template = m.group(1).strip() if m else ""
                fields = dict(re.findall(r"\n\|([A-Za-z0-9_]+)=([^\n|]*)", wikitext))
                interesting = [f"{k}={fields[k].strip()}" for k in
                               ("type", "family", "category", "rarity", "cargo_type")
                               if fields.get(k) and fields[k].strip()]
                page_url = "https://roguetrader.wh40k.wiki/wiki/" + urllib.parse.quote(resolved.replace(" ", "_"))

                cat_map = {"weapon": "weapon", "talent": "talent", "ability": "ability",
                           "skill": "skill", "homeworld": "homeworld", "archetype": "archetype",
                           "armour": "armour", "consumable": "consumable"}
                category = cat_map.get(template.lower(), "wiki_live")
                context = f"WH40K Wiki — {template or 'page'}"
                if interesting:
                    context += ": " + ", ".join(interesting[:4])
                context += f" ({page_url})"

                # 4) add to glossary (skip duplicates)
                data = {"terms": []}
                if os.path.exists(glossary):
                    with open(glossary, "r", encoding="utf-8") as f:
                        data = json.load(f)
                existing = {t.get("term_english", "").strip().lower() for t in data.get("terms", [])}
                if resolved.lower() in existing:
                    self._append_log(f"  '{resolved}' already in glossary — skipped.")
                    QMessageBox.information(dlg, "Already there", f"'{resolved}' is already in the glossary.")
                    return
                data.setdefault("terms", []).append({
                    "term_english": resolved,
                    "term_translated": resolved,
                    "category": category,
                    "preserve": True,
                    "source": "live_wiki",
                    "context": context,
                    "confidence": "medium",
                    "usage_count": 1,
                    "created_at": datetime.now().isoformat(),
                })
                with open(glossary, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._append_log(f"  Added '{resolved}' [{category}] from live wiki: {context}")
                self._load_glossary_into_table()
                QMessageBox.information(dlg, "Added", f"'{resolved}' added from the live wiki.\n\n{context}")
                dlg.accept()
            except Exception as ex:
                self._append_log(f"  Live fetch error (add manually if needed): {ex}")
                QMessageBox.warning(dlg, "Fetch issue", f"Could not fetch '{term}' from the live wiki. You can add it manually in the table with preserve checked.\n\nError: {ex}")
        btn_fetch.clicked.connect(do_fetch)
        lay.addWidget(btn_fetch)

        lay.addWidget(QLabel("Alternative (recommended for robustness): Use 'Wiki Sync (offline data)' + manual table edits for wiki terms."))

        dlg.exec()

    def _audit_glossary(self):
        """Audit the current glossary for quality, duplicates, and relevance to the loaded source."""
        glossary_path = self.glossary_path_edit.text().strip()
        if not glossary_path or not os.path.exists(glossary_path):
            QMessageBox.warning(self, "No glossary", "Load or specify a glossary file first.")
            return

        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            terms = data.get("terms", [])
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return

        if not terms:
            self._append_log("Glossary is empty.")
            return

        # 1. Duplicates
        seen = {}
        duplicates = []
        for t in terms:
            key = t.get("term_english", "").strip().lower()
            if not key:
                continue
            if key in seen:
                duplicates.append(t.get("term_english"))
            else:
                seen[key] = True

        # 2. Poor quality (no context, low confidence, empty translation)
        poor = []
        for t in terms:
            if not t.get("context", "").strip():
                poor.append((t.get("term_english"), "no context"))
            if t.get("confidence", "high") == "low":
                poor.append((t.get("term_english"), "low confidence"))
            if t.get("term_translated", "").strip() == "":
                poor.append((t.get("term_english"), "empty translation"))

        # 3. Coverage vs current source (if loaded)
        source_path = self.tr_input.text().strip()
        used_in_source = 0
        never_used = []
        source_texts = ""
        if source_path and os.path.exists(source_path):
            try:
                with open(source_path, "r", encoding="utf-8") as f:
                    src = json.load(f)
                for item in src.get("strings", {}).values():
                    source_texts += " " + (item.get("Text", "") or "").lower()
                for t in terms:
                    eng = t.get("term_english", "").lower()
                    if eng and eng in source_texts:
                        used_in_source += 1
                    else:
                        never_used.append(t.get("term_english"))
            except Exception:
                pass

        # Report
        report = []
        report.append(f"Total terms: {len(terms)}")
        report.append(f"Duplicates found: {len(duplicates)}")
        if duplicates:
            report.append("  Examples: " + ", ".join(duplicates[:5]))
        report.append(f"Poor quality entries: {len(poor)}")
        if poor:
            report.append("  Examples: " + ", ".join([f"{p[0]} ({p[1]})" for p in poor[:5]]))

        if source_path and os.path.exists(source_path):
            report.append(f"Terms that appear in current source: {used_in_source}")
            report.append(f"Terms that NEVER appear in current source: {len(never_used)}")
            if never_used:
                report.append("  (These may be dead weight or from old patches)")

        self._append_log("\n=== GLOSSARY AUDIT ===")
        for line in report:
            self._append_log(line)

        QMessageBox.information(self, "Glossary Audit", "\n".join(report[:12]) + "\n\nFull details in the log pane below.")

    def _clean_glossary_for_new_generation(self):
        """Clean or reset the glossary for a fresh start / new file generation."""
        glossary_path = self.glossary_path_edit.text().strip()
        if not glossary_path:
            QMessageBox.warning(self, "No glossary", "Specify a glossary file first.")
            return

        reply = QMessageBox.question(
            self,
            "Clean Glossary",
            "This will BACKUP your current glossary and then give you options to clean it.\n\n"
            "Options:\n"
            "• Keep ONLY official wiki terms (recommended for new generation)\n"
            "• Remove user-added and low-confidence terms\n"
            "• Full reset (empty glossary)\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Always backup first
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{glossary_path}.{ts}.backup.json"
        try:
            import shutil  # defensive import (in case of reload issues)
            shutil.copy2(glossary_path, backup_path)
            self._append_log(f"Backup created: {backup_path}")
        except Exception as e:
            QMessageBox.critical(self, "Backup failed", str(e))
            return

        # Ask what kind of clean
        options = [
            "Keep ONLY official wiki terms (cleanest for new file)",
            "Remove user-added and low-confidence terms",
            "Full reset (empty glossary)",
            "Cancel"
        ]
        import PySide6.QtWidgets as QtW  # defensive
        choice, ok = QtW.QInputDialog.getItem(
            self, "Choose Clean Mode", "What kind of clean do you want?", options, 0, False
        )
        if not ok or choice == "Cancel":
            return

        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_terms = data.get("terms", [])
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return

        def is_wiki_term(t):
            # wiki_sync.py writes source="wh40k_wiki"; older terms may use
            # "WH40K Wiki ...". Normalize case and separators so the clean can
            # never silently wipe the whole glossary again. (Fixes #2)
            src = (t.get("source") or "").lower().replace("-", "_").replace(" ", "_")
            return src.startswith("wh40k")

        if "ONLY official wiki" in choice:
            new_terms = [t for t in all_terms if is_wiki_term(t)]
            action = "kept only official wiki terms"
        elif "user-added and low" in choice:
            new_terms = [
                t for t in all_terms
                if is_wiki_term(t) or t.get("confidence") == "high"
            ]
            action = "removed most user-added / low-confidence terms"
        else:
            new_terms = []
            action = "performed full reset"

        data["terms"] = new_terms
        data["metadata"] = data.get("metadata", {})
        data["metadata"]["updated_at"] = datetime.now().isoformat()
        data["metadata"]["total_terms"] = len(new_terms)

        try:
            with open(glossary_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._append_log(f"Glossary cleaned: {action} ({len(new_terms)} terms remaining)")
            self._load_glossary_into_table()
            QMessageBox.information(
                self, "Clean Complete",
                f"Glossary cleaned ({action}).\n\n"
                f"Backup: {os.path.basename(backup_path)}\n"
                f"Remaining terms: {len(new_terms)}\n\n"
                "You can now re-run Wiki Sync or Populate Glossary First for a fresh generation."
            )
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _resume_last_population(self):
        """Resume the last glossary population extraction if the temp file exists."""
        if not os.path.exists("glossary_pass_temp.json"):
            QMessageBox.information(self, "No temp file", "No previous glossary_pass_temp.json found. Start a new population from the 'Populate Glossary First' button or the main flow.")
            return

        source = self.tr_input.text().strip()
        if not source or not os.path.exists(source):
            source, _ = QFileDialog.getOpenFileName(self, "Select the English source to resume population on", "", "JSON (*.json)")
            if not source:
                return

        glossary = self.glossary_path_edit.text().strip()
        if not glossary:
            glossary, _ = QFileDialog.getOpenFileName(self, "Select the glossary", "", "JSON (*.json)")
            if not glossary:
                return
            self.glossary_path_edit.setText(glossary)

        self._start_ai_extraction_step(source, glossary)

    def _build_preserve_map(self):
        """Scan the current English source with the current glossary (preserve=true terms) and build a map of which UUIDs contain which terms.
        This map can be used in full translation to give the LLM specific 'preserve these phrases inside the text' instructions for mixed strings.
        """
        source_path = self.tr_input.text().strip()
        glossary_path = self.glossary_path_edit.text().strip()
        if not source_path or not os.path.exists(source_path):
            QMessageBox.warning(self, "No source", "Load an English source first.")
            return
        if not glossary_path or not os.path.exists(glossary_path):
            QMessageBox.warning(self, "No glossary", "Load a glossary first.")
            return

        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                gdata = json.load(f)
            preserve_terms = [t["term_english"] for t in gdata.get("terms", []) if t.get("preserve")]
            if not preserve_terms:
                QMessageBox.information(self, "No preserve terms", "No terms with preserve=true in the glossary.")
                return

            with open(source_path, "r", encoding="utf-8") as f:
                sdata = json.load(f)

            preserve_map = {}
            for key, item in sdata.get("strings", {}).items():
                text = item.get("Text", "") or ""
                text_lower = text.lower()
                found = []
                for term in preserve_terms:
                    if term.lower() in text_lower:  # simple contains; can improve with word boundaries
                        found.append(term)
                if found:
                    preserve_map[key] = found

            map_path = "preserve_map.json"
            with open(map_path, "w", encoding="utf-8") as f:
                json.dump(preserve_map, f, indent=2, ensure_ascii=False)

            self._append_log(f"Preserve map built with {len(preserve_map)} UUIDs → {map_path}")
            self._append_log("In a full translation pass, strings in the map will get specific preserve instructions for the listed terms.")
            QMessageBox.information(self, "Map built", f"preserve_map.json created with {len(preserve_map)} entries.\nUse it in full translation for partial preserve on mixed texts (e.g. descriptions that contain a talent name).")
        except Exception as e:
            QMessageBox.critical(self, "Build failed", str(e))

    def _create_small_mechanics_input(self):
        """Using the preserve_map, extract only the UUIDs that contained preserve terms, creating a small English JSON.
        Use this small file as input for a full translation pass (preserve OFF), then use Merge to apply the resulting PT mechanics into your main translated file from the preserve pass.
        This way you translate the narrative only once, and the mechanics in a tiny second pass.
        """
        map_path = "preserve_map.json"
        source = self.tr_input.text().strip()
        if not os.path.exists(map_path) or not source or not os.path.exists(source):
            QMessageBox.warning(self, "Missing", "Need preserve_map.json and the English source loaded.")
            return
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                pmap = json.load(f)
            uuids = set(pmap.keys())
            with open(source, "r", encoding="utf-8") as f:
                idata = json.load(f)
            small_strings = {k: idata["strings"][k] for k in uuids if k in idata.get("strings", {})}
            small = {"strings": small_strings}
            out_path = "mechanics_for_full.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(small, f, indent=2, ensure_ascii=False)
            self._append_log(f"Created small input {out_path} with {len(small_strings)} UUIDs (the ones that had preserve terms).")
            self._append_log("Use this as Input for a full translation pass (preserve OFF, using the glossary for consistency).")
            self._append_log("Then use the Merge tab to apply the resulting PT texts for those UUIDs into your main pt file from the preserve pass.")
            QMessageBox.information(self, "Small input created", f"{out_path} ready. Run full translation on it, then merge back.")
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))

    # ───────────────────────────────
    # TAB: AUDIT & MERGE
    # ───────────────────────────────
    def _create_audit_merge_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Audit
        ag = QGroupBox("Audit Translation (find untranslated / broken tags)")
        al = QVBoxLayout(ag)
        self.audit_en = self._file_row(al, "Original EN", "data/en/enGB.json", lambda l: self._pick_file(l, "EN"))
        self.audit_pt = self._file_row(al, "Translated PT", "data/pt/ptBR.json", lambda l: self._pick_file(l, "PT"))
        self.audit_gloss = self._file_row(al, "Glossary (optional)", "glossary.json", lambda l: self._pick_file(l, "Glossary"))

        audit_btns = QHBoxLayout()
        audit_btn = QPushButton("Run Audit")
        audit_btn.clicked.connect(self._run_audit)
        audit_btns.addWidget(audit_btn)
        audit_btns.addStretch()
        al.addLayout(audit_btns)
        layout.addWidget(ag)

        # Merge
        mg = QGroupBox("Merge Corrections (Scenario 4)")
        ml = QVBoxLayout(mg)
        self.merge_base = self._file_row(ml, "Base PT file", "data/pt/ptBR.json", lambda l: self._pick_file(l, "Base PT"))
        self.merge_corrections = self._file_row(ml, "Corrections / Delta output", "data/en/delta_fix.json", lambda l: self._pick_file(l, "Corrections"))

        merge_btns = QHBoxLayout()
        merge_btn = QPushButton("Preview & Merge")
        merge_btn.setObjectName("primary")
        merge_btn.clicked.connect(self._run_merge)
        merge_btns.addWidget(merge_btn)
        merge_btns.addStretch()
        ml.addLayout(merge_btns)
        layout.addWidget(mg)

        layout.addStretch()
        return w

    def _run_audit(self):
        en = self.audit_en.text().strip()
        pt = self.audit_pt.text().strip()
        gloss = self.audit_gloss.text().strip()

        if not (en and pt):
            QMessageBox.warning(self, "Missing files", "Need both original EN and translated PT.")
            return

        cmd = [sys.executable, "diff_tool.py", "-i", en, "-t", pt, "--audit"]
        if gloss:
            cmd += ["--glossary", gloss]
        self._run_external(cmd, "Audit")

    def _run_merge(self):
        base = self.merge_base.text().strip()
        corr = self.merge_corrections.text().strip()
        if not (base and corr):
            QMessageBox.warning(self, "Missing", "Need base PT and corrections file.")
            return

        # For safety we always suggest --backup
        out_path, _ = QFileDialog.getSaveFileName(self, "Output file (can overwrite base)", base, "JSON (*.json)")
        if not out_path:
            return

        cmd = [sys.executable, "merge.py", "-b", base, "-c", corr, "-o", out_path, "--backup"]
        self._run_external(cmd, "Merge")

    # ───────────────────────────────
    # Core execution helpers
    # ───────────────────────────────
    def _start_translation(self, optimized=False):
        inp = self.tr_input.text().strip()
        outp = self.tr_output.text().strip()
        gloss = self.tr_glossary.text().strip()

        if not (inp and outp):
            QMessageBox.warning(self, "Missing files", "Input and Output paths are required.")
            return

        preserve_on = self.preserve_toggle.isChecked()

        # Stronger guard: rough count of work + model cost hint + budget confirmation for large jobs
        try:
            with open(inp, "r", encoding="utf-8") as f:
                src = json.load(f)
            n_items = len(src.get("strings", {})) if isinstance(src, dict) else 0
            model_now = self.model_edit.currentText().strip()
            
            # Optimized mode: show the smart batching strategy before starting
            if optimized:
                strings = src.get("strings", {})
                short = sum(1 for v in strings.values() if len(v.get("Text", "")) <= 50)
                medium = sum(1 for v in strings.values() if 50 < len(v.get("Text", "")) <= 300)
                long_ = sum(1 for v in strings.values() if 300 < len(v.get("Text", "")) <= 1000)
                xlong = sum(1 for v in strings.values() if len(v.get("Text", "")) > 1000)
                def _nb(count, size):
                    return count // size + (1 if count % size else 0)
                est_batches = _nb(short, 50) + _nb(medium, 30) + _nb(long_, 12) + _nb(xlong, 5)
                self._append_log("[OPTIMIZED] Smart batching strategy (by text length):")
                self._append_log(f"  Short  (≤50 chars):    {short:>6} strings → {_nb(short,50):>4} batches × 50")
                self._append_log(f"  Medium (51-300 chars): {medium:>6} strings → {_nb(medium,30):>4} batches × 30")
                self._append_log(f"  Long   (301-1000):     {long_:>6} strings → {_nb(long_,12):>4} batches × 12")
                self._append_log(f"  XLong  (>1000 chars):  {xlong:>6} strings → {_nb(xlong,5):>4} batches × 5")
                self._append_log(f"  Total estimated batches: ~{est_batches}")

            # Rough token & cost estimate
            total_chars = sum(len(item.get("Text", "")) for item in src.get("strings", {}).values())
            est_tokens = total_chars // 4
            est_input_tokens = est_tokens  # input tokens
            
            # Output tokens roughly same as input for translation
            if "v4-flash" in model_now.lower() or "flash" in model_now.lower():
                price_per_1k_in = 0.00014  # DeepSeek flash pricing
                price_per_1k_out = 0.00028
                model_tier = "cheap"
            elif "v4-pro" in model_now.lower() or "reasoner" in model_now.lower() or "pro" in model_now.lower():
                price_per_1k_in = 0.00055  # ~DeepSeek pro pricing
                price_per_1k_out = 0.00219
                model_tier = "expensive"
            elif "glm" in model_now.lower():
                price_per_1k_in = 0.0005
                price_per_1k_out = 0.0005
                model_tier = "mid"
            else:
                price_per_1k_in = 0.00027  # default deepseek-chat
                price_per_1k_out = 0.00110
                model_tier = "mid"
            
            est_cost = (est_input_tokens / 1000) * price_per_1k_in + (est_input_tokens / 1000) * price_per_1k_out
            est_cost = round(est_cost, 2)
            
            preserve_info = ""
            if preserve_on and gloss and os.path.exists(gloss):
                try:
                    from tradutor import SmartGlossary
                    g = SmartGlossary(gloss, "preserve")
                    # O(1) exact match only — fast enough for 77k strings on UI thread
                    preserve_count = sum(1 for item in src.get("strings", {}).values()
                                        if item.get("Text", "").strip().lower() in g._preserve_index)
                    if preserve_count > 0:
                        pct = round(preserve_count / max(n_items, 1) * 100)
                        preserve_info = (
                            f" | Exact glossary EN (free): ~{preserve_count} ({pct}%) "
                            f"— plus inline locks at translate time"
                        )
                except Exception:
                    pass

            self._append_log(f"[BUDGET] Input: ~{n_items} strings | ~{est_tokens:,} tokens | Est. cost: ${est_cost}{preserve_info}")
            self._append_log(f"[BUDGET] Model: {model_now} (tier: {model_tier})")

            # WARNING for expensive configurations
            if n_items > 5000 and model_tier == "expensive":
                warning_msg = (
                    f"⚠️  LARGE JOB + EXPENSIVE MODEL DETECTED\n\n"
                    f"• {n_items:,} strings to process\n"
                    f"• Model: {model_now} (expensive tier)\n"
                    f"• Estimated API cost: ~${est_cost}\n\n"
                )
                if preserve_on:
                    warning_msg += (
                        "Preserve ON — exact wiki terms stay EN (free); "
                        "phrases with terms still translate with hard locks.\n\n"
                    )
                warning_msg += (
                    f"RECOMMENDATION: Switch to a cheaper model to save money:\n"
                    f"• deepseek-v4-flash (fast + cheap, ~10x cheaper)\n"
                    f"• deepseek-chat (balanced)\n\n"
                    f"Or reduce batch size / use --resume on an existing output.\n\n"
                    f"Continue with {model_now} anyway?"
                )
                reply = QMessageBox.warning(self, "Budget Warning — Expensive Job", warning_msg,
                                           QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No:
                    self._append_log("[BUDGET] User cancelled — switch to a cheaper model and try again.")
                    return
                self._append_log("[BUDGET] User accepted the cost estimate. Proceeding...")
        except Exception:
            pass

        cmd = [sys.executable, "tradutor.py", "-i", inp, "-o", outp]
        if gloss:
            cmd += ["-g", gloss]

        if preserve_on:
            from tradutor import DEFAULT_PRESERVE_CATS_CSV
            cmd += ["--mode", "preserve", "--preserve-cats", DEFAULT_PRESERVE_CATS_CSV]
        else:
            cmd += ["--mode", "complete"]

        if self.dry_run_cb.isChecked():
            cmd.append("--dry-run")

        # Pre-Scan cache: skip re-classification of preserved/skip/eula UUIDs
        if os.path.exists("prescan_cache.json"):
            cmd += ["--prescan-cache", "prescan_cache.json"]
            self._append_log("[CACHE] Pre-Scan cache found — tradutor.py will skip re-classification for known UUIDs (O(1) lookups).")

        # Auto-resume if output already exists with content (prevents re-sending already translated strings to the API and burning budget)
        if os.path.exists(outp):
            try:
                with open(outp, "r", encoding="utf-8") as f:
                    prev = json.load(f)
                if prev and prev.get("strings"):
                    cmd.append("--resume")
                    self._append_log(f"[RESUME] Output file exists with {len(prev.get('strings',{}))} entries — skipping completed items to save API budget.")
            except Exception:
                pass  # if unreadable, just run without resume

        model_name = self.model_edit.currentText().strip() or "deepseek-v4-flash"
        w_val = self.workers_spin.value()
        cmd += [
            "-b", str(self.batch_spin.value()),
            "-w", str(w_val if w_val > 0 else 0),
            "--temperature", str(self.temp_spin.value()),
            "--model", model_name,
            "--optimized-batch",
        ]

        key = self.api_key_edit.text().strip()
        provider = self.provider_combo.currentText()
        env = os.environ.copy()
        if key:
            env["DEEPSEEK_API_KEY"] = key
            env["OPENAI_API_KEY"] = key
            env["ZHIPU_API_KEY"] = key
            env["KIMI_API_KEY"] = key
            env["MOONSHOT_API_KEY"] = key

        # Base URL: explicit field wins
        base = ""
        if hasattr(self, "base_url_edit"):
            base = self.base_url_edit.text().strip()
        if not base:
            if "GLM" in provider or "Zhipu" in provider:
                base = "https://open.bigmodel.cn/api/paas/v4"
            elif "Kimi" in provider:
                base = "https://api.kimi.com/coding/v1"
            elif "Custom" in provider:
                base = env.get("DEEPSEEK_BASE_URL") or "https://api.openai.com/v1"
            else:
                base = "https://api.deepseek.com"
        env["DEEPSEEK_BASE_URL"] = base

        env_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("KIMI_API_KEY")
        )
        if key:
            key_source = "from input field"
        elif env_key:
            key_source = "from environment variable"
        else:
            key_source = "NOT SET — translation will fail"

        try:
            from model_profiles import profile_summary
            self._append_log("Profile: " + profile_summary(model_name))
        except Exception:
            pass
        if "glm-5.2" in model_name.lower() or "v4-pro" in model_name.lower():
            self._append_log(
                "NOTE: Premium model — output is expensive. "
                "deepseek-v4-flash is the bulk default if cost matters."
            )

        self._append_log(f"Starting translation: {' '.join(cmd)}")
        self._append_log(f"Model: {model_name}")
        self._append_log(
            f"Preserve mode: {'ON (exact EN + inline term lock)' if preserve_on else 'OFF (full translate)'}"
        )
        self._append_log(
            f"Provider: {provider} | Base URL: {env.get('DEEPSEEK_BASE_URL')} | Key: {key_source}"
        )
        if self.tr_blacklist.text().strip():
            cmd += ["--blacklist", self.tr_blacklist.text().strip()]

        # Preserve map: where to save the UUID -> preserved terms mapping
        preserve_map_path = self.tr_preserve_map.text().strip() or "preserve_map.json"
        if preserve_on:
            cmd += ["--preserve-map", preserve_map_path]

        # Smart batches always on (engine default); flag kept for older tradutor.py)
        if optimized or True:
            cmd.append("--optimized-batch")

        task_label = "Preserve Translation" if preserve_on else "Full Translation"
        if self.dry_run_cb.isChecked():
            task_label = "Dry Run — " + task_label
        self._start_with_worker(cmd, task_label, env)

    def _start_fullize(self):
        """Free Full track: glossary EN→PT replace on the Preserved output (no LLM)."""
        src = self.tr_output.text().strip()
        outp = self.tr_full_output.text().strip() if hasattr(self, "tr_full_output") else ""
        gloss = self.tr_glossary.text().strip() or (
            self.glossary_path_edit.text().strip() if hasattr(self, "glossary_path_edit") else ""
        )

        if not src or not os.path.exists(src):
            QMessageBox.warning(
                self, "No Preserved file",
                "Set Output — Preserved PT to an existing preserve-mode result first.\n\n"
                "Run step 1 (Start Preserve Translation) before Fullize.",
            )
            return
        if not outp:
            QMessageBox.warning(self, "No Full output path", "Set Output — Full PT path.")
            return
        if not gloss or not os.path.exists(gloss):
            QMessageBox.warning(self, "No glossary", "Glossary is required for Fullize (EN→PT map).")
            return

        reply = QMessageBox.question(
            self, "Fullize (FREE — no API)",
            f"Build 100% PT file from preserved translation?\n\n"
            f"Input (preserved):\n  {src}\n\n"
            f"Output (full):\n  {outp}\n\n"
            f"Glossary:\n  {gloss}\n\n"
            f"No LLM calls — longest-first word-boundary replace of glossary terms.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        cmd = [
            sys.executable, "tradutor.py", "--fullize",
            "-i", src, "-o", outp, "-g", gloss,
        ]
        self._append_log(f"Fullize (free): {' '.join(cmd)}")
        self._start_with_worker(cmd, "Fullize (free EN→PT)", os.environ.copy())

    def _start_second_pass(self):
        """LEGACY: LLM retranslate of preserve-map UUIDs. Prefer Fullize for Full track."""
        tip = QMessageBox.information(
            self, "Prefer Fullize",
            "For the Full (100% PT) track, use Fullize — it is free and uses your glossary PT terms.\n\n"
            "Continue with the paid LLM 2nd pass only if you need model rewriting beyond glossary replace.",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if tip != QMessageBox.Ok:
            return

        inp = self.tr_input.text().strip()
        if not inp or not os.path.exists(inp):
            QMessageBox.warning(self, "No input", "Please select a valid Input (English JSON) first.")
            return

        preserve_map_path = self.tr_preserve_map.text().strip() or "preserve_map.json"
        if not os.path.exists(preserve_map_path):
            QMessageBox.warning(
                self, "Preserve map not found",
                f"No preserve map found at:\n{preserve_map_path}\n\n"
                "Run a preserve-mode translation first to generate the map of preserved UUIDs."
            )
            return

        # Suggest an output name based on the current output field
        base_out = self.tr_output.text().strip() or "data/pt/ptBR.json"
        out = base_out
        if base_out.endswith(".json"):
            out = base_out[:-5] + "_retranslated.json"
        else:
            out = base_out + "_retranslated.json"

        cmd = [sys.executable, "tradutor.py", "-i", inp, "-o", out]
        gloss = self.tr_glossary.text().strip()
        if gloss:
            cmd += ["-g", gloss]

        # Second pass is always complete mode (no preservation)
        cmd += ["--mode", "complete"]
        cmd += ["--retranslate-map", preserve_map_path]

        # Guard for second pass too
        try:
            with open(inp, "r", encoding="utf-8") as f:
                src = json.load(f)
            n_items = len(src.get("strings", {})) if isinstance(src, dict) else 0
            self._append_log(f"[GUARD] Second-pass input has ~{n_items} strings (will be filtered by the map).")
        except Exception:
            pass

        if self.dry_run_cb.isChecked():
            cmd.append("--dry-run")

        # Pre-Scan cache for second pass too
        if os.path.exists("prescan_cache.json"):
            cmd += ["--prescan-cache", "prescan_cache.json"]

        # Auto-resume for second pass too (if the chosen retranslate output already has work)
        if os.path.exists(out):
            try:
                with open(out, "r", encoding="utf-8") as f:
                    prev = json.load(f)
                if prev and prev.get("strings"):
                    cmd.append("--resume")
                    self._append_log(f"[RESUME] Second-pass output exists with prior entries — skipping completed.")
            except Exception:
                pass

        cmd += [
            "-b", str(self.batch_spin.value()),
            "-w", str(self.workers_spin.value()),
            "--temperature", str(self.temp_spin.value()),
            "--model", self.model_edit.currentText().strip() or "deepseek-v4-pro"
        ]

        # Provider / key handling
        key = self.api_key_edit.text().strip()
        provider = self.provider_combo.currentText()
        env = os.environ.copy()
        if key:
            env["DEEPSEEK_API_KEY"] = key
            env["OPENAI_API_KEY"] = key
        if "GLM" in provider or "Zhipu" in provider:
            env["DEEPSEEK_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
            if not self.model_edit.currentText().strip() or self.model_edit.currentText().strip() in ("deepseek-chat", "deepseek-v4-pro"):
                self.model_edit.setCurrentText("glm-4-plus")
        elif "Custom" in provider:
            pass
        else:
            if "DEEPSEEK_BASE_URL" not in env:
                env["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"

        self._append_log(f"Starting SECOND PASS (retranslate preserved UUIDs): {' '.join(cmd)}")
        self._append_log(f"Preserve mode: OFF (full localized translation on {preserve_map_path})")
        self._append_log(f"Provider: {provider} | Base URL effective: {env.get('DEEPSEEK_BASE_URL', '(default)')}")
        model_name2 = self.model_edit.currentText().strip() or "deepseek-v4-pro"
        if "v4-pro" in model_name2.lower() or "reasoner" in model_name2.lower():
            self._append_log("⚠️  WARNING: Expensive model selected for second pass.")

        self._start_with_worker(cmd, "Second-Pass Translation", env)

    def _run_external(self, cmd: List[str], task_name: str, custom_env: Optional[dict] = None):
        """ponytail: one runner — same TranslationWorker path as translate."""
        self._start_with_worker(cmd, task_name, custom_env)

    def _start_with_worker(self, cmd: List[str], task_name: str, env: Optional[dict] = None):
        """Launch any CLI via TranslationWorker (cmd fully built by caller)."""
        self._append_log(f"=== {task_name} started ===")
        self.progress.setValue(0)
        self.cancel_btn.setEnabled(True)

        self.active_worker = TranslationWorker(cmd=cmd, env=env)
        self.active_worker.signals.log.connect(self._append_log)
        self.active_worker.signals.progress.connect(self._on_worker_progress)
        self.active_worker.signals.stats.connect(self._on_worker_stats)
        self.active_worker.signals.finished.connect(lambda ok, msg: self._on_worker_finished(ok, msg, task_name))
        self.active_worker.start()

    def _on_worker_progress(self, current: int, total: int, message: str):
        pct = int((current / max(total, 1)) * 100)
        self.progress.setValue(pct)
        self._append_log(f"[progress] {message} ({current}/{total})")

    def _on_worker_stats(self, stats: dict):
        self._append_log(
            f"[stats] Tokens: {stats.get('tokens', '?')} | Est. cost: ${stats.get('cost_usd', '?')} | "
            f"Preserved: {stats.get('preserved', '?')}"
        )

    def _on_worker_finished(self, success: bool, message: str, task_name: str):
        self._append_log(f"=== {task_name} finished: {message} ===")
        self.progress.setValue(100 if success else 60)
        self.cancel_btn.setEnabled(False)
        self.active_worker = None

        # Populate-glossary chain: wiki sync → AI extraction
        if task_name == "Wiki Sync (official terms)":
            if success and self._pending_population_source and self._pending_population_glossary:
                self._append_log("Wiki Sync succeeded. Starting AI extraction step...")
                try:
                    with open(self._pending_population_source, "r", encoding="utf-8") as f:
                        sd = json.load(f)
                    n = len(sd.get("strings", {}))
                    est_api_calls = max(1, n // 8 // 20)  # batch_size=8, extract_every=20
                    model_now = self.model_edit.currentText().strip() or "deepseek-v4-pro"
                    confirm_msg = (
                        f"Wiki Sync done! Now: AI term extraction.\n\n"
                        f"Source: ~{n:,} strings → ~{est_api_calls} extraction API calls.\n"
                        f"Model: {model_now}\n\n"
                        f"ESTIMATED COST: ${round(est_api_calls * 0.003, 2)}–${round(est_api_calls * 0.01, 2)} USD\n\n"
                        f"RECOMMENDATION: Use deepseek-v4-flash for this step.\n\n"
                        f"Continue with AI extraction?"
                    )
                    reply = QMessageBox.question(
                        self, "Budget Confirmation — AI Extraction", confirm_msg,
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if reply != QMessageBox.Yes:
                        self._append_log("AI extraction cancelled by user after wiki sync.")
                        self._pending_population_source = None
                        self._pending_population_glossary = None
                        self._update_status(f"{task_name} completed successfully.")
                        return
                except Exception:
                    pass
                self._start_ai_extraction_step(
                    self._pending_population_source,
                    self._pending_population_glossary,
                )
                self._pending_population_source = None
                self._pending_population_glossary = None
            elif not success:
                self._append_log(
                    "Wiki Sync failed. Try 'Wiki Sync (offline data)' manually, then run population again."
                )
                self._pending_population_source = None
                self._pending_population_glossary = None

        elif task_name == "AI Glossary Population (term extraction)":
            if success:
                QMessageBox.information(
                    self, "Glossary Population Complete",
                    "Both steps finished.\n\n"
                    "Go to the Glossary tab, review the new terms (edit Preserve flags if needed),\n"
                    "then run your normal translation.",
                )
            else:
                QMessageBox.warning(
                    self, "Population Finished with Errors",
                    f"{message}\n\nCheck the log. You may still have partial results in the glossary.",
                )

        if success and task_name in (
            "Wiki Sync (official terms)",
            "AI Glossary Population (term extraction)",
            "Wiki Sync",
        ):
            self._load_glossary_into_table()
            self._append_log("Glossary table reloaded with updated file.")

        if success:
            self._update_status(f"{task_name} completed successfully.")
        else:
            self._update_status(f"{task_name} failed or cancelled (see log).")

    def _cancel_current(self):
        cancelled = False
        if self.active_worker:
            try:
                self.active_worker.cancel()
                self._append_log("=== Cancellation requested ===")
            except Exception as e:
                self._append_log(f"Error cancelling worker: {e}")
            cancelled = True
        if hasattr(self, "_wiki_worker") and self._wiki_worker is not None:
            try:
                if self._wiki_worker.isRunning():
                    self._wiki_worker.cancel()
                    self._append_log("=== Cancellation requested for Wiki Terms translation ===")
                    cancelled = True
            except Exception as e:
                self._append_log(f"Error cancelling wiki worker: {e}")

        if cancelled:
            self.cancel_btn.setEnabled(False)
        else:
            self._append_log("No running task to cancel.")

    def _append_log(self, text: str):
        self.log.append(text.rstrip())
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _update_status(self, msg: str):
        self.status.showMessage(msg)

    # ───────────────────────────────
    # ───────────────────────────────
    # Project / Workspace System (full support for interactive app vision)
    # ───────────────────────────────
    def _update_project_label(self):
        if self.current_project_path:
            name = os.path.basename(self.current_project_path)
            self.project_label.setText(f"📁 Project: {name}")
            self.project_label.setStyleSheet("color: #f0d9a0; font-weight: bold; padding: 2px 4px;")
        else:
            self.project_label.setText("No project loaded — use File → New/Open Project or the buttons above")
            self.project_label.setStyleSheet("color: #c9a84c; font-weight: bold; padding: 2px 4px;")

    def _collect_current_state(self) -> dict:
        """Collects the full UI state for saving as a project.

        All widget accesses are wrapped in try/except RuntimeError to guard against
        the occasional "C++ object already deleted" (libshiboken) errors that can occur
        with PySide6 on some Windows configurations or during complex UI lifetime events.
        We fall back to the last known in-memory state (self.current_project) or empty strings.
        """
        def safe_text(widget):
            if widget is None:
                return ""
            try:
                return widget.text().strip()
            except RuntimeError:
                # The C++ object was deleted underneath the Python wrapper.
                return ""

        def safe_checked(widget):
            if widget is None:
                return False
            try:
                return widget.isChecked()
            except RuntimeError:
                return False

        def safe_index(widget):
            if widget is None:
                return 0
            try:
                return widget.currentIndex()
            except RuntimeError:
                return 0

        def safe_value(widget):
            if widget is None:
                return 0
            try:
                return widget.value()
            except RuntimeError:
                return 0

        # Prefer current UI, fall back to last saved state if a widget is "dead"
        last = self.current_project.get("translate", {}) if self.current_project else {}

        state = {
            "version": "1.0",
            "saved_at": datetime.now().isoformat(),
            # Translate tab (dual-track)
            "translate": {
                "input": safe_text(getattr(self, 'tr_input', None)) or last.get("input", ""),
                "output": safe_text(getattr(self, 'tr_output', None)) or last.get("output", ""),
                "full_output": safe_text(getattr(self, 'tr_full_output', None)) or last.get("full_output", ""),
                "glossary": safe_text(getattr(self, 'tr_glossary', None)) or safe_text(getattr(self, 'glossary_path_edit', None)) or last.get("glossary", ""),
                "blacklist": safe_text(getattr(self, 'tr_blacklist', None)) if hasattr(self, 'tr_blacklist') else last.get("blacklist", ""),
                "preserve_map": safe_text(getattr(self, 'tr_preserve_map', None)) if hasattr(self, 'tr_preserve_map') else last.get("preserve_map", ""),
                "preserve": safe_checked(getattr(self, 'preserve_toggle', None)) if hasattr(self, 'preserve_toggle') else last.get("preserve", True),
                "provider_index": safe_index(getattr(self, 'provider_combo', None)) if hasattr(self, 'provider_combo') else last.get("provider_index", 0),
                "model": getattr(self, 'model_edit', None).currentText().strip() if (hasattr(self, 'model_edit') and self.model_edit is not None) else last.get("model", "deepseek-v4-pro"),
                "batch_size": safe_value(getattr(self, 'batch_spin', None)) if hasattr(self, 'batch_spin') else last.get("batch_size", 10),
                "workers": safe_value(getattr(self, 'workers_spin', None)) if hasattr(self, 'workers_spin') else last.get("workers", 3),
                "temperature": safe_value(getattr(self, 'temp_spin', None)) if hasattr(self, 'temp_spin') else last.get("temperature", 0.15),
                "dry_run": safe_checked(getattr(self, 'dry_run_cb', None)) if hasattr(self, 'dry_run_cb') else last.get("dry_run", False),
            },
            # Game Update tab (Scenario 3)
            "update": {
                "new_en": safe_text(getattr(self, 'up_new', None)) or (self.current_project.get("update", {}).get("new_en", "") if self.current_project else ""),
                "old_en": safe_text(getattr(self, 'up_old', None)) or (self.current_project.get("update", {}).get("old_en", "") if self.current_project else ""),
                "current_pt": safe_text(getattr(self, 'up_current_pt', None)) or (self.current_project.get("update", {}).get("current_pt", "") if self.current_project else ""),
            },
            # Glossary & Audit/Merge paths
            "glossary": safe_text(getattr(self, 'glossary_path_edit', None)) or (self.current_project.get("glossary", "") if self.current_project else ""),
            "audit": {
                "en": safe_text(getattr(self, 'audit_en', None)) or (self.current_project.get("audit", {}).get("en", "") if self.current_project else ""),
                "pt": safe_text(getattr(self, 'audit_pt', None)) or (self.current_project.get("audit", {}).get("pt", "") if self.current_project else ""),
                "gloss": safe_text(getattr(self, 'audit_gloss', None)) or (self.current_project.get("audit", {}).get("gloss", "") if self.current_project else ""),
            },
            "merge": {
                "base": safe_text(getattr(self, 'merge_base', None)) or (self.current_project.get("merge", {}).get("base", "") if self.current_project else ""),
                "corrections": safe_text(getattr(self, 'merge_corrections', None)) or (self.current_project.get("merge", {}).get("corrections", "") if self.current_project else ""),
            },
        }
        return state

    def _apply_project_state(self, proj: dict):
        """Restores UI from a saved project dict."""
        try:
            # Translate
            t = proj.get("translate", {})
            if t.get("input"): self.tr_input.setText(t["input"])
            if t.get("output"): self.tr_output.setText(t["output"])
            if t.get("full_output") and hasattr(self, "tr_full_output"):
                self.tr_full_output.setText(t["full_output"])
            if t.get("glossary"):
                self.tr_glossary.setText(t["glossary"])
                if hasattr(self, "glossary_path_edit"):
                    self.glossary_path_edit.setText(t["glossary"])
            if t.get("blacklist") and hasattr(self, "tr_blacklist"):
                self.tr_blacklist.setText(t["blacklist"])
            if t.get("preserve_map") and hasattr(self, "tr_preserve_map"):
                self.tr_preserve_map.setText(t["preserve_map"])
            self.preserve_toggle.setChecked(t.get("preserve", True))
            if "provider_index" in t:
                self.provider_combo.setCurrentIndex(t["provider_index"])
            if t.get("model"):
                self.model_edit.setCurrentText(t["model"])
            if "batch_size" in t: self.batch_spin.setValue(t["batch_size"])
            if "workers" in t: self.workers_spin.setValue(t["workers"])
            if "temperature" in t: self.temp_spin.setValue(t["temperature"])
            if "dry_run" in t: self.dry_run_cb.setChecked(t["dry_run"])

            # Update tab
            u = proj.get("update", {})
            if u.get("new_en"): self.up_new.setText(u["new_en"])
            if u.get("old_en"): self.up_old.setText(u["old_en"])
            if u.get("current_pt"): self.up_current_pt.setText(u["current_pt"])

            # Glossary
            g = proj.get("glossary", "")
            if g:
                self.glossary_path_edit.setText(g)
                # Optionally auto-load the glossary table
                if os.path.exists(g):
                    self._load_glossary_into_table()

            # Audit
            a = proj.get("audit", {})
            if a.get("en"): self.audit_en.setText(a["en"])
            if a.get("pt"): self.audit_pt.setText(a["pt"])
            if a.get("gloss"): self.audit_gloss.setText(a["gloss"])

            # Merge
            m = proj.get("merge", {})
            if m.get("base"): self.merge_base.setText(m["base"])
            if m.get("corrections"): self.merge_corrections.setText(m["corrections"])

            self._append_log(f"Project state restored. Preserve mode: {'ON' if self.preserve_toggle.isChecked() else 'OFF'}")
        except Exception as e:
            self._append_log(f"Warning: partial project load: {e}")

    def _new_project(self):
        self.current_project = {}
        self.current_project_path = None

        # Clear translate
        self.tr_input.clear()
        self.tr_output.clear()
        self.tr_glossary.clear()
        if hasattr(self, "tr_blacklist"):
            self.tr_blacklist.clear()
        if hasattr(self, "tr_preserve_map"):
            self.tr_preserve_map.clear()
        self.preserve_toggle.setChecked(True)
        self.provider_combo.setCurrentIndex(0)
        self.model_edit.setCurrentText("deepseek-v4-pro")
        self.batch_spin.setValue(10)
        self.workers_spin.setValue(3)
        self.temp_spin.setValue(0.15)
        self.dry_run_cb.setChecked(False)

        # Clear glossary tab
        self.glossary_path_edit.clear()
        if hasattr(self, "glossary_table"):
            self.glossary_table.setRowCount(0)

        # Clear update
        self.up_new.clear()
        self.up_old.clear()
        self.up_current_pt.clear()
        if hasattr(self, "update_results"):
            self.update_results.clear()

        # Clear audit/merge
        self.audit_en.clear()
        self.audit_pt.clear()
        self.audit_gloss.clear()
        self.merge_base.clear()
        self.merge_corrections.clear()

        self._update_project_label()
        self._update_status("New project started. Configure your files and Save Project when ready.")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "W40K Project (*.w40k *.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                proj = json.load(f)
            self.current_project = proj
            self.current_project_path = path

            self._apply_project_state(proj)

            self._update_project_label()
            self._add_to_recent_projects(path)
            self._update_status(f"Project loaded: {os.path.basename(path)}")
            self._append_log(f"Opened project: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Load project failed", str(e))

    def _save_project(self):
        default_name = "my_translation.w40k"
        if self.current_project_path:
            default_name = self.current_project_path

        path, _ = QFileDialog.getSaveFileName(self, "Save Project", default_name, "W40K Project (*.w40k *.json)")
        if not path:
            return

        try:
            # Collect the CURRENT UI state. _collect_current_state() wraps every
            # widget access in try/except RuntimeError and falls back to the last
            # known in-memory state, so this is safe even if a widget's C++
            # object was deleted. (Fixes #1: saving used to write the stale
            # last-loaded state, losing all current UI edits.)
            state = self._collect_current_state()
            state["project_path"] = path

            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            self.current_project = state
            self.current_project_path = path

            try:
                self._update_project_label()
            except Exception:
                pass
            self._add_to_recent_projects(path)
            self._update_status(f"Project saved: {os.path.basename(path)}")
            self._append_log(f"Project saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save project failed", str(e))

    def _add_to_recent_projects(self, path: str):
        if path not in self.recent_projects:
            self.recent_projects.insert(0, path)
            self.recent_projects = self.recent_projects[:8]  # keep last 8
            self.settings.setValue("recent_projects", self.recent_projects)
            self._rebuild_recent_menu()
        else:
            # move to top if already present
            self.recent_projects.remove(path)
            self.recent_projects.insert(0, path)
            self.settings.setValue("recent_projects", self.recent_projects)
            self._rebuild_recent_menu()

    def _load_recent_projects(self):
        rec = self.settings.value("recent_projects", [])
        if isinstance(rec, list):
            self.recent_projects = [p for p in rec if os.path.exists(p)][:8]
        else:
            self.recent_projects = []

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        if not self.recent_projects:
            act = QAction("(no recent projects)", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)
            return

        for p in self.recent_projects:
            name = os.path.basename(p)
            act = QAction(name, self)
            act.setToolTip(p)
            act.triggered.connect(lambda checked=False, path=p: self._open_recent_project(path))
            self.recent_menu.addAction(act)

        self.recent_menu.addSeparator()
        clear_act = QAction("Clear Recent List", self)
        clear_act.triggered.connect(self._clear_recent_projects)
        self.recent_menu.addAction(clear_act)

    def _open_recent_project(self, path: str):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                self.current_project = proj
                self.current_project_path = path
                self._apply_project_state(proj)
                self._update_project_label()
                self._add_to_recent_projects(path)  # move to top
                self._update_status(f"Opened recent project: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Failed to open recent project", str(e))
        else:
            QMessageBox.warning(self, "Project not found", f"The project file no longer exists:\n{path}")
            if path in self.recent_projects:
                self.recent_projects.remove(path)
                self.settings.setValue("recent_projects", self.recent_projects)
                self._rebuild_recent_menu()

    def _clear_recent_projects(self):
        self.recent_projects = []
        self.settings.setValue("recent_projects", [])
        self._rebuild_recent_menu()

    def _load_last_paths(self):
        # Load last used paths + last open project if available.
        # Everything is wrapped defensively because on some systems/Qt versions
        # child widgets (QLineEdit etc.) can have their C++ side deleted by the
        # time this deferred call runs, causing "Internal C++ object already deleted".
        try:
            g = self.settings.value("last_glossary")
            if g and os.path.exists(g):
                if hasattr(self, "tr_glossary") and self.tr_glossary is not None:
                    self.tr_glossary.setText(g)
                if hasattr(self, "glossary_path_edit") and self.glossary_path_edit is not None:
                    self.glossary_path_edit.setText(g)

            # Restore blacklist
            bl = self.settings.value("last_blacklist")
            if bl and os.path.exists(bl) and hasattr(self, "tr_blacklist") and self.tr_blacklist is not None:
                self.tr_blacklist.setText(bl)
            # Restore preserve map
            pm = self.settings.value("last_preserve_map")
            if pm and os.path.exists(pm) and hasattr(self, "tr_preserve_map") and self.tr_preserve_map is not None:
                self.tr_preserve_map.setText(pm)

            # Try to restore last opened project automatically
            last_proj = self.settings.value("last_project_path")
            if last_proj and os.path.exists(last_proj):
                with open(last_proj, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                self.current_project = proj
                self.current_project_path = last_proj
                self._apply_project_state(proj)
                self._update_project_label()
                self._update_status(f"Restored last project: {os.path.basename(last_proj)}")

            # Make sure provider-specific placeholder and saved key are applied
            # even when no project was restored (default index is 0 and may not
            # emit currentIndexChanged on startup).
            if hasattr(self, "provider_combo") and self.provider_combo is not None:
                self._on_provider_changed(self.provider_combo.currentIndex())
        except RuntimeError:
            # Widget C++ object was deleted — ignore safely. The values will be
            # loaded again the next time the app starts normally.
            pass
        except Exception:
            # Any other unexpected error during deferred load — don't crash the app.
            pass

    def _settings_key_for_provider(self, provider_text: str) -> str:
        """Return the storage key name used for a provider's API key."""
        if "GLM" in provider_text or "Zhipu" in provider_text:
            return "api_key_zhipu"
        if "Kimi" in provider_text or "Moonshot" in provider_text:
            return "api_key_kimi"
        if "Custom" in provider_text:
            return "api_key_custom"
        return "api_key_deepseek"

    # ── Secure API-key storage (issue #9) ──────────────────────────────
    def _key_store_set(self, key_name: str, value: str) -> bool:
        """Store an API key. Prefers the OS keychain via keyring; falls back
        to QSettings (plaintext) only if the keychain is unavailable.
        Returns True when the secure keychain was used."""
        if _KEYRING_AVAILABLE:
            try:
                _keyring.set_password(_KEYRING_SERVICE, key_name, value)
                self.settings.remove(key_name)  # drop any legacy plaintext copy
                return True
            except Exception as e:
                self._append_log(f"[WARN] OS keychain unavailable ({e}); key stored in plain app settings.")
        self.settings.setValue(key_name, value)
        return False

    def _key_store_get(self, key_name: str) -> str:
        """Read an API key: OS keychain first, legacy QSettings as fallback.
        Migrates legacy plaintext keys into the keychain on first read."""
        legacy = self.settings.value(key_name, "") or ""
        if _KEYRING_AVAILABLE:
            try:
                val = _keyring.get_password(_KEYRING_SERVICE, key_name)
            except Exception:
                val = None
            if val:
                return val
            if legacy:
                try:
                    _keyring.set_password(_KEYRING_SERVICE, key_name, legacy)
                    self.settings.remove(key_name)
                    self._append_log("🔐 API key migrated to the OS keychain (was stored unencrypted).")
                except Exception:
                    pass  # keep the legacy copy; the app keeps working
        return legacy

    def _key_store_delete(self, key_name: str):
        """Remove an API key from both the keychain and legacy QSettings."""
        if _KEYRING_AVAILABLE:
            try:
                _keyring.delete_password(_KEYRING_SERVICE, key_name)
            except Exception:
                pass
        self.settings.remove(key_name)

    def _save_key_if_checked(self):
        """Persist the current key when the user opted to save (called before
        runs). Called by the wiki-sync flow; previously missing entirely."""
        if self.save_key_cb.isChecked():
            self._on_save_key_toggled(Qt.Checked)

    def _load_saved_key_for_current_provider(self):
        """Load any previously saved API key for the active provider.

        Only overwrites the input field if it is currently empty, so the user
        does not lose a key they just typed. The save checkbox is synced to
        reflect whether a saved key exists for this provider.
        """
        provider = self.provider_combo.currentText()
        key_name = self._settings_key_for_provider(provider)
        saved = self._key_store_get(key_name)
        current = self.api_key_edit.text().strip()

        if saved:
            if not current:
                self.api_key_edit.setText(saved)
            self.save_key_cb.blockSignals(True)
            self.save_key_cb.setChecked(True)
            self.save_key_cb.blockSignals(False)
        else:
            self.save_key_cb.blockSignals(True)
            self.save_key_cb.setChecked(False)
            self.save_key_cb.blockSignals(False)

    def _on_provider_changed(self, index: int):
        """Update URL, default model, key placeholder when provider changes."""
        textp = self.provider_combo.currentText()

        if "GLM" in textp or "Zhipu" in textp:
            self.api_key_edit.setPlaceholderText("env: ZHIPU_API_KEY / OPENAI_API_KEY")
            if hasattr(self, "base_url_edit"):
                self.base_url_edit.setText("https://open.bigmodel.cn/api/paas/v4")
            self.model_edit.setCurrentText("glm-4.7-flash")
        elif "Kimi" in textp:
            self.api_key_edit.setPlaceholderText("env: KIMI_API_KEY")
            if hasattr(self, "base_url_edit"):
                self.base_url_edit.setText("https://api.kimi.com/coding/v1")
            self.model_edit.setCurrentText("kimi-for-coding")
        elif "Custom" in textp:
            self.api_key_edit.setPlaceholderText("env: OPENAI_API_KEY")
            if hasattr(self, "base_url_edit"):
                self.base_url_edit.setText("https://api.openai.com/v1")
        else:
            self.api_key_edit.setPlaceholderText("env: DEEPSEEK_API_KEY")
            if hasattr(self, "base_url_edit"):
                self.base_url_edit.setText("https://api.deepseek.com")
            self.model_edit.setCurrentText("deepseek-v4-flash")

        self._load_saved_key_for_current_provider()
        self._refresh_profile_label()

    def _on_model_changed_profile(self, *_args):
        self._refresh_profile_label()

    def _refresh_profile_label(self):
        if not hasattr(self, "profile_label"):
            return
        model = self.model_edit.currentText().strip() if hasattr(self, "model_edit") else ""
        try:
            from model_profiles import profile_summary
            self.profile_label.setText(profile_summary(model or "deepseek-v4-flash"))
        except Exception:
            self.profile_label.setText(
                "Profiles: model_profiles.py sets batches/workers/save_every at run time."
            )

    def _on_api_key_changed(self, text: str):
        """Auto-save the API key while typing if the user opted to save locally."""
        if self.save_key_cb.isChecked():
            provider = self.provider_combo.currentText()
            key_name = self._settings_key_for_provider(provider)
            key = text.strip()
            if key:
                self._key_store_set(key_name, key)
            else:
                self._key_store_delete(key_name)

    def _on_save_key_toggled(self, state: int):
        """Persist or remove the current API key for the active provider."""
        provider = self.provider_combo.currentText()
        key_name = self._settings_key_for_provider(provider)
        if state == Qt.Checked:
            key = self.api_key_edit.text().strip()
            if key:
                secure = self._key_store_set(key_name, key)
                where = "OS keychain" if secure else "plain app settings (keyring unavailable)"
                self._append_log(f"API key saved for {provider.split('(')[0].strip()} → {where}")
        else:
            self._key_store_delete(key_name)
            self._append_log(f"API key removed from local storage for {provider.split('(')[0].strip()}")

    def _open_provider_dialog(self):
        QMessageBox.information(
            self,
            "Providers & Keys",
            "Provider selection is available directly in the Translate tab.\n\n"
            "Keys can be stored securely in your OS keychain (Windows Credential\n"
            "Manager) by ticking 'Save securely' next to the key field.\n\n"
            "Alternatively, set environment variables:\n"
            "  • DEEPSEEK_API_KEY\n"
            "  • DEEPSEEK_BASE_URL (optional, for GLM use https://open.bigmodel.cn/api/paas/v4)"
        )

    def closeEvent(self, event):
        self._append_log("Application closing — attempting to stop any running API tasks...")

        # Stop wiki terms translation worker (direct LLM calls)
        if hasattr(self, "_wiki_worker") and self._wiki_worker is not None:
            try:
                if self._wiki_worker.isRunning():
                    self._wiki_worker.cancel()  # requestInterruption
                    self._append_log("Stopping wiki glossary translation...")
                    # Give it a moment to finish current batch call, then wait
                    self._wiki_worker.wait(4000)
            except Exception:
                pass

        # Cancel CLI worker (tradutor / wiki_sync / audit / merge) — wait so subprocess dies
        if self.active_worker:
            try:
                self.active_worker.cancel()
                self._append_log("Cancelled worker — waiting for shutdown...")
                if self.active_worker.isRunning():
                    self.active_worker.wait(5000)
                self.active_worker = None
            except Exception:
                pass

        # Persist window geometry so the app re-opens at the user's preferred size/position.
        self.settings.setValue("geometry", self.saveGeometry())

        # Persist a few other things + current project path for next launch
        g = self.tr_glossary.text() or (self.glossary_path_edit.text() if hasattr(self, "glossary_path_edit") else "")
        self.settings.setValue("last_glossary", g)
        # Persist blacklist and preserve_map paths
        if hasattr(self, "tr_blacklist"):
            bl = self.tr_blacklist.text().strip()
            if bl:
                self.settings.setValue("last_blacklist", bl)
        if hasattr(self, "tr_preserve_map"):
            pm = self.tr_preserve_map.text().strip()
            if pm:
                self.settings.setValue("last_preserve_map", pm)
        if self.current_project_path:
            self.settings.setValue("last_project_path", self.current_project_path)
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# DIRECT INTEGRATION GROUNDWORK (for full interactive feel — Phase 1 priority)
# These will replace subprocess calls with live, cancellable Qt threads.
# TranslationWorker skeleton below — can be expanded to call tradutor core
# classes directly (SmartGlossary, TranslationEngine, TagProtector, etc.)
# with proper signals for per-item progress, token counts, cost, and cancel.
# ─────────────────────────────────────────────────────────────────────────────

class TranslationSignals(QObject):
    log = Signal(str)
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(bool, str)       # success, message
    stats = Signal(dict)               # tokens, cost, preserved, etc.


class WikiTranslateWorker(QThread):
    """Background worker that translates wiki glossary terms (EN -> PT) via LLM.
    
    Uses configurable batch size + parallel workers for speed.
    Terms are short (~20-50 chars), so batch_size=30 with 3 workers
    is safe and dramatically faster than batch_size=6 single-threaded.
    """
    progress = Signal(int, int, str)
    log = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, terms, model, api_key, provider, base_url,
                 batch_size: int = 30, workers: int = 3):
        super().__init__()
        self.terms = terms
        self.model = model
        self.api_key = api_key
        self.provider = provider
        self.base_url = base_url
        self.batch_size = batch_size
        self.workers = workers

    def run(self):
        try:
            # Determine base URL based on provider
            base_url = self.base_url
            if "GLM" in self.provider or "Zhipu" in self.provider:
                base_url = "https://open.bigmodel.cn/api/paas/v4"

            from tradutor import TranslationEngine
            import concurrent.futures
            
            # Validate client once
            test_engine = TranslationEngine(self.model, 0.15, api_key=self.api_key, base_url=base_url)
            if not test_engine._ensure_client():
                self.finished_signal.emit(False, "Could not initialize LLM client. Check API key.")
                return

            total = len(self.terms)
            self.log.emit(f"[WIKI-START] Translating {total} terms | batch={self.batch_size} | workers={self.workers} | model={self.model}")

            # Split into batches
            batches = []
            for i in range(0, total, self.batch_size):
                batches.append((i, self.terms[i:i + self.batch_size]))
            
            total_batches = len(batches)
            self.log.emit(f"[WIKI-START] {total_batches} batches to process (~{total_batches // self.workers} rounds with {self.workers} workers)")

            system_prompt = (
                "You are translating a Warhammer 40K: Rogue Trader glossary from English to Brazilian Portuguese. "
                "Return ONLY valid JSON. No explanations, no markdown."
            )

            translated_count = [0]  # list for mutability in closure
            completed_batches = [0]
            lock = threading.Lock()

            def translate_single_batch(batch_idx, batch_terms):
                """Translate one batch. Runs in a thread pool worker."""
                if self.isInterruptionRequested():
                    return 0
                
                # Each thread gets its own engine
                engine = TranslationEngine(self.model, 0.2, api_key=self.api_key, base_url=base_url)
                if not engine._ensure_client():
                    self.log.emit(f"[WIKI-ERROR] Thread failed to init client for batch {batch_idx}")
                    return 0

                items = [{"en": t.get("term_english", "").strip()} for t in batch_terms]

                user = (
                    "Translate these Warhammer 40K: Rogue Trader game terms into Brazilian Portuguese.\n"
                    "These are talents, abilities, weapons, armour, items, attributes, skills, and other game mechanics.\n\n"
                    "RULES:\n"
                    "1. EVERY term MUST be translated to Portuguese. No exceptions.\n"
                    "2. Use grimdark, gothic, formal tone. Think: Imperium of Man, Ecclesiarchy, Inquisition.\n"
                    "3. Prefer short, punchy names — these appear in game UI.\n"
                    "4. Be consistent: if a word appears in multiple terms, translate it the same way.\n\n"
                    "EXAMPLES of good translations:\n"
                    "- \"Absolute Loyalty\" → \"Lealdade Absoluta\"\n"
                    "- \"Adrenaline Surge\" → \"Sobrecarga de Adrenalina\"\n"
                    "- \"Advanced Skill: Athletics\" → \"Perícia Avançada: Atletismo\"\n"
                    "- \"Aeldari Weapon Proficiency\" → \"Proficiência com Armas Aeldari\"\n"
                    "- \"Blade of Light\" → \"Lâmina de Luz\"\n"
                    "- \"Blood of Martyrs\" → \"Sangue dos Mártires\"\n"
                    "- \"Counter-Attack\" → \"Contra-Ataque\"\n"
                    "- \"Deathdealer\" → \"Ceifador\"\n"
                    "- \"For the Emperor!\" → \"Pelo Imperador!\"\n"
                    "- \"Iron Discipline\" → \"Disciplina de Ferro\"\n"
                    "- \"Plasma Gun\" → \"Arma de Plasma\"\n"
                    "- \"Power Armour Proficiency\" → \"Proficiência com Armadura Energética\"\n"
                    "- \"Sanctified Slayer\" → \"Carrasco Abençoado\"\n"
                    "- \"Unbreakable Will\" → \"Vontade Inquebrável\"\n\n"
                    "Respond with EXACTLY this JSON (nothing else):\n"
                    "{\"items\":[{\"en\":\"...\",\"pt\":\"...\"},...]}\n"
                    "Same order as input.\n\n"
                    f"Terms:{json.dumps(items, ensure_ascii=False)}"
                )

                raw_content = ""
                for attempt in range(2):  # one retry on bad JSON
                    if self.isInterruptionRequested():
                        return 0
                    try:
                        start = batch_idx
                        end = start + len(batch_terms) - 1
                        self.log.emit(f"[WIKI-LLM] Batch {start}-{end} (attempt {attempt+1})")

                        base_budget = 350 + len(batch_terms) * 160
                        dynamic_max = max(4000, base_budget)
                        
                        resp = engine._client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user}
                            ],
                            temperature=0.2,
                            max_tokens=dynamic_max,
                        )

                        raw_content = resp.choices[0].message.content or ""
                        finish_reason = getattr(resp.choices[0], "finish_reason", "unknown")
                        
                        usage = getattr(resp, "usage", None)
                        usage_str = f"prompt={getattr(usage,'prompt_tokens','?')} completion={getattr(usage,'completion_tokens','?')}" if usage else ""
                        self.log.emit(f"[WIKI-RAW] Batch {start}-{end} finish={finish_reason} {usage_str}")

                        # Clean content
                        content = raw_content.strip()
                        if "```" in content:
                            after = content.split("```", 1)[1] if "```" in content else content
                            if "```" in after:
                                after = after.split("```", 1)[0]
                            content = after.strip()
                        if content.lower().startswith("json"):
                            content = content[4:].lstrip(":\n\r\t ").strip()

                        if not content:
                            self.log.emit("[WIKI-ERROR] Model returned empty content!")
                            raise ValueError("Empty response content")

                        # Parse
                        try:
                            data = json.loads(content)
                            pts = []
                            if isinstance(data, dict):
                                for k in ("items", "translations", "terms", "results", "data", "list"):
                                    if k in data and isinstance(data[k], list):
                                        pts = [x for x in data[k] if isinstance(x, dict)]
                                        break
                                if not pts:
                                    for v in data.values():
                                        if isinstance(v, list):
                                            pts = [x for x in v if isinstance(x, dict)]
                                            break
                            elif isinstance(data, list):
                                pts = [x for x in data if isinstance(x, dict)]
                        except Exception:
                            # Regex fallback
                            pts = []
                            pattern = r'\{\s*"en"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*"pt"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*[},]'
                            for en_val, pt_val in re.findall(pattern, content):
                                pts.append({"en": en_val, "pt": pt_val})
                            if not pts:
                                pattern2 = r'"en"\s*:\s*"([^"]+)"\s*,\s*"pt"\s*:\s*"([^"]+)"'
                                for en_val, pt_val in re.findall(pattern2, content):
                                    pts.append({"en": en_val, "pt": pt_val})

                        if not pts:
                            self.log.emit(f"[WIKI-WARNING] Batch {start}-{end}: could not extract any items")
                            if attempt == 1:
                                return 0
                            continue

                        # Apply translations
                        batch_translated = 0
                        for j, term in enumerate(batch_terms):
                            en = term.get("term_english", "").strip()
                            pt = ""
                            if j < len(pts):
                                p = pts[j]
                                if isinstance(p, dict):
                                    pt = str(p.get("pt") or p.get("term_translated") or "").strip()
                                elif isinstance(p, str):
                                    pt = p.strip()
                            pt = pt.strip().strip('"').strip("'")

                            if pt and pt.lower() != en.lower():
                                term["term_translated"] = pt
                                term["confidence"] = "medium"
                                batch_translated += 1

                        return batch_translated

                    except Exception as e:
                        self.log.emit(f"[WIKI-ERR] Batch {batch_idx} attempt {attempt+1}: {e}")
                        if attempt == 1:
                            return 0
                        import time
                        time.sleep(2)

                return 0

            # Process batches in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {}
                for batch_idx, batch_terms in batches:
                    if self.isInterruptionRequested():
                        break
                    f = executor.submit(translate_single_batch, batch_idx, batch_terms)
                    futures[f] = (batch_idx, len(batch_terms))

                for future in concurrent.futures.as_completed(futures):
                    if self.isInterruptionRequested():
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.finished_signal.emit(False, "Cancelled by user")
                        return
                    
                    batch_idx, batch_len = futures[future]
                    try:
                        batch_count = future.result()
                        with lock:
                            translated_count[0] += batch_count
                            completed_batches[0] += 1
                            self.progress.emit(
                                completed_batches[0], total_batches,
                                f"Batch {completed_batches[0]}/{total_batches} | {translated_count[0]} translated"
                            )
                    except Exception as e:
                        self.log.emit(f"[WIKI-ERR] Batch {batch_idx} future failed: {e}")

            self.finished_signal.emit(
                True,
                f"Translated {translated_count[0]} / {total} wiki terms "
                f"({completed_batches[0]}/{total_batches} batches, "
                f"batch_size={self.batch_size}, workers={self.workers})"
            )
        except Exception as e:
            self.finished_signal.emit(False, f"Wiki translation error: {e}")

    def cancel(self):
        self.requestInterruption()


class TranslationWorker(QThread):
    """Run a pre-built tradutor.py command; stream logs/progress; hard-kill on cancel."""

    def __init__(self, cmd: List[str], env: Optional[dict] = None):
        super().__init__()
        self.signals = TranslationSignals()
        self.cmd = cmd
        self.env = env
        self._cancel_requested = False
        self._proc = None

    def run(self):
        try:
            cmd = self.cmd
            env = self.env if self.env is not None else os.environ.copy()
            self.signals.log.emit(f"Launching: {' '.join(cmd)}")

            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env
            )

            final_counts = None
            for line in iter(self._proc.stdout.readline, ""):
                if self._cancel_requested:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                    self.signals.finished.emit(False, "Cancelled by user")
                    return
                line = line.rstrip()
                if not line:
                    continue
                self.signals.log.emit(line)

                if "%" in line and "|" in line:
                    try:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if "%" in p:
                                pct = int(p.replace("%", ""))
                                self.signals.progress.emit(pct, 100, "Processing batches...")
                            if "/" in p and i > 0:
                                nums = p.split("/")
                                if len(nums) == 2:
                                    int(nums[0]); int(nums[1])  # validate only
                    except Exception:
                        pass

                # e.g. "✅ Concluído: 1234 traduzidos | 5 falhas | 678 preservados"
                if "Concluído:" in line:
                    nums = re.findall(r"\d+", line)
                    if len(nums) >= 3:
                        final_counts = {
                            "translated": int(nums[0]),
                            "failed": int(nums[1]),
                            "preserved": int(nums[2]),
                        }

            self._proc.stdout.close()
            exit_code = self._proc.wait()

            run_stats = {
                "tokens": "see final log lines",
                "cost_usd": "see final log lines",
                "preserved": final_counts.get("preserved", "see log") if final_counts else "see log",
                "extracted_terms": "see log if --extract-every was used",
            }
            if final_counts:
                run_stats["translated"] = final_counts["translated"]
                run_stats["failed"] = final_counts["failed"]
            self.signals.stats.emit(run_stats)

            if exit_code == 0:
                self.signals.finished.emit(True, "Completed successfully.")
            else:
                self.signals.finished.emit(False, f"Command exited with code {exit_code}")

        except Exception as e:
            self.signals.finished.emit(False, f"Worker error: {e}")

    def cancel(self):
        """Flag + kill subprocess (flag alone hangs while waiting on API)."""
        self._cancel_requested = True
        if self._proc:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
    except ImportError:
        print("=" * 70)
        print("ERROR: PySide6 is not installed.")
        print("=" * 70)
        print()
        print("This desktop GUI requires PySide6.")
        print()
        print("Install with (PowerShell / CMD in this folder):")
        print("    pip install -r requirements-gui.txt")
        print()
        print("Or manually:")
        print("    pip install PySide6")
        print()
        print("After install, run:")
        print("    python tradutor_desktop.py")
        print()
        print("See requirements-gui.txt and SCENARIOS.md for details.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("W40K Rogue Trader Translator")
    app.setOrganizationName("TradutorW40k")

    # Nice default font size
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = W40kTranslatorGUI()
    window.show()

    # Friendly first-run hint
    print("W40K Desktop GUI started. Use the tabs to drive the documented scenarios.")
    print("Big 'PRESERVE' toggle in Translate tab controls Scenario 1 vs 2.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
