#!/usr/bin/env python3
"""Coleta os planos de uma operadora em todas as praças (capitais) e grava planos/_coleta/<operadora>.json.

Uso: python planos/coletar.py vivo|claro|tim [--pracas SP,RJ]

Como cada site troca de praça:
- Vivo: cookies vivo_reg_city / vivo_reg_state / vivo_reg_ddd / vivo_pretty_city (o mesmo que o seletor grava).
- Claro: seletor "Alterar cidade" no topo (a cidade fica no cookie clr_hcms_city).
- TIM: a UF vai no endereço (/sp/para-voce/...) e cada oferta traz as UFs onde vale.
Toda praça é conferida: se a página mostrar outra cidade, a coleta daquela praça é marcada como falha.
"""
import base64, json, re, sys, time, traceback, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import extrair  # noqa: E402
import taxonomia  # noqa: E402

AQUI = Path(__file__).parent
SAIDA = AQUI / "_coleta"
BRT = timezone(timedelta(hours=-3))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

PRACAS = [  # UF, capital, DDD
    ("AC", "Rio Branco", "68"), ("AL", "Maceió", "82"), ("AP", "Macapá", "96"), ("AM", "Manaus", "92"),
    ("BA", "Salvador", "71"), ("CE", "Fortaleza", "85"), ("DF", "Brasília", "61"), ("ES", "Vitória", "27"),
    ("GO", "Goiânia", "62"), ("MA", "São Luís", "98"), ("MT", "Cuiabá", "65"), ("MS", "Campo Grande", "67"),
    ("MG", "Belo Horizonte", "31"), ("PA", "Belém", "91"), ("PB", "João Pessoa", "83"), ("PR", "Curitiba", "41"),
    ("PE", "Recife", "81"), ("PI", "Teresina", "86"), ("RJ", "Rio de Janeiro", "21"), ("RN", "Natal", "84"),
    ("RS", "Porto Alegre", "51"), ("RO", "Porto Velho", "69"), ("RR", "Boa Vista", "95"), ("SC", "Florianópolis", "48"),
    ("SP", "São Paulo", "11"), ("SE", "Aracaju", "79"), ("TO", "Palmas", "63"),
]

PAGINAS = {
    "vivo": [
        ("pos", "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-pos-pago"),
        ("controle", "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-controle"),
        ("pre", "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/pre-pago/vivo-pre"),
        ("lite", "https://vivo.com.br/para-voce/produtos-e-servicos/para-o-celular/planos-lite"),
        ("fibra", "https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/internet"),
    ],
    "claro": [
        ("pos", "https://www.claro.com.br/celular/pos"),
        ("controle", "https://www.claro.com.br/celular/controle"),
        ("pre", "https://www.claro.com.br/celular/planos-pre"),
        ("flex", "https://www.claro.com.br/celular/flex"),
        ("fibra", "https://www.claro.com.br/internet"),
    ],
    "tim": [
        ("pos", "https://www.tim.com.br/{uf}/para-voce/planos/pos-pago/tim-black"),
        ("familia", "https://www.tim.com.br/{uf}/para-voce/planos/pos-pago/tim-black-familia"),
        ("controle", "https://www.tim.com.br/{uf}/para-voce/planos/controle"),
        ("pre", "https://www.tim.com.br/{uf}/para-voce/planos/pre-pago"),
        ("fibra", "https://www.tim.com.br/{uf}/para-voce/internet/internet-para-casa/tim-ultrafibra"),
    ],
}


