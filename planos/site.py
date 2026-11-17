#!/usr/bin/env python3
"""Gera o site estático do monitor de planos em planos/_site/ (um index.html autossuficiente + arquivos para baixar).

Tudo embutido no HTML (estilo, gráficos em SVG, um pouco de JavaScript), sem nada carregado de fora:
abre em qualquer navegador, inclusive em rede que bloqueia CDNs.
Uso: python planos/site.py   (depois de historico.py, planilha.py e painel.py)
"""
import csv
import html
import io
import shutil
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"  # texto como texto: SVG bem menor
matplotlib.rcParams["font.family"] = "sans-serif"
import matplotlib.pyplot as plt  # noqa: E402

import sys
sys.path.insert(0, str(Path(__file__).parent))
import graficos  # noqa: E402

AQUI = Path(__file__).parent
SITE = AQUI / "_site"
BRT = timezone(timedelta(hours=-3))
OPS = graficos.OPS
COR = graficos.COR
TIPOS = ["Pré", "Controle", "Lite/Anual", "Flex", "Pós", "Família", "Fibra", "FWA (5G residencial)"]
e = html.escape


def ler(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def real(v):
    return "R$ " + ("%.2f" % v).replace(".", ",") if v is not None else "–"


def dia(s):
    return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")


def svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):].replace("<svg ", '<svg class="graf" ', 1)


def estilo(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    ax.tick_params(labelsize=9, colors="#555")
    ax.set_axisbelow(True)


def graf_escada(serie, tipo):
    campo = "mega" if tipo == "Fibra" else "gb"
    datas = sorted({r["data"] for r in serie})
    pri, ult = datas[0], datas[-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    tem = False
    for op in OPS:
        for dt, trac in ([(pri, True)] if pri != ult else []) + [(ult, False)]:
            pts = sorted((num(r[campo]), num(r["preco"])) for r in serie
                         if r["tipo"] == tipo and r["operadora"] == op and r["data"] == dt and num(r[campo]) and num(r["preco"]))
            if not pts:
                continue
            tem = True
            xs, ys = zip(*pts)
            ax.plot(xs, ys, marker="o", color=COR[op], linestyle="--" if trac else "-", alpha=0.45 if trac else 1,
                    markersize=3.5 if trac else 5, linewidth=1.2 if trac else 2, label=None if trac else op)
    if not tem:
        plt.close(fig)
        return ""
    estilo(ax)
    ax.set_xlabel("Mega" if campo == "mega" else "GB por mês", fontsize=9, color="#555")
    ax.set_ylabel("R$ por mês", fontsize=9, color="#555")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    return svg(fig)


def graf_tempo(por_dia, tipo, campo, rotulo):
    fig, ax = plt.subplots(figsize=(7.5, 2.8))
    tem = False
    for op in OPS:
        pts = sorted((datetime.strptime(d, "%Y-%m-%d"), v[campo]) for (d, o, t), v in por_dia.items()
                     if o == op and t == tipo and v[campo] is not None)
        if not pts:
            continue
        tem = True
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker="o", color=COR[op], linewidth=2, markersize=4, label=op)
    if not tem:
        plt.close(fig)
        return ""
    estilo(ax)
    ax.set_ylabel(rotulo, fontsize=9, color="#555")
    ax.set_ylim(bottom=0)
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    n = max(1, (max(xs) - min(xs)).days // 7 + 1) if tem else 1
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=n))
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    return svg(fig)


