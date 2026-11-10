#!/usr/bin/env python3
"""Baixa e lê os formulários CVM 44 das empresas acompanhadas e gera cvm44/negociacoes_cvm44.xlsx.

Uso:
  python cvm44/planilha.py processar DOCS.json   → baixa/lê os docs listados (JSON do checar.py) que ainda
                                                  não têm leitura em cvm44/dados/, depois regenera o Excel
  python cvm44/planilha.py gerar                 → só regenera o Excel a partir de cvm44/dados/
  python cvm44/planilha.py resumo PROTOCOLO      → frase curta com o que o formulário mostra (para o push)

Pastas: cvm44/pdf/ (PDFs originais, nome TICKER_AAAA-MM_tipo_vN.pdf) e cvm44/dados/ (leitura em JSON por protocolo).
"""
import glob, json, os, re, sys, urllib.request
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(AQUI, "pdf"); DADOS_DIR = os.path.join(AQUI, "dados")
XLSX = os.path.join(AQUI, "negociacoes_cvm44.xlsx")
sys.path.insert(0, AQUI)
from ler_pdf import ler  # noqa: E402


def nome_pdf(d):
    m, a = d["ref"].split("/")
    tipo = "consolidado" if "Consolidada" in d["tipo"] else "individual"
    return "%s_%s-%s_%s_v%s.pdf" % (d["ticker"], a, m, tipo, d["versao"])


