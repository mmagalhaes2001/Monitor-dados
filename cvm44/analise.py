#!/usr/bin/env python3
"""Analisa um formulário recém-lido contra o histórico da própria empresa (12 meses anteriores),
por grupo (Controlador, Conselho, Diretoria, Outros, Recompra), e diz se é relevante.

Uso: python cvm44/analise.py PROTOCOLO [--png saida.png]
Saída: JSON {"relevante": bool, "nivel": "alta"|"media"|"baixa", "texto": str, "png": caminho|None}

Regras (sem IA, só comparação com o histórico da empresa):
- líquido do grupo no mês (R$) vs meses anteriores com atividade do mesmo grupo:
  ALTA  : |líquido| >= R$ 5 mi e >= 2x a média dos meses ativos, OU maior dos 13 meses com >= R$ 1 mi,
          OU controlador/conselho/diretoria negociou pela 1ª vez em 12 meses com >= R$ 1 mi,
          OU inverteu direção (vinha comprando e vendeu, ou vice-versa) com >= R$ 1 mi
  MÉDIA : |líquido| >= R$ 1 mi, ou >= 1,5x a média dos meses ativos
  BAIXA : resto (inclusive "sem movimentação")
- Recompra: compara volume do mês com a média dos meses em que houve recompra; ALTA se >= 2x ou se
  é a 1ª recompra em 12 meses com >= R$ 5 mi; MÉDIA se >= 1,3x ou parou após 3+ meses seguidos comprando.
"""
import glob, json, os, sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "dados")
sys.path.insert(0, AQUI)
from planilha import _classe, GRUPOS, chave_ordem, fmt  # noqa: E402

MI = 1e6


