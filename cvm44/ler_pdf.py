#!/usr/bin/env python3
"""Lê um formulário "Valores Mobiliários Negociados e Detidos" (art. 11 da Res. CVM 44) gerado
pelo ENET da CVM e devolve as linhas estruturadas.

Uso: python cvm44/ler_pdf.py arquivo.pdf  → imprime JSON
Cada página é um órgão. Saída: {"empresa", "tipo_form" (Consolidado/Individual), "ref" (MM/AAAA),
"paginas": [{"orgao", "sem_movimentacao", "saldo_inicial": [...], "movimentacoes": [...], "saldo_final": [...]}]}

Como lê: pela posição (x) das palavras na página, usando o cabeçalho da tabela de movimentações
(Intermediário | Operação | Dia | Quantidade | Preço | Volume) para delimitar as colunas. Isso aguenta
intermediário com nome quebrado em várias linhas e variações de layout entre empresas.
"""
import json, re, sys
import pdfplumber

ORGAOS = ["Controlador", "Conselho Administração", "Diretoria", "Conselho Fiscal", "Órgãos Técnicos ou Consultivos"]
COLS = ["Intermediário", "Operação", "Dia", "Quantidade", "Preço", "Volume"]
RE_NUM = re.compile(r"^-?[\d.]+(,\d+)?$")


def num(s):
    if s is None: return None
    s = str(s).strip().replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None


def linhas_da_pagina(pg):
    """Agrupa palavras por linha (top arredondado), ordenadas por x."""
    ws = pg.extract_words(x_tolerance=1.5)
    por_top = {}
    for w in ws:
        por_top.setdefault(round(w["top"] / 3) * 3, []).append(w)
    return [(top, sorted(v, key=lambda w: w["x0"])) for top, v in sorted(por_top.items())]


def texto(linha):
    return " ".join(w["text"] for w in linha)


def ler_pagina(pg, secao=None, limites=None):
    txt = pg.extract_text() or ""
    pagina = {"orgao": "", "sem_movimentacao": "(X) não foram realizadas" in txt.replace("( X )", "(X)"),
              "saldo_inicial": [], "movimentacoes": [], "saldo_final": []}
    # órgão: no cabeçalho (antes de "Saldo Inicial") há um "( X )" marcando o grupo. Se vier seguido do nome,
    # é esse; se o X estiver solto (fica acima/abaixo da linha "Grupo e Pessoas Ligadas"), é a Diretoria.
    cab = re.sub(r"\(\s*X\s*\)", "(X)", txt.split("Saldo Inicial")[0])
    for o in ORGAOS:
        if re.search(r"\(X\)\s*" + re.escape(o).replace("\\ ", r"\s*"), cab):
            pagina["orgao"] = o
    if not pagina["orgao"] and "(X)" in cab.split("não foram realizadas")[-1].split("Denominação")[-1]:
        pagina["orgao"] = "Diretoria"
    linhas = linhas_da_pagina(pg)
    conts = []
    for top, linha in linhas:
        t = texto(linha)
        if t.startswith("Saldo Inicial"): secao = "saldo_inicial"; limites = None; continue
        if t.startswith("Movimentações no Mês"): secao = "movimentacoes"; limites = None; continue
        if t.startswith("Saldo Final"): secao = "saldo_final"; limites = None; continue
        if secao == "movimentacoes" and "Operação" in t and "Dia" in t:
            xs = {w["text"]: w["x0"] for w in linha if w["text"] in COLS}
            if all(c in xs for c in COLS):
                # colunas numéricas são alinhadas à direita: classifica pela borda direita (x1) da palavra
                # contra a borda esquerda (x0) de cada cabeçalho
                limites = [xs[c] - 3 for c in COLS]
            continue
        if secao in ("saldo_inicial", "saldo_final"):
            if t.startswith("Valor") or t.startswith("Mobiliário") or not linha: continue
            ult = linha[-1]["text"]
            if RE_NUM.match(ult) and len(linha) >= 2:
                pagina[secao].append({"ativo": linha[0]["text"], "caracteristica": " ".join(w["text"] for w in linha[1:-1]),
                                      "quantidade": num(ult)})
        elif secao == "movimentacoes" and limites:
            cols = {c: [] for c in ["Ativo", "Característica"] + COLS}
            for w in linha:
                if w["x1"] < limites[0]:
                    cols["Ativo" if w["x0"] < 115 else "Característica"].append(w["text"])
                else:
                    i = sum(1 for l in limites if w["x1"] >= l) - 1
                    cols[COLS[i]].append(w["text"])
            qtd, preco, vol = " ".join(cols["Quantidade"]), " ".join(cols["Preço"]), " ".join(cols["Volume"])
            dia = " ".join(cols["Dia"])
            if RE_NUM.match(qtd.replace(" ", "")) and (RE_NUM.match(preco) or RE_NUM.match(vol)):
                pagina["movimentacoes"].append({
                    "ativo": " ".join(cols["Ativo"]), "caracteristica": " ".join(cols["Característica"]),
                    "intermediario": " ".join(cols["Intermediário"]), "operacao": " ".join(cols["Operação"]),
                    "dia": dia, "quantidade": num(qtd.replace(" ", "")), "preco": num(preco), "volume": num(vol),
                    "_top": top})
            elif (cols["Intermediário"] or cols["Operação"]) and not qtd:
                # pedaço de nome de intermediário/operação quebrado em várias linhas: guarda para colar depois
                conts.append((top, cols["Intermediário"], cols["Operação"]))
    # cola cada pedaço na linha de movimentação mais próxima (acima ou abaixo), mantendo a ordem vertical
    for top, inter, oper in conts:
        if not pagina["movimentacoes"]: break
        alvo = min(pagina["movimentacoes"], key=lambda m: abs(m["_top"] - top))
        alvo.setdefault("_pedacos", []).append((top, " ".join(inter), " ".join(oper)))
    for m in pagina["movimentacoes"]:
        for i, campo in ((1, "intermediario"), (2, "operacao")):
            antes = [pd[i] for pd in sorted(m.get("_pedacos", [])) if pd[0] < m["_top"] and pd[i]]
            depois = [pd[i] for pd in sorted(m.get("_pedacos", [])) if pd[0] > m["_top"] and pd[i]]
            m[campo] = " ".join(antes + [m[campo]] + depois).strip()
        m.pop("_pedacos", None)
    for m in pagina["movimentacoes"]:
        m.pop("_top", None)
    pagina["_secao"], pagina["_limites"] = secao, limites
    return pagina


