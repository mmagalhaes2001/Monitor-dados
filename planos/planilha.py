#!/usr/bin/env python3
"""Gera planos/planos_operadoras.xlsx a partir de planos/dados/historico.csv e coletas.csv.

Abas:
  Atual            – planos que valem hoje, uma linha por plano × praça
  Preços por praça – mesma grade, preço de cada plano nas 27 capitais lado a lado
  Mudanças         – tudo que mudou desde o início do monitor (antes → depois), mais recente primeiro
  Histórico        – todas as versões de cada plano, com início e fim de vigência
  Coletas          – cada página lida em cada praça (ok ou falha), para conferir cobertura
"""
import csv
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

AQUI = Path(__file__).parent
sys_path = AQUI
import sys  # noqa: E402
sys.path.insert(0, str(AQUI))
from historico import CAMPOS_COMPARA, COLS, COLS_LOG, HIST, LOG, NOMES, ler  # noqa: E402

ARQ = AQUI / "planos_operadoras.xlsx"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
       "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
ORD_SEG = {"pre": 0, "controle": 1, "pos": 2, "familia": 3, "fibra": 4}
SEG_NOME = {"pre": "Pré", "controle": "Controle", "pos": "Pós", "familia": "Família", "fibra": "Fibra"}
CAB = Font(bold=True, color="FFFFFF")
FUNDO = PatternFill("solid", fgColor="1F3864")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v if v not in (None, "") else None


