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
        if atual["compra"] > 0 and atual["venda"] > 0:
            ops = [m["operacao"].lower() for d_ in docs if d_["ref"] == ref and "Consolidada" in d_["tipo"] for p_ in d_["paginas"]
                   if GRUPOS.get(p_["orgao"], "Outros") == g for m in p_["movimentacoes"]]
            exerc = any(("opç" in o or "exerc" in o) and _classe(o) == "compra" for o in ops)
            base = "%s comprou R$ %s%s e vendeu R$ %s (líquido: %s R$ %s)" % (
                g, fmt(atual["compra"]), " via exercício de opções" if exerc else "", fmt(atual["venda"]), dirc, fmt(abs(liq)))
        else:
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
        # sequência: quantos meses seguidos (antes deste) o grupo veio na mesma direção
        seq = 0
        for r in reversed(hist):
            x = s[g][r]["compra"] - s[g][r]["venda"] if r in s[g] else 0
            if x and (x > 0) == (liq > 0): seq += 1
            elif x: break
            else: break
        # preço desta operação vs média das operações anteriores na mesma direção
        lado = "venda" if liq < 0 else "compra"
        q_at = atual["q_" + lado]; p_at = atual[lado] / q_at if q_at else 0
        qh = sum(s[g][r]["q_" + lado] for r in hist if r in s[g]); vh = sum(s[g][r][lado] for r in hist if r in s[g])
        p_h = vh / qh if qh else 0
        extra = []
        if seq >= 2: extra.append("%dº mês seguido %s" % (seq + 1, "vendendo" if liq < 0 else "comprando"))
        if p_h and p_at and abs(p_at / p_h - 1) >= 0.15:
            extra.append("a R$ %.2f, %s%.0f%% vs média anterior de R$ %.2f" % (p_at, "+" if p_at > p_h else "−", abs(p_at / p_h - 1) * 100, p_h))
        if motivos:
            sobe("alta"); frases.append(base + " — " + "; ".join(motivos + extra))
        elif abs(liq) >= 1 * MI or (media and abs(liq) >= 1.5 * media):
            sobe("media"); frases.append(base + " — " + "; ".join(((["%.1fx a média" % (abs(liq) / media)] if media else []) + extra) or ["acima de R$ 1 mi"]))
        else:
            frases.append(base + (" — " + "; ".join(extra) if extra else ""))
    if not frases:
        frases.append("Sem movimentação de insiders no mês" if cons else "Sem recompra no mês")

    flags = casos_especiais(d)
    if flags:
        frases.append("⚑ " + " ⚑ ".join(flags))
        sobe("media")
    if getattr(casos_especiais, "notas", None):
        frases.append("nota: " + "; ".join(casos_especiais.notas))
    out = {"relevante": nivel != "baixa", "nivel": nivel, "texto": "; ".join(frases), "png": None, "flags": flags}
    if png and any(any(v for _, v in serie_) for serie_ in series_png.values()):
        out["png"] = grafico(ticker, ref, series_png, png)
    return out