def tabela(cab, linhas, cls=""):
    h = ['<div class="tw"><table class="%s"><thead><tr>' % cls]
    h += ["<th>%s</th>" % e(c) for c in cab]
    h.append("</tr></thead><tbody>")
    for l in linhas:
        h.append("<tr>" + "".join("<td>%s</td>" % (c if isinstance(c, Markup) else e("" if c is None else str(c))) for c in l) + "</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


class Markup(str):
    pass


def gerar():
    hist = ler(AQUI / "dados" / "historico.csv")
    log = ler(AQUI / "dados" / "coletas.csv")
    serie = ler(AQUI / "painel" / "serie_sp.csv")
    mud = ler(AQUI / "painel" / "mudancas.csv")
    vig = [r for r in hist if not r["fim"]]
    ult_coleta = max(r["data"] for r in log)
    cob = defaultdict(lambda: [0, 0])
    for r in log:
        if r["data"] == ult_coleta:
            cob[r["operadora"]][1] += 1
            cob[r["operadora"]][0] += r["ok"] == "sim"

    por_dia = {}
    g = defaultdict(list)
    for r in serie:
        g[(r["data"], r["operadora"], r["tipo"])].append(r)
    for k, rows in g.items():
        un = [num(r["valor_unidade"]) for r in rows if num(r["valor_unidade"])]
        por_dia[k] = {"un": round(statistics.median(un), 2) if un else None, "entrada": min(num(r["preco"]) for r in rows)}

    # resumo do último dia com mudança
    dia_mud = max((r["data"] for r in mud), default=None)
    resumo = ""
    if dia_mud:
        n = {op: len({r["plano"] for r in mud if r["data"] == dia_mud and r["operadora"] == op}) for op in OPS if op in cob}
        resumo = "Último dia com mudança: <b>%s</b> — %s." % (
            dia(dia_mud), ", ".join("<b>%d</b> plano%s da %s" % (v, "" if v == 1 else "s", op) for op, v in n.items()))

    # mapa de preços (estilo "antes → agora")
    datas = sorted({r["data"] for r in serie})
    d1 = datas[-1]
    d0 = graficos.data_comparacao(datas, d1)
    # (título, tipos no gráfico, eixo x, corte x, corte y, tipos dos cartões de entrada, nome do cartão)
    grupos = [("Pré (recarga de 30 dias), híbridos (Lite, Fit, Flex) e Controle", ["Pré", "Lite/Anual", "Flex", "Controle"],
               "gb", None, 130, ["Controle"], "Controle de entrada"),
              ("Pós", ["Pós"], "gb", None, None, ["Pós"], "Pós de entrada"),
              ("Fibra (até 1 Giga)", ["Fibra"], "mega", 1000, None, ["Fibra"], "Fibra de entrada")]
    mapas = []
    for tit, tipos_g, campo, xmax, ymax, tipos_c, nome_c in grupos:
        fig, _ = graficos.mapa(serie, tipos_g, d0, d1, campo=campo, xmax=xmax, ymax=ymax)
        if not fig:
            continue
        ent0, ent1 = graficos.entrada(serie, tipos_c, d0, campo), graficos.entrada(serie, tipos_c, d1, campo)
        cards = []
        for op in OPS:
            if op not in ent1:
                continue
            a, b = ent0.get(op), ent1[op]
            dif = "" if not a or a["preco"] == b["preco"] else " <span class='var'>(%s)</span>" % (("+" if b["preco"] > a["preco"] else "–") + real(abs(b["preco"] - a["preco"]))[3:])
            xs = ("%g %s" % (b["x"], "Mega" if campo == "mega" else "GB")) if b["x"] else ""
            if b.get("livre") and b["x"] and b["livre"] != b["x"]:
                xs += " (%g livres)" % b["livre"]
            cards.append("<div class='card' style='border-top:4px solid %s'><div class='op'>%s · %s</div><div class='big'>%s%s</div>"
                         "<div class='nota'>%s · %s</div></div>" % (COR[op], op, nome_c, real(b["preco"]), dif, e(xs), e(b["plano"])))
        mapas.append("<h3>%s</h3><div class='cards'>%s</div>%s" % (e(tit), "".join(cards), graficos.svg(fig)))
    # R$/GB no tempo
    tempos = []
    for tit, tipos_t, campo in graficos.TEMPO:
        f = graficos.tempo(serie, tipos_t, campo, tamanho=(7.5, 3.0))
        if f:
            tempos.append("<div class='tempo'><h3>%s</h3>%s</div>" % (e(tit), graficos.svg(f)))

    # pré: R$/GB por dia
    pre = sorted([r for r in serie if r["data"] == d1 and r["tipo"] == "Pré" and r.get("rs_gb_dia")],
                 key=lambda r: (num(r["dias"]), OPS.index(r["operadora"]) if r["operadora"] in OPS else 9))
    tab_pre = tabela(["Validade", "Operadora", "Recarga", "GB", "R$/GB por dia"],
                     [["%s dias" % r["dias"], r["operadora"], real(num(r["preco"])), "%g" % num(r["gb"]),
                       ("R$ %.3f" % num(r["rs_gb_dia"])).replace(".", ",")] for r in pre])

    # abas por tipo
    tipos = [t for t in TIPOS if any(r["tipo"] == t for r in vig)]
    abas, paineis = [], []
    for i, tipo in enumerate(tipos):
        tid = "t%d" % i
        abas.append('<button class="aba%s" data-alvo="%s">%s</button>' % (" on" if tipo == "Pós" else "", tid, e(tipo)))
        sp = sorted([r for r in vig if r["tipo"] == tipo and r["uf"] == "SP"],
                    key=lambda r: (OPS.index(r["operadora"]) if r["operadora"] in OPS else 9, num(r["preco"]) or 0))
        # quantas capitais têm cada plano e se o preço varia
        pr = defaultdict(set)
        nuf = defaultdict(set)
        for r in vig:
            if r["tipo"] == tipo:
                pr[(r["operadora"], r["chave"])].add(r["preco"])
                nuf[(r["operadora"], r["chave"])].add(r["uf"])
        linhas = []
        for r in sp:
            k = (r["operadora"], r["chave"])
            ps = sorted(num(p) for p in pr[k] if num(p))
            varia = "igual" if len(ps) <= 1 else "%s a %s" % (real(ps[0]), real(ps[-1]))
            gbv = r["gb_total"] or (r["velocidade_mega"] + " Mega" if r["velocidade_mega"] else "")
            linhas.append([r["operadora"], r["linha"], r["plano"], real(num(r["preco"])),
                           real(num(r["preco_de"])) if r["preco_de"] else "", gbv, real(num(r["rs_por_gb"])) if r["rs_por_gb"] else "",
                           r["condicao"], r["selo"], "%d" % len(nuf[k]), varia])
        so_fora = sorted({(r["operadora"], r["plano"]) for r in vig if r["tipo"] == tipo} - {(r["operadora"], r["plano"]) for r in sp})
        blocos = ['<section class="painel%s" id="%s">' % ("" if tipo == "Pós" else " oculto", tid)]
        esc = graf_escada(serie, tipo)
        if esc:
            blocos.append("<h3>Escada de preços em SP (preço × %s)</h3><p class='nota'>Linha cheia = última coleta; tracejada = primeira coleta. "
                          "Se a linha anda para a direita, a operadora deu mais %s pelo mesmo preço.</p>%s"
                          % ("velocidade" if tipo == "Fibra" else "franquia", "velocidade" if tipo == "Fibra" else "GB", esc))
        un = graf_tempo(por_dia, tipo, "un", "R$ por 100 Mega" if tipo == "Fibra" else "R$ por GB (mediana)")
        if un:
            blocos.append("<h3>%s ao longo do tempo (SP)</h3>%s" % ("R$ por 100 Mega" if tipo == "Fibra" else "R$ por GB, mediana dos planos", un))
        en = graf_tempo(por_dia, tipo, "entrada", "R$ por mês")
        if en:
            blocos.append("<h3>Preço de entrada (plano mais barato) ao longo do tempo (SP)</h3>%s" % en)
        blocos.append("<h3>Planos hoje em SP</h3>")
        blocos.append(tabela(["Operadora", "Linha", "Plano", "Preço", "De", "GB / Mega", "R$/GB", "Condição", "Selo", "Nº capitais", "Preço nas capitais"], linhas))
        if so_fora:
            blocos.append("<p class='nota'>Fora de SP também aparecem: %s.</p>" % e("; ".join("%s %s" % x for x in so_fora[:15])))
        blocos.append("</section>")
        paineis.append("".join(blocos))

    # mudanças (últimos 45 dias)
    corte = (datetime.strptime(ult_coleta, "%Y-%m-%d") - timedelta(days=45)).strftime("%Y-%m-%d")
    lm = [[dia(r["data"]), r["operadora"], r["tipo"], r["plano"], r["campo"] if r["mudanca"] == "Mudou" else r["mudanca"],
           r["antes"], r["depois"], "todas (27)" if r["pracas"] == "todas" else r["pracas"]] for r in mud if r["data"] >= corte]

    relatorios = sorted((AQUI / "relatorios").glob("relatorio_planos_*.pdf"), reverse=True)
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    pagina = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Monitor de planos – móvel e fibra</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;color:#1f1f1f;background:#fafafa}}
main{{max-width:1100px;margin:0 auto;padding:20px}}
h1{{font-size:26px;font-weight:600;margin:0 0 6px}} h2{{font-size:19px;margin:28px 0 8px}} h3{{font-size:15px;margin:22px 0 6px}}
.lead{{font-size:16px;margin:4px 0}} .nota{{color:#666;font-size:13px;margin:4px 0}}
.abas{{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}} .aba{{border:1px solid #ccc;background:#fff;border-radius:16px;padding:6px 14px;cursor:pointer;font-size:14px}}
.aba.on{{background:#1f1f1f;color:#fff;border-color:#1f1f1f}} .oculto{{display:none}}
.graf{{width:100%;height:auto;max-width:820px;background:#fff;border:1px solid #eee;border-radius:8px}}
.tw{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #eee;vertical-align:top;white-space:nowrap}} th{{background:#f2f2f2;position:sticky;top:0}}
td:nth-child(n+8){{white-space:normal;min-width:120px}}
.tempos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:8px}}
.cards{{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}} .card{{background:#fff;border:1px solid #eee;border-radius:8px;padding:8px 12px;min-width:150px}}
.card .op{{font-size:12px;color:#666}} .card .big{{font-size:20px;font-weight:600}} .var{{font-size:13px;color:#b45309}}
.dl a{{display:inline-block;margin:4px 10px 4px 0;padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;color:#1f1f1f;text-decoration:none;font-size:14px}}
input.busca{{padding:6px 10px;border:1px solid #ccc;border-radius:6px;width:260px;max-width:100%;margin:6px 0}}
footer{{color:#888;font-size:12px;margin:30px 0 10px}}
</style></head><body><main>
<h1>Monitor de planos – móvel e fibra</h1>
<p class="lead">Última coleta: <b>{dia(ult_coleta)}</b> ({"; ".join("%s %d/%d páginas" % (op, cob[op][0], cob[op][1]) for op in OPS if op in cob)}).</p>
<p class="lead">{resumo}</p>
<p class="nota">Preço de vitrine dos sites de Vivo, Claro e TIM (o que se vende hoje a cliente novo), coletado uma vez por dia nas 27 capitais. Não inclui reajuste da base de clientes. Gráficos em São Paulo (no celular o preço é o mesmo em quase todas as capitais).</p>

<h2>Mapa de preços em SP: hoje × {dia(d0)}</h2>
<p class="nota">Cada ponto é um plano. Ponto vazado = posição em {dia(d0)}; a seta mostra para onde o plano foi (direita = mais GB, cima = mais caro). Anel = plano novo. Nos cartões, o plano mais barato de cada operadora no grupo (no pré, recarga de 30 dias).</p>
{"".join(mapas)}
<h2>R$ por GB ao longo do tempo (SP)</h2>
<p class="nota">{e(graficos.NOTA_TEMPO)}</p>
<div class="tempos">{"".join(tempos)}</div>

<h3>Pré: custo por GB por dia de validade (recargas de prazos diferentes)</h3>
{tab_pre}

<h2>Baixar os dados</h2>
<div class="dl"><a href="planos_operadoras.xlsx" download>Planilha completa (.xlsx)</a><a href="historico.csv" download>Histórico (.csv)</a><a href="serie_sp.csv" download>Série diária SP (.csv)</a><a href="mudancas.csv" download>Mudanças (.csv)</a></div>
<div class="dl">{"".join('<a href="%s" download>Relatório mensal %s (PDF)</a>' % (r.name, r.stem[-7:]) for r in relatorios)}</div>

<h2>Por tipo de plano</h2>
<div class="abas">{"".join(abas)}</div>
{"".join(paineis)}

<h2>Mudanças (últimos 45 dias, todas as capitais)</h2>
<input class="busca" id="busca" placeholder="Filtrar (ex.: Claro, Pós, preço)">
{tabela(["Data", "Operadora", "Tipo", "Plano", "Campo", "Antes", "Depois", "Capitais"], lm, "mud")}

<footer>Atualizado em {agora}. Fonte: sites das operadoras. "Plano/GB (preço igual)" = a operadora trocou o nome do plano junto com os GB, mantendo o preço. R$/GB = preço ÷ franquia total com bônus; fibra em R$ por 100 Mega.</footer>
</main>
<script>
document.querySelectorAll('.aba').forEach(b=>b.addEventListener('click',()=>{{
 document.querySelectorAll('.aba').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 document.querySelectorAll('.painel').forEach(p=>p.classList.toggle('oculto',p.id!==b.dataset.alvo));}}));
const bu=document.getElementById('busca');bu.addEventListener('input',()=>{{const q=bu.value.toLowerCase();
 document.querySelectorAll('table.mud tbody tr').forEach(tr=>tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none');}});
</script></body></html>"""
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    (SITE / "index.html").write_text(pagina, encoding="utf-8")
    (SITE / ".nojekyll").write_text("")
    shutil.copy(AQUI / "planos_operadoras.xlsx", SITE)
    shutil.copy(AQUI / "dados" / "historico.csv", SITE)
    shutil.copy(AQUI / "painel" / "serie_sp.csv", SITE)
    shutil.copy(AQUI / "painel" / "mudancas.csv", SITE)
    for r in relatorios:
        shutil.copy(r, SITE)
    return SITE / "index.html"


if __name__ == "__main__":
    print(gerar())
