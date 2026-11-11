#!/usr/bin/env python3
"""Teste de descoberta: abre as páginas de planos de Vivo, Claro e TIM com navegador
(Playwright/Chromium) e guarda tudo para análise: status, HTML final, print, cookies,
links da página e TODAS as respostas JSON que a página buscou (é onde costuma estar o preço).

Saída em planos/_descoberta/<alvo>/ (vira artefato do GitHub Actions, não é versionada).
"""
import json, os, re, sys, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

ALVOS = {
    "vivo_pos": "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-pos-pago",
    "vivo_controle": "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-controle",
    "vivo_pre": "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/pre-pago/vivo-pre",
    "vivo_fibra": "https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/internet",
    "claro_pos": "https://www.claro.com.br/celular/pos",
    "claro_controle": "https://www.claro.com.br/celular/controle",
    "claro_pre": "https://www.claro.com.br/celular/pre-pago",
    "claro_fibra": "https://www.claro.com.br/internet",
    "tim_sp": "https://www.tim.com.br/sp/para-voce/planos",
    "tim_rj": "https://www.tim.com.br/rj/para-voce/planos",
    "tim_black": "https://www.tim.com.br/sp/para-voce/planos/pos-pago/tim-black",
    "tim_controle": "https://www.tim.com.br/sp/para-voce/planos/controle",
    "tim_fibra": "https://www.tim.com.br/sp/para-voce/internet-residencial/tim-ultrafibra",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SAIDA = Path(__file__).parent / "_descoberta"


def coletar(ctx, nome, url):
    pasta = SAIDA / nome
    (pasta / "net").mkdir(parents=True, exist_ok=True)
    resumo = {"url": url, "respostas": []}
    page = ctx.new_page()
    n = [0]

    def ao_responder(r):
        try:
            ct = r.headers.get("content-type", "")
            item = {"url": r.url[:400], "status": r.status, "ct": ct[:60]}
            if "json" in ct and r.request.method in ("GET", "POST"):
                corpo = r.body()
                item["bytes"] = len(corpo)
                if len(corpo) > 200:
                    n[0] += 1
                    arq = "%03d.json" % n[0]
                    (pasta / "net" / arq).write_bytes(corpo)
                    item["arquivo"] = arq
                    item["tem_preco"] = bool(re.search(rb'(preco|price|valor|amount)', corpo, re.I))
            resumo["respostas"].append(item)
        except Exception as e:
            pass

    page.on("response", ao_responder)
    try:
        r = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        resumo["status"] = r.status if r else None
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        # rola a página para carregar o que é preguiçoso
        for _ in range(8):
            page.mouse.wheel(0, 1500)
            time.sleep(0.7)
        time.sleep(3)
        resumo["url_final"] = page.url
        resumo["titulo"] = page.title()
        html = page.content()
        (pasta / "pagina.html").write_text(html, encoding="utf-8")
        texto = page.inner_text("body")
        (pasta / "texto.txt").write_text(texto, encoding="utf-8")
        resumo["precos_no_texto"] = sorted(set(re.findall(r"R\$\s*\d{1,4}(?:,\d{2})?", texto)))[:60]
        resumo["links"] = sorted(set(
            a for a in page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            if re.search(r"plano|pos|controle|pre-pago|internet|fibra|black", a, re.I)))[:200]
        resumo["cookies"] = [{"nome": c["name"], "valor": c["value"][:120], "dominio": c["domain"]}
                             for c in ctx.cookies()]
        page.screenshot(path=str(pasta / "print.png"), full_page=True)
    except Exception as e:
        resumo["erro"] = traceback.format_exc()[-800:]
    finally:
        page.close()
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    return resumo


def main():
    alvos = sys.argv[1:] or list(ALVOS)
    SAIDA.mkdir(exist_ok=True)
    geral = {}
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for nome in alvos:
            ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1366, "height": 900})
            r = coletar(ctx, nome, ALVOS[nome])
            ctx.close()
            geral[nome] = {k: r.get(k) for k in ("status", "url_final", "titulo", "erro")}
            geral[nome]["n_json"] = sum(1 for x in r["respostas"] if x.get("arquivo"))
            geral[nome]["n_precos"] = len(r.get("precos_no_texto") or [])
            print(nome, json.dumps(geral[nome], ensure_ascii=False)[:300], flush=True)
        nav.close()
    (SAIDA / "geral.json").write_text(json.dumps(geral, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
