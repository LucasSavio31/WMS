"""Inicia o servidor do Mini WMS e abre a tela no navegador.

É este arquivo que vira o WMS-Servidor.exe (PyInstaller), para rodar
no Windows sem precisar instalar o Python.
"""
import os
import socket
import sys
import threading
import webbrowser

import uvicorn

from app import db
from app.main import app

# O banco fica em Documentos\MiniWMS\estoque.db do usuário (ver app/db.py).

PORTA = int(os.environ.get("WMS_PORTA", "8000"))   # outra porta: set WMS_PORTA=8080 antes de abrir


def porta_livre(porta: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", porta))
        return True
    except OSError:
        return False
    finally:
        s.close()


def sair(mensagem: str) -> None:
    """Mostra o problema e espera o ENTER (senão a janela do .exe fecha sem dar para ler)."""
    print()
    print(mensagem)
    input("Pressione ENTER para fechar...")
    sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)  # mostra o texto na hora
    ip = db.ip_da_rede()
    print("=" * 64)
    print(" MINI WMS - SERVIDOR")
    print(f" Tela do PC ...........: http://localhost:{PORTA}")
    print(f" Endereço no coletor ..: http://{ip}:{PORTA}")
    try:
        db.inicializar()   # escolhe a pasta do banco (Documentos) antes de mostrar o caminho
    except Exception as e:  # noqa: BLE001
        sair(f"Não foi possível abrir o banco de dados: {e}")
    print(f" Banco de dados .......: {db.DB_PATH}")
    if db.AVISO:
        print()
        print(" ATENÇÃO: " + db.AVISO)
        print()
    print(" (o coletor também acha o servidor sozinho: Procurar servidor na rede)")
    print(" Para desligar, feche esta janela.")
    print("=" * 64)
    if not porta_livre(PORTA):
        sair(f"A porta {PORTA} já está em uso: o servidor já está aberto em outra janela?\n"
             f"Se estiver, use essa janela. Senão, feche o programa que está usando a porta {PORTA}.")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORTA}")).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=PORTA, log_level="warning")
    except Exception as e:  # noqa: BLE001
        sair(f"O servidor parou com erro: {e}")