def casos_especiais(d):
    """Sinais que mudam a leitura ou indicam erro de preenchimento. Devolve lista de frases curtas."""
    import statistics
    flags = []; notas = []
    cons = "Consolidada" in d["tipo"]
    import re as _re
    for p_ in d["paginas"]:
        for m in p_["movimentacoes"]:
            m["operacao"] = _re.sub(r"\s+", " ", m["operacao"]).strip()
    if d.get("versao", "1") != "1":
        flags.append("reapresentação (versão %s) — compare com a anterior" % d["versao"])
    for p in d["paginas"]:
        g = GRUPOS.get(p["orgao"], "Outros") if cons else "Companhia"
        movs = [m for m in p["movimentacoes"] if (m["quantidade"] or 0) != 0]
        vista = [m for m in movs if "à vista" in m["operacao"].lower() and (m["preco"] or 0) > 0]
        exerc = [m for m in movs if ("opç" in m["operacao"].lower() or "exerc" in m["operacao"].lower()) and _classe(m["operacao"]) == "compra"]
        vendas = [m for m in movs if _classe(m["operacao"]) == "venda"]
        compras_vista = [m for m in vista if _classe(m["operacao"]) == "compra"]
        # 1) exercício de opção + venda no mesmo mês: venda é cash-out de remuneração, não redução de posição antiga
        if cons and exerc and vendas:
            qe = sum(m["quantidade"] for m in exerc); qv = sum(m["quantidade"] for m in vendas)
            pe = sum(m["volume"] or 0 for m in exerc) / qe if qe else 0; pv = sum(m["volume"] or 0 for m in vendas) / qv if qv else 0
            flags.append("%s: venda vinculada a exercício de opções (exerceu %s a R$ %.2f, vendeu %s a R$ %.2f) — não é redução de posição antiga" % (g, fmt(qe), pe, fmt(qv), pv))
        # 2) preço implícito absurdo → provável erro de preenchimento da companhia
        precos = [m["preco"] for m in vista]
        if len(precos) >= 1:
            med = statistics.median(precos)
            for m in vista:
                if m["preco"] < 0.05 or (med > 0 and (m["preco"] < med / 20 or m["preco"] > med * 20)):
                    flags.append("%s: %s de %s ações a R$ %.3f (R$ %s) — provável erro de preenchimento da companhia, confirmar antes de somar" % (
                        g, m["operacao"], fmt(m["quantidade"]), m["preco"], fmt(m["volume"] or 0)))
        # 3) saldos não fecham sem derivativo que explique
        si = {(x["ativo"], x["caracteristica"]): x["quantidade"] for x in p["saldo_inicial"]}
        sf = {(x["ativo"], x["caracteristica"]): x["quantidade"] for x in p["saldo_final"]}
        for k in set(si) & set(sf):
            if not k[0].lower().startswith("aç"): continue
            c = sum(m["quantidade"] or 0 for m in movs if (m["ativo"], m["caracteristica"]) == k and _classe(m["operacao"]) == "compra")
            v = sum(m["quantidade"] or 0 for m in movs if (m["ativo"], m["caracteristica"]) == k and _classe(m["operacao"]) == "venda")
            outros = [m for m in movs if (m["ativo"], m["caracteristica"]) == k and _classe(m["operacao"]) == "outro"]
            dif = (si[k] or 0) + c - v - (sf[k] or 0)
            if abs(dif) > 0.5 and not outros and si[k] is not None:
                flags.append("%s: saldos não fecham (%s + %s − %s ≠ %s; diferença %s ações)" % (g, fmt(si[k]), fmt(c), fmt(v), fmt(sf[k]), fmt(abs(dif))))
        # 4) operações realmente atípicas (termo, doação, herança, empréstimo, permuta, leilão de frações...)
        chaves = ("termo", "doaç", "heran", "emprést", "alugu", "permuta", "leilão", "integraliz", "dação", "conferência", "cisão", "incorpora")
        atip = [m for m in movs if any(k in m["operacao"].lower() for k in chaves)]
        raros = sorted({m["operacao"] for m in atip})
        pos_ref = max([v for k_, v in si.items() if k_[0].lower().startswith("aç") and v] or [0])
        q_atip = sum(abs(m["quantidade"] or 0) for m in atip if m["ativo"].lower().startswith("aç"))
        # aluguel/termo/opção em volume desprezível (<0,1% da posição) só vira nota, não sobe o nível
        if raros and pos_ref and q_atip / pos_ref < 0.001:
            notas.append("%s: %s em lote desprezível (%s ações, %.3f%% da posição)" % (g, "; ".join(r[:30] for r in raros), fmt(q_atip), 100 * q_atip / pos_ref))
        elif raros:
            flags.append("%s: operação atípica — %s" % (g, "; ".join(r[:45] for r in raros)))
        # 5) zerou ou montou posição do zero
        for k in set(si) & set(sf):
            if not k[0].lower().startswith("aç"): continue
            if (si[k] or 0) > 0 and (sf[k] or 0) == 0 and vendas and cons:
                flags.append("%s zerou a posição em %s %s" % (g, k[0], k[1]))
            if (si[k] or 0) == 0 and (sf[k] or 0) > 0 and compras_vista and cons and g in ("Controlador", "Conselho", "Diretoria"):
                flags.append("%s montou posição do zero em %s %s (%s ações)" % (g, k[0], k[1], fmt(sf[k])))
        # 5b) vendeu/comprou fatia grande da posição (insiders, só à vista)
        if cons and g in ("Controlador", "Conselho", "Diretoria"):
            for k in set(si):
                if not k[0].lower().startswith("aç") or not si[k]: continue
                qv = sum(m["quantidade"] or 0 for m in vista if (m["ativo"], m["caracteristica"]) == k and _classe(m["operacao"]) == "venda")
                qc = sum(m["quantidade"] or 0 for m in vista if (m["ativo"], m["caracteristica"]) == k and _classe(m["operacao"]) == "compra")
                if qv / si[k] >= 0.2 and not exerc: flags.append("%s vendeu %.0f%% da posição que tinha em %s %s" % (g, 100 * qv / si[k], k[0], k[1]))
                if qc / si[k] >= 0.2: flags.append("%s aumentou a posição em %.0f%% (%s %s)" % (g, 100 * qc / si[k], k[0], k[1]))
        # 6) individual: venda de tesouraria sem ser plano de remuneração
        if not cons:
            vt = [m for m in vendas if "à vista" in m["operacao"].lower()]
            if vt:
                flags.append("Tesouraria vendeu em mercado %s ações (R$ %s)" % (fmt(sum(m["quantidade"] for m in vt)), fmt(sum(m["volume"] or 0 for m in vt))))
    casos_especiais.notas = notas
    return flags


def grafico(ticker, ref, series_png, caminho):
    try:
        import matplotlib
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "matplotlib==3.9.2", "pillow"], capture_output=True, timeout=300)
        try:
            import matplotlib
        except ImportError:
            return None   # sem gráfico, mas o aviso sai normalmente
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
