#!/usr/bin/env python3
"""Monitor dos comunicados públicos da Vivo (reajustes, novas condições comerciais, mudanças de serviço).

Junta os endereços /comunicados/ de três fontes: as páginas índice de comunicados, o sitemap do site
e os links internos dessas páginas. Para cada endereço novo abre a página e lê título e data de publicação.
- Primeira execução: só monta a base (não avisa um por um).
- Depois: um push no ntfy por comunicado novo; prioridade alta quando fala de preço/valor/reajuste/franquia.
Estado em estado/comunicados_vivo.json; lista legível em comunicados/comunicados_vivo.csv.
Uso: python comunicados/vivo.py [--teste]
"""
import csv, json, os, re, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

RAIZ = Path(__file__).resolve().parent.parent
ESTADO = RAIZ / "estado" / "comunicados_vivo.json"
CSV = RAIZ / "comunicados" / "comunicados_vivo.csv"
BRT = timezone(timedelta(hours=-3))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = "https://www.vivo.com.br"
INDICES = [
    "/para-voce/comunicados",
    "/para-voce/comunicados/regulatorios",
    "/para-voce/comunicados/planos",
    "/para-voce/ajuda/comunicados",
    "/para-empresas/comunicados",
]
SITEMAPS = ["/sitemap.xml", "/sitemap_index.xml", "/robots.txt"]
# comunicados de reajuste que nem sempre aparecem nas listas
SEMENTES = [
    BASE + "/para-voce/comunicados/regulatorios/comunicado-nova-condicao-comercial-controle-2026",
    BASE + "/para-voce/comunicados/regulatorios/comunicado_publico_ncc_2026_controle",
    BASE + "/para-voce/comunicados/regulatorios/novos-valores-vivo-pos-e-controle",
    BASE + "/para-voce/comunicados/planos/reajuste-dos-planos-controle",
]
RELEVANTE = re.compile(r"reajust|novos?[ -]valor|novo[ -]pre|pre[cç]o|condi[cç][aã]o[ -]comercial|franquia|"
                       r"altera[cç][aã]o|regulariza|encerramento|descontinu", re.I)


def normal(u):
    p = urlparse(u)
    if not p.netloc.endswith("vivo.com.br"):
        return None
    caminho = re.sub(r"/+$", "", p.path)
    if "/comunicados/" not in caminho + "/" or caminho.rstrip("/").endswith("/comunicados"):
        return None
    return "https://www.vivo.com.br" + caminho


def ntfy(titulo, msg, prioridade="default", tags="loudspeaker", click=""):
    topico = os.environ.get("NTFY_TOPIC", "")
    if not topico:
        print("sem NTFY_TOPIC:", titulo); return
    cab = ["-H", "Title: " + titulo, "-H", "Priority: " + prioridade, "-H", "Tags: " + tags]
    if click:
        cab += ["-H", "Click: " + click]
    if os.environ.get("NTFY_TOKEN"):
        cab += ["-H", "Authorization: Bearer " + os.environ["NTFY_TOKEN"]]
    for _ in range(3):
        if subprocess.run(["curl", "-sSf", "-m", "30", "--data-binary", msg[:3900]] + cab +
                          ["https://ntfy.sh/" + topico], capture_output=True).returncode == 0:
            return
    print("falha no ntfy:", titulo)


def ler_pdf(ctx, url):
    """PDF: título pelo nome do arquivo, data pelo Last-Modified do servidor."""
    from email.utils import parsedate_to_datetime
    r = ctx.request.head(url, timeout=30000)
    pub = ""
    try:
        pub = parsedate_to_datetime(r.headers.get("last-modified", "")).astimezone(BRT).strftime("%d/%m/%Y")
    except Exception:
        pass
    nome = re.sub(r"\.pdf(\.html)?$", "", url.rsplit("/", 1)[-1], flags=re.I)
    pasta = url.rsplit("/", 2)[-2]
    titulo = re.sub(r"[-_]+", " ", nome if pasta == "comunicados" else pasta + " / " + nome).strip()
    return r.status, "(PDF) " + titulo[:180], pub, "", []


