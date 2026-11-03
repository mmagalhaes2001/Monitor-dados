"""Lê a tabela "Vendas do Mercado Farmacêutico" do BI do Sindusfarma (Power BI público).

Abre o relatório num Chromium headless e lê a tabela mês × ano em cada métrica
(Unidades é a padrão; as outras são lidas clicando nos botões do painel).
Imprime um JSON:
  {"ok": true, "metricas": {"Unidades": {"2026": {"janeiro": 522482429, ...}, ...}, ...}}
Em caso de falha: {"ok": false, "erro": "..."} (código de saída 1).
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

URL = (
    "https://app.powerbi.com/view?r=eyJrIjoiMGZlMGQ1M2EtYWI2NC00MmEzLTgwMzctMzQ4ODJmOTFhNzhhIiwid"
    "CI6ImQwOGY1MzU5LTdhOWEtNDQ0Yi04MzhjLTBkZDA0ZjI1ODI3YiJ9"
)
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
OUTRAS = ["Reais (R$) PPP", "Reais (R$) PMB", "Dólares ($) PPP", "Dólares ($) PMB"]


def num(s: str):
    s = re.sub(r"[^\d\-]", "", s or "")
    return int(s) if s not in ("", "-") else None


def parse(txt: str) -> dict:
    linhas = txt.split("\n")
    i = next(k for k, l in enumerate(linhas) if l.strip() == "Mês")
    anos = []
    k = i + 1
    while linhas[k].strip() != "janeiro":
        if re.fullmatch(r"\d{4}", linhas[k].strip()):
            anos.append(linhas[k].strip())
        k += 1
    tabela = {a: {} for a in anos}
    for mes in MESES:
        while linhas[k].strip() != mes:
            k += 1
        vals = linhas[k + 1:k + 1 + len(anos)]
        for a, v in zip(anos, vals):
            n = num(v)
            if n is not None:
                tabela[a][mes] = n
        k += 1 + len(anos)
    if not anos or not any(tabela.values()):
        raise ValueError("tabela vazia")
    return tabela


def esperar_tabela(page, anterior=None, tentativas=20):
    for _ in range(tentativas):
        page.wait_for_timeout(2000)
        try:
            t = parse(page.inner_text("body"))
            if t != anterior:
                return t
        except Exception:
            pass
    raise TimeoutError("tabela não carregou")


def ler() -> dict:
    metricas = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000})
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_selector("text=setembro", timeout=90_000)
            metricas["Unidades"] = esperar_tabela(page)
            ultima = metricas["Unidades"]
            for nome in OUTRAS:
                try:
                    page.get_by_text(nome, exact=False).first.click(timeout=20_000)
                    ultima = metricas[nome] = esperar_tabela(page, anterior=ultima, tentativas=10)
                except Exception as e:  # noqa: BLE001
                    print(f"aviso: não li {nome}: {e}"[:200], file=sys.stderr)
        finally:
            b.close()
    return {"ok": True, "metricas": metricas}


if __name__ == "__main__":
    try:
        r = ler()
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "erro": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["ok"] else 1)