def carregar(ticker):
    docs = []
    for p in glob.glob(os.path.join(DADOS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        if d["ticker"] == ticker:
            docs.append(d)
    ult = {}
    for d in docs:
        k = (d["ref"], d["tipo"])
        if k not in ult or int(d["versao"]) > int(ult[k]["versao"]):
            ult[k] = d
    return list(ult.values())


def serie(docs):
    """{grupo: {ref: {"compra": R$, "venda": R$, "q_compra": n, "q_venda": n}}}"""
    s = defaultdict(lambda: defaultdict(lambda: {"compra": 0.0, "venda": 0.0, "q_compra": 0.0, "q_venda": 0.0}))
    for d in docs:
        cons = "Consolidada" in d["tipo"]
        for p in d["paginas"]:
            if cons:
                g = GRUPOS.get(p["orgao"], "Outros")
            else:
                g = "Recompra"
            for m in p["movimentacoes"]:
                c = _classe(m["operacao"])
                if c == "outro": continue
                if g == "Recompra" and (not m["ativo"].lower().startswith("aç") or (m["quantidade"] or 0) <= 0): continue
                s[g][d["ref"]][c] += m["volume"] or 0
                s[g][d["ref"]]["q_" + c] += m["quantidade"] or 0
    return s


def analisar(protocolo, png=None):
    p = os.path.join(DADOS, protocolo + ".json")
    if not os.path.exists(p):
        return {"relevante": False, "nivel": "baixa", "texto": "", "png": None}
    d = json.load(open(p, encoding="utf-8"))
    ticker, ref, cons = d["ticker"], d["ref"], "Consolidada" in d["tipo"]
    docs = carregar(ticker)
    s = serie(docs)
    refs = sorted({r for g in s for r in s[g]} | {ref}, key=chave_ordem)
    hist = [r for r in refs if chave_ordem(r) < chave_ordem(ref)][-12:]
    grupos = ["Controlador", "Conselho", "Diretoria", "Outros"] if cons else ["Recompra"]

    nivel, frases, series_png = "baixa", [], {}
    ordem = {"baixa": 0, "media": 1, "alta": 2}

    def sobe(n):
        nonlocal nivel
        if ordem[n] > ordem[nivel]: nivel = n

    for g in grupos:
        atual = s[g].get(ref)
        liq = (atual["compra"] - atual["venda"]) if atual else 0.0
        bruto = (atual["compra"] + atual["venda"]) if atual else 0.0
        h = [s[g][r]["compra"] - s[g][r]["venda"] for r in hist if r in s[g]]
        ativos = [x for x in h if abs(x) > 0]
        media = sum(abs(x) for x in ativos) / len(ativos) if ativos else 0.0
        maior = max((abs(x) for x in ativos), default=0.0)
        series_png[g] = [(r, s[g][r]["compra"] - s[g][r]["venda"] if r in s[g] else 0.0) for r in hist] + [(ref, liq)]
        if g == "Recompra":
            vol = atual["compra"] if atual else 0.0
            hv = [s[g][r]["compra"] for r in hist if r in s[g] and s[g][r]["compra"] > 0]
            mv = sum(hv) / len(hv) if hv else 0.0
            seguidos = 0
            for r in reversed(hist):
                if r in s[g] and s[g][r]["compra"] > 0: seguidos += 1
                else: break
            if vol > 0:
                base = "Recompra R$ %s (%s ações, média R$ %.2f)" % (fmt(vol), fmt(atual["q_compra"]), vol / atual["q_compra"])
                if not hv and vol >= 5 * MI: sobe("alta"); frases.append(base + " — 1ª recompra em 12 meses")
                elif mv and vol >= 2 * mv: sobe("alta"); frases.append(base + " — %.1fx a média mensal (R$ %s)" % (vol / mv, fmt(mv)))
                elif mv and vol >= 1.3 * mv: sobe("media"); frases.append(base + " — %.1fx a média mensal (R$ %s)" % (vol / mv, fmt(mv)))
                elif mv and seguidos >= 2 and vol <= 0.4 * mv: sobe("media"); frases.append(base + " — desacelerou forte (%.0f%% da média mensal, R$ %s)" % (100 * vol / mv, fmt(mv)))
                elif mv: frases.append(base + " — em linha (média R$ %s)" % fmt(mv))
                else: frases.append(base)
            else:
                if seguidos >= 3: sobe("media"); frases.append("Recompra parou após %d meses seguidos comprando" % seguidos)
                else: frases.append("Sem recompra no mês")
            if atual and atual["venda"] > 0:
                frases.append("Tesouraria vendeu/usou R$ %s" % fmt(atual["venda"]))
            continue
        # insiders
        if bruto == 0:
            continue
        dirc = "comprou" if liq > 0 else "vendeu"
        base = "%s %s R$ %s líquido" % (g, dirc, fmt(abs(liq)))
        if abs(liq) < 1 * MI and bruto < 1 * MI:
            frases.append(base + " (pequeno)")
            continue
        motivos = []
        if not ativos and g in ("Controlador", "Conselho", "Diretoria"): motivos.append("1ª movimentação em 12 meses")
        if ativos and abs(liq) >= maior and abs(liq) >= 1 * MI: motivos.append("maior dos últimos 13 meses")
        ult_dir = next((x for x in reversed(ativos) if x), None)
        if ult_dir is not None and (ult_dir > 0) != (liq > 0) and abs(liq) >= 1 * MI: motivos.append("inverteu direção (vinha %s)" % ("comprando" if ult_dir > 0 else "vendendo"))
        if media and abs(liq) >= 2 * media and abs(liq) >= 5 * MI: motivos.append("%.1fx a média (R$ %s)" % (abs(liq) / media, fmt(media)))
        if motivos:
            sobe("alta"); frases.append(base + " — " + "; ".join(motivos))
        elif abs(liq) >= 1 * MI or (media and abs(liq) >= 1.5 * media):
            sobe("media"); frases.append(base + (" — %.1fx a média" % (abs(liq) / media) if media else ""))
        else:
            frases.append(base)
    if not frases:
        frases.append("Sem movimentação de insiders no mês" if cons else "Sem recompra no mês")

    out = {"relevante": nivel != "baixa", "nivel": nivel, "texto": "; ".join(frases), "png": None}
    if png and any(any(v for _, v in serie_) for serie_ in series_png.values()):
        out["png"] = grafico(ticker, ref, series_png, png)
    return out


def grafico(ticker, ref, series_png, caminho):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    grupos = [g for g, sr in series_png.items() if any(v for _, v in sr)]
    if not grupos: return None
    fig, axes = plt.subplots(len(grupos), 1, figsize=(7, 2.2 * len(grupos) + 0.6), squeeze=False, dpi=160)
    for ax, g in zip(axes[:, 0], grupos):
        sr = series_png[g]
        xs = [r[:2] + "/" + r[5:] for r, _ in sr]
        ys = [v / MI for _, v in sr]
        cores = ["#2E75B6" if v >= 0 else "#C00000" for v in ys]
        cores[-1] = "#1F3864" if ys[-1] >= 0 else "#7F0000"
        ax.bar(xs, ys, color=cores, width=0.7)
        ax.axhline(0, color="#999", lw=0.8)
        ax.set_title("%s — %s: líquido mensal (R$ mi)%s" % (ticker, g, "" if g != "Recompra" else " (volume recomprado)"), fontsize=10, loc="left")
        ax.tick_params(axis="x", labelsize=7, rotation=0); ax.tick_params(axis="y", labelsize=8)
        for sp in ("top", "right"): ax.spines[sp].set_visible(False)
        ax.annotate("%.1f" % ys[-1], (len(xs) - 1, ys[-1]), ha="center", va="bottom" if ys[-1] >= 0 else "top", fontsize=8, fontweight="bold")
    fig.text(0.01, 0.005, "Fonte: CVM (formulários art. 11 Res. CVM 44), ref. %s. Azul = compra líquida, vermelho = venda líquida; barra escura = mês atual." % ref, fontsize=6.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(caminho); plt.close(fig)
    return caminho


if __name__ == "__main__":
    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    print(json.dumps(analisar(sys.argv[1], png), ensure_ascii=False))
