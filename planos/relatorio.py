#!/usr/bin/env python3
"""Relatório mensal de preços (PDF), no formato dos trackers de mercado, gerado do histórico do monitor.

Páginas: resumo do mês; um mapa "início × fim do mês" por grupo (Pré/híbridos/Controle, Pós, Fibra) com cartões
do plano de entrada e o que mudou por operadora; pré em R$/GB por dia; diferenças entre capitais; comunicados
de reajuste da base (Vivo); lista de todas as mudanças do mês.
Títulos e bullets são montados a partir das mudanças detectadas (sem texto fixo que possa ficar errado).

Uso: python planos/relatorio.py [AAAA-MM]   (sem argumento: mês anterior ao de hoje; com "atual": mês corrente até hoje)
Saída: planos/relatorios/relatorio_planos_AAAA-MM.pdf (e .html ao lado)
"""
import csv
import html
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
import graficos  # noqa: E402
from graficos import COR, OPS, num  # noqa: E402

RAIZ = AQUI.parent
SAIDA = AQUI / "relatorios"
BRT = timezone(timedelta(hours=-3))
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
e = html.escape
GRUPOS = [  # título, tipos no mapa, eixo, corte x, corte y, tipos do cartão de entrada, nome do cartão
    ("Pré, híbridos e Controle", ["Pré", "Lite/Anual", "Flex", "Controle"], "gb", None, 130, ["Controle"], "Controle de entrada"),
    ("Pós", ["Pós"], "gb", None, None, ["Pós"], "Pós de entrada"),
    ("Fibra (até 1 Giga)", ["Fibra"], "mega", 1000, None, ["Fibra"], "Fibra de entrada"),
]


def ler(p, sep=","):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=sep))


def real(v, casas=2):
    return ("R$ %." + str(casas) + "f") % v if v is not None else "–"


def br(s):
    return s.replace(".", "#").replace(",", ".").replace("#", ",")


def rs(v):
    return br(real(v))


def dia(s):
    return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m")


def unid(campo):
    return "Mega" if campo == "mega" else "GB"


def descrever(p, campo):
    """Uma mudança do mapa em texto curto."""
    a, b = p["antigo"], p["atual"]
    u = unid(campo)
    if p["estado"] == "novo":
        return "novo: %s (%g %s por %s)" % (b["plano"], b["x"], u, rs(b["y"]))
    if p["estado"] == "saiu":
        return "saiu: %s (%g %s por %s)" % (a["plano"], a["x"], u, rs(a["y"]))
    partes = []
    if b["x"] != a["x"]:
        partes.append("%g→%g %s" % (a["x"], b["x"], u))
    if b["y"] != a["y"]:
        partes.append("%s→%s" % (rs(a["y"]), rs(b["y"])))
    elif b["x"] != a["x"]:
        partes.append("a %s" % rs(b["y"]))
    nome = b["plano"] if b["plano"] == a["plano"] else "%s (antes %s)" % (b["plano"], a["plano"])
    return "%s: %s" % (nome, ", ".join(partes))


def classe(p):
    if p["estado"] in ("novo", "saiu"):
        return p["estado"]
    a, b = p["antigo"], p["atual"]
    if b["y"] > a["y"]:
        return "preço maior"
    if b["y"] < a["y"]:
        return "preço menor"
    return "mais franquia, mesmo preço" if b["x"] > a["x"] else "menos franquia, mesmo preço"


def titulo_grupo(pts, ops_ativas):
    """Frase-título montada das mudanças: quem mexeu e como; quem ficou parado."""
    por = defaultdict(lambda: defaultdict(int))
    for p in pts:
        if p["estado"] != "igual":
            por[(p["atual"] or p["antigo"])["op"]][classe(p)] += 1
    if not por:
        return "Nenhuma operadora mudou planos no mês"
    frases = []
    for op in OPS:
        if op in por:
            c = sorted(por[op].items(), key=lambda x: -x[1])
            frases.append("%s: %s" % (op, ", ".join(rotulo(k, n) for k, n in c)))
    ops_grupo = {(p["atual"] or p["antigo"])["op"] for p in pts}
    paradas = [o for o in ops_ativas if o not in por and o in ops_grupo]
    return "; ".join(frases) + (" — %s sem mudança" % juntar(paradas) if paradas else "")


