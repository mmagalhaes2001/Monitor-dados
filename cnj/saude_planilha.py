"""Monta a planilha de acompanhamento do painel de saúde do CNJ (Saúde Suplementar) a partir das
fotos guardadas em estado/cnj-saude-sup/*.json (uma por publicação/revisão do painel).

Uso: python cnj/saude_planilha.py estado/cnj-saude-sup resultados/cnj/cnj_saude_suplementar.xlsx

Abas:
  Resumo        - cards da foto mais recente vs foto anterior
  Série mensal  - série da foto mais recente (casos novos, baixados, pendentes, tempos médios) + a/a
  Casos novos por versão - casos novos de cada mês em cada foto (para ver revisões)
  Revisões      - lista de mudanças entre fotos consecutivas
  Notas         - fonte e ressalvas
"""
import json
import pathlib
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from saude_compara import CAMPOS_MES, ROTULO, revisoes  # noqa: E402

FONTE = "Arial"
F = Font(name=FONTE, size=10)
FB = Font(name=FONTE, size=10, bold=True)
FT = Font(name=FONTE, size=12, bold=True)
FIN = Font(name=FONTE, size=10, color="0000FF")  # números vindos do painel (hardcoded)
CAB = PatternFill("solid", start_color="DDE4EE")
LIN = Border(bottom=Side(style="thin", color="999999"))
FONTE_TXT = ("Fonte: CNJ, Painel Estatísticas Processuais de Direito à Saúde (Justiça em Números, DataJud), "
             "filtro Temas = Saúde Suplementar. https://justica-em-numeros.cnj.jus.br/painel-saude/")


def data_painel(texto):
    m = re.search(r"atualizado em (\d{2}/\d{2}/\d{4})", texto or "")
    return m.group(1) if m else "?"


def cabecalho(ws, linha, nomes, larguras=None):
    for i, n in enumerate(nomes, 1):
        c = ws.cell(row=linha, column=i, value=n)
        c.font, c.fill, c.border = FB, CAB, LIN
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    if larguras:
        for i, w in enumerate(larguras, 1):
            ws.column_dimensions[get_column_letter(i)].width = w


