#!/usr/bin/env python3
"""Teste de descoberta 2: como cada operadora troca de praça.

- Vivo: troca a cidade pelo seletor do topo e registra URL, cookies, requisições e os cards.
- Claro: chama /api/catalog com outros estado/cidade e compara os preços.
- TIM: abre /<uf>/para-voce/planos para algumas UFs e compara as ofertas embutidas.
Saída em planos/_descoberta/regiao/.
"""
import json, re, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SAIDA = Path(__file__).parent / "_descoberta" / "regiao"
VIVO_POS = "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-pos-pago"


def cards_vivo(page):
    return page.eval_on_selector_all(
        ".unique-card", """els => els.map(e => {
            const t = s => (e.querySelector(s)||{}).innerText || '';
            return {plano: t('.unique-card__plan'), gb: t('.unique-card__header-benefit'),
                    texto: e.innerText.replace(/\\s+/g,' ').slice(0,400)};
        })""")


def vivo(nav):
    out = {}
    for cidade in ["Recife", "Porto Alegre", "Manaus"]:
        r = {"cidade": cidade, "reqs": []}
        ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
                              viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(VIVO_POS, wait_until="domcontentloaded", timeout=60000)
            time.sleep(6)
            r["antes"] = [c["texto"][:160] for c in cards_vivo(page)][:3]
            page.on("request", lambda q: r["reqs"].append(q.method + " " + q.url[:300])
                    if q.resource_type in ("xhr", "fetch", "document") else None)
            page.locator("a.change-compass").first.click(timeout=15000)
            time.sleep(1)
            caixa = page.get_by_placeholder("Preencha com o nome da sua cidade").first
            caixa.click()
            caixa.type(cidade, delay=120)
            time.sleep(3)
            # guarda o html do popup para entender a lista de sugestões
            r["popup_html"] = page.eval_on_selector(".new-compass-popup, [class*=compass]",
                                                     "e => e.outerHTML.slice(0, 4000)")
            sug = page.locator("[class*=compass] li, [class*=compass] [role=option], .autocomplete li").first
            sug.click(timeout=10000)
            time.sleep(1)
            page.locator("[class*=compass] button:has-text('Confirmar')").first.click(timeout=10000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            time.sleep(6)
            r["url_depois"] = page.url
            r["cabecalho"] = page.locator("text=Ofertas para").first.inner_text(timeout=5000)
            r["depois"] = cards_vivo(page)
            r["cookies"] = {c["name"]: c["value"][:200] for c in ctx.cookies() if "vivo" in c["name"].lower()}
            page.screenshot(path=str(SAIDA / ("vivo_%s.png" % cidade.replace(" ", "_"))))
        except Exception:
            r["erro"] = traceback.format_exc()[-1200:]
            try:
                page.screenshot(path=str(SAIDA / ("vivo_%s_erro.png" % cidade.replace(" ", "_"))))
            except Exception:
                pass
        ctx.close()
        out[cidade] = r
        print("vivo", cidade, json.dumps({k: r.get(k) for k in ("url_depois", "cabecalho", "erro")}, ensure_ascii=False)[:600], flush=True)
    return out


def claro(nav):
    out = {}
    ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo")
    page = ctx.new_page()
    urls = []
    page.on("request", lambda q: urls.append(q.url) if "/api/catalog" in q.url else None)
    for pag in ["https://www.claro.com.br/celular/pos", "https://www.claro.com.br/celular/controle",
                "https://www.claro.com.br/internet", "https://www.claro.com.br/celular/pre-pago-claro",
                "https://www.claro.com.br/celular"]:
        try:
            page.goto(pag, wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        time.sleep(3)
        out.setdefault("paginas", {})[pag] = {"url_final": page.url, "titulo": page.title()}
    out["catalog_urls"] = urls
    for base in urls:
        for st, ct in [("SP", "sao_paulo"), ("PE", "recife"), ("RS", "porto_alegre"), ("AM", "manaus")]:
            u = re.sub(r"state=[A-Z]+", "state=" + st, base)
            u = re.sub(r"city=[a-z_]+", "city=" + ct, u)
            try:
                resp = page.request.get(u, timeout=30000)
                d = resp.json()
                precos = re.findall(r'"price":\s*"?([\d.,]+)', json.dumps(d))
                out.setdefault("catalogo", []).append({"base": base[:160], "uf": st, "status": resp.status,
                                                       "n": len(d.get("data", [])), "precos": precos[:30]})
                (SAIDA / ("claro_%s_%s.json" % (st, abs(hash(base)) % 10000))).write_text(json.dumps(d, ensure_ascii=False))
            except Exception as e:
                out.setdefault("catalogo", []).append({"base": base[:160], "uf": st, "erro": str(e)[:200]})
    ctx.close()
    print("claro", json.dumps(out.get("catalogo", [])[:8], ensure_ascii=False)[:1500], flush=True)
    return out


def tim(nav):
    out = {}
    ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo")
    page = ctx.new_page()
    for uf in ["sp", "pe", "rs", "am", "mg"]:
        for sec in ["planos/pos-pago/tim-black", "planos/controle", "planos/pre-pago", "internet-residencial", "planos/tim-black-familia"]:
            u = "https://www.tim.com.br/%s/para-voce/%s" % (uf, sec)
            try:
                r = page.goto(u, wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)
                h = page.content()
                dec = json.JSONDecoder()
                of = []
                for m in re.finditer(r'\{"nid":\[\{"value":"\d+"\}\]', h):
                    try:
                        o, _ = dec.raw_decode(h, m.start())
                    except Exception:
                        continue
                    if o.get("type", [{}])[0].get("target_id") == "oferta":
                        of.append((o["nid"][0]["value"], o["title"][0]["value"],
                                   (o.get("field_preco_card_oferta") or [{}])[0].get("value")))
                out["%s/%s" % (uf, sec)] = {"status": r.status if r else None, "url": page.url, "ofertas": sorted(set(of))}
                (SAIDA / ("tim_%s_%s.html" % (uf, sec.replace("/", "_")))).write_text(h, encoding="utf-8")
            except Exception as e:
                out["%s/%s" % (uf, sec)] = {"erro": str(e)[:200]}
            print("tim", uf, sec, json.dumps(out["%s/%s" % (uf, sec)], ensure_ascii=False)[:700], flush=True)
    ctx.close()
    return out


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    res = {}
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for nome, f in [("tim", tim), ("claro", claro), ("vivo", vivo)]:
            try:
                res[nome] = f(nav)
            except Exception:
                res[nome] = {"erro": traceback.format_exc()[-1500:]}
        nav.close()
    (SAIDA / "regiao.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
