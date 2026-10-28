"""
Acessos Anatel (móvel e banda larga fixa) -> planilha de market share por grupo econômico.

Fonte: zips de dados abertos da Anatel (os mesmos que o painel de acessos oferece para download):
  https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_telefonia_movel.zip
  https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_banda_larga_fixa.zip

Os zips têm 1-3 GB, mas o script não baixa tudo: lê só os arquivos "_Colunas" (meses em colunas)
dos períodos mais recentes, direto de dentro do zip (~20 MB no total).

Uso:
  python anatel/acessos.py --saida resultados/anatel        # gera planilha + resumo
  python anatel/acessos.py --ultimo-mes                     # só imprime o último mês publicado
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from remotezip import RemoteZip

BASE = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/"
ZIP_MOVEL = BASE + "acessos_telefonia_movel.zip"
ZIP_BLF = BASE + "acessos_banda_larga_fixa.zip"
N_MESES = 13  # 12 meses + o mesmo mês do ano anterior
# Únicas colunas usadas (o resto é descartado na leitura para caber na memória)
DIMENSOES = ["Grupo Econômico", "Tipo de Produto", "Modalidade de Cobrança",
             "Tecnologia Geração", "Meio de Acesso"]

# Nomes de mercado dos grupos (o rótulo original da Anatel fica na coluna B)
APELIDO = {
    "TELEFONICA": "Vivo",
    "TELECOM AMERICAS": "Claro",
    "TELECOM ITALIA": "TIM",
    "ALGAR (CTBC TELECOM)": "Algar",
}
# Base do total oficial do móvel: a Anatel exclui M2M e ponto de serviço
# (bate exatamente com Acessos_Telefonia_Movel_Total.csv).
MOVEL_FORA_DO_TOTAL = ["M2M", "PONTO_DE_SERVICO"]

FONTE = "Arial"
F = Font(name=FONTE, size=10)
F_B = Font(name=FONTE, size=10, bold=True)
F_T = Font(name=FONTE, size=12, bold=True)
F_NOTA = Font(name=FONTE, size=9, italic=True, color="666666")
FILL_CAB = PatternFill("solid", fgColor="DDE4EE")
LINHA = Side(style="thin", color="999999")


# ---------------------------------------------------------------- leitura dos zips
def listar(zip_url):
    with RemoteZip(zip_url) as rz:
        return {i.filename: i for i in rz.infolist()}, rz


def ultimo_mes(zip_url, total_csv):
    with RemoteZip(zip_url) as rz:
        txt = rz.read(total_csv).decode("utf-8-sig")
    df = pd.read_csv(pd.io.common.StringIO(txt), sep=";")
    df = df.sort_values(["Ano", "Mês"])
    a, m, v = df.iloc[-1][["Ano", "Mês", "Acessos"]]
    return f"{int(a)}-{int(m):02d}", int(v), df


def ler_colunas(zip_url, padrao, n_meses, pasta):
    """Lê os arquivos _Colunas mais recentes até cobrir n_meses. Devolve (df longo, arquivos, data do zip)."""
    with RemoteZip(zip_url) as rz:
        infos = rz.infolist()
        cands = []
        for i in infos:
            m = re.search(padrao, i.filename)
            if m:
                cands.append((m.groups(), i.filename))
        cands.sort(reverse=True)
        partes, usados, meses = [], [], set()
        for _, nome in cands:
            caminho = rz.extract(nome, pasta)
            cab = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", nrows=0).columns
            cols_mes = [c for c in cab if re.fullmatch(r"\d{4}-\d{2}", c)]
            ids = [c for c in DIMENSOES if c in cab]
            df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", usecols=ids + cols_mes,
                             dtype={c: "category" for c in ids})
            for c in cols_mes:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            df = df.groupby(ids, observed=True, dropna=False)[cols_mes].sum().reset_index()
            longo = df.melt(id_vars=ids, value_vars=cols_mes, var_name="mes", value_name="acessos")
            for c in ids:
                longo[c] = longo[c].astype(str).replace("nan", pd.NA)
            partes.append(longo)
            usados.append(nome)
            meses.update(cols_mes)
            os.remove(caminho)
            if len(meses) >= n_meses:
                break
    df = pd.concat(partes, ignore_index=True)
    df["Grupo Econômico"] = df["Grupo Econômico"].fillna("SEM GRUPO")
    return df, usados


def ler_longo(zip_url, padrao, n_meses):
    """Lê os arquivos em formato longo (uma linha por mês) mais recentes, em pedaços, agregando na hora."""
    with RemoteZip(zip_url) as rz:
        cands = sorted(((re.search(padrao, i.filename).groups(), i.filename)
                        for i in rz.infolist() if re.search(padrao, i.filename)), reverse=True)
        partes, usados, meses = [], [], set()
        for _, nome in cands:
            with rz.open(nome) as fh:
                cab = pd.read_csv(fh, sep=";", encoding="utf-8-sig", nrows=0).columns
            ids = [c for c in DIMENSOES if c in cab]
            with rz.open(nome) as fh:
                for ch in pd.read_csv(fh, sep=";", encoding="utf-8-sig", usecols=ids + ["Ano", "Mês", "Acessos"],
                                      dtype={c: "category" for c in ids}, chunksize=1_000_000):
                    ch["mes"] = ch["Ano"].astype(int).astype(str) + "-" + ch["Mês"].astype(int).map("{:02d}".format)
                    ch["acessos"] = pd.to_numeric(ch["Acessos"], errors="coerce").fillna(0)
                    g = ch.groupby(ids + ["mes"], observed=True, dropna=False)["acessos"].sum().reset_index()
                    for c in ids:
                        g[c] = g[c].astype(str).replace("nan", pd.NA)
                    partes.append(g)
                    meses.update(g["mes"].unique())
            usados.append(nome)
            if len(meses) >= n_meses:
                break
    df = pd.concat(partes, ignore_index=True)
    df = df.groupby([c for c in df.columns if c != "acessos"], dropna=False)["acessos"].sum().reset_index()
    df["Grupo Econômico"] = df["Grupo Econômico"].fillna("SEM GRUPO")
    return df, usados


# ---------------------------------------------------------------- tabelas
def pivot(df, meses, top_n):
    p = df.groupby(["Grupo Econômico", "mes"])["acessos"].sum().unstack("mes").reindex(columns=meses).fillna(0)
    p = p.sort_values(meses[-1], ascending=False)
    if top_n and len(p) > top_n:
        cabeca, resto = p.iloc[:top_n], p.iloc[top_n:]
        p = pd.concat([cabeca, pd.DataFrame([resto.sum()], index=["DEMAIS GRUPOS"])])
    return p


def escrever_aba(wb, nome, titulo, base_txt, p, meses):
    ws = wb.create_sheet(nome)
    ws["A1"] = titulo
    ws["A1"].font = F_T
    ws["A2"] = base_txt
    ws["A2"].font = F_NOTA
    n = len(p)
    rot = [f"{m[5:]}/{m[2:4]}" for m in meses]
    c0 = 3  # primeira coluna de mês

    def cabecalho(linha, texto):
        ws.cell(linha, 1, texto).font = F_B
        ws.cell(linha, 2, "Grupo (rótulo Anatel)").font = F_B
        for j, r in enumerate(rot):
            c = ws.cell(linha, c0 + j, r)
            c.font = F_B
            c.alignment = Alignment(horizontal="right")
        for j in range(1, c0 + len(meses)):
            ws.cell(linha, j).fill = FILL_CAB

    # Bloco 1: acessos (dados)
    l_cab1 = 4
    cabecalho(l_cab1, "Acessos")
    l_ini = l_cab1 + 1
    for i, (grupo, linha) in enumerate(p.iterrows()):
        r = l_ini + i
        ws.cell(r, 1, APELIDO.get(grupo, grupo.title() if grupo != "DEMAIS GRUPOS" else "Demais grupos")).font = F
        ws.cell(r, 2, grupo).font = F_NOTA
        for j, m in enumerate(meses):
            c = ws.cell(r, c0 + j, float(linha[m]))
            c.font = Font(name=FONTE, size=10, color="0000FF")
            c.number_format = "#,##0;(#,##0);-"
    l_tot = l_ini + n
    ws.cell(l_tot, 1, "Total").font = F_B
    for j in range(len(meses)):
        col = get_column_letter(c0 + j)
        c = ws.cell(l_tot, c0 + j, f"=SUM({col}{l_ini}:{col}{l_tot - 1})")
        c.font = F_B
        c.number_format = "#,##0;(#,##0);-"
        c.border = Border(top=LINHA)

    # Bloco 2: market share (fórmulas)
    l_cab2 = l_tot + 2
    cabecalho(l_cab2, "Market share")
    for i in range(n + 1):
        r = l_cab2 + 1 + i
        src = l_ini + i
        ws.cell(r, 1, f"=A{src}").font = F_B if i == n else F
        if i < n:
            ws.cell(r, 2, f"=B{src}").font = F_NOTA
        for j in range(len(meses)):
            col = get_column_letter(c0 + j)
            c = ws.cell(r, c0 + j, f"=IF({col}${l_tot}=0,0,{col}{src}/{col}${l_tot})")
            c.number_format = "0.0%;(0.0%);-"
            c.font = F_B if i == n else F

    # Bloco 3: adições líquidas mês a mês (fórmulas)
    l_cab3 = l_cab2 + n + 3
    cabecalho(l_cab3, "Adições líquidas (m/m)")
    for i in range(n + 1):
        r = l_cab3 + 1 + i
        src = l_ini + i
        ws.cell(r, 1, f"=A{src}").font = F_B if i == n else F
        if i < n:
            ws.cell(r, 2, f"=B{src}").font = F_NOTA
        for j in range(1, len(meses)):
            col, ant = get_column_letter(c0 + j), get_column_letter(c0 + j - 1)
            c = ws.cell(r, c0 + j, f"={col}{src}-{ant}{src}")
            c.number_format = "#,##0;(#,##0);-"
            c.font = F_B if i == n else F

    # Bloco 4: variação a/a do último mês e var. de share em p.p.
    l_cab4 = l_cab3 + n + 3
    ult, prim = get_column_letter(c0 + len(meses) - 1), get_column_letter(c0)
    ws.cell(l_cab4, 1, f"Último mês vs {rot[0]}").font = F_B
    ws.cell(l_cab4, 2, "").font = F_B
    ws.cell(l_cab4, c0, "Var. a/a").font = F_B
    ws.cell(l_cab4, c0 + 1, "Δ share (p.p.)").font = F_B
    for j in range(1, c0 + 2):
        ws.cell(l_cab4, j).fill = FILL_CAB
    for i in range(n + 1):
        r = l_cab4 + 1 + i
        src, sh = l_ini + i, l_cab2 + 1 + i
        ws.cell(r, 1, f"=A{src}").font = F_B if i == n else F
        c = ws.cell(r, c0, f"=IF({prim}{src}=0,0,{ult}{src}/{prim}{src}-1)")
        c.number_format = "0.0%;(0.0%);-"
        c = ws.cell(r, c0 + 1, f"=({ult}{sh}-{prim}{sh})*100")
        c.number_format = "0.00;(0.00);-"

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 26
    for j in range(len(meses)):
        ws.column_dimensions[get_column_letter(c0 + j)].width = 13
    ws.freeze_panes = ws.cell(l_cab1 + 1, c0)
    return ws, l_ini, l_tot


def gerar(saida):
    pasta = tempfile.mkdtemp()
    hoje = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    mes_m, tot_m_ofic, serie_m = ultimo_mes(ZIP_MOVEL, "Acessos_Telefonia_Movel_Total.csv")
    mes_b, tot_b_ofic, serie_b = ultimo_mes(ZIP_BLF, "Acessos_Banda_Larga_Fixa_Total.csv")

    mov, arq_m = ler_colunas(ZIP_MOVEL, r"Movel_(\d{4})_([12])S_Colunas\.csv$", N_MESES, pasta)
    # BLF pelo arquivo longo: o "_Colunas" da BLF soma alguns milhares de acessos a menos que o total oficial
    blf, arq_b = ler_longo(ZIP_BLF, r"Fixa_(\d{4})\.csv$", N_MESES)

    meses_m = sorted(mov["mes"].unique())[-N_MESES:]
    meses_b = sorted(blf["mes"].unique())[-N_MESES:]

    base_m = mov[~mov["Tipo de Produto"].isin(MOVEL_FORA_DO_TOTAL)]
    abas = [
        ("Móvel", "Telefonia móvel — acessos por grupo econômico",
         "Base do total oficial Anatel: exclui M2M e ponto de serviço", base_m, meses_m, 10),
        ("Móvel pós-pago", "Móvel pós-pago",
         "Mesma base (sem M2M e ponto de serviço), só pós-pago", base_m[base_m["Modalidade de Cobrança"] == "Pós-pago"], meses_m, 10),
        ("Móvel pré-pago", "Móvel pré-pago",
         "Mesma base (sem M2M e ponto de serviço), só pré-pago", base_m[base_m["Modalidade de Cobrança"] == "Pré-pago"], meses_m, 10),
        ("Móvel 5G", "Móvel 5G",
         "Mesma base (sem M2M e ponto de serviço), só 'Tecnologia Geração' = 5G", base_m[base_m["Tecnologia Geração"] == "5G"], meses_m, 10),
        ("Móvel M2M", "Móvel M2M",
         "Só 'Tipo de Produto' = M2M (fora do total oficial)", mov[mov["Tipo de Produto"] == "M2M"], meses_m, 10),
        ("BLF", "Banda larga fixa — acessos por grupo econômico",
         "Todos os acessos de SCM (bate com o total oficial Anatel, ver Notas)", blf, meses_b, 15),
        ("BLF fibra", "Banda larga fixa — fibra",
         "Só 'Meio de Acesso' = Fibra", blf[blf["Meio de Acesso"] == "Fibra"], meses_b, 15),
    ]

    wb = Workbook()
    wb.remove(wb.active)
    pos = {}
    piv = {}
    for nome, tit, base_txt, df, meses, top in abas:
        p = pivot(df, meses, top)
        piv[nome] = (p, meses)
        _, l_ini, l_tot = escrever_aba(wb, nome, tit, base_txt, p, meses)
        pos[nome] = (l_ini, l_tot, len(meses))

    # Notas + conferência com o total oficial
    ws = wb.create_sheet("Notas")
    ws["A1"] = "Notas"
    ws["A1"].font = F_T
    lt_m, lt_b = pos["Móvel"][1], pos["BLF"][1]
    col_m = get_column_letter(3 + pos["Móvel"][2] - 1)
    col_b = get_column_letter(3 + pos["BLF"][2] - 1)
    linhas = [
        ("Gerado em", hoje),
        ("Fonte móvel", ZIP_MOVEL),
        ("Arquivos lidos (móvel)", ", ".join(arq_m)),
        ("Fonte banda larga fixa", ZIP_BLF),
        ("Arquivos lidos (BLF)", ", ".join(arq_b)),
        ("Último mês móvel", mes_m),
        ("Último mês BLF", mes_b),
        ("", ""),
        ("Conferência com o total oficial (arquivos _Total.csv do zip)", ""),
        ("Móvel: total oficial Anatel", tot_m_ofic),
        ("Móvel: total desta planilha", f"='Móvel'!{col_m}{lt_m}"),
        ("Móvel: diferença", "=B12-B11"),
        ("BLF: total oficial Anatel", tot_b_ofic),
        ("BLF: total desta planilha", f"=BLF!{col_b}{lt_b}"),
        ("BLF: diferença", "=B15-B14"),
        ("Obs.", "Móvel lido dos arquivos '_Colunas' (batem com o total oficial); BLF lida dos arquivos longos, porque o '_Colunas' da BLF soma alguns milhares de acessos a menos que o total oficial."),
        ("", ""),
        ("Definições", ""),
        ("Grupo econômico", "Rótulo da Anatel (coluna 'Grupo Econômico'). Nomes comerciais na coluna A só para Vivo/Claro/TIM/Algar; 'OUTROS' é o rótulo da própria Anatel."),
        ("Base do móvel", "O total oficial exclui M2M e ponto de serviço; as abas Móvel/pós/pré/5G usam essa base. M2M tem aba própria."),
        ("Acessos", "Acessos ativos no último dia do mês."),
        ("Cores", "Azul = dado da Anatel; preto = fórmula."),
    ]
    for i, (a, b) in enumerate(linhas, start=2):
        ws.cell(i, 1, a).font = F_B if b == "" else F
        c = ws.cell(i, 2, b)
        c.font = Font(name=FONTE, size=10, color="0000FF") if isinstance(b, (int, float)) else F
        if isinstance(b, (int, float)) or str(b).startswith("="):
            c.number_format = "#,##0;(#,##0);-"
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 110

    os.makedirs(saida, exist_ok=True)
    ref = max(mes_m, mes_b)
    arq = os.path.join(saida, f"anatel_acessos_{ref}.xlsx")
    wb.save(arq)

    # Resumo em texto (vai no push do celular)
    def br(x, fmt):
        return format(x, fmt).replace(",", "X").replace(".", ",").replace("X", ".")

    def share(nome, grupos):
        p, meses = piv[nome]
        tot = p[meses[-1]].sum()
        ant = p[meses[-2]].sum() if len(meses) > 1 else tot
        out = []
        for g in grupos:
            if g in p.index:
                s, s0 = p.loc[g, meses[-1]] / tot, p.loc[g, meses[-2]] / ant
                out.append(f"{APELIDO.get(g, g.title())} {br(s * 100, '.1f')}% ({br((s - s0) * 100, '+.2f')}pp)")
        return out, tot, tot - ant

    sm, tm, dm = share("Móvel", ["TELEFONICA", "TELECOM AMERICAS", "TELECOM ITALIA"])
    sb, tb, db = share("BLF", ["TELECOM AMERICAS", "TELEFONICA", "OI", "BRISANET"])
    resumo = {
        "mes_movel": mes_m, "mes_blf": mes_b,
        "texto": (
            f"Móvel {mes_m[5:]}/{mes_m[2:4]}: {br(tm / 1e6, '.1f')} mi ({br(dm / 1e3, '+,.0f')} mil m/m). "
            + "; ".join(sm) + ".\n"
            f"BLF {mes_b[5:]}/{mes_b[2:4]}: {br(tb / 1e6, '.1f')} mi ({br(db / 1e3, '+,.0f')} mil m/m). "
            + "; ".join(sb) + "."
        ),
        "arquivo": arq,
    }
    with open(os.path.join(saida, "ultimo_resumo.json"), "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=1)
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    return arq


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="resultados/anatel")
    ap.add_argument("--ultimo-mes", action="store_true")
    a = ap.parse_args()
    if a.ultimo_mes:
        print(ultimo_mes(ZIP_MOVEL, "Acessos_Telefonia_Movel_Total.csv")[0],
              ultimo_mes(ZIP_BLF, "Acessos_Banda_Larga_Fixa_Total.csv")[0])
        sys.exit(0)
    gerar(a.saida)
