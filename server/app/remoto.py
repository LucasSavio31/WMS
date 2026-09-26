"""Leitor remoto: o PC aciona o leitor RFID do coletor, com o servidor no meio.

    PC (tela Leitor remoto) --comando--> servidor <--pergunta a cada 0,4 s-- coletor (tela Leitor do PC)
    PC <--leituras e eventos-- servidor <--leituras e eventos-- coletor

Fica tudo em memória (é o estado de uma sessão de bancada, não vai para o banco).
Um coletor por vez faz o papel de leitor do PC.
"""
import threading
import time

from . import db

_trava = threading.Lock()
_comandos: list[dict] = []          # últimos comandos do PC (ler, parar, gravar, limpar)
_seq_comando = 0
_leituras: dict[str, dict] = {}     # EPC -> {epc, vezes, primeira, ultima}
_versao = 0                         # muda a cada leitura nova (o PC só redesenha quando muda)
_eventos: list[dict] = []           # respostas do coletor (gravação, parou de ler)
_seq_evento = 0
_sinal = 0.0                        # última vez que o coletor perguntou por comandos
_lendo = False

ONLINE_SEGUNDOS = 3


def comando(acao: str, ms: int = 3000, texto: str | None = None, potencia: int | None = None) -> dict:
    """PC manda um comando para o coletor."""
    global _seq_comando, _versao, _lendo
    with _trava:
        _seq_comando += 1
        c = {"id": _seq_comando, "acao": acao, "ms": ms, "texto": texto, "potencia": potencia, "hora": db.agora()}
        _comandos.append(c)
        del _comandos[:-50]
        if acao == "limpar":
            _leituras.clear()
            _versao += 1
        elif acao == "ler":
            _lendo = True
        elif acao in ("parar", "gravar"):
            _lendo = False
        return c


def comandos_para_coletor(apos: int) -> dict:
    """Coletor pergunta por comandos novos (apos=-1: só quer saber o número do último, para começar dali)."""
    global _sinal
    with _trava:
        _sinal = time.time()
        novos = [] if apos < 0 else [c for c in _comandos if c["id"] > apos]
        return {"ultimo": _seq_comando, "comandos": novos}


def registrar_leituras(epcs: list[str]) -> int:
    """Coletor manda as etiquetas lidas (cada leitura conta: a mesma etiqueta pode vir várias vezes)."""
    global _sinal, _versao
    agora = db.agora()
    with _trava:
        _sinal = time.time()
        for epc in (e.strip().upper() for e in epcs if e and e.strip()):
            r = _leituras.get(epc)
            if r:
                r["vezes"] += 1
                r["ultima"] = agora
            else:
                _leituras[epc] = {"epc": epc, "vezes": 1, "primeira": agora, "ultima": agora}
        _versao += 1
        return len(_leituras)


def registrar_evento(tipo: str, dados: dict) -> None:
    """Coletor avisa o resultado de um comando (gravação feita, leitura parou)."""
    global _seq_evento, _lendo, _sinal
    with _trava:
        _sinal = time.time()
        _seq_evento += 1
        _eventos.append({"id": _seq_evento, "tipo": tipo, "dados": dados, "hora": db.agora()})
        del _eventos[:-50]
        if tipo in ("parou", "gravacao"):
            _lendo = False


def estado(con, eventos_apos: int = 0) -> dict:
    """O que o PC mostra: coletor conectado?, lendo?, etiquetas lidas (com a situação no estoque) e eventos."""
    with _trava:
        leituras = sorted((dict(r) for r in _leituras.values()), key=lambda r: r["primeira"], reverse=True)
        eventos = [e for e in _eventos if e["id"] > eventos_apos]
        sinal_ha = time.time() - _sinal if _sinal else None
        resposta = {"online": sinal_ha is not None and sinal_ha < ONLINE_SEGUNDOS,
                    "sinal_ha": None if sinal_ha is None else round(sinal_ha, 1),
                    "lendo": _lendo, "versao": _versao, "eventos": eventos}
    for r in leituras:
        t = con.execute("""SELECT t.status, p.id AS produto_id, p.sku, p.descricao, l.endereco_id, e.codigo AS endereco
                           FROM tags t JOIN lotes l ON l.id=t.lote_id JOIN produtos p ON p.id=l.produto_id
                           LEFT JOIN enderecos e ON e.id=l.endereco_id WHERE t.epc=?""", (r["epc"],)).fetchone()
        r.update(dict(t) if t else {"status": None})
    resposta["leituras"] = leituras
    return resposta
