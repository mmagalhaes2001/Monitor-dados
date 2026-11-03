"""Compara a leitura atual do BI do Sindusfarma com a última guardada.

Uso: python sindusfarma/comparar.py leitura.json estado/sindusfarma.json
Imprime um JSON com:
  evento: "primeira" | "novo_mes" | "revisao" | "nada"
  titulo, mensagem: texto pronto para o push
O arquivo de estado é atualizado pelo workflow só quando evento != "nada".
"""
import json
import sys
from pathlib import Path

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
ABREV = {m: m[:3] for m in MESES}


def ultimo_mes(tab: dict):
    """(ano, mês) do último mês preenchido na tabela de uma métrica."""
    for ano in sorted(tab, reverse=True):
        meses = [m for m in MESES if m in tab[ano]]
        if meses:
            return ano, meses[-1]
    return None


def fmt(v):
    return f"{v:,.0f}".replace(",", ".")


def pct(a, b):
    return f"{(b / a - 1) * 100:+.1f}%".replace(".", ",") if a else "n/d"


def main(leitura_path, estado_path):
    atual = json.load(open(leitura_path))["metricas"]
    est_p = Path(estado_path)
    antes = json.load(open(est_p))["metricas"] if est_p.exists() else None
    u = atual["Unidades"]
    ano, mes = ultimo_mes(u)
    ref = f"{ABREV[mes]}/{ano[2:]}"

    if antes is None:
        print(json.dumps({"evento": "primeira", "ref": ref, "titulo": "", "mensagem": ""}, ensure_ascii=False))
        return

    novo = ultimo_mes(u) != ultimo_mes(antes.get("Unidades", {}))

    # Revisões: qualquer mês que já existia e mudou de valor, em qualquer métrica
    revs = []
    for met, tab in atual.items():
        for a, meses in tab.items():
            for m, v in meses.items():
                old = antes.get(met, {}).get(a, {}).get(m)
                if old is not None and old != v:
                    revs.append((met, a, m, old, v))

    linhas_rev = []
    if revs:
        por_met = {}
        for met, a, m, old, v in revs:
            por_met.setdefault(met, []).append(f"{ABREV[m]}/{a[2:]} {pct(old, v)}")
        for met, itens in por_met.items():
            mostra = ", ".join(itens[:6]) + (f" (+{len(itens) - 6})" if len(itens) > 6 else "")
            linhas_rev.append(f"{met}: {mostra}")

    if novo:
        v = u[ano][mes]
        anterior_ano = u.get(str(int(ano) - 1), {}).get(mes)
        msg = f"Unidades {ref}: {fmt(v)}"
        if anterior_ano:
            msg += f" ({pct(anterior_ano, v)} a/a)"
        rs = atual.get("Reais (R$) PPP", {}).get(ano, {}).get(mes)
        if rs:
            rs_ant = atual["Reais (R$) PPP"].get(str(int(ano) - 1), {}).get(mes)
            msg += f"\nR$ PPP {ref}: {rs / 1e9:.2f} bi".replace(".", ",")
            if rs_ant:
                msg += f" ({pct(rs_ant, rs)} a/a)"
        msg += "\nRevisões em meses anteriores: " + ("\n" + "\n".join(linhas_rev) if linhas_rev else "nenhuma")
        print(json.dumps({"evento": "novo_mes", "ref": ref,
                          "titulo": f"Sindusfarma: dados de {ref} saíram", "mensagem": msg}, ensure_ascii=False))
    elif revs:
        print(json.dumps({"evento": "revisao", "ref": ref,
                          "titulo": f"Sindusfarma: dados revisados (último mês {ref})",
                          "mensagem": "Meses anteriores mudaram:\n" + "\n".join(linhas_rev)}, ensure_ascii=False))
    else:
        print(json.dumps({"evento": "nada", "ref": ref, "titulo": "", "mensagem": ""}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
