#!/usr/bin/env python3
"""Lê o HTML já renderizado das páginas de planos e devolve uma lista de planos padronizada.

Cada plano vira um dicionário com:
  operadora, segmento (pre | controle | pos | familia | fibra), plano, chave,
  preco (R$/mês ou por recarga), preco_de (preço "De" riscado, se houver), preco_depois (ex.: "Após 1 ano"),
  condicao (texto curto do preço: "na fatura", "débito automático", "por 30 dias"...),
  gb_total, gb_detalhe, velocidade_mega (fibra), linhas (família), beneficios, selo, extra (id interno etc.)
"""
import html as html_mod
import json
import re
import unicodedata

from bs4 import BeautifulSoup

RE_PRECO = re.compile(r"R\$\s*(\d{1,4}(?:\.\d{3})*)(?:\s*,\s*(\d{2}))?")


def limpa(t):
    t = html_mod.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def num(txt):
    """'R$ 1.999,90' -> 1999.9 ; '129,99' -> 129.99"""
    if txt is None:
        return None
    m = RE_PRECO.search(txt) or re.search(r"(\d{1,4}(?:\.\d{3})*)(?:,(\d{2}))?", txt)
    if not m:
        return None
    inteiro = m.group(1).replace(".", "")
    return round(float(inteiro + "." + (m.group(2) or "00")), 2)


def gb(txt):
    m = re.search(r"(\d{1,4})\s*(GB|giga)", txt or "", re.I)
    return int(m.group(1)) if m else None


def mega(txt):
    m = re.search(r"(\d{1,4})\s*(Mega|Giga|Mbps|Gbps)\b", txt or "", re.I)
    if not m:
        return None
    v = int(m.group(1))
    return v * 1000 if m.group(2).lower().startswith("g") else v


