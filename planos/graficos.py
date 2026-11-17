#!/usr/bin/env python3
"""Gráficos compartilhados pelo site e pelo relatório mensal.

mapa(): todos os planos de um grupo num plano R$ × GB (ou × Mega), um ponto por plano, cor por operadora.
Onde o plano mudou desde a data de comparação, a posição antiga aparece vazada e uma seta liga à atual
(mais GB pelo mesmo preço = seta para a direita; reajuste = seta para cima). Plano novo ganha anel; plano
que saiu fica só vazado. Planos que trocaram de nome junto com os GB (mesma operadora, tipo e preço) são
tratados como o mesmo plano.
"""
import io
from collections import defaultdict
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["font.family"] = "sans-serif"
import matplotlib.pyplot as plt  # noqa: E402

OPS = ["Vivo", "Claro", "TIM", "NuCel"]
COR = {"Vivo": "#7B2CBF", "Claro": "#D62828", "TIM": "#1D4ED8", "NuCel": "#E0A100"}
MARCA = {"Pré": "s", "Controle": "o", "Lite/Anual": "D", "Flex": "^", "Pós": "o", "Família": "o", "Fibra": "o",
         "FWA (5G residencial)": "o"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def data_comparacao(datas, ult, dias=30):
    """Primeira coleta de pelo menos `dias` atrás; se o histórico for mais curto, a primeira coleta."""
    alvo = (datetime.strptime(ult, "%Y-%m-%d") - timedelta(days=dias)).strftime("%Y-%m-%d")
    antes = [d for d in datas if d <= alvo]
    return antes[-1] if antes else datas[0]


def pontos(serie, tipos, data, campo):
    out = {}
    for r in serie:
        if r["data"] == data and r["tipo"] in tipos:
            if r["tipo"] == "Pré" and num(r.get("dias")) and num(r["dias"]) < 28:
                continue  # no mapa, pré só com recarga de ~30 dias (comparável à mensalidade)
            x, y = num(r[campo]), num(r["preco"])
            if x and y:
                out[(r["operadora"], r.get("chave") or r["plano"])] = {"x": x, "y": y, "op": r["operadora"],
                                                                        "tipo": r["tipo"], "plano": r["plano"]}
    return out


def comparar(serie, tipos, d0, d1, campo="gb"):
    """Devolve lista de dicts: atual, antigo (ou None), estado (igual, mudou, novo, saiu).

    Ordem do pareamento: (1) mesmo plano sem mudança; (2) mesma operadora/tipo/preço (GB mudou, às vezes com
    nome novo, como na Claro, que põe os GB no nome); (3) mesmo plano com preço diferente; o resto é novo/saiu.
    Plano que só entrou no monitor nas primeiras coletas (inclusão de página) conta como base, não como novo.
    """
    a, b = pontos(serie, tipos, d0, campo), pontos(serie, tipos, d1, campo)
    datas = sorted({r["data"] for r in serie})
    inicio_base = datas[1:2]  # 2ª coleta: entradas de página (ex.: TIM Fit em 12/11), não lançamentos
    for dt in inicio_base:  # completa a base com o que entrou logo depois da 1ª coleta
        if dt > d0:
            for k, v in pontos(serie, tipos, dt, campo).items():
                if k not in a and k in b:
                    a[k] = v
    res, sa, sb = [], set(a), set(b)

    def casa(ka, kb, estado):
        res.append({"atual": b[kb], "antigo": a[ka], "estado": estado})
        sa.discard(ka); sb.discard(kb)

    for k in list(sb):
        if k in sa and (a[k]["x"], a[k]["y"]) == (b[k]["x"], b[k]["y"]):
            casa(k, k, "igual")
    livres = defaultdict(list)
    for k in sorted(sa, key=lambda k: a[k]["x"]):
        livres[(a[k]["op"], a[k]["tipo"], a[k]["y"])].append(k)
    for k in sorted(sb, key=lambda k: b[k]["x"]):
        cand = [c for c in livres.get((b[k]["op"], b[k]["tipo"], b[k]["y"]), []) if c in sa]
        if cand:
            casa(cand[0], k, "mudou")
    for k in list(sb):
        if k in sa:
            casa(k, k, "mudou")
    # sobrou exatamente um que saiu e um que entrou na mesma operadora/tipo: é o mesmo degrau reformulado
    for k in list(sb):
        mesmo = [c for c in sa if (a[c]["op"], a[c]["tipo"]) == (b[k]["op"], b[k]["tipo"])]
        outros = [c for c in sb if (b[c]["op"], b[c]["tipo"]) == (b[k]["op"], b[k]["tipo"])]
        if len(mesmo) == 1 and len(outros) == 1:
            casa(mesmo[0], k, "mudou")
    for k in sb:
        res.append({"atual": b[k], "antigo": None, "estado": "novo"})
    for k in sa:
        res.append({"atual": None, "antigo": a[k], "estado": "saiu"})
    return res


def mapa(serie, tipos, d0, d1, campo="gb", titulo="", tamanho=(8.5, 5.2), xmax=None, ymax=None):
    """xmax/ymax cortam planos fora da faixa (ex.: fibra de 2 a 10 Giga), para não achatar o gráfico."""
    pts = comparar(serie, tipos, d0, d1, campo)
    if not pts:
        return None, pts
    fig, ax = plt.subplots(figsize=tamanho)
    vistos = set()
    for p in pts:
        at, an = p["atual"], p["antigo"]
        op = (at or an)["op"]
        cor = COR.get(op, "#555")
        mk = MARCA.get((at or an)["tipo"], "o")
        if xmax and (at or an)["x"] > xmax or ymax and (at or an)["y"] > ymax:
            continue
        if an and p["estado"] in ("mudou", "saiu"):
            ax.scatter(an["x"], an["y"], s=55, facecolors="white", edgecolors=cor, linewidths=1.3, marker=mk, zorder=2)
        if at:
            vistos.add(op)
            ax.scatter(at["x"], at["y"], s=60, color=cor, marker=mk, zorder=3)
            if p["estado"] == "novo":
                ax.scatter(at["x"], at["y"], s=170, facecolors="none", edgecolors=cor, linewidths=1, zorder=3)
        if at and an and p["estado"] == "mudou":
            ax.annotate("", xy=(at["x"], at["y"]), xytext=(an["x"], an["y"]),
                        arrowprops=dict(arrowstyle="-|>", color=cor, lw=1.2, alpha=0.8, shrinkA=5, shrinkB=5), zorder=1)
            dx, dy = at["x"] - an["x"], at["y"] - an["y"]
            txt = " ".join(t for t in ["%+g%s" % (dx, " Mega" if campo == "mega" else "GB") if dx else "",
                                        ("%+.0f R$" % dy).replace("+-", "-") if dy else ""] if t)
            ax.annotate(txt, (at["x"], at["y"]), xytext=(6, 4), textcoords="offset points", fontsize=7.5, color=cor)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(color="#ececec", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=9, colors="#555")
    ax.set_xlabel("Mega" if campo == "mega" else "GB (franquia total com bônus)", fontsize=9, color="#555")
    ax.set_ylabel("R$ por mês" + (" (no pré, a recarga)" if "Pré" in tipos else ""), fontsize=9, color="#555")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    if titulo:
        ax.set_title(titulo, fontsize=11, loc="left")
    # legenda: operadoras + formatos
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="o", color=COR[o], linestyle="", label=o) for o in OPS if o in vistos]
    l = [x.get_label() for x in h]
    forma = [Line2D([], [], marker=MARCA[t], color="#777", linestyle="", label=t) for t in tipos if len(tipos) > 1]
    vaz = [Line2D([], [], marker="o", markerfacecolor="white", markeredgecolor="#777", color="#777", linestyle="",
                  label=datetime.strptime(d0, "%Y-%m-%d").strftime("em %d/%m"))]
    ax.legend(h + forma + vaz, l + [f.get_label() for f in forma] + [vaz[0].get_label()],
              frameon=False, fontsize=8, loc="upper left", ncol=2)
    return fig, pts


def svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):].replace("<svg ", '<svg class="graf" ', 1)


def entrada(serie, tipos, data, campo="gb"):
    """Plano mais barato de cada operadora no grupo, na data."""
    out = {}
    for r in serie:
        if r["data"] == data and r["tipo"] in tipos and num(r["preco"]):
            if r["tipo"] == "Pré" and r.get("dias") and num(r["dias"]) and num(r["dias"]) < 28:
                continue  # entrada do pré = recarga de ~30 dias, como nos relatórios do mercado
            if r["tipo"] == "Controle" and "fit" in (r.get("linha") or "").lower():
                continue  # Controle Fit é híbrido (cartão, sem fatura), como Lite e Flex: fica fora do Controle tradicional
            o = r["operadora"]
            if o not in out or num(r["preco"]) < out[o]["preco"]:
                out[o] = {"preco": num(r["preco"]), "x": num(r[campo]), "plano": r["plano"],
                          "unid": num(r["valor_unidade"])}
    return out