def aba(wb, nome, cab, linhas, larguras=None, num_cols=()):
    ws = wb.create_sheet(nome)
    ws.append(cab)
    for c in ws[1]:
        c.font, c.fill = CAB, FUNDO
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for l in linhas:
        ws.append(l)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, _ in enumerate(cab, 1):
        ws.column_dimensions[get_column_letter(i)].width = (larguras or {}).get(i, 14)
    for col in num_cols:
        for (cel,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            cel.number_format = "#,##0.00"
    return ws


def gerar():
    hist = ler(HIST, COLS)
    log = ler(LOG, COLS_LOG)
    wb = Workbook()
    wb.remove(wb.active)
    vig = [r for r in hist if not r["fim"]]
    chave_ord = lambda r: (r["operadora"], ORD_SEG.get(r["segmento"], 9), f(r["preco"]) or 0, r["plano"], r["uf"])

    # Atual
    aba(wb, "Atual", ["Operadora", "Segmento", "Plano", "UF", "Cidade", "Preço (R$)", "Preço De (R$)",
                      "Preço após promo (R$)", "Condição", "GB", "R$/GB", "Composição dos GB", "Velocidade (Mega)",
                      "Linhas", "Selo/promoção", "Benefícios", "Desde", "Visto em", "Link"],
        [[r["operadora"], SEG_NOME.get(r["segmento"], r["segmento"]), r["plano"], r["uf"], r["cidade"], f(r["preco"]),
          f(r["preco_de"]), f(r["preco_depois"]), r["condicao"], f(r["gb_total"]), f(r["rs_por_gb"]), r["gb_detalhe"],
          f(r["velocidade_mega"]), f(r["linhas"]), r["selo"], r["beneficios"], r["inicio"], r["visto_ultimo"], r["url"]]
         for r in sorted(vig, key=chave_ord)],
        {3: 34, 9: 18, 12: 40, 15: 22, 16: 60}, num_cols=(6, 7, 8, 11))

    # Preços por praça
    grade = defaultdict(dict)
    meta = {}
    for r in vig:
        k = (r["operadora"], r["segmento"], r["chave"])
        grade[k][r["uf"]] = f(r["preco"])
        meta.setdefault(k, (r["plano"], r["gb_total"] or r["velocidade_mega"]))
    linhas = []
    for k in sorted(grade, key=lambda k: (k[0], ORD_SEG.get(k[1], 9), min(v for v in grade[k].values() if v) if any(grade[k].values()) else 0)):
        precos = [grade[k].get(u) for u in UFS]
        val = [p for p in precos if p]
        linhas.append([k[0], SEG_NOME.get(k[1], k[1]), meta[k][0], f(meta[k][1]), len(val),
                       min(val) if val else None, max(val) if val else None] + precos)
    ws = aba(wb, "Preços por praça", ["Operadora", "Segmento", "Plano", "GB / Mega", "Nº praças", "Mín", "Máx"] + UFS,
             linhas, {3: 34}, num_cols=range(6, 8 + len(UFS)))
    for i in range(8, 8 + len(UFS)):
        ws.column_dimensions[get_column_letter(i)].width = 8

    # Mudanças (todas, desde o início)
    base = min((r["inicio"] for r in hist), default="")
    por = defaultdict(list)
    for r in hist:
        por[(r["operadora"], r["uf"], r["chave"])].append(r)
    mud = []
    for k, vs in por.items():
        vs.sort(key=lambda r: r["inicio"])
        if vs[0]["inicio"] > base:
            mud.append([vs[0]["inicio"], vs[0]["operadora"], SEG_NOME.get(vs[0]["segmento"]), vs[0]["plano"], vs[0]["uf"],
                        "Novo", "", "", "R$ %s" % vs[0]["preco"]])
        for a, b in zip(vs, vs[1:]):
            for c in CAMPOS_COMPARA:
                if a[c] != b[c]:
                    mud.append([b["inicio"], b["operadora"], SEG_NOME.get(b["segmento"]), b["plano"], b["uf"],
                                "Mudou", NOMES[c], a[c], b[c]])
        if vs[-1]["fim"]:
            mud.append([vs[-1]["fim"], vs[-1]["operadora"], SEG_NOME.get(vs[-1]["segmento"]), vs[-1]["plano"], vs[-1]["uf"],
                        "Saiu (visto pela última vez)", "", "R$ %s" % vs[-1]["preco"], ""])
    mud.sort(key=lambda l: (l[0], l[1], l[3], l[4]), reverse=True)
    aba(wb, "Mudanças", ["Data", "Operadora", "Segmento", "Plano", "UF", "Tipo", "Campo", "Antes", "Depois"],
        mud, {4: 34, 8: 40, 9: 40})

    # Histórico
    aba(wb, "Histórico", ["Operadora", "Segmento", "Plano", "UF", "Preço (R$)", "Preço De", "Preço após promo",
                          "Condição", "GB", "R$/GB", "Composição dos GB", "Velocidade (Mega)", "Linhas", "Selo",
                          "Benefícios", "Início", "Fim", "Visto por último", "Chave"],
        [[r["operadora"], SEG_NOME.get(r["segmento"], r["segmento"]), r["plano"], r["uf"], f(r["preco"]), f(r["preco_de"]),
          f(r["preco_depois"]), r["condicao"], f(r["gb_total"]), f(r["rs_por_gb"]), r["gb_detalhe"], f(r["velocidade_mega"]),
          f(r["linhas"]), r["selo"], r["beneficios"], r["inicio"], r["fim"], r["visto_ultimo"], r["chave"]]
         for r in sorted(hist, key=lambda r: (r["operadora"], ORD_SEG.get(r["segmento"], 9), r["chave"], r["uf"], r["inicio"]))],
        {3: 34, 11: 40, 15: 60}, num_cols=(5, 6, 7, 10))

    # Coletas
    aba(wb, "Coletas", ["Data", "Hora", "Operadora", "UF", "Cidade", "Página", "OK", "Nº planos", "Praça na tela", "Erro"],
        [[r[c] for c in COLS_LOG] for r in sorted(log, key=lambda r: (r["data"], r["hora"], r["operadora"], r["uf"]), reverse=True)],
        {9: 24, 10: 60})
    wb.save(ARQ)
    return ARQ


if __name__ == "__main__":
    print(gerar())
