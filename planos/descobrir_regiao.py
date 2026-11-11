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
    for cid in ["sao-paulo-SP-11", "recife-PE-81", "porto-alegre-RS-51", "manaus-AM-92", "belo-horizonte-MG-31"]:
        ctx = novo_ctx(nav)
        ctx.add_cookies([{"name": "clr_hcms_city", "value": cid, "domain": ".claro.com.br", "path": "/"},
                         {"name": "clr_hcms_prehome", "value": "false", "domain": ".claro.com.br", "path": "/"}])
        page = ctx.new_page()
        r = {}
        for nome, url in [("fibra", "https://www.claro.com.br/internet"), ("controle", "https://www.claro.com.br/celular/controle"),
                          ("pos", "https://www.claro.com.br/celular/pos")]:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:
                pass
            time.sleep(4)
            t = page.inner_text("body")
            cab = re.search(r"Para você\s+Pequenas.*?\n(.+?)\n/ ?([A-Z]{2})", t, re.S)
            r[nome] = {"cidade_na_tela": (cab.group(1).strip() + "/" + cab.group(2)) if cab else None,
                       "precos": re.findall(r"R\$\s*\n?(\d{2,4})\s*\n?,(\d{2})", t)[:20]}
            (SAIDA / ("claro_%s_%s.txt" % (cid, nome))).write_text(t, encoding="utf-8")
        r["cookie_depois"] = {c["name"]: c["value"] for c in ctx.cookies() if c["name"] == "clr_hcms_city"}
        ctx.close()
        out[cid] = r
        print("claro", cid, json.dumps(r, ensure_ascii=False)[:900], flush=True)
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
        for nome, f in [("claro", claro), ("vivo", vivo)]:
            try:
                res[nome] = f(nav)
            except Exception:
                res[nome] = {"erro": traceback.format_exc()[-1500:]}
        nav.close()
    (SAIDA / "regiao.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
