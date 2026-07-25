"""Pacote de testes — isola a pasta de configuração do usuário.

w40k_settings lê/grava em %APPDATA%/W40KTranslator; apontar
W40K_CONFIG_DIR para um diretório temporário garante que a suíte
nunca toca a configuração real do usuário, mesmo quando um teste
esquece de isolar por conta própria.
"""

import os
import tempfile

os.environ.setdefault(
    "W40K_CONFIG_DIR",
    tempfile.mkdtemp(prefix="w40k_test_config_"),
)
