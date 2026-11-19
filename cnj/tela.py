"""Confere se o painel do CNJ MOSTRA os números de Saúde Suplementar na tela (não só na base).

Abre o painel num navegador headless, clica no botão "Saúde Suplementar" e lê o card de pendentes.
Imprime JSON: {"visivel": bool, "pendentes": "441,400" | null, "titulo": "Pendentes em ..."}
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

URL = ("https://app.powerbi.com/view?r=eyJrIjoiZGFiMTIxNzAtNWY4ZC00OWQzLWIwOGMtOTYwNDgyY2VhOTY5Iiwid"
       "CI6ImFkOTE5MGU2LWM0NWQtNDYwMC1iYzVjLWVjYTU1NGNjZjQ5NyIsImMiOjJ9&pageName=fb5a27b946fb01e949ce")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        pg.wait_for_selector("text=/atualizado em/", state="attached", timeout=90_000)
        pg.wait_for_timeout(8_000)
        el = pg.locator("text=/Sa[úu]de Suplementar/ >> visible=true").first
        bb = el.bounding_box(timeout=30_000)
        pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        pg.wait_for_timeout(15_000)
        txt = pg.inner_text("body")
        b.close()
    m = re.search(r"(Pendentes em[^\n]*)\n+\s*([^\n]+)", txt)
    titulo, valor = (m.group(1).strip(), m.group(2).strip()) if m else (None, None)
    visivel = bool(valor and re.fullmatch(r"[\d.,]+", valor))
    print(json.dumps({"visivel": visivel, "pendentes": valor, "titulo": titulo}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"visivel": False, "erro": f"{type(e).__name__}: {e}"[:200]}))
        sys.exit(1)
