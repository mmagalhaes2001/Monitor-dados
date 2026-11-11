#!/usr/bin/env python3
"""Gera cvm44/matriz_cvm44.xlsx: empresas nas linhas, meses nas colunas, um bloco por
(grupo × tipo de operação), em três abas: Volume (R$), Quantidade (ações) e Preço médio (R$).

Fontes: formulários lidos dos PDFs (cvm44/dados) para os meses cobertos pelo ENET; para meses anteriores,
o CSV de dados abertos da CVM (vlmo_cia_aberta_con_AAAA.csv e vlmo_cia_aberta_AAAA.csv), baixado para cvm44/vlmo/.
Uso: python cvm44/matriz.py [--desde 2025-01]
"""
import csv, glob, io, json, os, re, sys, urllib.request, zipfile
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "dados"); VLMO = os.path.join(AQUI, "vlmo")
XLSX = os.path.join(AQUI, "matriz_cvm44.xlsx")
sys.path.insert(0, AQUI)

GRUPOS = [("Controlador", "Controlador"), ("Conselho Administração", "Conselho"), ("Diretoria", "Diretoria"),
          ("Conselho Fiscal", "Cons. Fiscal"), ("Órgãos Técnicos ou Consultivos", "Comitês"), ("Companhia", "Companhia (tesouraria)")]
CARGO_CSV = {"Controlador ou Vinculado": "Controlador", "Conselho de Administração ou Vinculado": "Conselho",
             "Diretor ou Vinculado": "Diretoria", "Conselho Fiscal ou Vinculado": "Cons. Fiscal",
             "Órgão Estatutário ou Vinculado": "Comitês", "Órgãos Técnicos ou Consultivos ou Vinculado": "Comitês",
             "Órgãos Técnicos ou Consultivos": "Comitês"}
OPS = [("Compra à vista", "compra_vista"), ("Venda à vista", "venda_vista"), ("Compra a termo", "compra_termo"),
       ("Venda a termo", "venda_termo"), ("Exercício de opção (compra)", "exerc_opcao"), ("Subscrição", "subscricao"),
       ("Plano de remuneração / ações restritas", "remuneracao"), ("Empréstimo de ações (cessão)", "emprestimo"),
       ("Devolução de empréstimo", "devolucao"), ("Outras operações em ações", "outros")]


def classificar(op, ativo=""):
    o = re.sub(r"\s+", " ", (op or "")).strip().lower()
    a = (ativo or "").lower()
    if not a.startswith("aç") and a: return None            # derivativos / debêntures / opções ficam fora
    if "devolução" in o and "emprést" in o: return "devolucao"
    if "emprést" in o or "aluguel" in o: return "emprestimo"
    if "remunera" in o or "restrita" in o or "outorga" in o: return "remuneracao"
    if "subscri" in o: return "subscricao"
    if ("opç" in o or "opc" in o or "exerc" in o) and "venda" not in o: return "exerc_opcao"
    if "termo" in o: return "venda_termo" if "venda" in o else "compra_termo"
    if "venda" in o or "aliena" in o: return "venda_vista"
    if "compra" in o or "aquisi" in o: return "compra_vista"
    return "outros"


def empresas():
    with open(os.path.join(AQUI, "empresas.csv"), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if r.get("cod_cvm")]


def cnpjs():
    """ticker → CNPJ, via cadastro da CVM (cod_cvm)."""
    cad = os.path.join(VLMO, "cad_cia_aberta.csv")
    os.makedirs(VLMO, exist_ok=True)
    if not os.path.exists(cad):
        urllib.request.urlretrieve("https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv", cad)
    por_cod = {}
    with open(cad, encoding="latin-1") as f:
        for r in csv.DictReader(f, delimiter=";"):
            por_cod[r["CD_CVM"].zfill(6)] = r["CNPJ_CIA"]
    return {e["ticker"]: por_cod.get(e["cod_cvm"]) for e in empresas()}