def slug(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def chaves_unicas(regs):
    """Garante chave única por operadora/praça/segmento: soma GB/velocidade e, se ainda repetir, um sufixo pela ordem."""
    cont = {}
    for r in regs:
        base = r["chave"]
        if not base.startswith("tim-"):
            dim = r.get("gb_total") or r.get("velocidade_mega")
            if dim and str(dim) not in base:
                base = "%s-%s" % (base, dim)
        cont[base] = cont.get(base, 0) + 1
        r["chave"] = base if cont[base] == 1 else "%s-%d" % (base, cont[base])
    return regs


def registro(operadora, segmento, plano, **kw):
    r = dict(operadora=operadora, segmento=segmento, plano=plano, preco=None, preco_de=None,
             preco_depois=None, condicao="", gb_total=None, gb_detalhe="", velocidade_mega=None,
             linhas=None, beneficios="", selo="", extra="")
    r.update({k: v for k, v in kw.items() if v is not None})
    r["chave"] = kw.get("chave") or slug("%s-%s-%s" % (operadora, segmento, plano))
    return r


# ---------------------------------------------------------------- Vivo
def vivo(html, segmento_pagina):
    """Cards 'unique-card' (mesmo componente em Pós, Família, Controle, Pré e Fibra)."""
    soup = BeautifulSoup(html, "lxml")
    out, vistos = [], set()
    for card in soup.select("div.unique-card"):
        nome_el = card.select_one(".unique-card__plan")
        if not nome_el:
            continue
        nome = limpa(nome_el.get_text(" "))
        texto = limpa(card.get_text(" "))
        if not nome or (nome, texto) in vistos:
            continue
        vistos.add((nome, texto))
        titulo = limpa(" ".join(e.get_text(" ") for e in card.select(".unique-card__header-benefit")))
        itens = [limpa(li.get_text(" ")) for li in card.select(".unique-card__switch-list li, .unique-card__features li")]
        itens = [i for i in dict.fromkeys(itens) if i]
        apps = [limpa(p.get_text(" ")) for p in card.select("p") if re.search(r"inclus|grátis|gratis", p.get_text(), re.I)]
        selo_el = card.select_one(".unique-card__label")
        selo = limpa(selo_el.get_text(" ")).replace("Oferta Recomendada", "").strip() if selo_el else ""
        # preço: bloco .unique-card__price (o "{{ total }}" é molde não preenchido; o valor real está em .total-card-price-value)
        pv = card.select_one(".unique-card__price-new .total-card-price-value, .total-card-price-value")
        preco = num(limpa(pv.get_text(""))) if pv else None
        lado = card.select_one(".unique-card__price-new--side")
        cond = limpa(lado.get_text(" ")) if lado else ""
        velho = card.select_one(".unique-card__price-old")
        de = num(limpa(velho.get_text(" "))) if velho and limpa(velho.get_text(" ")) else None
        desc_el = card.select_one(".unique-card__price-description")
        desc = limpa(desc_el.get_text(" ")) if desc_el else ""
        mdep = re.search(r"Após ([^:]+):\s*(R\$\s*[\d.,]+)", texto)
        depois = num(mdep.group(2)) if mdep else None
        if mdep:
            cond = (cond + "; após %s: R$ %s" % (mdep.group(1), mdep.group(2).replace("R$", "").strip())).strip("; ")
        if desc and desc not in cond and not desc.lower().startswith("após"):
            cond = (cond + "; " + desc).strip("; ")
        seg = segmento_pagina
        linhas = None
        if seg == "pos" and re.search(r"fam[ií]lia", nome, re.I):
            seg = "familia"
            ml = re.search(r"\+\s*(\d)\s*linha", texto)
            linhas = int(ml.group(1)) + 1 if ml else None
        if seg == "fibra":
            out.append(registro("Vivo", seg, nome + " " + titulo, preco=preco, preco_de=de,
                                preco_depois=depois, condicao=cond,
                                velocidade_mega=mega(titulo or texto), beneficios="; ".join(itens + apps)[:500], selo=selo))
        else:
            out.append(registro("Vivo", seg, nome, preco=preco, preco_de=de,
                                preco_depois=depois, condicao=cond,
                                gb_total=gb(titulo), gb_detalhe=next((i for i in itens if re.search(r"GB", i)), ""),
                                linhas=linhas, beneficios="; ".join([i for i in itens if not re.search(r"\d+\s*GB de franquia", i)] + apps)[:500],
                                selo=selo))
    return out


# ---------------------------------------------------------------- Claro
def claro(html, segmento_pagina):
    """Cards 'mdn-Card' (Pós, Controle, Internet)."""
    soup = BeautifulSoup(html, "lxml")
    out, vistos = [], set()
    for card in soup.select("div.mdn-Card"):
        tit = card.select_one(".mdn-Card-top-main-title")
        preco_el = card.select_one(".mdn-Card-bottom-price, .mdn-Price")
        if not tit or not preco_el:
            continue
        titulo = limpa(tit.get_text(" "))
        desc_el = card.select_one(".mdn-Card-top-main-description")
        desc = limpa(desc_el.get_text(" ")) if desc_el else ""
        tags = limpa(" | ".join(t.get_text(" ") for t in card.select(".mdn-Card-top-header-tags")))
        itens = []
        for li in card.select(".mdn-Card-middle-list-item"):
            rot = limpa(" ".join(p.get_text(" ") for p in li.find_all("p", recursive=False)))
            val_el = li.select_one(".mdn-Card-middle-list-item-value")
            val = ""
            if val_el:
                val = limpa(val_el.get_text(" ")) or ", ".join(i.get("alt", "") for i in val_el.select("img[alt]"))
            itens.append((rot + (": " + val if val and val not in rot else "")).strip(": "))
        ptxt = limpa(preco_el.get_text(" "))
        main = card.select_one(".mdn-Price-main")
        preco = None
        if main:
            preco = num("R$ " + limpa(main.get_text("")).replace("R$", ""))
        if preco is None:
            preco = num(ptxt)
        de = re.search(r"De:?\s*~?R\$\s*([\d.,]+)", ptxt)
        cond = re.sub(r"R\$.*", "", ptxt).replace("Valor mensal", "").strip()
        cond = re.sub(r"^De:?\s*~?$", "", cond).strip()
        key = (titulo, preco, tags)
        if key in vistos:
            continue
        vistos.add(key)
        if segmento_pagina == "fibra":
            out.append(registro("Claro", "fibra", titulo, preco=preco, preco_de=num(de.group(1)) if de else None,
                                condicao=cond, velocidade_mega=mega(titulo), beneficios="; ".join(itens)[:500], selo=tags))
        else:
            texto_card = limpa(card.get_text(" "))
            rotulo = {"pos": "Claro Pós", "controle": "Claro Controle", "pre": "Claro Pré", "flex": "Claro Flex"}.get(segmento_pagina, "Claro")
            nome = "%s %s" % (rotulo, titulo)
            if re.search(r"GeForce", texto_card + tags, re.I):
                nome += " GeForce"
            ml = re.search(r"(\d)\s*linhas? inclusa", texto_card)
            out.append(registro("Claro", segmento_pagina, nome, preco=preco, preco_de=num(de.group(1)) if de else None,
                                condicao=cond, gb_total=gb(titulo),
                                velocidade_mega=None if gb(titulo) else mega(titulo),
                                gb_detalhe="; ".join(i for i in itens if re.search(r"\d+\s*GB", i)),
                                linhas=(int(ml.group(1)) + 1) if ml else None,
                                beneficios="; ".join(i for i in itens if not re.search(r"^Para uso livre", i))[:500], selo=tags))
    return out


# ---------------------------------------------------------------- TIM
def _tim_nodes(html):
    dec = json.JSONDecoder()
    vistos = {}
    for m in re.finditer(r'\{"nid":\[\{"value":"\d+"\}\]', html):
        try:
            o, _ = dec.raw_decode(html, m.start())
        except Exception:
            continue
        if (o.get("type") or [{}])[0].get("target_id") == "oferta":
            vistos[o["nid"][0]["value"]] = o
    return list(vistos.values())


def _v(o, campo):
    v = o.get(campo) or []
    if not v:
        return ""
    x = v[0]
    return x.get("value", "") if isinstance(x, dict) else str(x)


def tim(html, segmento_pagina, uf):
    """Ofertas embutidas no JSON do Drupal. Cada oferta traz as UFs (field_regioes) e DDDs onde vale."""
    out = []
    for o in _tim_nodes(html):
        regioes = [r.get("target_id") for r in o.get("field_regioes") or []]
        if regioes and uf not in regioes:
            continue  # oferta não vale nesta UF
        titulo_interno = _v(o, "title")
        nome = limpa(_v(o, "field_nome_da_oferta")) or limpa(_v(o, "field_subtitle")) or titulo_interno
        gbtxt = limpa(_v(o, "field_titulo")) or limpa(_v(o, "field_oferta_adicional"))
        preco = num(_v(o, "field_preco_card_oferta"))
        principal = limpa(_v(o, "field_preco_principal_7_1_3"))
        adicional = limpa(_v(o, "field_preco_adicional_original"))
        if preco is None:
            preco = num(principal)
        m = re.search(r"R\$\s*[\d.,]+\s*/?\s*([^R]{0,50})", principal)
        cond = limpa(m.group(1)) if m else ""
        cond = re.split(r"\s*(Incluso|Inclu[ií]do|Trazer|Benef|Conferir|Contratar|\d+\s*GB)", cond)[0].strip()
        benef = [limpa(b.get("name", [{}])[0].get("value", "")) for b in (o.get("field_outros_beneficios") or []) + (o.get("field_beneficios_destaque") or [])]
        info = limpa(_v(o, "field_information_text"))
        seg = segmento_pagina
        if re.search(r"ultrafibra|mega|giga", titulo_interno + nome, re.I) and not re.search(r"\d+\s*GB", gbtxt):
            seg = "fibra"
        linhas = None
        mt = re.search(r"R\$\s*([\d.,]+)\s*/?\s*m[eê]s por pessoa", principal + " " + limpa(_v(o, "field_destaque_descricao_preco")))
        extra = {"nid": o["nid"][0]["value"], "sku": _v(o, "field_sku"), "titulo_interno": titulo_interno,
                 "n_ddd": len(o.get("field_oferta_ddd") or [])}
        if adicional and num(adicional) and num(adicional) != preco:
            extra["preco_alternativo"] = adicional[:120]
        if seg == "fibra":
            vel = mega(gbtxt) or mega(titulo_interno) or mega(nome)
            out.append(registro("TIM", "fibra", "%s %s" % (nome, gbtxt), preco=preco, condicao=cond[:80],
                                velocidade_mega=vel, beneficios="; ".join(filter(None, benef))[:500],
                                extra=json.dumps(extra, ensure_ascii=False), chave=slug("tim-fibra-" + extra["nid"])))
        else:
            out.append(registro("TIM", seg, "%s %s" % (nome, gbtxt), preco=preco, condicao=cond[:80],
                                gb_total=gb(gbtxt), gb_detalhe=info[:200], linhas=linhas,
                                beneficios="; ".join(filter(None, benef))[:500],
                                extra=json.dumps(extra, ensure_ascii=False), chave=slug("tim-%s-%s" % (seg, extra["nid"]))))
    return out
