#!/usr/bin/env python3
"""Descoberta (uso único): onde o site do Nubank mostra os planos NuCel. Grava texto e respostas JSON."""
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "descoberta_nucel"
OUT.mkdir(exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
URLS = ["https://nubank.com.br/nu/nucel"]
res = []
with sync_playwright() as p:
    nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo")
    for i, u in enumerate(URLS):
        pg = ctx.new_page(); js = []
        pg.on("response", lambda r: js.append(r.url) if "json" in (r.headers.get("content-type") or "") else None)
        try:
            r = pg.goto(u, wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(9000)
            txt = pg.inner_text("body")
            links = sorted({h for h in pg.eval_on_selector_all("a[href]", "e=>e.map(x=>x.href)") if re.search("nucel|celular", h, re.I)})
            res.append({"url": u, "final": pg.url, "status": r.status if r else 0, "links": links, "json": js[:40]})
            (OUT / ("b%02d.txt" % i)).write_text(txt[:30000], encoding="utf-8")
            (OUT / ("b%02d.html" % i)).write_text(pg.content()[:400000], encoding="utf-8")
        except Exception as e:
            res.append({"url": u, "erro": str(e)[:200]})
        pg.close()
    nav.close()
(OUT / "resumo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