def main(pasta, saida):
    fotos = [(p.stem, json.loads(p.read_text())) for p in sorted(pathlib.Path(pasta).glob("*.json"))]
    if not fotos:
        raise SystemExit("sem fotos")
    nome_ult, ult = fotos[-1]
    ant = fotos[-2][1] if len(fotos) > 1 else None
    wb = Workbook()

    # ---------- Série mensal ----------
    sm = wb.active
    sm.title = "Série mensal"
    sm["A1"], sm["A1"].font = f"Saúde Suplementar - série mensal (painel atualizado em {data_painel(ult['data_texto'])})", FT
    sm["A2"], sm["A2"].font = FONTE_TXT, Font(name=FONTE, size=8, italic=True)
    cols = ["Mês", "Casos novos", "Baixados", "Pendentes (fim do mês)", "Tempo médio do pendente (dias)",
            "Tempo médio do pendente líquido (dias)", "Tempo médio da 1ª baixa (dias)",
            "Casos novos a/a", "Casos novos 12m", "Baixados 12m"]
    cabecalho(sm, 4, cols, [10, 12, 12, 14, 14, 14, 14, 11, 13, 13])
    sm.row_dimensions[4].height = 45
    r0 = 5
    for i, r in enumerate(ult["mensal"]):
        lin = r0 + i
        sm.cell(row=lin, column=1, value=r["mes"]).font = F
        for j, c in enumerate(CAMPOS_MES, 2):
            v = r.get(c)
            cel = sm.cell(row=lin, column=j, value=round(v, 1) if isinstance(v, float) else v)
            cel.font, cel.number_format = FIN, "#,##0" if "tempo" not in c else "#,##0.0"
        if i >= 12:
            sm.cell(row=lin, column=8, value=f"=IFERROR(B{lin}/B{lin - 12}-1,\"\")")
        if i >= 11:
            sm.cell(row=lin, column=9, value=f"=SUM(B{lin - 11}:B{lin})")
            sm.cell(row=lin, column=10, value=f"=SUM(C{lin - 11}:C{lin})")
        for j, fmtn in ((8, "0.0%;-0.0%;-"), (9, "#,##0"), (10, "#,##0")):
            sm.cell(row=lin, column=j).font, sm.cell(row=lin, column=j).number_format = F, fmtn
    fim = r0 + len(ult["mensal"]) - 1
    sm.cell(row=fim + 2, column=1, value=(
        "Pendentes e tempos médios por mês: recalculados com a base atual, filtrando o painel até cada mês "
        "(podem diferir do que o painel mostrava na época). Últimos meses costumam ser revisados para cima "
        "nas publicações seguintes (envio tardio dos tribunais).")).font = Font(name=FONTE, size=8, italic=True)
    sm.freeze_panes = "B5"

    # ---------- Resumo ----------
    rs = wb.create_sheet("Resumo", 0)
    rs["A1"], rs["A1"].font = "CNJ - Saúde Suplementar: resumo", FT
    rs["A2"], rs["A2"].font = ult["data_texto"], Font(name=FONTE, size=9, italic=True)
    cabecalho(rs, 4, ["Indicador", "Atual", "Foto anterior", "Var."], [42, 14, 14, 10])
    itens = [("Pendentes (último mês)", "pendentes", "#,##0"),
             ("Tempo médio do pendente (dias)", "tempo_medio_pendente_dias", "#,##0"),
             ("Tempo médio do pendente líquido (dias)", "tempo_medio_pendente_liquido_dias", "#,##0"),
             ("Saídas: baixados no ano", "baixados_no_ano", "#,##0"),
             ("Tempo médio da 1ª baixa (dias)", "tempo_medio_primeira_baixa_dias", "#,##0"),
             ("Casos novos no ano", "casos_novos_no_ano", "#,##0")]
    for i, (rot, k, nf) in enumerate(itens, 5):
        rs.cell(row=i, column=1, value=rot).font = F
        b = rs.cell(row=i, column=2, value=ult["cards"].get(k))
        c = rs.cell(row=i, column=3, value=ant["cards"].get(k) if ant else None)
        for x in (b, c):
            x.font, x.number_format = FIN, nf
        d = rs.cell(row=i, column=4, value=f'=IF(OR(C{i}="",C{i}=0),"",B{i}/C{i}-1)')
        d.font, d.number_format = F, "0.0%;-0.0%;-"
    rs.cell(row=12, column=1, value=(f"Foto atual: {nome_ult}" + (f" | anterior: {fotos[-2][0]}" if ant else
                                     " | ainda não há foto anterior (primeira leitura)"))).font = Font(name=FONTE, size=8, italic=True)
    rs.cell(row=13, column=1, value=FONTE_TXT).font = Font(name=FONTE, size=8, italic=True)

    # ---------- Casos novos por versão ----------
    cv = wb.create_sheet("Casos novos por versão")
    cv["A1"], cv["A1"].font = "Casos novos por mês em cada publicação (foto) do painel", FT
    nomes = [n for n, _ in fotos]
    cabecalho(cv, 3, ["Mês"] + nomes + (["Última - anterior"] if len(fotos) > 1 else []),
              [10] + [16] * len(nomes) + [14])
    meses = sorted({r["mes"] for _, f in fotos for r in f["mensal"]})
    for i, m in enumerate(meses, 4):
        cv.cell(row=i, column=1, value=m).font = F
        for j, (_, f) in enumerate(fotos, 2):
            v = next((r["casos_novos"] for r in f["mensal"] if r["mes"] == m), None)
            cel = cv.cell(row=i, column=j, value=v)
            cel.font, cel.number_format = FIN, "#,##0"
        if len(fotos) > 1:
            a, b = get_column_letter(len(fotos)), get_column_letter(len(fotos) + 1)
            d = cv.cell(row=i, column=len(fotos) + 2, value=f'=IF(OR({a}{i}="",{b}{i}=""),"",{b}{i}-{a}{i})')
            d.font, d.number_format = F, "#,##0;-#,##0;-"
    cv.freeze_panes = "B4"

    # ---------- Revisões ----------
    rv = wb.create_sheet("Revisões")
    rv["A1"], rv["A1"].font = "Mudanças entre publicações consecutivas", FT
    cabecalho(rv, 3, ["De (foto)", "Para (foto)", "Mês", "Indicador", "Antes", "Depois", "Var."],
              [24, 24, 10, 26, 13, 13, 9])
    lin = 4
    for (n0, f0), (n1, f1) in zip(fotos, fotos[1:]):
        for r in revisoes(f0, f1):
            vals = [n0, n1, r["mes"], ROTULO[r["campo"]], r["antes"], r["depois"]]
            for j, v in enumerate(vals, 1):
                c = rv.cell(row=lin, column=j, value=round(v, 1) if isinstance(v, float) else v)
                c.font = FIN if j in (5, 6) else F
                if j in (5, 6):
                    c.number_format = "#,##0"
            p = rv.cell(row=lin, column=7, value=f'=IF(E{lin}=0,"",F{lin}/E{lin}-1)')
            p.font, p.number_format = F, "0.0%;-0.0%;-"
            lin += 1
    if lin == 4:
        rv.cell(row=4, column=1, value="Ainda sem revisões: só existe uma foto do painel.").font = F

    # ---------- Notas ----------
    nt = wb.create_sheet("Notas")
    nt.column_dimensions["A"].width = 120
    notas = [
        "Fonte: CNJ - Painel Estatísticas Processuais de Direito à Saúde (Power BI público), https://justica-em-numeros.cnj.jus.br/painel-saude/",
        "Base de origem do painel: DataJud (Base Nacional de Dados do Poder Judiciário), alimentada pelos tribunais.",
        "Recorte: Temas = Saúde Suplementar; Tipo = Processo (casos novos); ramos Estadual, Federal e Tribunais Superiores (padrão do painel).",
        "Coleta: robô no GitHub (repositório Monitor-dados) consulta o painel; cada publicação/revisão vira uma foto em estado/cnj-saude-sup/.",
        "Números em azul vêm direto do painel; células em preto são fórmulas.",
        "Pendentes e tempos médios mensais são recalculados com a base atual filtrando até cada mês; não são as fotos publicadas na época.",
    ]
    for i, t in enumerate(notas, 1):
        nt.cell(row=i, column=1, value=t).font = F

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    pathlib.Path(saida).parent.mkdir(parents=True, exist_ok=True)
    wb.save(saida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
