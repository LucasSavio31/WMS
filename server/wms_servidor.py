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

PORTA = int(os.environ.get("WMS_PORTA", "8000"))   # outra porta: set WMS_PORTA=8080 antes de abrir


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
    ip = ip_da_rede()
    print("=" * 64)
    print(" MINI WMS - SERVIDOR")
    print(f" Tela do PC ...........: http://localhost:{PORTA}")
    print(f" Endereço no coletor ..: http://{ip}:{PORTA}")
    print(f" Simulador do coletor .: http://localhost:{PORTA}/coletor")
    print(f" Banco de dados .......: {os.environ['WMS_DB']}")
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
