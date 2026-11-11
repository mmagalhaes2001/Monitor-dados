#!/usr/bin/env python3
"""Junta as coletas do dia ao histórico e lista o que mudou.

Histórico (planos/dados/historico.csv) é guardado por vigência: cada linha é uma "versão" de um plano numa praça,
com data de início, data de fim (vazia = ainda vale) e a última data em que foi visto.
Qualquer mudança em preço, preço "De", preço depois da promoção, condição, GB, detalhe dos GB, velocidade,
número de linhas, benefícios ou selo fecha a versão anterior e abre uma nova.
Um plano só é dado como "saiu" se a página daquela praça foi lida com sucesso e ele não estava lá.

Uso: python planos/historico.py  (lê planos/_coleta/*.json, grava historico.csv, coletas.csv e _coleta/mudancas.json)
"""
import csv, json, sys
from pathlib import Path

AQUI = Path(__file__).parent
DADOS = AQUI / "dados"
HIST = DADOS / "historico.csv"
LOG = DADOS / "coletas.csv"

CAMPOS_COMPARA = ["preco", "preco_de", "preco_depois", "condicao", "gb_total", "gb_detalhe",
                  "velocidade_mega", "linhas", "beneficios", "selo"]
NOMES = {"preco": "preço", "preco_de": "preço De", "preco_depois": "preço após promoção", "condicao": "condição",
         "gb_total": "GB", "gb_detalhe": "composição dos GB", "velocidade_mega": "velocidade (Mega)",
         "linhas": "linhas", "beneficios": "benefícios", "selo": "selo/promoção", "plano": "nome"}
COLS = ["operadora", "uf", "cidade", "segmento", "chave", "plano", "preco", "preco_de", "preco_depois",
        "condicao", "gb_total", "gb_detalhe", "velocidade_mega", "linhas", "rs_por_gb", "beneficios", "selo",
        "pagina", "url", "extra", "inicio", "fim", "visto_ultimo"]
COLS_LOG = ["data", "hora", "operadora", "uf", "cidade", "pagina", "ok", "n", "praca_tela", "erro"]


def norm(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v).strip()


def ler(caminho, cols):
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8", newline="") as f:
        return [{c: r.get(c, "") for c in cols} for r in csv.DictReader(f)]


def gravar(caminho, linhas, cols):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in linhas:
            w.writerow({c: r.get(c, "") for c in cols})


def ident(r):
    return (r["operadora"], r["uf"], r["chave"])


