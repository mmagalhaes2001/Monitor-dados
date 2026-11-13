"""Compara uma leitura nova do painel de saúde do CNJ com a última foto guardada.

Uso: python cnj/saude_compara.py nova.json pasta_de_fotos/
Imprime JSON: {"evento": "primeira"|"atualizacao"|"revisao"|"nada", "titulo": ..., "mensagem": ...,
               "revisoes": [...]}
 - atualizacao: mudou a frase "Painel atualizado em ...".
 - revisao: mesma frase, mas algum número mudou (cards ou série mensal).
As revisões listam os meses cujo valor mudou em relação à foto anterior.
"""
import json
import pathlib
import re
import sys

CAMPOS_MES = ["casos_novos", "baixados", "pendentes", "tempo_medio_pendente_dias",
              "tempo_medio_pendente_liquido_dias", "tempo_medio_primeira_baixa_dias"]
ROTULO = {"casos_novos": "Casos novos", "baixados": "Baixados", "pendentes": "Pendentes",
          "tempo_medio_pendente_dias": "T. médio pendente",
          "tempo_medio_pendente_liquido_dias": "T. médio pend. líquido",
          "tempo_medio_primeira_baixa_dias": "T. médio 1ª baixa"}


def ultima_foto(pasta):
    fotos = sorted(pathlib.Path(pasta).glob("*.json"))
    return (json.loads(fotos[-1].read_text()), fotos[-1].name) if fotos else (None, None)


def data_painel(texto):
    m = re.search(r"atualizado em (\d{2}/\d{2}/\d{4})", texto or "")
    return m.group(1) if m else "?"


def fmt(v):
    if isinstance(v, float):
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:,}".replace(",", ".") if isinstance(v, int) else str(v)


def pct(a, b):
    if not a or a is None or b is None:
        return "n/d"
    return f"{(b / a - 1) * 100:+.1f}%".replace(".", ",")


def revisoes(antes, nova):
    """Meses que já existiam na foto anterior e mudaram de valor (tempos: só se mudar >= 0,5 dia)."""
    a = {r["mes"]: r for r in antes.get("mensal", [])}
    out = []
    for r in nova.get("mensal", []):
        old = a.get(r["mes"])
        if not old:
            continue
        for c in CAMPOS_MES:
            x, y = old.get(c), r.get(c)
            if x is None or y is None:
                continue
            tol = 0.5 if "tempo" in c else 0
            if abs(y - x) > tol:
                out.append({"mes": r["mes"], "campo": c, "antes": x, "depois": y})
    return out


def resumo_revisoes(revs, limite=8):
    if not revs:
        return "nenhuma"
    linhas = []
    for c in CAMPOS_MES:
        rs = [r for r in revs if r["campo"] == c]
        if not rs:
            continue
        itens = [f"{r['mes'][5:]}/{r['mes'][2:4]} {pct(r['antes'], r['depois'])}" for r in rs[-limite:]]
        extra = f" (+{len(rs) - limite} meses)" if len(rs) > limite else ""
        linhas.append(f"{ROTULO[c]}: " + ", ".join(itens) + extra)
    return "\n".join(linhas)


def main(nova_path, pasta):
    nova = json.loads(pathlib.Path(nova_path).read_text())
    antes, nome = ultima_foto(pasta)
    if antes is None:
        print(json.dumps({"evento": "primeira", "titulo": "", "mensagem": "", "revisoes": []}))
        return
    revs = revisoes(antes, nova)
    cards_mudaram = any(nova["cards"].get(k) != antes["cards"].get(k) for k in nova["cards"])
    nova_data, velha_data = data_painel(nova.get("data_texto")), data_painel(antes.get("data_texto"))
    c = nova["cards"]
    ult = nova["mensal"][-1] if nova.get("mensal") else {}
    corpo = (f"Saúde Suplementar (dados até {ult.get('mes', '?')[5:]}/{ult.get('mes', '?')[2:4]}):\n"
             f"Pendentes: {fmt(c.get('pendentes'))} | T. médio pendente: {fmt(c.get('tempo_medio_pendente_dias'))} dias\n"
             f"Baixados no ano: {fmt(c.get('baixados_no_ano'))} | T. médio 1ª baixa: {fmt(c.get('tempo_medio_primeira_baixa_dias'))} dias\n"
             f"Casos novos no ano: {fmt(c.get('casos_novos_no_ano'))}")
    if nova_data != velha_data:
        ev, tit = "atualizacao", f"CNJ saúde: painel atualizado em {nova_data}"
        msg = corpo + "\nRevisões em meses anteriores:\n" + resumo_revisoes(revs)
    elif revs or cards_mudaram:
        ev, tit = "revisao", f"CNJ saúde: números revisados (painel ainda de {nova_data})"
        msg = "Números mudaram sem mudar a data do painel.\n" + resumo_revisoes(revs) + "\n" + corpo
    else:
        ev, tit, msg = "nada", "", ""
    print(json.dumps({"evento": ev, "titulo": tit, "mensagem": msg, "revisoes": revs,
                      "foto_anterior": nome}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
