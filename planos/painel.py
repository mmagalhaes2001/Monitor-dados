#!/usr/bin/env python3
"""Gera os arquivos do painel de gráficos a partir do histórico:

planos/painel/serie_sp.csv  – foto diária de cada plano em São Paulo (praça de referência: no móvel o preço
                              é igual em quase todas as capitais): data, operadora, tipo, linha, plano, preço, GB,
                              Mega, R$/GB (ou R$ por 100 Mega na fibra)
planos/painel/mudancas.csv  – mudanças agrupadas por dia, operadora, plano e campo, com o nº de praças
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
from historico import COLS, COLS_LOG, HIST, LOG, ler  # noqa: E402

SAIDA = AQUI / "painel"
REF = "SP"


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def serie():
    hist = ler(HIST, COLS)
    datas = sorted({r["data"] for r in ler(LOG, COLS_LOG) if r["ok"] == "sim" and r["uf"] == REF})
    linhas = []
    for d in datas:
        for r in hist:
            if r["uf"] != REF or r["inicio"] > d or (r["fim"] and r["fim"] < d):
                continue
            preco, gb, mega = f(r["preco"]), f(r["gb_total"]), f(r["velocidade_mega"])
            if not preco:
                continue
            if gb:
                unid, nome_unid = round(preco / gb, 2), "R$/GB"
            elif mega:
                unid, nome_unid = round(preco / (mega / 100), 2), "R$ por 100 Mega"
            else:
                unid, nome_unid = None, ""
            linhas.append({"data": d, "operadora": r["operadora"], "tipo": r["tipo"] or r["segmento"],
                           "linha": r["linha"], "plano": r["plano"], "preco": preco, "gb": gb or "",
                           "mega": mega or "", "valor_unidade": unid if unid is not None else "", "unidade": nome_unid})
    return linhas


def mudancas():
    from openpyxl import load_workbook
    wb = load_workbook(AQUI / "planos_operadoras.xlsx", read_only=True)
    g = defaultdict(set)
    for r in wb["Mudanças"].iter_rows(min_row=2, values_only=True):
        data, op, tipo, linha, plano, uf, mud, campo, antes, depois = r[:10]
        if campo == "benefícios":
            antes, depois = "", "(texto mudou)"
        g[(data, op, tipo or "", linha or "", plano, mud, campo or "", str(antes or ""), str(depois or ""))].add(uf)
    out = []
    for k, ufs in g.items():
        out.append(dict(zip(["data", "operadora", "tipo", "linha", "plano", "mudanca", "campo", "antes", "depois"], k),
                        n_pracas=len(ufs), pracas="todas" if len(ufs) == 27 else ",".join(sorted(ufs))))
    out.sort(key=lambda x: (x["data"], x["operadora"], x["plano"]), reverse=True)
    return out


def gravar(nome, linhas, cols):
    SAIDA.mkdir(exist_ok=True)
    with open(SAIDA / nome, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(linhas)


if __name__ == "__main__":
    s = serie()
    gravar("serie_sp.csv", s, ["data", "operadora", "tipo", "linha", "plano", "preco", "gb", "mega", "valor_unidade", "unidade"])
    m = mudancas()
    gravar("mudancas.csv", m, ["data", "operadora", "tipo", "linha", "plano", "mudanca", "campo", "antes", "depois", "n_pracas", "pracas"])
    print(len(s), "linhas na série;", len(m), "mudanças agrupadas")
