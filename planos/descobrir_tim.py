#!/usr/bin/env python3
"""Descoberta (uso único): todas as ofertas da página TIM Ultrafibra SP, com UFs/DDDs, e o texto visível."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from coletar import UA, abrir  # noqa
import extrair  # noqa
from playwright.sync_api import sync_playwright
OUT = Path(__file__).parent / "descoberta_tim"; OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    pg = nav.new_context(user_agent=UA, locale="pt-BR").new_page()
    for uf in ["sp", "rj"]:
        abrir(pg, "https://www.tim.com.br/%s/para-voce/internet/internet-para-casa/tim-ultrafibra" % uf, rolar=True, espera=5000)
        html = pg.content()
        nodes = [{"nid": o["nid"][0]["value"], "titulo": extrair._v(o, "title"), "preco": extrair._v(o, "field_preco_card_oferta"), "field_titulo": extrair._v(o, "field_titulo"), "adicional": extrair._v(o, "field_oferta_adicional"),
                  "principal": extrair._v(o, "field_preco_principal_7_1_3")[:120],
                  "regioes": [r.get("target_id") for r in o.get("field_regioes") or []],
                  "ddds": [d.get("target_id") for d in o.get("field_oferta_ddd") or []][:80]} for o in extrair._tim_nodes(html)]
        (OUT / ("%s.json" % uf)).write_text(json.dumps(nodes, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / ("%s.txt" % uf)).write_text(pg.inner_text("body")[:40000], encoding="utf-8")
    nav.close()
# rodar