def ler_pagina(pg, url):
    """Abre o comunicado e devolve (titulo, publicado, resumo, links internos)."""
    if re.search(r"\.pdf(\.html)?$", url, re.I):
        return ler_pdf(pg.context, url)
    r = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(2500)
    status = r.status if r else 0
    texto = pg.inner_text("body") if status < 400 else ""
    titulo = ""
    for sel in ["main h1", "h1", "main h2", "title"]:
        try:
            t = pg.locator(sel).first.inner_text(timeout=2000).strip()
        except Exception:
            t = ""
        if t and "libras" not in t.lower():
            titulo = t; break
    if not titulo:
        titulo = (pg.title() or "").strip()
    m = re.search(r"(?:Publicado|Data da Publica[cç][aã]o:?)\s*(?:em\s*)?(\d{2}/\d{2}/\d{4})", texto)
    pub = m.group(1) if m else ""
    linhas = [l.strip() for l in texto.splitlines() if len(l.strip()) > 40 and not re.search(
        r"libras|cookie|navegador|acessibilidade", l, re.I)]
    resumo = " ".join(linhas[:3])[:500]
    hrefs = pg.eval_on_selector_all("a[href]", "els => els.map(e => e.href)") if texto else []
    return status, titulo[:200], pub, resumo, hrefs


def expandir(pg):
    """Clica em "ver mais"/"carregar mais" enquanto existir (listas paginadas)."""
    for _ in range(30):
        b = pg.locator("button, a").filter(has_text=re.compile(r"(ver|carregar|mostrar) mais", re.I))
        try:
            if not b.count() or not b.first.is_visible():
                return
            b.first.click(timeout=3000); pg.wait_for_timeout(1500)
        except Exception:
            return


def coletar_urls(pg, ctx, fontes, origem):
    urls = set()
    # sitemap (com sub-sitemaps)
    fila, vistos = [BASE + s for s in SITEMAPS], set()
    while fila and len(vistos) < 60:
        s = fila.pop(0)
        if s in vistos:
            continue
        vistos.add(s)
        try:
            r = ctx.request.get(s, timeout=45000)
            corpo = r.text() if r.ok else ""
        except Exception:
            corpo = ""
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", corpo) + re.findall(r"(?im)^sitemap:\s*(\S+)", corpo)
        n = 0
        for l in locs:
            if l.endswith(".xml") or "sitemap" in l.lower():
                if l not in vistos:
                    fila.append(l)
            else:
                u = normal(l)
                if u:
                    urls.add(u); n += 1; origem.setdefault(u, set()).add("sitemap")
        fontes[urlparse(s).path] = {"ok": bool(corpo), "comunicados": n}
    # páginas índice
    for i in INDICES:
        try:
            status, _, _, _, hrefs = ler_pagina(pg, BASE + i)
            if status < 400:
                expandir(pg)
                hrefs = pg.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        except Exception:
            status, hrefs = 0, []
        achados = {normal(h) for h in hrefs} - {None}
        urls |= achados
        for u in achados:
            origem.setdefault(u, set()).add(i)
        fontes[i] = {"status": status, "comunicados": len(achados)}
    return urls


