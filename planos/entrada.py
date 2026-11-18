#!/usr/bin/env python3
"""Acompanhamento dos planos de entrada (SP), no formato de tabela usado no mercado:
Controle de entrada (Vivo Controle, Claro Controle, TIM Controle, NuCel) e Digital de entrada (Vivo Lite,
Claro Flex, TIM Fit Anual). Para cada coleta: franquia base (recorrente), bônus, total (de uso livre),
preço, R$/GB total, R$/GB base e se mudou desde a coleta anterior.

Plano de entrada = o mais barato da linha comercial na praça de referência (SP).
Saída: planos/dados/entrada.csv (uma linha por coleta × plano). Usado pela planilha (aba "Planos de entrada"),
pelo aviso diário e pelo relatório.
"""
import csv
import re
import sys
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
from historico import COLS, COLS_LOG, HIST, LOG, ler  # noqa: E402
from taxonomia import RE_CARIMBADO, gb_livre  # noqa: E402

REF = "SP"
SAIDA = AQUI / "dados" / "entrada.csv"
# grupo, rótulo da coluna, operadora, linha comercial (regex), excluir plano (regex)
PLANOS = [
    ("Controle de entrada", "Vivo Controle", "Vivo", r"^Vivo Controle$", r"youtube|netflix|max|disney|premium"),
    ("Controle de entrada", "Claro Controle", "Claro", r"^Claro Controle$", r"geforce"),
    ("Controle de entrada", "TIM Controle", "TIM", r"^TIM Controle$", r"^$"),
    ("Controle de entrada", "NuCel", "NuCel", r"^NuCel$", r"^$"),
    ("Digital de entrada", "Vivo Lite", "Vivo", r"^Vivo Lite", r"mensal"),
    ("Digital de entrada", "Claro Flex", "Claro", r"^Claro Flex", r"^$"),
    ("Digital de entrada", "TIM Fit Anual", "TIM", r"^TIM Controle Fit Anual", r"^$"),
]
COLS_E = ["data", "grupo", "rotulo", "operadora", "plano", "chave", "preco", "gb_base", "gb_bonus", "gb_total",
          "gb_redes", "rs_gb_total", "rs_gb_base", "condicao", "mudou"]


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def decompor(r):
    """(base, bônus de uso livre, GB carimbados para redes/apps) a partir da composição anunciada."""
    total = f(r["gb_total"])
    det = r["gb_detalhe"] or ""
    if not det:
        if r["operadora"] == "NuCel":
            return total, 0.0, 0.0
        return None, None, 0.0
    base = bonus = redes = 0.0
    achou = False
    for parte in re.split(r"[;+]", det):
        nums = re.findall(r"(\d+(?:[.,]\d+)?)\s*GB", parte, re.I)
        if not nums:
            continue
        v = float(nums[-1].replace(",", "."))
        achou = True
        if RE_CARIMBADO.search(parte) and not re.search(r"uso livre|como quiser", parte, re.I):
            redes += v
        elif re.search(r"b[ôo]nus|promo", parte, re.I):
            bonus += v
        else:
            base += v
    if not achou:
        return None, None, 0.0
    # composição incompleta no site (ex.: card lista só o bônus): o que falta para o total é base
    if total and base + bonus + redes < total and base == 0:
        base = total - bonus - redes
    return base, bonus, redes


def escolher(vig, op, re_linha, re_excl):
    cand = [r for r in vig if r["operadora"] == op and re.search(re_linha, r["linha"] or "", re.I)
            and not re.search(re_excl, r["plano"], re.I) and f(r["preco"])]
    return min(cand, key=lambda r: f(r["preco"])) if cand else None


def gerar():
    hist = ler(HIST, COLS)
    datas = sorted({r["data"] for r in ler(LOG, COLS_LOG) if r["ok"] == "sim" and r["uf"] == REF})
    out, anterior = [], {}
    for d in datas:
        vig = [r for r in hist if r["uf"] == REF and r["inicio"] <= d and not (r["fim"] and r["fim"] < d)]
        for grupo, rot, op, re_linha, re_excl in PLANOS:
            r = escolher(vig, op, re_linha, re_excl)
            if not r:
                continue
            preco = f(r["preco"])
            base, bonus, redes = decompor(r)
            total = (base + bonus) if base is not None else gb_livre(r["gb_total"], r["gb_detalhe"])
            linha = {"data": d, "grupo": grupo, "rotulo": rot, "operadora": op, "plano": r["plano"], "chave": r["chave"],
                     "preco": preco, "gb_base": base if base is not None else "", "gb_bonus": bonus if bonus is not None else "",
                     "gb_total": total or "", "gb_redes": redes or "",
                     "rs_gb_total": round(preco / total, 2) if total else "",
                     "rs_gb_base": round(preco / base, 2) if base else "", "condicao": r["condicao"]}
            a = anterior.get(rot)
            dif = []
            if a:
                if a["chave"] != linha["chave"]:
                    dif.append("plano de entrada trocou: %s → %s" % (a["plano"], linha["plano"]))
                for campo, nome in (("preco", "preço"), ("gb_base", "base"), ("gb_bonus", "bônus"), ("gb_total", "total"),
                                    ("gb_redes", "redes sociais")):
                    if str(a[campo]) != str(linha[campo]):
                        dif.append("%s %s → %s" % (nome, a[campo] or "–", linha[campo] or "–"))
            linha["mudou"] = "; ".join(dif)
            anterior[rot] = linha
            out.append(linha)
    SAIDA.parent.mkdir(exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS_E)
        w.writeheader()
        w.writerows(out)
    return out


def resumo(linhas, data=None):
    """Texto curto do dia: o que mudou nos planos de entrada (ou 'sem mudança')."""
    data = data or max(l["data"] for l in linhas)
    dia = [l for l in linhas if l["data"] == data]
    mud = ["%s: %s" % (l["rotulo"], l["mudou"]) for l in dia if l["mudou"]]
    return mud


if __name__ == "__main__":
    ls = gerar()
    ult = max(l["data"] for l in ls)
    for l in ls:
        if l["data"] == ult:
            print("%-20s %-38s R$%7.2f base %-5s bônus %-5s total %-5s R$/GB %-5s %s" % (
                l["rotulo"], l["plano"][:38], l["preco"], l["gb_base"], l["gb_bonus"], l["gb_total"], l["rs_gb_total"],
                l["mudou"] or "sem mudança"))
