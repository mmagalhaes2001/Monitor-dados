#!/usr/bin/env python3
"""Classificação dos planos em TIPO padronizado e LINHA comercial de cada operadora.

TIPO (igual para as três operadoras, para comparar): Pré | Controle | Pós | Família | Lite/Anual | Flex | Fibra
LINHA (o nome que a operadora usa): ex. "TIM Black" x "TIM Black Express", "Claro Pré (Prezão)", "Vivo Lite".
Para incluir um nome novo: uma linha em REGRAS (operadora, padrão no nome do plano, tipo, linha). A primeira que casar vale.
"""
import re

TIPOS = ["Pré", "Controle", "Lite/Anual", "Flex", "Pós", "Família", "Fibra", "FWA (5G residencial)"]

# (operadora, regex no nome do plano ou "" para qualquer, página de origem ou None, tipo, linha)
REGRAS = [
    # TIM
    ("TIM", r"ultrafibra|ultracombo", None, "Fibra", "TIM Ultrafibra"),
    ("TIM", r"black.*fam[ií]lia|fam[ií]lia", None, "Família", "TIM Black Família"),
    ("TIM", r"black.*express", None, "Pós", "TIM Black Express (cartão)"),
    ("TIM", r"black", None, "Pós", "TIM Black"),
    ("TIM", r"controle fit.*anual", None, "Lite/Anual", "TIM Controle Fit Anual"),
    ("TIM", r"controle fit", None, "Controle", "TIM Controle Fit"),
    ("TIM", r"controle.*express", None, "Controle", "TIM Controle Express (cartão)"),
    ("TIM", r"controle", None, "Controle", "TIM Controle"),
    ("TIM", r"beta", None, "Pré", "TIM Beta / BetaCreator"),
    ("TIM", r"pr[ée]|xip", None, "Pré", "TIM Pré XIP"),
    # Vivo
    ("Vivo", r"box 5g|fwa", None, "FWA (5G residencial)", "Vivo Box 5G"),
    ("Vivo", r"fibra.*tv|tv por assinatura", None, "Fibra", "Vivo Fibra + TV"),
    ("Vivo", r"", "fibra", "Fibra", "Vivo Fibra"),
    ("Vivo", r"fam[ií]lia", None, "Família", "Vivo Família"),
    ("Vivo", r"", "lite", "Lite/Anual", "Vivo Lite (antigo Vivo Easy Lite)"),
    ("Vivo", r"easy", None, "Controle", "Vivo Easy"),
    ("Vivo", r"", "controle", "Controle", "Vivo Controle"),
    ("Vivo", r"", "pre", "Pré", "Vivo Pré"),
    ("Vivo", r"", "pos", "Pós", "Vivo Pós"),
    # Claro
    ("Claro", r"", "fibra", "Fibra", "Claro Fibra"),
    ("Claro", r"", "flex", "Flex", "Claro Flex"),
    ("Claro", r"", "pre", "Pré", "Claro Pré (Prezão)"),
    ("Claro", r"", "controle", "Controle", "Claro Controle"),
    ("Claro", r"fam[ií]lia|dependente", "pos", "Família", "Claro Pós Família"),
    ("Claro", r"", "pos", "Pós", "Claro Pós"),
]

SEG = {"Pré": "pre", "Controle": "controle", "Pós": "pos", "Família": "familia", "Lite/Anual": "lite",
       "Flex": "flex", "Fibra": "fibra", "FWA (5G residencial)": "fwa"}


def classificar(operadora, pagina, nome, linhas=None):
    texto = nome or ""
    for op, rx, pag, tipo, linha in REGRAS:
        if op != operadora:
            continue
        if pag and pag != pagina:
            continue
        if rx and not re.search(rx, texto, re.I):
            continue
        if tipo == "Pós" and linhas and int(linhas) > 1:
            tipo = "Família"
        return tipo, linha
    return {"pos": "Pós", "familia": "Família", "controle": "Controle", "pre": "Pré", "lite": "Lite/Anual",
            "flex": "Flex", "fibra": "Fibra"}.get(pagina, pagina), "%s (outros)" % operadora