def juntar(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " e " + xs[-1]


def rotulo(k, n):
    um = {"novo": "plano novo", "saiu": "plano retirado", "preço maior": "preço maior", "preço menor": "preço menor",
          "mais franquia, mesmo preço": "com mais franquia pelo mesmo preço",
          "menos franquia, mesmo preço": "com menos franquia pelo mesmo preço"}[k]
    if n == 1:
        return "1 " + um
    return "%d %s" % (n, {"plano novo": "planos novos", "plano retirado": "planos retirados", "preço maior": "com preço maior",
                         "preço menor": "com preço menor"}.get(um, um))


def periodo(arg, datas):
    hoje = datetime.now(BRT)
    if arg == "atual":
        ano, mes = hoje.year, hoje.month
    elif arg:
        ano, mes = map(int, arg.split("-"))
    else:
        pri = hoje.replace(day=1) - timedelta(days=1)
        ano, mes = pri.year, pri.month
    ini = "%04d-%02d-01" % (ano, mes)
    fim = "%04d-%02d-31" % (ano, mes)
    no_mes = [d for d in datas if ini <= d <= fim]
    if not no_mes:
        raise SystemExit("sem coletas em %04d-%02d" % (ano, mes))
    antes = [d for d in datas if d < ini]
    d0 = antes[-1] if antes else no_mes[0]  # última coleta do mês anterior (ou a primeira do mês)
    return ano, mes, d0, no_mes[-1], no_mes


def gerar(arg=None):
    serie = ler(AQUI / "painel" / "serie_sp.csv")
    hist = ler(AQUI / "dados" / "historico.csv")
    log = ler(AQUI / "dados" / "coletas.csv")
    mud = ler(AQUI / "painel" / "mudancas.csv")
    datas = sorted({r["data"] for r in serie})
    ano, mes, d0, d1, no_mes = periodo(arg, datas)
    nome_mes = "%s de %d" % (MESES[mes - 1], ano)
    parcial = d1 < (datetime(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)).strftime("%Y-%m-%d")
    ops_ativas = [o for o in OPS if any(r["operadora"] == o and r["data"] == d1 for r in serie)]
    n_dias = len({r["data"] for r in log if r["data"] in no_mes})

    paginas, resumo = [], []
    for tit, tipos, campo, xmax, ymax, tipos_c, nome_c in GRUPOS:
        fig, pts = graficos.mapa(serie, tipos, d0, d1, campo=campo, xmax=xmax, ymax=ymax, tamanho=(8.2, 4.6))
        if not fig:
            continue
        frase = titulo_grupo(pts, ops_ativas)
        resumo.append((tit, frase))
        e0, e1 = graficos.entrada(serie, tipos_c, d0, campo), graficos.entrada(serie, tipos_c, d1, campo)
        cards = []
        for op in OPS:
            if op not in e1:
                continue
            a, b = e0.get(op), e1[op]
            var = "" if not a or a["preco"] == b["preco"] else "<span class='var'>%s%s</span>" % (
                "+" if b["preco"] > a["preco"] else "–", rs(abs(b["preco"] - a["preco"]))[3:])
            gbv = ""
            if a and a["x"] and b["x"] and a["x"] != b["x"]:
                gbv = " (antes %g)" % a["x"]
            un = "%s/%s" % (rs(b["unid"]), "GB" if campo == "gb" else "100 Mega") if b["unid"] else ""
            cards.append("<div class='card' style='border-top:4px solid %s'><div class='op'>%s</div><div class='big'>%s %s</div>"
                         "<div class='sm'>%g %s%s · %s</div><div class='sm'>%s</div></div>"
                         % (COR[op], op, rs(b["preco"]), var, b["x"] or 0, unid(campo), gbv, un, e(b["plano"])))
        mud_op = defaultdict(list)
        for p in pts:
            if p["estado"] != "igual":
                mud_op[(p["atual"] or p["antigo"])["op"]].append(descrever(p, campo))
        lista = "".join("<li><b style='color:%s'>%s</b>: %s</li>" % (COR[o], o, e("; ".join(mud_op[o])))
                        for o in OPS if o in mud_op) or "<li>Sem mudanças no mês.</li>"
        paginas.append("""<section class="pg"><div class="topo"><span>{t}</span><span>{m}</span></div>
<h2>{frase}</h2>
<div class="cards"><div class="rot">{nc} (SP)</div>{cards}</div>
{svg}
<p class="nota">Ponto vazado = {d0}; cheio = {d1}; seta = para onde o plano foi; anel = plano novo. Pré só com recarga de ~30 dias.</p>
<h3>O que mudou</h3><ul>{lista}</ul></section>""".format(
            t=e(tit), m=e(nome_mes), frase=e(frase), nc=e(nome_c), cards="".join(cards), svg=graficos.svg(fig),
            d0=dia(d0), d1=dia(d1), lista=lista))

    # pré por dia
    pre = sorted([r for r in serie if r["data"] == d1 and r["tipo"] == "Pré" and r.get("rs_gb_dia")],
                 key=lambda r: (num(r["dias"]), num(r["rs_gb_dia"])))
    mais_barato = {}
    for r in pre:
        k = num(r["dias"])
        if k not in mais_barato or num(r["rs_gb_dia"]) < num(mais_barato[k]["rs_gb_dia"]):
            mais_barato[k] = r
    trinta = mais_barato.get(30.0)
    frase_pre = ("No pré de 30 dias, o menor custo por GB é da %s (%s com %g GB)" % (
        trinta["operadora"], rs(num(trinta["preco"])), num(trinta["gb"]))) if trinta else "Pré por validade"
    linhas_pre = "".join("<tr><td>%s dias</td><td style='color:%s'><b>%s</b></td><td>%s</td><td>%g GB</td><td>%s</td></tr>" % (
        r["dias"], COR.get(r["operadora"], "#333"), r["operadora"], rs(num(r["preco"])), num(r["gb"]),
        br("R$ %.3f" % num(r["rs_gb_dia"])) + (" ◀" if mais_barato.get(num(r["dias"])) is r else "")) for r in pre)
    paginas.append("""<section class="pg"><div class="topo"><span>Pré-pago</span><span>{m}</span></div>
<h2>{f}</h2><p class="nota">Recargas com validades diferentes, comparadas em R$ por GB por dia de validade (◀ = mais barato no prazo). SP, {d1}.</p>
<table><tr><th>Validade</th><th>Operadora</th><th>Recarga</th><th>Franquia</th><th>R$/GB por dia</th></tr>{l}</table></section>""".format(
        m=e(nome_mes), f=e(frase_pre), d1=dia(d1), l=linhas_pre))

    # diferenças entre capitais (vigentes hoje)
    vig = [r for r in hist if not r["fim"]]
    g = defaultdict(lambda: defaultdict(set))
    nome = {}
    for r in vig:
        if r["tipo"] in ("Família",):
            continue
        k = (r["operadora"], r["tipo"], r["linha"], r["chave"])
        g[k][(num(r["preco"]), num(r["gb_total"]) or num(r["velocidade_mega"]))].add(r["uf"])
        nome[k] = r["plano"]
    reg = []
    for k, combos in g.items():
        if len(combos) > 1:
            ordem = sorted(combos.items(), key=lambda x: -len(x[1]))
            txt = " | ".join("%s%s em %s" % (rs(p), " (%g %s)" % (x, "Mega" if k[1] == "Fibra" else "GB") if x else "",
                                                 "demais capitais" if i == 0 and len(u) > 13 else ",".join(sorted(u)))
                               for i, ((p, x), u) in enumerate(ordem))
            reg.append((k[0], k[1], nome[k], txt))
    reg.sort(key=lambda x: (OPS.index(x[0]) if x[0] in OPS else 9, x[1], x[2]))
    linhas_reg = "".join("<tr><td style='color:%s'><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        COR.get(o, "#333"), o, e(t), e(n), e(x)) for o, t, n, x in reg[:28])
    frase_reg = ("%d planos com preço ou franquia diferente entre capitais" % len(reg)) if reg else "Mesmo preço e franquia em todas as capitais"
    paginas.append("""<section class="pg"><div class="topo"><span>Diferenças regionais</span><span>{m}</span></div>
<h2>{f}</h2><p class="nota">Planos vigentes em {d1} nas 27 capitais, onde a mesma oferta aparece com preço ou franquia diferente (Família fora). {extra}</p>
<table class="peq"><tr><th>Operadora</th><th>Tipo</th><th>Plano</th><th>Preço/franquia por capital</th></tr>{l}</table></section>""".format(
        m=e(nome_mes), f=e(frase_reg), d1=dia(d1), l=linhas_reg or "<tr><td colspan=4>Nenhuma.</td></tr>",
        extra="Mostrando 28 de %d; lista completa na planilha." % len(reg) if len(reg) > 28 else ""))

    # comunicados de reajuste (base de clientes)
    com_p = RAIZ / "comunicados" / "comunicados_vivo.csv"
    coms = []
    if com_p.exists():
        for r in ler(com_p, ";"):
            pub = r["publicado"]
            iso = "%s-%s-%s" % (pub[6:], pub[3:5], pub[:2]) if pub else ""
            if iso[:7] == "%04d-%02d" % (ano, mes):
                coms.append(r)
    linhas_com = "".join("<tr><td>%s</td><td>%s%s</td></tr>" % (
        e(r["publicado"]), e(r["titulo"]), " <b>(preço/oferta)</b>" if r["relevante_preco"] else "") for r in coms)
    paginas.append("""<section class="pg"><div class="topo"><span>Base de clientes (back book)</span><span>{m}</span></div>
<h2>{f}</h2><p class="nota">Comunicados públicos da Vivo publicados no mês (reajuste de quem já é cliente não aparece na vitrine). Claro e TIM ainda não monitorados.</p>
<table><tr><th>Publicado</th><th>Comunicado</th></tr>{l}</table></section>""".format(
        m=e(nome_mes), f=e("%d comunicado%s da Vivo no mês" % (len(coms), "" if len(coms) == 1 else "s")),
        l=linhas_com or "<tr><td colspan=2>Nenhum comunicado publicado no mês.</td></tr>"))

    # mudanças do mês (todas as capitais)
    mm = [r for r in mud if r["data"] in no_mes]
    linhas_mm = "".join("<tr><td>%s</td><td style='color:%s'><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s → %s</td><td>%s</td></tr>" % (
        dia(r["data"]), COR.get(r["operadora"], "#333"), r["operadora"], e(r["tipo"]), e(r["plano"]),
        e(r["campo"] if r["mudanca"] == "Mudou" else r["mudanca"]), e(r["antes"][:40]), e(r["depois"][:40]),
        "todas" if r["pracas"] == "todas" else "%s (%s)" % (r["n_pracas"], e(r["pracas"][:40])))
        for r in sorted(mm, key=lambda r: (r["data"], r["operadora"])))
    paginas.append("""<section class="pg"><div class="topo"><span>Todas as mudanças</span><span>{m}</span></div>
<h2>{n} mudanças registradas no mês, nas 27 capitais</h2>
<table class="peq"><tr><th>Data</th><th>Operadora</th><th>Tipo</th><th>Plano</th><th>Campo</th><th>Antes → depois</th><th>Capitais</th></tr>{l}</table></section>""".format(
        m=e(nome_mes), n=len(mm), l=linhas_mm or "<tr><td colspan=7>Nenhuma.</td></tr>"))

    capa = """<section class="pg capa"><div class="topo"><span>Monitor de planos · móvel e fibra</span><span>{m}</span></div>
<h1>Preços de celular e fibra — {m}{p}</h1>
<p class="nota">Coleta diária nos sites de {ops}, nas 27 capitais ({nd} dias de coleta no mês). Comparação: {d0} → {d1}. Gráficos e planos de entrada em São Paulo.</p>
<h3>Resumo por segmento</h3><ul class="res">{res}</ul>
<h3>Metodologia</h3><ul class="sm">
<li>Preço de vitrine (cliente novo) lido nos sites oficiais; franquia = GB totais anunciados, incluindo bônus.</li>
<li>Pré: recargas comparadas por R$/GB por dia de validade; no mapa, só a recarga de ~30 dias.</li>
<li>Híbridos: Vivo Lite, TIM Controle Fit, Claro Flex (pagamento no cartão, sem fatura). Controle de entrada = Controle tradicional mais barato.</li>
<li>Mudança de nome com mudança de GB pelo mesmo preço é tratada como o mesmo plano.</li></ul>
</section>""".format(m=e(nome_mes), p=" (parcial até %s)" % dia(d1) if parcial else "", ops=", ".join(ops_ativas), nd=n_dias,
                     d0=dia(d0), d1=dia(d1),
                     res="".join("<li><b>%s</b> — %s</li>" % (e(t), e(f)) for t, f in resumo))

    pagina = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Preços de celular e fibra — {m}</title><style>
@page {{size: A4 landscape; margin: 12mm}}
body{{font-family:Helvetica,Arial,sans-serif;color:#1f1f1f;margin:0;font-size:12px}}
.pg{{page-break-after:always;padding:2px 4px}} .pg:last-child{{page-break-after:auto}}
.topo{{display:flex;justify-content:space-between;color:#777;font-size:11px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-bottom:8px}}
h1{{font-size:24px;margin:30px 0 8px}} h2{{font-size:17px;font-weight:600;margin:4px 0 8px}} h3{{font-size:13px;margin:10px 0 4px}}
.nota,.sm{{color:#666;font-size:10.5px}} ul{{margin:4px 0 4px 18px;padding:0}} li{{margin:2px 0}} .res li{{font-size:13px;margin:6px 0}}
.cards{{display:flex;gap:8px;align-items:stretch;margin:4px 0}} .rot{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:10px;color:#777}}
.card{{border:1px solid #eee;border-radius:6px;padding:4px 10px;min-width:150px}} .card .op{{font-size:10px;color:#666}}
.card .big{{font-size:17px;font-weight:600}} .var{{font-size:11px;color:#b45309;margin-left:4px}}
.graf{{width:62%;height:auto;float:left;margin-right:12px}} h3+ul{{font-size:11px}}
table{{border-collapse:collapse;width:100%;font-size:11px}} th,td{{border-bottom:1px solid #eee;padding:3px 6px;text-align:left;vertical-align:top}}
th{{background:#f3f3f3}} table.peq{{font-size:9.5px}}
.capa h3{{margin-top:18px}}
</style></head><body>{c}{p}</body></html>""".format(m=e(nome_mes), c=capa, p="".join(paginas))
    SAIDA.mkdir(exist_ok=True)
    base = SAIDA / ("relatorio_planos_%04d-%02d" % (ano, mes))
    base.with_suffix(".html").write_text(pagina, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page()
        pg.goto(base.with_suffix(".html").resolve().as_uri())
        pg.pdf(path=str(base.with_suffix(".pdf")), format="A4", landscape=True, print_background=True,
               margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
        nav.close()
    print(base.with_suffix(".pdf"))
    return base.with_suffix(".pdf"), resumo, nome_mes, parcial


if __name__ == "__main__":
    gerar(sys.argv[1] if len(sys.argv) > 1 else None)
