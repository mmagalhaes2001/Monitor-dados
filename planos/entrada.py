#!/usr/bin/env python3
"""Cesta mensal de produtos (SP), no formato dos trackers de mercado: o mais barato de cada operadora em
Pré (por validade: 30, 22–25, 17–20 e 15 dias), Controle de entrada (Vivo, Claro, TIM, NuCel), Digital de
entrada (Vivo Lite, Claro Flex, TIM Fit; anual e mensal) e Pós de entrada (Vivo, Claro, TIM Black). Para cada coleta: franquia base (recorrente), bônus, total (de uso livre),
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
from historico import COLS, COLS_LOG, HIST, INCLUSOES, LOG, ler  # noqa: E402
from taxonomia import RE_CARIMBADO, gb_livre  # noqa: E402

REF = "SP"
SAIDA = AQUI / "dados" / "entrada.csv"
# Cesta mensal (formato dos trackers de mercado): o mais barato de cada operadora em cada categoria.
# grupo, rótulo, operadora, linha comercial (regex), excluir plano (regex), validade em dias (mín, máx) ou None,
# critério ("barato" = menor preço; "mais_gb" = maior franquia na faixa)
PLANOS = [
    ("Pré 30 dias", "Vivo", "Vivo", r"^Vivo Pré", r"^$", (28, 31), "barato"),
    ("Pré 30 dias", "Vivo (maior)", "Vivo", r"^Vivo Pré", r"^$", (28, 31), "mais_gb"),
    ("Pré 30 dias", "Claro", "Claro", r"^Claro Pré", r"^$", (28, 31), "barato"),
    ("Pré 30 dias", "TIM", "TIM", r"^TIM Pré", r"^$", (28, 31), "barato"),
    ("Pré 22–25 dias", "Vivo", "Vivo", r"^Vivo Pré", r"^$", (21, 26), "barato"),
    ("Pré 22–25 dias", "Claro", "Claro", r"^Claro Pré", r"^$", (21, 26), "barato"),
    ("Pré 22–25 dias", "TIM", "TIM", r"^TIM Pré", r"^$", (21, 26), "barato"),
    ("Pré 17–20 dias", "Vivo", "Vivo", r"^Vivo Pré", r"^$", (16, 20), "barato"),
    ("Pré 17–20 dias", "Claro", "Claro", r"^Claro Pré", r"^$", (16, 20), "barato"),
    ("Pré 17–20 dias", "TIM", "TIM", r"^TIM Pré", r"^$", (16, 20), "barato"),
    ("Pré 15 dias", "Vivo", "Vivo", r"^Vivo Pré", r"^$", (14, 15), "barato"),
    ("Pré 15 dias", "Claro", "Claro", r"^Claro Pré", r"^$", (14, 15), "barato"),
    ("Pré 15 dias", "TIM", "TIM", r"^TIM Pré", r"^$", (14, 15), "barato"),
    ("Controle de entrada", "Vivo Controle", "Vivo", r"^Vivo Controle$", r"youtube|netflix|max|disney|premium|amazon|educa|m[uú]sica|sa[uú]de|entret", None, "barato"),
    ("Controle de entrada", "Claro Controle", "Claro", r"^Claro Controle$", r"geforce", None, "barato"),
    ("Controle de entrada", "TIM Controle", "TIM", r"^TIM Controle$", r"^$", None, "barato"),
    ("Controle de entrada", "NuCel", "NuCel", r"^NuCel$", r"^$", None, "barato"),
    ("Digital de entrada", "Vivo Lite", "Vivo", r"^Vivo Lite", r"mensal", None, "barato"),
    ("Digital de entrada", "Claro Flex", "Claro", r"^Claro Flex", r"mega", None, "barato"),
    ("Digital de entrada", "TIM Fit Anual", "TIM", r"^TIM Controle Fit Anual", r"^$", None, "barato"),
    ("Digital de entrada", "Vivo Lite mensal", "Vivo", r"^Vivo Lite", r"^(?!.*mensal)", None, "barato"),
    ("Digital de entrada", "TIM Fit Mensal", "TIM", r"^TIM Controle Fit$", r"^$", None, "barato"),
    ("Pós de entrada", "Vivo Pós", "Vivo", r"^Vivo Pós$", r"^$", None, "barato"),
    ("Pós de entrada", "Claro Pós", "Claro", r"^Claro Pós$", r"geforce", None, "barato"),
    ("Pós de entrada", "TIM Black", "TIM", r"^TIM Black$", r"^$", None, "barato"),
]
GRUPOS = list(dict.fromkeys(p[0] for p in PLANOS))
COLS_E = ["data", "grupo", "rotulo", "dias", "operadora", "plano", "chave", "preco", "gb_base", "gb_bonus", "gb_total",
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


def dias_de(r):
    m = re.search(r"(\d+)\s*dias", r["condicao"] or "", re.I)
    return int(m.group(1)) if m else None


def escolher(vig, op, re_linha, re_excl, faixa=None, criterio="barato"):
    cand = [r for r in vig if r["operadora"] == op and re.search(re_linha, r["linha"] or "", re.I)
            and not re.search(re_excl, r["plano"], re.I) and f(r["preco"])]
    if faixa:
        cand = [r for r in cand if dias_de(r) and faixa[0] <= dias_de(r) <= faixa[1]]
    if not cand:
        return None
    if criterio == "mais_gb":
        return max(cand, key=lambda r: (f(r["gb_total"]) or 0, -f(r["preco"])))
    return min(cand, key=lambda r: (f(r["preco"]), -(f(r["gb_total"]) or 0)))


def gerar():
    hist = ler(HIST, COLS)
    datas = sorted({r["data"] for r in ler(LOG, COLS_LOG) if r["ok"] == "sim" and r["uf"] == REF})
    out, anterior, reinicio = [], {}, {}
    for d in datas:
        vig = [r for r in hist if r["uf"] == REF and r["inicio"] <= d and not (r["fim"] and r["fim"] < d)]
        for grupo, rot, op, re_linha, re_excl, faixa, criterio in PLANOS:
            r = escolher(vig, op, re_linha, re_excl, faixa, criterio)
            if not r:
                continue
            preco = f(r["preco"])
            base, bonus, redes = decompor(r)
            total = (base + bonus) if base is not None else gb_livre(r["gb_total"], r["gb_detalhe"])
            linha = {"data": d, "grupo": grupo, "rotulo": rot, "dias": dias_de(r) or "", "operadora": op, "plano": r["plano"], "chave": r["chave"],
                     "preco": preco, "gb_base": base if base is not None else "", "gb_bonus": bonus if bonus is not None else "",
                     "gb_total": total or "", "gb_redes": redes or "",
                     "rs_gb_total": round(preco / total, 2) if total else "",
                     "rs_gb_base": round(preco / base, 2) if base else "", "condicao": r["condicao"]}
            chave_rot = (grupo, rot)
            a = anterior.get(chave_rot)
            dif = []
            incluido = any(op == o and linha["chave"].startswith(pref) and d <= dt for (o, pref), dt in INCLUSOES.items())
            if a and a["chave"] != linha["chave"] and incluido:
                a = None  # plano que já existia e só passou a ser lido agora: a série recomeça aqui, sem mudança
                reinicio[chave_rot] = d
            if a:
                if a["chave"] != linha["chave"]:
                    if a["preco"] == linha["preco"]:
                        dif.append("mesmo plano com franquia nova (no site: %s → %s)" % (a["plano"], linha["plano"]))
                    else:
                        dif.append("plano de entrada trocou: %s → %s" % (a["plano"], linha["plano"]))
                for campo, nome in (("preco", "preço"), ("gb_base", "base"), ("gb_bonus", "bônus"), ("gb_total", "total"),
                                    ("gb_redes", "redes sociais")):
                    if str(a[campo]) != str(linha[campo]):
                        dif.append("%s %s → %s" % (nome, a[campo] or "–", linha[campo] or "–"))
            linha["mudou"] = "; ".join(dif)
            anterior[chave_rot] = linha
            out.append(linha)
    out = [l for l in out if l["data"] >= reinicio.get((l["grupo"], l["rotulo"]), "")]
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
