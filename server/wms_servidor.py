"""Inicia o servidor do Mini WMS e abre a tela no navegador.

É este arquivo que vira o WMS-Servidor.exe (PyInstaller), para rodar
no Windows sem precisar instalar o Python.
"""
import os
import socket
import sys
import threading
import webbrowser

# O banco estoque.db fica na mesma pasta do .exe (ou deste arquivo)
pasta = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.environ.setdefault("WMS_DB", os.path.join(pasta, "estoque.db"))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

PORTA = 8000


def ip_da_rede() -> str:
    """IP deste PC na rede local (é o que vai no coletor)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)  # mostra o texto na hora
    print("=" * 60)
    print(" MINI WMS RFID")
    print(f" Tela do PC ......: http://localhost:{PORTA}")
    print(f" Usar no coletor .: http://{ip_da_rede()}:{PORTA}")
    print(f" Banco de dados ..: {os.environ['WMS_DB']}")
    print(" Para desligar, feche esta janela.")
    print("=" * 60)
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORTA}")).start()
    uvicorn.run(app, host="0.0.0.0", port=PORTA, log_level="warning")
