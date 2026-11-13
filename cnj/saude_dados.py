"""Puxa números do painel de saúde do CNJ (Power BI público) direto da API de consulta do Power BI,
sem navegador, para um recorte de matéria (padrão: Saúde Suplementar).

Uso: python cnj/saude_dados.py [--materia "Saúde Suplementar"]
Imprime JSON com:
  data_texto: frase "Painel atualizado em ..."
  cards: pendentes (último mês), tempo médio do pendente (dias), tempo médio do pendente líquido,
         baixados no ano, tempo médio da 1ª baixa (dias), casos novos no ano
  mensal: [{"mes": "2020-01", "casos_novos": n, "baixados": n}, ...]

As consultas são as mesmas que o próprio painel faz (modelos em cnj/templates_saude.json),
trocando só o filtro de matéria.
"""
import argparse
import copy
import datetime as dt
import json
import pathlib
import sys
import urllib.request
import uuid

# Endereço da API, chave do relatório e consultas-modelo ficam em templates_saude.json
# (o cnj/recapturar.py reescreve esse arquivo se o CNJ mudar a estrutura do painel).
import os
TPL = json.loads(pathlib.Path(os.environ.get("CNJ_TEMPLATES") or
                              pathlib.Path(__file__).parent / "templates_saude.json").read_text())
_CFG = TPL.pop("_config", {})
URL = _CFG.get("url", "https://wabi-us-east-a-primary-api.analysis.windows.net/public/reports/querydata") + "?synchronous=true"
CHAVE = _CFG.get("chave", "dab12170-5f8d-49d3-b08c-960482cea969")

CARDS = {
    "pendentes": "medidas_matéria.ultimo_mes_pendentes_temas",
    "tempo_medio_pendente_dias": "medidas_matéria.Temp_CP_Ind19_media_ultimo_ano_assunto",
    "tempo_medio_pendente_liquido_dias": "medidas_matéria.Temp_CPL_Ind18_media_ultimo_ano_assunto",
    "baixados_no_ano": "medidas_matéria.ano_atual_baixados_temas",
    "tempo_medio_primeira_baixa_dias": "medidas_matéria.Temp_baixa_Ind16_media_ultimo_ano_assunto_temas",
    "casos_novos_no_ano": "medidas_matéria.ano_atual_novos_temas",
}
MENSAL = "tbl_fato_materias_R.primeiro_dia"
DATA = "Medidas.Texto_data"
COLS_MENSAL = {"mes": "tbl_fato_materias_R.primeiro_dia", "casos_novos": "Sum(tbl_fato_materias_R.CN)",
               "baixados": "Sum(tbl_fato_materias_R.TBaix)"}
COL_DATA, COL_MATERIA = "primeiro_dia", "materia"

# Se o painel mudar de estrutura, o recapturar.py grava os nomes novos aqui (sem mexer no código)
_N = _CFG.get("nomes", {})
CARDS = {k: _N.get(k, v) for k, v in CARDS.items()}
MENSAL, DATA = _N.get("mensal", MENSAL), _N.get("data", DATA)
COLS_MENSAL.update(_CFG.get("cols_mensal", {}))
COL_DATA, COL_MATERIA = _CFG.get("col_data", COL_DATA), _CFG.get("col_materia", COL_MATERIA)
ENT_DATA = _CFG.get("ent_data", "tbl_fato_materias_R")


def alias_de(q, entidade):
    """Apelido da tabela na consulta (ex.: "t"); acrescenta a tabela se ela não estiver lá."""
    for f in q["From"]:
        if f.get("Entity") == entidade:
            return f["Name"]
    nome = "d" + str(len(q["From"]))
    q["From"].append({"Name": nome, "Entity": entidade, "Type": 0})
    return nome


def com_materia(nome, materia):
    t = copy.deepcopy(TPL[nome])
    q = t["query"]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"]
    for w in q.get("Where", []):
        cond = w["Condition"].get("In")
        if cond and cond["Expressions"][0].get("Column", {}).get("Property") == COL_MATERIA:
            cond["Values"] = [[{"Literal": {"Value": f"' {materia}'"}}]]
    return t