def sem_acento(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def abrir(page, url, rolar=True, espera=8000):
    """Abre e espera os cards. Sites com rastreadores quase nunca ficam 'quietos', então a espera é curta."""
    r = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if espera:
        try:
            page.wait_for_load_state("networkidle", timeout=espera)
        except Exception:
            pass
    if rolar:
        for _ in range(4):
            page.mouse.wheel(0, 2000)
            time.sleep(0.4)
        time.sleep(1.5)
    return r.status if r else None


# ------------------------------------------------------------------ Vivo
def vivo_cookies(ctx, uf, cidade, ddd):
    slug = re.sub(r"[^a-z0-9]+", "_", sem_acento(cidade).lower()).strip("_")
    pretty = base64.b64encode(quote_plus(cidade).encode()).decode()
    ctx.clear_cookies()
    ctx.add_cookies([{"name": n, "value": v, "domain": ".vivo.com.br", "path": "/"} for n, v in [
        ("vivo_reg_city", slug), ("vivo_reg_state", uf), ("vivo_reg_ddd", ddd),
        ("vivo_pretty_city", pretty), ("vivo_reg_temp", "false")]])


def vivo_praca_tela(page):
    try:
        t = page.locator(":text('Ofertas para')").first.evaluate("e => e.parentElement.innerText")
        return re.sub(r"\s+", " ", t).replace("Ofertas para", "").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------ Claro
def claro_trocar_cidade(page, uf, cidade):
    abrir(page, "https://www.claro.com.br/internet", rolar=False)
    page.locator(":visible:text-is('Alterar cidade')").first.click(timeout=15000)
    time.sleep(1.5)
    caixa = page.locator("input[name='autocompleteCities']:visible").first
    caixa.click()
    caixa.type(cidade, delay=120)
    time.sleep(3)
    page.locator("button:visible:text-is('%s/%s')" % (cidade, uf)).first.click(timeout=10000)
    time.sleep(2)
    for txt in ["Confirmar", "Continuar"]:
        b = page.locator("button:visible:has-text('%s')" % txt)
        if b.count():
            b.first.click(timeout=5000)
            break
    time.sleep(3)


def claro_praca_tela(page):
    t = page.inner_text("body")[:600]
    m = re.search(r"governo\s*\n\s*(.+?)\s*\n\s*/\s*([A-Z]{2})", t)
    return "%s (%s)" % (m.group(1).strip(), m.group(2)) if m else ""


# ------------------------------------------------------------------ principal
def coletar(operadora, pracas):
    SAIDA.mkdir(exist_ok=True)
    (SAIDA / "html").mkdir(exist_ok=True)
    agora = datetime.now(BRT)
    res = {"operadora": operadora, "data": agora.strftime("%Y-%m-%d"), "hora": agora.strftime("%H:%M"),
           "paginas": [], "planos": []}
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
                              viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for uf, cidade, ddd in pracas:
            praca_ok = True
            erro_praca = ""
            if operadora in ("claro", "vivo"):
                # sessão nova por cidade: Claro só mostra "Alterar cidade" na primeira visita;
                # Vivo guarda a praça da primeira visita além dos cookies
                ctx.close()
                ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                      viewport={"width": 1366, "height": 900})
                page = ctx.new_page()
            try:
                if operadora == "vivo":
                    vivo_cookies(ctx, uf, cidade, ddd)
                elif operadora == "claro":
                    claro_trocar_cidade(page, uf, cidade)
            except Exception:
                praca_ok = False
                erro_praca = traceback.format_exc()[-300:]
            for seg, url in PAGINAS[operadora]:
                url = url.format(uf=uf.lower())
                reg = {"uf": uf, "cidade": cidade, "pagina": seg, "url": url, "ok": False, "n": 0, "erro": "", "praca_tela": ""}
                if not praca_ok:
                    reg["erro"] = "não consegui trocar a praça: " + erro_praca
                    res["paginas"].append(reg)
                    print("%s %s %-8s ok=False n=0 %s" % (operadora, uf, seg, reg["erro"][-160:].replace("\n", " ")), flush=True)
                    continue
                for tentativa in range(2):
                    try:
                        status = abrir(page, url, rolar=(operadora != "tim"), espera=(0 if operadora == "tim" else 8000))
                        reg["status"] = status
                        html = page.content()
                        if operadora == "vivo":
                            reg["praca_tela"] = vivo_praca_tela(page)
                            planos = extrair.vivo(html, seg)
                            esperado = sem_acento(cidade).lower()
                        elif operadora == "claro":
                            reg["praca_tela"] = claro_praca_tela(page)
                            planos = extrair.claro(html, seg)
                            esperado = sem_acento(cidade).lower()
                        else:
                            reg["praca_tela"] = uf
                            planos = extrair.tim(html, seg, uf.lower())
                            esperado = uf.lower()
                        if esperado not in sem_acento(reg["praca_tela"]).lower():
                            reg["erro"] = "página mostrou outra praça: %s" % reg["praca_tela"]
                            planos = []
                        elif status == 404:
                            reg["ok"] = True  # página não existe (nesta praça ou em geral): fica registrado, sem plano
                            reg["erro"] = "404 (página não existe)"
                            planos = []
                        elif status and status >= 400:
                            reg["erro"] = "HTTP %s" % status
                            planos = []
                        elif not planos and operadora == "tim" and '"target_id":"oferta"' in html:
                            reg["ok"] = True  # página carregou, mas nenhuma oferta vale nesta UF (ex.: fibra sem cobertura)
                            reg["erro"] = "sem oferta para esta UF"
                        elif not planos:
                            reg["erro"] = "nenhum plano lido (layout mudou?)"
                        else:
                            reg["ok"] = True
                        extrair.chaves_unicas(planos)
                        op_nome = {"vivo": "Vivo", "claro": "Claro", "tim": "TIM"}[operadora]
                        for pl in planos:
                            tipo, linha = taxonomia.classificar(op_nome, seg, pl["plano"], pl.get("linhas"))
                            pl.update(uf=uf, cidade=cidade, pagina=seg, url=url, tipo=tipo, linha=linha,
                                      segmento=taxonomia.SEG.get(tipo, pl["segmento"]))
                        reg["n"] = len(planos)
                        res["planos"].extend(planos)
                        if uf in ("SP", "RJ"):  # guarda amostra do HTML para conferência
                            (SAIDA / "html" / ("%s_%s_%s.html" % (operadora, uf, seg))).write_text(html, encoding="utf-8")
                        break
                    except Exception:
                        reg["erro"] = traceback.format_exc()[-300:]
                        time.sleep(5)
                res["paginas"].append(reg)
                (SAIDA / ("%s.json" % operadora)).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")  # parcial
                print("%s %s %-8s ok=%s n=%s %s %s" % (operadora, uf, seg, reg["ok"], reg["n"], reg["praca_tela"], reg["erro"][:120]), flush=True)
        ctx.close()
        nav.close()
    (SAIDA / ("%s.json" % operadora)).write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding="utf-8")
    ok = sum(1 for r in res["paginas"] if r["ok"])
    print("FIM %s: %d de %d páginas ok, %d planos" % (operadora, ok, len(res["paginas"]), len(res["planos"])))


if __name__ == "__main__":
    op = sys.argv[1]
    pr = PRACAS
    if "--pracas" in sys.argv:
        sel = sys.argv[sys.argv.index("--pracas") + 1].split(",")
        pr = [x for x in PRACAS if x[0] in sel]
    coletar(op, pr)
