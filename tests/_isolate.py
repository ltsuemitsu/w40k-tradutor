"""Isolamento da pasta de configuração para a suíte.

`python -m unittest discover -s tests` (Python 3.11+) importa os módulos
de teste "flat" — tests/__init__.py NÃO é executado. Importar este módulo
no topo dos arquivos de teste que resolvem config efetiva garante que
w40k_settings nunca lê o %APPDATA% real do usuário.
"""

import os
import tempfile

os.environ.setdefault(
    "W40K_CONFIG_DIR",
    tempfile.mkdtemp(prefix="w40k_test_config_"),
)