def baixar(d):
    os.makedirs(PDF_DIR, exist_ok=True)
    import time
    alvo = os.path.join(PDF_DIR, nome_pdf(d))
    for tentativa in range(3):
        if not os.path.exists(alvo):
            req = urllib.request.Request(d["download"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                conteudo = r.read()
            if conteudo[:4] != b"%PDF":
                time.sleep(20); continue          # recém-protocolado: a CVM às vezes devolve HTML por alguns minutos
            with open(alvo, "wb") as f:
                f.write(conteudo)
        with open(alvo, "rb") as f:
            if f.read(4) == b"%PDF": return alvo
        os.remove(alvo)
    raise RuntimeError("download não é PDF (CVM ainda processando?)")


def processar(docs):
    """Baixa e lê os docs sem leitura. Devolve lista de protocolos lidos agora e de falhas."""
    os.makedirs(DADOS_DIR, exist_ok=True)
    lidos, falhas = [], []
    for d in docs:
        if not d.get("protocolo") or not d.get("download"):
            continue
        destino = os.path.join(DADOS_DIR, d["protocolo"] + ".json")
        if os.path.exists(destino):
            continue
        try:
            leitura = ler(baixar(d))
            leitura.update({"ticker": d["ticker"], "nome": d["nome"], "tipo": d["tipo"], "ref": d["ref"],
                            "entrega": d["entrega"], "versao": d["versao"], "protocolo": d["protocolo"],
                            "link": d["link"], "pdf": nome_pdf(d)})
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(leitura, f, ensure_ascii=False, indent=1)
            lidos.append(d["protocolo"])
        except Exception as e:
            falhas.append("%s %s %s: %s" % (d["ticker"], d["ref"], d["tipo"][:12], str(e)[:80]))
    return lidos, falhas


def carregar_tudo():
    docs = []
    for p in glob.glob(os.path.join(DADOS_DIR, "*.json")):
        with open(p, encoding="utf-8") as f:
            docs.append(json.load(f))
    # Só a versão mais recente de cada (ticker, ref, tipo)
    ult = {}
    for d in docs:
        k = (d["ticker"], d["ref"], d["tipo"])
        if k not in ult or int(d["versao"]) > int(ult[k]["versao"]):
            ult[k] = d
    return sorted(ult.values(), key=lambda d: (d["ticker"], d["ref"][3:], d["ref"][:2], d["tipo"]))


def chave_ordem(ref):
    return ref[3:] + ref[:2]


def gerar():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    docs = carregar_tudo()
    wb = Workbook()

    def aba(nome, cab, linhas, larguras=None):
        ws = wb.create_sheet(nome)
        ws.append(cab)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3864")
            c.alignment = Alignment(horizontal="center")
        for l in linhas:
            ws.append(l)
        ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
        for i, w in enumerate(larguras or [14] * len(cab), 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    # Movimentações
    mov = []
    for d in docs:
        for p in d["paginas"]:
            for m in p["movimentacoes"]:
                mov.append([d["ticker"], d["nome"], d["ref"], d["tipo"].split(" - ")[0], p["orgao"],
                            m["ativo"], m["caracteristica"], m["operacao"], m["dia"], m["quantidade"], m["preco"], m["volume"],
                            m["intermediario"], d["entrega"], d["versao"], d["link"]])
    mov.sort(key=lambda r: (chave_ordem(r[2]), r[0], r[4], int(r[8] or 0)))
    ws = aba("Movimentações", ["Ticker", "Empresa", "Mês ref", "Formulário", "Órgão", "Ativo", "Classe", "Operação", "Dia",
                               "Quantidade", "Preço (R$)", "Volume (R$)", "Intermediário", "Entregue em", "Versão", "Link"],
             mov, [8, 16, 9, 12, 24, 10, 8, 18, 5, 13, 11, 15, 22, 16, 7, 60])
    for r in ws.iter_rows(min_row=2):
        r[9].number_format = "#,##0"; r[10].number_format = "#,##0.00000"; r[11].number_format = "#,##0.00"

    # Resumo por empresa / mês / órgão (só Consolidado)
    res = defaultdict(lambda: {"compra_q": 0, "venda_q": 0, "compra_v": 0.0, "venda_v": 0.0, "outros": 0})
    for d in docs:
        if "Consolidada" not in d["tipo"]: continue
        for p in d["paginas"]:
            k = (d["ticker"], d["ref"], p["orgao"])
            res[k]  # garante linha mesmo sem movimentação
            for m in p["movimentacoes"]:
                op = m["operacao"].lower()
                if _classe(op) == "compra":
                    res[k]["compra_q"] += m["quantidade"] or 0; res[k]["compra_v"] += m["volume"] or 0
                elif _classe(op) == "venda":
                    res[k]["venda_q"] += m["quantidade"] or 0; res[k]["venda_v"] += m["volume"] or 0
                else:
                    res[k]["outros"] += 1
    linhas = [[t, ref, o, v["compra_q"], v["compra_v"], v["venda_q"], v["venda_v"], v["compra_q"] - v["venda_q"],
               v["compra_v"] - v["venda_v"], v["outros"]] for (t, ref, o), v in res.items()]
    linhas.sort(key=lambda r: (chave_ordem(r[1]), r[0], r[2]))
    ws = aba("Resumo", ["Ticker", "Mês ref", "Órgão", "Comprado (qtd)", "Comprado (R$)", "Vendido (qtd)", "Vendido (R$)",
                        "Líquido (qtd)", "Líquido (R$)", "Outras operações"], linhas, [8, 9, 26, 14, 15, 14, 15, 14, 15, 10])
    for r in ws.iter_rows(min_row=2):
        for i in (3, 5, 7): r[i].number_format = "#,##0"
        for i in (4, 6, 8): r[i].number_format = "#,##0.00"

    # Posições (saldo final por órgão/ativo, Consolidado)
    pos = []
    for d in docs:
        if "Consolidada" not in d["tipo"]: continue
        for p in d["paginas"]:
            si = {(s["ativo"], s["caracteristica"]): s["quantidade"] for s in p["saldo_inicial"]}
            for s in p["saldo_final"]:
                pos.append([d["ticker"], d["ref"], p["orgao"], s["ativo"], s["caracteristica"],
                            si.get((s["ativo"], s["caracteristica"])), s["quantidade"]])
    pos.sort(key=lambda r: (chave_ordem(r[1]), r[0], r[2], r[3], r[4]))
    ws = aba("Posições", ["Ticker", "Mês ref", "Órgão", "Ativo", "Classe", "Saldo inicial", "Saldo final"], pos,
             [8, 9, 26, 12, 8, 16, 16])
    for r in ws.iter_rows(min_row=2):
        r[5].number_format = "#,##0"; r[6].number_format = "#,##0"

    # Fontes
    fontes = [[d["ticker"], d["ref"], d["tipo"].split(" - ")[0], d["versao"], d["entrega"], d["protocolo"], d["link"], d["pdf"]] for d in docs]
    fontes.sort(key=lambda r: (chave_ordem(r[1]), r[0], r[2]))
    aba("Fontes", ["Ticker", "Mês ref", "Formulário", "Versão", "Entregue em", "Protocolo CVM", "Link", "PDF no repositório"],
        fontes, [8, 9, 12, 7, 16, 13, 60, 36])

    abas_monitor(wb, docs, aba)
    aba_entregas(wb, docs, aba)
    del wb["Sheet"]
    wb.save(XLSX)
    return len(mov), len(docs)


def resumo(protocolo):
    """Frase curta para o push: o que o formulário consolidado mostra."""
    p = os.path.join(DADOS_DIR, protocolo + ".json")
    if not os.path.exists(p): return ""
    d = json.load(open(p, encoding="utf-8"))
    partes = []
    for pg in d["paginas"]:
        c = sum(m["quantidade"] or 0 for m in pg["movimentacoes"] if _classe(m["operacao"]) == "compra")
        v = sum(m["quantidade"] or 0 for m in pg["movimentacoes"] if _classe(m["operacao"]) == "venda")
        cv = sum(m["volume"] or 0 for m in pg["movimentacoes"] if _classe(m["operacao"]) == "compra")
        vv = sum(m["volume"] or 0 for m in pg["movimentacoes"] if _classe(m["operacao"]) == "venda")
        o = pg["orgao"].replace("Conselho Administração", "Conselho").replace("Órgãos Técnicos ou Consultivos", "Órgãos técnicos")
        if o.startswith("Companhia"):
            o = "Recompra" if "Tesouraria" in (pg.get("entidade") or "") or len(d["paginas"]) == 1 else (pg.get("entidade") or "Controlada").split(" - ")[0][:25]
        if o == "Recompra":
            if c: partes.append("Recompra: %s ações (R$ %s, média %.2f)" % (fmt(c), fmt(cv), cv / c))
            if v: partes.append("Tesouraria vendeu/usou %s ações (R$ %s)" % (fmt(v), fmt(vv)))
        else:
            if c: partes.append("%s comprou %s (R$ %s)" % (o, fmt(c), fmt(cv)))
            if v: partes.append("%s vendeu %s (R$ %s)" % (o, fmt(v), fmt(vv)))
        outros = [m for m in pg["movimentacoes"] if _classe(m["operacao"]) == "outro"]
        if outros: partes.append("%s: %d outra(s) operação(ões)" % (o, len(outros)))
    return "; ".join(partes) if partes else "sem movimentação no mês"


def fmt(x):
    x = float(x)
    if x >= 1e6: return "%.1f mi" % (x / 1e6)
    if x >= 1e3: return "%.0f mil" % (x / 1e3)
    return "%d" % x


# ---------------------------------------------------------------------------
# Abas "Monitor mensal" e "12 meses" no formato do relatório (buybacks + insiders por grupo)
# ---------------------------------------------------------------------------
GRUPOS = {"Controlador": "Controlador", "Diretoria": "Diretoria", "Conselho Administração": "Conselho",
          "Conselho Fiscal": "Outros", "Órgãos Técnicos ou Consultivos": "Outros"}


def _classe(op):
    op = op.lower()
    if "venda" in op: return "venda"          # antes de "compra": "venda ... exercício de opção de compra"
    if "compra" in op or "subscri" in op: return "compra"
    return "outro"


def tabela_monitor(docs):
    """Por (ticker, ref): buyback (Individual) e insiders por grupo (Consolidado), em R$ e ações."""
    from collections import defaultdict
    t = defaultdict(lambda: defaultdict(float))
    for d in docs:
        k = (d["ticker"], d["ref"])
        if "Consolidada" in d["tipo"]:
            for p in d["paginas"]:
                g = GRUPOS.get(p["orgao"], "Outros")
                for m in p["movimentacoes"]:
                    c = _classe(m["operacao"])
                    if c == "outro": continue
                    t[k][g + "_" + c + "_q"] += m["quantidade"] or 0
                    t[k][g + "_" + c + "_v"] += m["volume"] or 0
        else:  # Individual: a própria companhia (recompra = compra; venda de tesouraria = venda); só ações
            for p in d["paginas"]:
                for m in p["movimentacoes"]:
                    c = _classe(m["operacao"])
                    if c == "outro" or not m["ativo"].lower().startswith("aç") or (m["quantidade"] or 0) <= 0: continue
                    t[k]["buyback_" + c + "_q"] += m["quantidade"] or 0
                    t[k]["buyback_" + c + "_v"] += m["volume"] or 0
    return t


def abas_monitor(wb, docs, aba):
    t = tabela_monitor(docs)
    mi = 1e6
    cab = ["Ticker", "Mês ref", "Buyback ações ('000)", "Buyback R$ mn", "Buyback preço médio", "Venda tesouraria R$ mn",
           "Controlador compra R$ mn", "Controlador venda R$ mn", "Controlador saldo R$ mn",
           "Diretoria compra R$ mn", "Diretoria venda R$ mn", "Diretoria saldo R$ mn",
           "Conselho compra R$ mn", "Conselho venda R$ mn", "Conselho saldo R$ mn",
           "Outros compra R$ mn", "Outros venda R$ mn", "Outros saldo R$ mn", "Insiders saldo total R$ mn"]

    def linha(ticker, ref, v):
        bq, bv = v.get("buyback_compra_q", 0), v.get("buyback_compra_v", 0)
        r = [ticker, ref, bq / 1e3, bv / mi, (bv / bq) if bq else None, v.get("buyback_venda_v", 0) / mi]
        tot = 0
        for g in ("Controlador", "Diretoria", "Conselho", "Outros"):
            c, s = v.get(g + "_compra_v", 0) / mi, v.get(g + "_venda_v", 0) / mi
            r += [c, s, c - s]; tot += c - s
        return r + [tot]

    mensal = [linha(tk, ref, v) for (tk, ref), v in t.items()]
    mensal.sort(key=lambda r: (chave_ordem(r[1]), r[0]), reverse=True)
    ws = aba("Monitor mensal", cab, mensal, [8, 9] + [14] * 17)
    for r in ws.iter_rows(min_row=2):
        for c in r[2:]: c.number_format = "#,##0.0"

    # 12 meses: soma dos últimos 12 meses de referência disponíveis, por ticker
    refs = sorted({ref for _, ref in t}, key=chave_ordem)[-12:]
    from collections import defaultdict
    soma = defaultdict(lambda: defaultdict(float))
    for (tk, ref), v in t.items():
        if ref in refs:
            for kk, vv in v.items(): soma[tk][kk] += vv
    janela = "%s a %s" % (refs[0], refs[-1]) if refs else ""
    linhas = [linha(tk, janela, v) for tk, v in soma.items()]
    linhas.sort(key=lambda r: r[-1])
    ws = aba("12 meses", cab[:1] + ["Janela"] + cab[2:], linhas, [8, 18] + [14] * 17)
    for r in ws.iter_rows(min_row=2):
        for c in r[2:]: c.number_format = "#,##0.0"


def aba_entregas(wb, docs, aba):
    """Mapa mês a mês: data de entrega do consolidado e do individual por empresa (vazio = não entregou)."""
    import csv
    tickers = [e["ticker"] for e in csv.DictReader(open(os.path.join(AQUI, "empresas.csv"), encoding="utf-8"), delimiter=";")]
    refs = sorted({d["ref"] for d in docs}, key=chave_ordem, reverse=True)
    ent = {(d["ticker"], d["ref"], "C" if "Consolidada" in d["tipo"] else "I"): d["entrega"] for d in docs}
    cab = ["Mês ref", "Ticker", "Consolidado (insiders)", "Individual (recompra)", "Status"]
    linhas = []
    for ref in refs:
        for t in tickers:
            c, i = ent.get((t, ref, "C"), ""), ent.get((t, ref, "I"), "")
            st = "ok" if c and i else ("só consolidado" if c else ("só individual" if i else "FALTA"))
            linhas.append([ref, t, c, i, st])
    ws = aba("Entregas", cab, linhas, [9, 8, 22, 22, 16])
    from openpyxl.styles import PatternFill
    for r in ws.iter_rows(min_row=2):
        if r[4].value == "FALTA": r[4].fill = PatternFill("solid", fgColor="F8CBAD")
        elif r[4].value != "ok": r[4].fill = PatternFill("solid", fgColor="FFE699")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gerar"
    if cmd == "processar":
        docs = json.load(open(sys.argv[2], encoding="utf-8"))
        docs = docs.get("docs", docs)
        lidos, falhas = processar(docs)
        n_mov, n_docs = gerar()
        print(json.dumps({"lidos": lidos, "falhas": falhas, "movimentacoes": n_mov, "formularios": n_docs}, ensure_ascii=False))
    elif cmd == "resumo":
        print(resumo(sys.argv[2]))
    else:
        print(gerar())