def dos_pdfs():
    """{(ticker, 'AAAA-MM', grupo, op): [qtd, vol]} a partir dos JSONs lidos dos PDFs. Devolve também os meses cobertos por ticker."""
    acc = defaultdict(lambda: [0.0, 0.0]); cobertos = defaultdict(set)
    ult = {}
    for p in glob.glob(os.path.join(DADOS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        k = (d["ticker"], d["ref"], d["tipo"])
        if k not in ult or int(d["versao"]) > int(ult[k]["versao"]): ult[k] = d
    for d in ult.values():
        mes = d["ref"][3:] + "-" + d["ref"][:2]
        cons = "Consolidada" in d["tipo"]
        cobertos[(d["ticker"], "C" if cons else "I")].add(mes)
        for pg in d["paginas"]:
            g = dict(GRUPOS).get(pg["orgao"], "Companhia (tesouraria)" if not cons else "Comitês")
            for m in pg["movimentacoes"]:
                c = classificar(m["operacao"], m["ativo"])
                if not c or not (m["quantidade"] or 0): continue
                acc[(d["ticker"], mes, g, c)][0] += m["quantidade"]; acc[(d["ticker"], mes, g, c)][1] += m["volume"] or 0
    return acc, cobertos


def do_csv(anos, por_cnpj, cobertos):
    """Complementa com os dados abertos nos meses/formulários que os PDFs não cobrem."""
    acc = defaultdict(lambda: [0.0, 0.0])
    os.makedirs(VLMO, exist_ok=True)
    for ano in anos:
        z = os.path.join(VLMO, "vlmo_%d.zip" % ano)
        if not os.path.exists(z):
            urllib.request.urlretrieve("https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_%d.zip" % ano, z)
        with zipfile.ZipFile(z) as zf:
            # o dado aberto só traz o consolidado (insiders); recompra (individual) vem apenas dos PDFs
            for nome, tipo in (("vlmo_cia_aberta_con_%d.csv" % ano, "C"),):
                with zf.open(nome) as f:
                    rd = csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")
                    ult_versao = {}
                    linhas = list(rd)
                    for r in linhas:
                        t = por_cnpj.get(r["CNPJ_Companhia"])
                        if not t: continue
                        k = (t, r["Data_Referencia"][:7]); v = int(r["Versao"] or 1)
                        ult_versao[k] = max(ult_versao.get(k, 0), v)
                    for r in linhas:
                        t = por_cnpj.get(r["CNPJ_Companhia"])
                        if not t: continue
                        mes = r["Data_Referencia"][:7]
                        if mes in cobertos.get((t, tipo), set()): continue
                        if int(r["Versao"] or 1) != ult_versao[(t, mes)]: continue
                        if r["Tipo_Movimentacao"] in ("Saldo Inicial", "Saldo Final"): continue
                        g = "Companhia (tesouraria)" if tipo == "I" else CARGO_CSV.get(r["Tipo_Cargo"], "Comitês")
                        c = classificar(r["Tipo_Movimentacao"], r["Tipo_Ativo"])
                        q = float(r["Quantidade"] or 0); vol = float(r["Volume"] or 0)
                        if not c or not q: continue
                        acc[(t, mes, g, c)][0] += q; acc[(t, mes, g, c)][1] += vol
    return acc


def gerar(desde="2025-01"):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    emps = empresas(); tickers = [e["ticker"] for e in emps]; nomes = {e["ticker"]: e["nome"] for e in emps}
    por_cnpj = {v: k for k, v in cnpjs().items() if v}
    pdf, cobertos = dos_pdfs()
    anos = sorted({int(desde[:4])} | {a for a in range(int(desde[:4]), 2027)})
    csvd = do_csv(anos, por_cnpj, cobertos)
    acc = defaultdict(lambda: [0.0, 0.0])
    for src in (pdf, csvd):
        for k, (q, v) in src.items():
            acc[k][0] += q; acc[k][1] += v
    meses = sorted({k[1] for k in acc} | {k[1] for k in []})
    meses = [m for m in meses if m >= desde]
    rot = lambda m: ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"][int(m[5:]) - 1] + "-" + m[2:4]

    wb = Workbook(); wb.remove(wb.active)
    cab_fill = PatternFill("solid", fgColor="1F3864"); sub_fill = PatternFill("solid", fgColor="D9E1F2"); hl = PatternFill("solid", fgColor="FFF2CC")
    for aba, idx, fmt_num in (("Volume (R$)", 1, "#,##0"), ("Quantidade", 0, "#,##0"), ("Preço médio", 2, "#,##0.00")):
        ws = wb.create_sheet(aba); linha = 1
        ws.column_dimensions["A"].width = 18; ws.column_dimensions["B"].width = 8
        for i in range(len(meses)): ws.column_dimensions[get_column_letter(3 + i)].width = 11
        for g_long, g in GRUPOS:
            for op_rot, op in OPS:
                if g == "Companhia (tesouraria)" and op in ("exerc_opcao",): continue
                if not any(acc.get((t, m, g, op), [0, 0])[1] or acc.get((t, m, g, op), [0, 0])[0] for t in tickers for m in meses):
                    continue
                ws.cell(linha, 1, "%s — %s" % (g, op_rot)).font = Font(bold=True, color="FFFFFF")
                for c in range(1, 3 + len(meses)): ws.cell(linha, c).fill = cab_fill
                ws.cell(linha + 1, 1, "Empresa").font = Font(bold=True); ws.cell(linha + 1, 2, "Ticker").font = Font(bold=True)
                for i, m in enumerate(meses):
                    cc = ws.cell(linha + 1, 3 + i, rot(m)); cc.font = Font(bold=True); cc.alignment = Alignment(horizontal="center"); cc.fill = sub_fill
                ws.cell(linha + 1, 1).fill = sub_fill; ws.cell(linha + 1, 2).fill = sub_fill
                r = linha + 2
                for t in tickers:
                    ws.cell(r, 1, nomes[t]); ws.cell(r, 2, t)
                    for i, m in enumerate(meses):
                        q, v = acc.get((t, m, g, op), [0.0, 0.0])
                        val = [round(q), round(v, 2), (round(v / q, 4) if q else None)][idx]
                        cell = ws.cell(r, 3 + i, val if val else (0 if idx != 2 else None))
                        cell.number_format = fmt_num
                        if val: cell.fill = hl
                    r += 1
                linha = r + 1
        ws.freeze_panes = "C1"
    # Fontes / cobertura
    ws = wb.create_sheet("Cobertura")
    ws.append(["Mês", "Fonte dos dados"])
    for m in meses:
        n_pdf = sum(1 for t in tickers if m in cobertos.get((t, "C"), set()))
        ws.append([rot(m), "PDF ENET (%d empresas) + dados abertos CVM para as demais" % n_pdf if n_pdf else "dados abertos CVM (vlmo)"])
    ws.append([]); ws.append(["Classificação das operações:"])
    for op_rot, op in OPS: ws.append([op_rot, op])
    ws.append([]); ws.append(["Derivativos (opções, swaps) e debêntures ficam fora; só ações. Empréstimo = ações cedidas em aluguel (não é venda)."])
    ws.column_dimensions["A"].width = 40; ws.column_dimensions["B"].width = 70
    wb.save(XLSX)
    return len(meses), len(acc)


if __name__ == "__main__":
    desde = sys.argv[sys.argv.index("--desde") + 1] if "--desde" in sys.argv else "2025-01"
    print(gerar(desde))
