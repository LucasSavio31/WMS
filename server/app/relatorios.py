"""Relatórios em PDF (estoque por local e histórico de movimentos)."""
from fpdf import FPDF
from fpdf.fonts import FontFace

from . import db


def _t(valor) -> str:
    """Texto para a fonte padrão do PDF (latin-1: acentos do português funcionam)."""
    return str("" if valor is None else valor).replace("—", "-").replace("→", "->").encode("latin-1", "replace").decode("latin-1")


def _data(dh: str) -> str:
    """2026-09-23 22:10:05 -> 23/09/2026 22:10"""
    return f"{dh[8:10]}/{dh[5:7]}/{dh[:4]} {dh[11:16]}"


def _num(q) -> str:
    return f"{q:g}".replace(".", ",") if isinstance(q, (int, float)) else _t(q)


class Relatorio(FPDF):
    def __init__(self, titulo, subtitulo="", paisagem=False):
        super().__init__(orientation="L" if paisagem else "P", unit="mm", format="A4")
        self.titulo, self.subtitulo = titulo, subtitulo
        self.set_auto_page_break(True, 14)
        self.alias_nb_pages()
        self.add_page()

    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 8, _t("Mini WMS - " + self.titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100)
        self.cell(0, 5, _t(f"Gerado em {_data(db.agora())}  {self.subtitulo}"), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0)
        self.ln(3)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120)
        self.cell(0, 5, _t(f"Página {self.page_no()}/{{nb}}"), align="R")

    def tabela(self, cabecalho, linhas, larguras, alinhar):
        self.set_font("Helvetica", "", 9)
        with self.table(col_widths=larguras, text_align=alinhar, line_height=6,
                        headings_style=FontFace(emphasis="BOLD", fill_color=(225, 230, 238)),
                        cell_fill_color=(246, 248, 251), cell_fill_mode="ROWS") as t:
            r = t.row()
            for c in cabecalho:
                r.cell(_t(c))
            for linha in linhas:
                r = t.row()
                for c in linha:
                    r.cell(_t(c))


def pdf_estoque(locais) -> bytes:
    total = sum(l["quantidade"] for l in locais)
    pdf = Relatorio("Estoque por local", f"· {len(locais)} local(is) · {_num(total)} unidade(s)")
    for local in locais:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _t(f"{local['codigo']}  ({_num(local['quantidade'])} unidades, {len(local['itens'])} item(ns))"),
                 new_x="LMARGIN", new_y="NEXT")
        if local.get("descricao"):
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 5, _t(local["descricao"]), new_x="LMARGIN", new_y="NEXT")
        if local["itens"]:
            pdf.tabela(["Item", "Descrição", "Quantidade", "Com etiqueta RFID"],
                       [[i["sku"], i["descricao"], f"{_num(i['quantidade'])} {i['unidade']}", _num(i["etiquetas"] or 0)] for i in local["itens"]],
                       (22, 48, 15, 15), ("LEFT", "LEFT", "RIGHT", "RIGHT"))
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 6, _t("Sem itens neste local"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    return bytes(pdf.output())


def pdf_movimentos(movs, filtros="") -> bytes:
    pdf = Relatorio("Histórico de movimentações", f"· {len(movs)} movimento(s) {filtros}", paisagem=True)
    linhas = [[_data(m["data_hora"]), m["tipo"], m["sku"], m["descricao"], m.get("endereco") or "",
               ("+" if m["quantidade"] > 0 else "") + _num(m["quantidade"]) if m["quantidade"] else "",
               " · ".join(x for x in (m.get("documento"), m.get("motivo")) if x), m.get("epc") or "",
               f"{m['origem']} / {m['meio']}"] for m in movs]
    pdf.tabela(["Data/hora", "Tipo", "Item", "Descrição", "Local", "Qtd", "Motivo / documento", "EPC", "Origem"],
               linhas, (13, 14, 10, 21, 11, 6, 19, 19, 12),
               ("LEFT", "LEFT", "LEFT", "LEFT", "LEFT", "RIGHT", "LEFT", "LEFT", "LEFT"))
    return bytes(pdf.output())