def main():
    teste = "--teste" in sys.argv
    from playwright.sync_api import sync_playwright
    est = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {"itens": {}}
    itens, primeira = est["itens"], not est["itens"]
    agora = datetime.now(BRT).strftime("%Y-%m-%d %H:%M")
    fontes, novos = {}, []
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for tentativa in range(3):
            # site às vezes devolve 403 para robô: espera e tenta com navegador limpo
            if tentativa:
                ctx.close()
                import time; time.sleep(90)
            ctx = nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo")
            pg = ctx.new_page()
            fontes, origem = {}, {}
            urls = coletar_urls(pg, ctx, fontes, origem)
            if urls:
                break
        if not urls:
            nav.close()
            est.update({"ultima_checagem": agora, "fontes": fontes, "ok": False})
            if est["itens"]:  # sem base ainda: não grava nada, a próxima checagem monta a base
                ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            print(json.dumps({"fontes": fontes}, ensure_ascii=False))
            ntfy(("Teste - " if teste else "") + "Comunicados Vivo: não consegui ler a lista",
                 "O site da Vivo não respondeu às listas de comunicados (%s). Tento de novo na próxima checagem." % agora,
                 prioridade="low", tags="warning")
            return
        urls |= {normal(u) for u in SEMENTES}
        if primeira:
            # tudo o que já está publicado hoje é base: entra sem aviso, os detalhes são lidos aos poucos
            for u in urls:
                itens[u] = {"titulo": "", "publicado": "", "visto_em": agora, "resumo": "", "base": True}
        else:
            # lista que nunca tinha aberto (ou estava fora): o que vier dela é base, não novidade
            ja_ok = set(est.get("fontes_ok", []))
            for u in urls:
                if u not in itens and not (origem.get(u, set()) & ja_ok) and u not in SEMENTES:
                    itens[u] = {"titulo": "", "publicado": "", "visto_em": agora, "resumo": "", "base": True}
                elif u not in itens:
                    itens[u] = {"titulo": "", "publicado": "", "visto_em": agora, "resumo": "", "base": False}
                    novos.append(u)
        ordem = lambda u: ("/para-voce/" not in u, ".pdf" in u.lower(), u)
        sem_detalhe = novos + sorted((u for u in itens if not itens[u]["titulo"] and u not in novos), key=ordem)
        for u in sem_detalhe[:150]:
            pg.wait_for_timeout(800)
            try:
                status, titulo, pub, resumo, hrefs = ler_pagina(pg, u)
            except Exception:
                status, titulo, pub, resumo, hrefs = 0, "", "", "", []
            itens[u]["status"] = status
            if 0 < status < 400:
                itens[u].update({"titulo": titulo, "publicado": pub, "resumo": resumo})
        nav.close()

    ok = sum(1 for f in fontes.values() if f.get("comunicados")) > 0
    if not ok and not primeira:
        novos = []  # lista não abriu: não confundir com comunicado novo
    est["fontes_ok"] = sorted(set(est.get("fontes_ok", [])) | {f for f, v in fontes.items() if v.get("comunicados")}
                              | ({"sitemap"} if any(f.endswith(".xml") or f.endswith(".txt") for f, v in fontes.items()
                                                    if v.get("comunicados")) else set()))
    est.update({"itens": itens, "ultima_checagem": agora, "fontes": fontes, "ok": ok,
                "sem_detalhe": sum(1 for d in itens.values() if not d["titulo"])})
    ESTADO.parent.mkdir(exist_ok=True)
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    def chave(u):
        d = itens[u]["publicado"]
        return (d[6:] + d[3:5] + d[:2]) if d else "0"
    with CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["publicado", "titulo", "relevante_preco", "visto_pelo_monitor_em", "link", "resumo"])
        for u in sorted(itens, key=chave, reverse=True):
            d = itens[u]
            w.writerow([d["publicado"], d["titulo"], "sim" if RELEVANTE.search(d["titulo"] + " " + u) else "",
                        d["visto_em"], u, d["resumo"]])

    print(json.dumps({"fontes": fontes, "total": len(itens), "novos": len(novos)}, ensure_ascii=False, indent=1))
    pre = "Teste - " if teste else ""
    if not ok:
        ntfy(pre + "Comunicados Vivo: não consegui ler a lista", "Nenhuma fonte trouxe comunicados (%s)." % agora,
             tags="warning")
        return
    if primeira or teste:
        recentes = sorted(itens, key=chave, reverse=True)[:5]
        msg = "%d comunicados na base (%d ainda sem título). Mais recentes:\n" % (
            len(itens), est["sem_detalhe"]) + "\n".join(
            "%s %s" % (itens[u]["publicado"] or "s/ data", itens[u]["titulo"][:90]) for u in recentes)
        ntfy(pre + "Comunicados Vivo: base montada" if primeira else pre + "Comunicados Vivo: ok", msg,
             tags="white_check_mark")
        if primeira:
            return
    for u in novos:
        d = itens[u]
        if d.get("status") and d["status"] >= 400:
            continue  # link quebrado na lista; não avisa
        rel = bool(RELEVANTE.search(d["titulo"] + " " + u))
        ntfy("%sVivo: novo comunicado%s" % (pre, " (preço/oferta)" if rel else ""),
             "%s\nPublicado: %s\n%s" % (d["titulo"], d["publicado"] or "sem data", d["resumo"][:600]),
             prioridade="high" if rel else "default", tags="rotating_light" if rel else "loudspeaker", click=u)


if __name__ == "__main__":
    main()