def atualizar():
    hist = ler(HIST, COLS)
    log = ler(LOG, COLS_LOG)
    primeira_vez = not hist
    mudancas = []
    resumo = {"operadoras": {}, "primeira_vez": primeira_vez}
    for arq in sorted((AQUI / "_coleta").glob("*.json")):
        if arq.name == "mudancas.json":
            continue
        c = json.loads(arq.read_text(encoding="utf-8"))
        op_nome = {"vivo": "Vivo", "claro": "Claro", "tim": "TIM"}[c["operadora"]]
        data = c["data"]
        ok_paginas = {(p["uf"], p["pagina"]) for p in c["paginas"] if p["ok"]}
        for p in c["paginas"]:
            log.append({"data": data, "hora": c["hora"], "operadora": op_nome, "uf": p["uf"], "cidade": p["cidade"],
                        "pagina": p["pagina"], "ok": "sim" if p["ok"] else "NÃO", "n": p["n"],
                        "praca_tela": p.get("praca_tela", ""), "erro": p.get("erro", "")[:200]})
        resumo["operadoras"][op_nome] = {"paginas_ok": len(ok_paginas), "paginas": len(c["paginas"]),
                                         "planos": len(c["planos"]),
                                         "falhas": [("%s %s" % (p["uf"], p["pagina"])) for p in c["paginas"] if not p["ok"]]}
        vigentes = {ident(r): r for r in hist if r["operadora"] == op_nome and not r["fim"]}
        vistos = set()
        for pl in c["planos"]:
            novo = {k: norm(pl.get(k)) for k in COLS if k in pl}
            novo["operadora"] = op_nome
            g = pl.get("gb_total")
            novo["rs_por_gb"] = norm(round(pl["preco"] / g, 2)) if pl.get("preco") and g else ""
            novo.update(inicio=data, fim="", visto_ultimo=data)
            k = ident(novo)
            if k in vistos:
                continue
            vistos.add(k)
            velho = vigentes.get(k)
            if velho is None:
                hist.append(novo)
                if not primeira_vez:
                    mudancas.append({"tipo": "novo", "operadora": op_nome, "uf": novo["uf"], "segmento": novo["segmento"],
                                     "plano": novo["plano"], "chave": novo["chave"], "data": data,
                                     "detalhe": "R$ %s | %s" % (novo["preco"], (novo["gb_total"] + " GB") if novo["gb_total"] else (novo["velocidade_mega"] + " Mega"))})
                continue
            difs = [(f, velho[f], novo[f]) for f in CAMPOS_COMPARA if velho[f] != novo[f]]
            if not difs:
                velho["visto_ultimo"] = data
                for f in ("plano", "url", "extra", "rs_por_gb", "cidade", "pagina"):
                    velho[f] = novo[f]
                continue
            velho["fim"] = velho["visto_ultimo"]
            hist.append(novo)
            mudancas.append({"tipo": "mudou", "operadora": op_nome, "uf": novo["uf"], "segmento": novo["segmento"],
                             "plano": novo["plano"], "chave": novo["chave"], "data": data,
                             "campos": [{"campo": NOMES[f], "antes": a, "depois": b} for f, a, b in difs]})
        for k, velho in vigentes.items():
            if k in vistos:
                continue
            if (velho["uf"], velho["pagina"]) not in ok_paginas:
                continue  # página não foi lida hoje: não dá para dizer que saiu
            velho["fim"] = velho["visto_ultimo"]
            mudancas.append({"tipo": "saiu", "operadora": op_nome, "uf": velho["uf"], "segmento": velho["segmento"],
                             "plano": velho["plano"], "chave": velho["chave"], "data": data,
                             "detalhe": "último preço R$ %s" % velho["preco"]})
    hist.sort(key=lambda r: (r["operadora"], r["segmento"], r["chave"], r["uf"], r["inicio"]))
    gravar(HIST, hist, COLS)
    gravar(LOG, log, COLS_LOG)
    resumo["mudancas"] = mudancas
    resumo["n_vigentes"] = sum(1 for r in hist if not r["fim"])
    (AQUI / "_coleta" / "mudancas.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    return resumo


def agrupar(mudancas):
    """Junta a mesma mudança em várias praças numa linha só: 'Vivo Pós com Amazon: preço 150 → 160 (27 praças)'."""
    grupos = {}
    for m in mudancas:
        if m["tipo"] == "mudou":
            sig = (m["tipo"], m["operadora"], m["plano"], json.dumps(m["campos"], ensure_ascii=False))
        else:
            sig = (m["tipo"], m["operadora"], m["plano"], m.get("detalhe", ""))
        grupos.setdefault(sig, {"m": m, "ufs": []})["ufs"].append(m["uf"])
    linhas = []
    for (tipo, op, plano, _), g in grupos.items():
        m, ufs = g["m"], sorted(set(g["ufs"]))
        if plano.lower().startswith(op.lower()):
            op_txt = ""
        else:
            op_txt = op + " "
        onde = "todas as 27 praças" if len(ufs) == 27 else ("%d praças" % len(ufs) if len(ufs) > 6 else ", ".join(ufs))
        if tipo == "mudou":
            txt = "; ".join("%s %s → %s" % (c["campo"], c["antes"] or "–", c["depois"] or "–") for c in m["campos"]
                            if c["campo"] not in ("benefícios",)) or "benefícios mudaram"
            if any(c["campo"] == "benefícios" for c in m["campos"]) and "benefícios mudaram" not in txt:
                txt += "; benefícios mudaram"
            linhas.append((op, "%s%s: %s (%s)" % (op_txt, plano, txt, onde)))
        elif tipo == "novo":
            linhas.append((op, "NOVO %s%s: %s (%s)" % (op_txt, plano, m["detalhe"], onde)))
        else:
            linhas.append((op, "SAIU %s%s: %s (%s)" % (op_txt, plano, m["detalhe"], onde)))
    return [l for _, l in sorted(linhas)]


if __name__ == "__main__":
    r = atualizar()
    print(json.dumps({k: v for k, v in r.items() if k != "mudancas"}, ensure_ascii=False, indent=1))
    for l in agrupar(r["mudancas"]):
        print(l)
