"""Lê as datas do painel de saúde do CNJ (Justiça em Números, Power BI público).

Abre o relatório num Chromium headless, espera o texto de data aparecer e imprime um JSON:
  {"ok": true, "atualizado": "29/09/2026", "dados_ate": "30/09/2026", "frase": "..."}
Em caso de falha: {"ok": false, "erro": "..."} (código de saída 1).
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

URL = (
    "https://app.powerbi.com/view?r=eyJrIjoiZGFiMTIxNzAtNWY4ZC00OWQzLWIwOGMtOTYwNDgyY2VhOTY5Iiwid"
    "CI6ImFkOTE5MGU2LWM0NWQtNDYwMC1iYzVjLWVjYTU1NGNjZjQ5NyIsImMiOjJ9&pageName=fb5a27b946fb01e949ce"
)
RE_ATUALIZADO = re.compile(r"Painel atualizado em\s*(\d{2}/\d{2}/\d{4})[^\n]*", re.I)
RE_DADOS_ATE = re.compile(r"Dados até\s*(\d{2}/\d{2}/\d{4})", re.I)


def texto_da_pagina(page) -> str:
    partes = []
    for f in page.frames:
        try:
            partes.append(f.evaluate("() => document.body ? document.body.innerText : ''"))
        except Exception:
            pass
    return "\n".join(partes)


def ler() -> dict:
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000})
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            # O Power BI carrega os visuais aos poucos: tenta por até ~90s
            txt = ""
            for _ in range(30):
                page.wait_for_timeout(3000)
                txt = texto_da_pagina(page)
                if RE_ATUALIZADO.search(txt):
                    break
        finally:
            b.close()
    m = RE_ATUALIZADO.search(txt)
    if not m:
        return {"ok": False, "erro": "texto 'Painel atualizado em' não encontrado"}
    d = RE_DADOS_ATE.search(txt)
    return {
        "ok": True,
        "atualizado": m.group(1),
        "dados_ate": d.group(1) if d else "",
        "frase": m.group(0).strip(),
    }


if __name__ == "__main__":
    try:
        r = ler()
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "erro": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["ok"] else 1)