def ler(caminho):
    out = {"empresa": "", "tipo_form": "", "ref": "", "paginas": []}
    with pdfplumber.open(caminho) as pdf:
        for n, pg in enumerate(pdf.pages, 1):
            txt = pg.extract_text() or ""
            if "FORMULÁRIO" not in txt and "Saldo Inicial" not in txt:
                # página de continuação sem cabeçalho (só o resto das movimentações / Saldo Final)
                if out["paginas"]:
                    ant = out["paginas"][-1]
                    cont = ler_pagina(pg, ant.get("_secao"), ant.get("_limites"))
                    out["paginas"][-1]["movimentacoes"] += cont["movimentacoes"]
                    if cont["saldo_final"]: out["paginas"][-1]["saldo_final"] = cont["saldo_final"]
                    out["paginas"][-1]["_secao"], out["paginas"][-1]["_limites"] = cont["_secao"], cont["_limites"]
                continue
            m = re.search(r"FORMULÁRIO (\w+)", txt)
            if m and not out["tipo_form"]: out["tipo_form"] = m.group(1).capitalize()
            m = re.search(r"Em (\d{2}/\d{4})", txt)
            if m and not out["ref"]: out["ref"] = m.group(1)
            m = re.search(r"Denominação da Companhia: (.+)", txt)
            if m and not out["empresa"]: out["empresa"] = m.group(1).strip()
            pagina = ler_pagina(pg)
            pagina["pagina"] = n
            if out["tipo_form"] == "Individual":
                # no formulário individual cada página é uma entidade (tesouraria, controlada, coligada)
                pagina["orgao"] = "Companhia (cia, controladas e coligadas)"
                mn = re.search(r"Nome:\s*(.+?)\s*CPF/CNPJ", txt); mq = re.search(r"Qualificação:\s*(.*)", txt)
                pagina["entidade"] = ((mn.group(1).strip() if mn else "") + (" - " + mq.group(1).strip() if mq and mq.group(1).strip() else "")).strip()
            ant = out["paginas"][-1] if out["paginas"] else None
            # continuação do mesmo órgão (lista longa de movimentações quebrada em páginas)
            if ant and not pagina["saldo_inicial"] and not ant["saldo_final"] and (pagina["orgao"] == ant["orgao"] or not pagina["orgao"]):
                ant["movimentacoes"] += pagina["movimentacoes"]; ant["saldo_final"] = pagina["saldo_final"]
                continue
            out["paginas"].append(pagina)
    return out


if __name__ == "__main__":
    print(json.dumps(ler(sys.argv[1]), ensure_ascii=False, indent=1))
