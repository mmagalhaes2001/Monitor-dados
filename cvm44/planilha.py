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
    alvo = os.path.join(PDF_DIR, nome_pdf(d))
    if not os.path.exists(alvo):
        req = urllib.request.Request(d["download"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(alvo, "wb") as f:
            f.write(r.read())
    with open(alvo, "rb") as f:
        if f.read(4) != b"%PDF":
            os.remove(alvo); raise RuntimeError("download não é PDF")
    return alvo


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
                if op.startswith("compra") or "subscri" in op or "exerc" in op:
                    res[k]["compra_q"] += m["quantidade"] or 0; res[k]["compra_v"] += m["volume"] or 0
                elif op.startswith("venda"):
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
        c = sum(m["quantidade"] or 0 for m in pg["movimentacoes"] if m["operacao"].lower().startswith("compra"))
        v = sum(m["quantidade"] or 0 for m in pg["movimentacoes"] if m["operacao"].lower().startswith("venda"))
        cv = sum(m["volume"] or 0 for m in pg["movimentacoes"] if m["operacao"].lower().startswith("compra"))
        vv = sum(m["volume"] or 0 for m in pg["movimentacoes"] if m["operacao"].lower().startswith("venda"))
        o = pg["orgao"].replace("Conselho Administração", "Conselho").replace("Órgãos Técnicos ou Consultivos", "Órgãos técnicos")
        if c: partes.append("%s comprou %s (R$ %s)" % (o, fmt(c), fmt(cv)))
        if v: partes.append("%s vendeu %s (R$ %s)" % (o, fmt(v), fmt(vv)))
        outros = [m for m in pg["movimentacoes"] if not re.match(r"(compra|venda)", m["operacao"].lower())]
        if outros: partes.append("%s: %d outra(s) operação(ões)" % (o, len(outros)))
    return "; ".join(partes) if partes else "sem movimentação no mês"


def fmt(x):
    x = float(x)
    if x >= 1e6: return "%.1f mi" % (x / 1e6)
    if x >= 1e3: return "%.0f mil" % (x / 1e3)
    return "%d" % x


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