def consultar(t):
    corpo = {"version": t["version"], "queries": [t["query"]], "cancelQueries": [], "modelId": t["modelId"]}
    req = urllib.request.Request(URL, data=json.dumps(corpo).encode(), method="POST", headers={
        "Content-Type": "application/json;charset=UTF-8",
        "X-PowerBI-ResourceKey": CHAVE,
        "ActivityId": str(uuid.uuid4()), "RequestId": str(uuid.uuid4()),
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)
    data = res["results"][0]["result"]["data"]
    return data["descriptor"]["Select"], data["dsr"]


def linhas(select, dsr):
    """Decodifica o formato DSR do Power BI para uma lista de dicts {Name: valor}."""
    ds = dsr["DS"][0]
    dicts = ds.get("ValueDicts", {})
    cols = {s["Value"]: s["Name"] for s in select}
    out = []
    for ph in ds["PH"]:
        for chave, rows in ph.items():
            esquema, anterior = None, None
            for row in rows:
                if "S" in row:
                    esquema = row["S"]
                if "C" not in row:  # linha de medidas simples (cards)
                    out.append({cols.get(k, k): v for k, v in row.items() if k in cols})
                    continue
                rep = row.get("R", 0)
                nulos = row.get("Ø", 0)
                vals, it = [], iter(row["C"])
                for i, col in enumerate(esquema):
                    if rep >> i & 1:
                        v = anterior[i]
                    elif nulos >> i & 1:
                        v = None
                    else:
                        v = next(it)
                        if "DN" in col and isinstance(v, int):
                            v = dicts[col["DN"]][v]
                    vals.append(v)
                anterior = vals
                out.append({cols.get(c["N"], c["N"]): v for c, v in zip(esquema, vals)})
    return out


def num(v):
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return v


ESTOQUE = ["pendentes", "tempo_medio_pendente_dias", "tempo_medio_pendente_liquido_dias",
           "tempo_medio_primeira_baixa_dias"]


def card_ate(chave, materia, mes):
    """Valor de um card com a base filtrada até o mês (primeiro_dia <= mês): recalculado com a base atual."""
    nome = CARDS[chave]
    t = com_materia(nome, materia)
    q = t["query"]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"]
    q["Where"].append({"Condition": {"Comparison": {"ComparisonKind": 4,
        "Left": {"Column": {"Expression": {"SourceRef": {"Source": alias_de(q, ENT_DATA)}}, "Property": COL_DATA}},
        "Right": {"Literal": {"Value": f"datetime'{mes}-01T00:00:00'"}}}}})
    rs = linhas(*consultar(t))
    return num(rs[0].get(nome)) if rs else None


def historico(materia, meses):
    """Pendentes e tempos médios mês a mês (posição no fim de cada mês)."""
    from concurrent.futures import ThreadPoolExecutor
    tarefas = [(m, k) for m in meses for k in ESTOQUE]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda mk: card_ate(mk[1], materia, mk[0]), tarefas))
    out = {m: {} for m in meses}
    for (m, k), v in zip(tarefas, res):
        out[m][k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--materia", default="Saúde Suplementar")
    ap.add_argument("--historico", action="store_true",
                    help="inclui pendentes e tempos médios no fim de cada mês (mais lento)")
    a = ap.parse_args()

    cards = {}
    for chave, nome in CARDS.items():
        rs = linhas(*consultar(com_materia(nome, a.materia)))
        cards[chave] = num(rs[0].get(nome)) if rs else None

    rs = linhas(*consultar(com_materia(MENSAL, a.materia)))
    mensal = []
    for r in rs:
        d = r.get(COLS_MENSAL["mes"])
        if d is None:
            continue
        mes = dt.datetime.fromtimestamp(int(d) / 1000, dt.timezone.utc).strftime("%Y-%m")
        mensal.append({"mes": mes,
                       "casos_novos": num(r.get(COLS_MENSAL["casos_novos"])),
                       "baixados": num(r.get(COLS_MENSAL["baixados"]))})
    mensal.sort(key=lambda x: x["mes"])

    if a.historico:
        h = historico(a.materia, [r["mes"] for r in mensal])
        for r in mensal:
            r.update(h[r["mes"]])

    rs = linhas(*consultar(TPL[DATA]))
    texto = rs[0].get(DATA) if rs else None

    print(json.dumps({"materia": a.materia, "data_texto": texto, "cards": cards, "mensal": mensal},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erro": f"{type(e).__name__}: {e}"[:300]}))
        sys.exit(1)
