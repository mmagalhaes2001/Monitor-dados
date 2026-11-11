#!/usr/bin/env python3
"""Teste de descoberta 3: troca de praça na Claro (cookie) e na Vivo (seletor do topo).
Saída em planos/_descoberta/regiao/.
"""
import json, re, time, traceback, base64
from pathlib import Path
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SAIDA = Path(__file__).parent / "_descoberta" / "regiao"
VIVO_POS = "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-pos-pago"


def novo_ctx(nav):
    return nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
                           viewport={"width": 1366, "height": 900})


def claro(nav):
    out = {}
    for cidade, uf in [("Recife", "PE"), ("Porto Alegre", "RS")]:
        ctx = novo_ctx(nav)
        page = ctx.new_page()
        r = {"reqs": []}
        try:
            page.goto("https://www.claro.com.br/internet", wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        try:
            time.sleep(3)
            page.on("request", lambda q: r["reqs"].append(q.method + " " + q.url[:250])
                    if q.resource_type in ("xhr", "fetch", "document") and "claro" in q.url else None)
            page.locator(":visible:text-is('Alterar cidade')").first.click(timeout=15000)
            time.sleep(2)
            caixa = page.locator("input:visible").first
            r["input"] = caixa.evaluate("e => e.outerHTML.slice(0,300)")
            caixa.click(); caixa.type(cidade, delay=150); time.sleep(4)
            opc = page.locator(":visible:text-matches('^%s', 'i')" % cidade).all()
            r["opcoes"] = [o.evaluate("e => e.tagName + '.' + e.className.toString().slice(0,60) + ' :: ' + e.innerText.slice(0,60)") for o in opc[:10]]
            alvo = [o for o in opc if uf in o.inner_text() and o.evaluate("e => e.tagName") != "INPUT"]
            (alvo or opc)[-1].click(timeout=8000)
            time.sleep(2)
            for txt in ["Confirmar", "Continuar", "Salvar", "Ver ofertas"]:
                b = page.locator("button:visible:has-text('%s')" % txt)
                if b.count():
                    b.first.click(timeout=5000); break
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            time.sleep(5)
            t = page.inner_text("body")
            r["url"] = page.url
            r["cabecalho"] = t[:400]
            r["precos"] = re.findall(r"R\$\s*\n?(\d{2,4})\s*\n?,(\d{2})", t)[:20]
            r["cookies"] = {c["name"]: c["value"][:150] for c in ctx.cookies() if c["name"].startswith("clr_")}
            r["storage"] = page.evaluate("() => Object.fromEntries(Object.entries(localStorage).filter(([k]) => /cit|uf|ddd|loc|reg/i.test(k)).map(([k,v]) => [k, v.slice(0,200)]))")
            page.screenshot(path=str(SAIDA / ("claro_%s.png" % uf)))
        except Exception:
            r["erro"] = traceback.format_exc()[-900:]
            page.screenshot(path=str(SAIDA / ("claro_%s_erro.png" % uf)))
        ctx.close()
        out[cidade] = r
        print("claro", cidade, json.dumps(r, ensure_ascii=False)[:2500], flush=True)
    return out


def vivo(nav):
    out = {}
    for cidade in ["Recife", "Porto Alegre"]:
        r = {"reqs": []}
        ctx = novo_ctx(nav)
        page = ctx.new_page()
        try:
            page.goto(VIVO_POS, wait_until="domcontentloaded", timeout=60000)
            time.sleep(6)
            page.on("request", lambda q: r["reqs"].append(q.method + " " + q.url[:300])
                    if q.resource_type in ("xhr", "fetch", "document") else None)
            page.locator("button.btn-change:visible, a.change-compass:visible").first.click(timeout=15000)
            time.sleep(1.5)
            caixa = page.locator("input:visible[placeholder*='cidade']").first
            caixa.click()
            caixa.type(cidade, delay=150)
            time.sleep(4)
            r["popup_html"] = page.evaluate("""() => { const i = [...document.querySelectorAll("input[placeholder*='cidade']")].find(e => e.offsetParent);
                                                     let p = i; for (let k=0;k<5 && p;k++) p = p.parentElement; return p ? p.outerHTML.slice(0, 6000) : null; }""")
            opc = page.locator(":visible:text-matches('%s', 'i')" % cidade).all()
            r["opcoes"] = [o.evaluate("e => e.tagName + '.' + e.className + ' :: ' + e.innerText.slice(0,80)") for o in opc[:10]]
            alvo = [o for o in opc if o.evaluate("e => e.tagName") in ("LI", "A", "BUTTON", "SPAN", "P", "DIV") and
                    o.evaluate("e => e.tagName") != "INPUT"]
            if alvo:
                alvo[-1].click(timeout=8000)
            time.sleep(1.5)
            page.locator("button:visible:has-text('Confirmar')").first.click(timeout=8000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            time.sleep(6)
            r["url_depois"] = page.url
            r["cabecalho"] = page.locator(":text('Ofertas para')").first.evaluate("e => e.parentElement.innerText")
            r["cards"] = page.eval_on_selector_all(".unique-card", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').slice(0,200))")
            r["cookies"] = {c["name"]: c["value"][:200] for c in ctx.cookies() if "vivo" in c["name"].lower()}
            page.screenshot(path=str(SAIDA / ("vivo_%s.png" % cidade.replace(" ", "_"))))
        except Exception:
            r["erro"] = traceback.format_exc()[-900:]
            try:
                page.screenshot(path=str(SAIDA / ("vivo_%s_erro.png" % cidade.replace(" ", "_"))))
            except Exception:
                pass
        ctx.close()
        out[cidade] = r
        print("vivo", cidade, json.dumps({k: r.get(k) for k in ("url_depois", "cabecalho", "cookies", "opcoes", "erro")}, ensure_ascii=False)[:1500], flush=True)
        print("vivo", cidade, "cards", json.dumps(r.get("cards", [])[:4], ensure_ascii=False)[:800], flush=True)
    return out


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    res = {}
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for nome, f in [("claro", claro)]:
            try:
                res[nome] = f(nav)
            except Exception:
                res[nome] = {"erro": traceback.format_exc()[-1500:]}
        nav.close()
    (SAIDA / "regiao.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
