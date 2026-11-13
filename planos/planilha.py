#!/usr/bin/env python3
"""Gera planos/planos_operadoras.xlsx a partir de planos/dados/historico.csv e coletas.csv.

Abas:
  Linhas comerciais – por tipo (Pré, Controle, Lite/Anual, Flex, Pós, Família, Fibra), os nomes que cada operadora usa,
                     nº de planos, faixa de preço e de GB/velocidade hoje
  Pré, Controle, … – uma aba por tipo: grade de preços (plano × 27 capitais), para acompanhar cada tipo separado
  Atual            – planos que valem hoje, uma linha por plano × praça
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
ORD_SEG = {"pre": 0, "controle": 1, "lite": 2, "flex": 3, "pos": 4, "familia": 5, "fibra": 6, "fwa": 7}
SEG_NOME = {"pre": "Pré", "controle": "Controle", "lite": "Lite/Anual", "flex": "Flex", "pos": "Pós",
            "familia": "Família", "fibra": "Fibra", "fwa": "FWA (5G residencial)"}
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
    tipo_de = lambda r: r.get("tipo") or SEG_NOME.get(r["segmento"], r["segmento"])
    linha_de = lambda r: r.get("linha") or ""

    # Linhas comerciais
    lc = defaultdict(lambda: {"planos": set(), "precos": [], "dims": []})
    for r in vig:
        d = lc[(tipo_de(r), r["operadora"], linha_de(r))]
        d["planos"].add(r["chave"])
        if f(r["preco"]):
            d["precos"].append(f(r["preco"]))
        dim = f(r["gb_total"]) or f(r["velocidade_mega"])
        if isinstance(dim, float):
            d["dims"].append(dim)
    ord_tipo = {t: i for i, t in enumerate(["Pré", "Controle", "Lite/Anual", "Flex", "Pós", "Família", "Fibra", "FWA (5G residencial)"])}
    aba(wb, "Linhas comerciais", ["Tipo", "Operadora", "Linha comercial", "Nº planos", "Preço mín (R$)", "Preço máx (R$)",
                                  "GB/Mega mín", "GB/Mega máx"],
        [[k[0], k[1], k[2], len(v["planos"]), min(v["precos"]) if v["precos"] else None, max(v["precos"]) if v["precos"] else None,
          min(v["dims"]) if v["dims"] else None, max(v["dims"]) if v["dims"] else None]
         for k, v in sorted(lc.items(), key=lambda kv: (ord_tipo.get(kv[0][0], 9), kv[0][1], kv[0][2]))],
        {1: 12, 3: 30}, num_cols=(5, 6))

    # Uma aba por tipo: grade plano × praça
    por_tipo = defaultdict(lambda: defaultdict(dict))
    meta_t = {}
    for r in vig:
        k = (r["operadora"], linha_de(r), r["chave"])
        por_tipo[tipo_de(r)][k][r["uf"]] = f(r["preco"])
        meta_t[(tipo_de(r),) + k] = (r["plano"], f(r["gb_total"]) or f(r["velocidade_mega"]), r["condicao"])
    for tipo in sorted(por_tipo, key=lambda t: ord_tipo.get(t, 9)):
        g = por_tipo[tipo]
        linhas_t = []
        for k in sorted(g, key=lambda k: (k[0], k[1], min([v for v in g[k].values() if v] or [0]))):
            precos = [g[k].get(u) for u in UFS]
            val = [x for x in precos if x]
            m_ = meta_t[(tipo,) + k]
            linhas_t.append([k[0], k[1], m_[0], m_[1], m_[2], len(val), min(val) if val else None,
                             max(val) if val else None] + precos)
        ws = aba(wb, tipo.replace("/", "-").replace(" (5G residencial)", "")[:31], ["Operadora", "Linha comercial", "Plano", "GB / Mega", "Condição", "Nº praças",
                                              "Mín", "Máx"] + UFS, linhas_t, {2: 26, 3: 34, 5: 16},
                 num_cols=range(7, 9 + len(UFS)))
        for i in range(9, 9 + len(UFS)):
            ws.column_dimensions[get_column_letter(i)].width = 8

    aba(wb, "Atual", ["Operadora", "Tipo", "Linha comercial", "Plano", "UF", "Cidade", "Preço (R$)", "Preço De (R$)",
                      "Preço após promo (R$)", "Condição", "GB", "R$/GB", "Composição dos GB", "Velocidade (Mega)",
                      "Linhas", "Selo/promoção", "Benefícios", "Desde", "Visto em", "Link"],
        [[r["operadora"], tipo_de(r), linha_de(r), r["plano"], r["uf"], r["cidade"], f(r["preco"]),
          f(r["preco_de"]), f(r["preco_depois"]), r["condicao"], f(r["gb_total"]), f(r["rs_por_gb"]), r["gb_detalhe"],
          f(r["velocidade_mega"]), f(r["linhas"]), r["selo"], r["beneficios"], r["inicio"], r["visto_ultimo"], r["url"]]
         for r in sorted(vig, key=chave_ord)],
        {3: 26, 4: 34, 10: 18, 13: 40, 16: 22, 17: 60}, num_cols=(7, 8, 9, 12))

    # Mudanças (todas, desde o início)
    base = min((r["inicio"] for r in hist), default="")
    por = defaultdict(list)
    for r in hist:
        por[(r["operadora"], r["uf"], r["chave"])].append(r)
    mud = []
    for k, vs in por.items():
        vs.sort(key=lambda r: r["inicio"])
        if vs[0]["inicio"] > base:
            mud.append([vs[0]["inicio"], vs[0]["operadora"], tipo_de(vs[0]), linha_de(vs[0]), vs[0]["plano"], vs[0]["uf"],
                        "Novo", "", "", "R$ %s" % vs[0]["preco"]])
        for a, b in zip(vs, vs[1:]):
            for c in CAMPOS_COMPARA:
                if a[c] != b[c]:
                    mud.append([b["inicio"], b["operadora"], tipo_de(b), linha_de(b), b["plano"], b["uf"],
                                "Mudou", NOMES[c], a[c], b[c]])
        if vs[-1]["fim"]:
            mud.append([vs[-1]["fim"], vs[-1]["operadora"], tipo_de(vs[-1]), linha_de(vs[-1]), vs[-1]["plano"], vs[-1]["uf"],
                        "Saiu (visto pela última vez)", "", "R$ %s" % vs[-1]["preco"], ""])
    # junta "saiu" + "novo" do mesmo dia/operadora/praça/tipo com o mesmo preço numa linha "Mudou (nome/GB)"
    novos = [l for l in mud if l[6] == "Novo"]
    datas = sorted({r["visto_ultimo"] for r in hist} | {r["inicio"] for r in hist})
    prox = {d: datas[i + 1] for i, d in enumerate(datas[:-1])}
    usados, pares = set(), []
    for l in mud:
        if not l[6].startswith("Saiu"):
            continue
        n = next((x for x in novos if id(x) not in usados and x[1] == l[1] and x[5] == l[5] and x[2] == l[2]
                  and x[9] == l[8] and x[0] == prox.get(l[0])), None)
        if n:
            usados.update({id(n), id(l)})
            pares.append([n[0], n[1], n[2], n[3], "%s → %s" % (l[4], n[4]), n[5], "Mudou", "plano/GB (preço igual)", l[4], n[4]])
    mud = [l for l in mud if id(l) not in usados] + pares
    mud.sort(key=lambda l: (l[0], l[1], l[4], l[5]), reverse=True)
    aba(wb, "Mudanças", ["Data", "Operadora", "Tipo de plano", "Linha comercial", "Plano", "UF", "Mudança", "Campo", "Antes", "Depois"],
        mud, {4: 26, 5: 34, 9: 40, 10: 40})

    # Histórico
    aba(wb, "Histórico", ["Operadora", "Tipo", "Linha comercial", "Plano", "UF", "Preço (R$)", "Preço De", "Preço após promo",
                          "Condição", "GB", "R$/GB", "Composição dos GB", "Velocidade (Mega)", "Linhas", "Selo",
                          "Benefícios", "Início", "Fim", "Visto por último", "Chave"],
        [[r["operadora"], tipo_de(r), linha_de(r), r["plano"], r["uf"], f(r["preco"]), f(r["preco_de"]),
          f(r["preco_depois"]), r["condicao"], f(r["gb_total"]), f(r["rs_por_gb"]), r["gb_detalhe"], f(r["velocidade_mega"]),
          f(r["linhas"]), r["selo"], r["beneficios"], r["inicio"], r["fim"], r["visto_ultimo"], r["chave"]]
         for r in sorted(hist, key=lambda r: (r["operadora"], ORD_SEG.get(r["segmento"], 9), r["chave"], r["uf"], r["inicio"]))],
        {3: 26, 4: 34, 12: 40, 16: 60}, num_cols=(6, 7, 8, 11))

    # Coletas
    aba(wb, "Coletas", ["Data", "Hora", "Operadora", "UF", "Cidade", "Página", "OK", "Nº planos", "Praça na tela", "Erro"],
        [[r[c] for c in COLS_LOG] for r in sorted(log, key=lambda r: (r["data"], r["hora"], r["operadora"], r["uf"]), reverse=True)],
        {9: 24, 10: 60})
    nota = wb.create_sheet("Notas")
    for l in [
        "Fonte: sites de Vivo, Claro e TIM, lidos todo dia pelo robô nas 27 capitais (o mesmo que um cliente vê na vitrine).",
        "Fibra: é o preço de vitrine da cidade; a disponibilidade de fato depende do CEP. A TIM mostra as ofertas 'gerais' de Ultrafibra em todas as UFs.",
        "TIM: a grade vem do cadastro de ofertas do site, com a lista de UFs onde cada uma aparece.",
        "Mudança = qualquer alteração em preço, preço De, preço após promoção, condição, GB, composição dos GB, velocidade, nº de linhas, benefícios ou selo.",
        "Um plano só é dado como 'saiu' se a página daquela praça foi lida com sucesso naquele dia.",
        "Tipo e linha comercial: regras em planos/taxonomia.py.",
    ]:
        nota.append([l])
    nota.column_dimensions["A"].width = 140
    wb.save(ARQ)
    return ARQ


if __name__ == "__main__":
    print(gerar())
