#!/usr/bin/env python3
"""Lê um formulário "Valores Mobiliários Negociados e Detidos" (art. 11 da Res. CVM 44) gerado
pelo ENET da CVM e devolve as linhas estruturadas.

Uso: python cvm44/ler_pdf.py arquivo.pdf  → imprime JSON
Cada página é um órgão. Saída: {"empresa", "tipo_form" (Consolidado/Individual), "ref" (MM/AAAA),
"paginas": [{"orgao", "sem_movimentacao", "saldo_inicial": [...], "movimentacoes": [...], "saldo_final": [...]}]}
"""
import json, re, sys
import pdfplumber

ORGAOS = ["Controlador", "Conselho Administração", "Diretoria", "Conselho Fiscal", "Órgãos Técnicos ou Consultivos"]


def num(s):
    """'1.081.599,00' → 1081599.0 ; '' → None"""
    if s is None: return None
    s = str(s).strip().replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return None


def celula(c):
    return re.sub(r"\s+", " ", (c or "")).strip()


def ler(caminho):
    out = {"empresa": "", "tipo_form": "", "ref": "", "paginas": []}
    with pdfplumber.open(caminho) as pdf:
        for n, pg in enumerate(pdf.pages, 1):
            txt = pg.extract_text() or ""
            if "FORMULÁRIO" not in txt:
                continue
            m = re.search(r"FORMULÁRIO (\w+)", txt)
            if m and not out["tipo_form"]: out["tipo_form"] = m.group(1).capitalize()
            m = re.search(r"Em (\d{2}/\d{4})", txt)
            if m and not out["ref"]: out["ref"] = m.group(1)
            m = re.search(r"Denominação da Companhia: (.+)", txt)
            if m and not out["empresa"]: out["empresa"] = m.group(1).strip()
            pagina = {"pagina": n, "orgao": "", "sem_movimentacao": "(X) não foram realizadas" in txt,
                      "saldo_inicial": [], "movimentacoes": [], "saldo_final": []}
            tabelas = pg.extract_tables()
            if not tabelas:
                continue
            secao = None
            for linha in tabelas[0]:
                cels = [celula(c) for c in linha]
                juntas = " ".join(cels)
                if cels[0].startswith("Grupo e Pessoas Ligadas"):
                    # órgão marcado com ( X ) — pode estar na mesma célula que o nome ou quebrado em linha
                    for c in cels:
                        if re.search(r"\(\s*X\s*\)", c, re.I):
                            nome = re.sub(r"\(\s*X\s*\)", "", c, flags=re.I).strip()
                            for o in ORGAOS:
                                if o in nome: pagina["orgao"] = o
                    continue
                if juntas.startswith("Saldo Inicial"): secao = "saldo_inicial"; continue
                if juntas.startswith("Movimentações no Mês"): secao = "movimentacoes"; continue
                if juntas.startswith("Saldo Final"): secao = "saldo_final"; continue
                if cels[0].startswith("Valor Mobiliário"): continue   # cabeçalho
                if not secao or not any(cels):
                    continue
                vals = [c for c in cels if c]
                if secao in ("saldo_inicial", "saldo_final") and len(vals) >= 3:
                    pagina[secao].append({"ativo": vals[0], "caracteristica": vals[1], "quantidade": num(vals[-1])})
                elif secao == "movimentacoes" and len(cels) >= 8:
                    pagina["movimentacoes"].append({
                        "ativo": cels[0], "caracteristica": cels[1], "intermediario": cels[2], "operacao": cels[3],
                        "dia": cels[4], "quantidade": num(cels[5]), "preco": num(cels[6]), "volume": num(cels[7])})
            if not pagina["orgao"] and out["tipo_form"] == "Individual":
                pagina["orgao"] = "Companhia (cia, controladas e coligadas)"
            out["paginas"].append(pagina)
    return out


if __name__ == "__main__":
    print(json.dumps(ler(sys.argv[1]), ensure_ascii=False, indent=1))
