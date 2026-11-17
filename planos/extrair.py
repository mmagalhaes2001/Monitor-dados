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
import base64
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


RE_CARIMBADO = re.compile(r"redes? sociais|\bapps?\b|youtube|tiktok|whats|instagram|exclusiv|dedicad", re.I)


def gb_livre(gb_total, gb_detalhe):
    """Franquia de uso livre = total menos os GB carimbados (só redes sociais/apps/YouTube etc.).
    É o critério dos relatórios de mercado (ex.: Claro Controle 45GB = 40GB livres + 5GB redes sociais).
    Bônus de uso livre (inclusive de campanha, como Claro Day/Multi Friday) continuam contando."""
    try:
        total = float(gb_total)
    except (TypeError, ValueError):
        return None
    tirar = 0.0
    for parte in re.split(r"[;+]", gb_detalhe or ""):
        if RE_CARIMBADO.search(parte) and not re.search(r"uso livre|como quiser", parte, re.I):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*GB", parte, re.I)
            if m:
                tirar += float(m.group(1).replace(",", "."))
    return round(total - tirar, 1) if tirar < total else total


def fmt(v):
    """17.0 -> '17'; 44.9 -> '44,90'"""
    return ("%d" % v) if float(v).is_integer() else ("%.2f" % v).replace(".", ",")


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
            # Vivo Lite: o mesmo card tem "Plano anual" (preço mostrado) e "Plano mensal / sem fidelidade", cujo
            # acréscimo vem em base64 no data-value do botão (ex.: "MTU=" = +15 -> R$ 45 no plano de R$ 30)
            for rb in card.select('input[type=radio][aria-label="Plano mensal"]'):
                try:
                    extra = float(base64.b64decode(rb.get("data-value", "")).decode())
                except Exception:
                    continue
                if preco and extra > 0:
                    out.append(registro("Vivo", seg, nome + " mensal sem fidelidade (%sGB)" % gb(titulo), preco=preco + extra,
                                        condicao="/mês; sem fidelidade (o card mostra o anual: 12x de R$ %s)" % fmt(preco),
                                        gb_total=gb(titulo), gb_detalhe=next((i for i in itens if re.search(r"GB", i)), ""),
                                        beneficios="; ".join(itens + apps)[:500], selo=selo,
                                        chave="vivo-lite-mensal-sem-fidelidade-%s" % gb(titulo)))
    if segmento_pagina == "pre":
        out += vivo_pre_tabela(soup, out)
    return out


def vivo_pre_tabela(soup, cards):
    """Tabela 'Renovação automática da oferta Vivo Pré' (Preço | Dias | Franquia | Benefício): todas as recargas,
    inclusive as que não têm card (ex.: R$ 17 por 15 dias). Entram as de 15 dias ou mais que não estão nos cards."""
    out = []
    ja = {(c["preco"], re.search(r"(\d+)\s*dias", c["condicao"] or "") and re.search(r"(\d+)\s*dias", c["condicao"]).group(1))
          for c in cards}
    for t in soup.find_all("table"):
        linhas = t.find_all("tr")
        cab = [c.get_text(" ", strip=True).lower() for c in linhas[0].find_all(["th", "td"])] if linhas else []
        if not (cab[:3] == ["preço", "dias", "franquia"]):
            continue
        for tr in linhas[1:]:
            cel = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cel) < 3:
                continue
            preco, dias = num(cel[0]), int(num(cel[1]) or 0)
            mgb = re.search(r"([\d.,]+)\s*(GB|MB)", cel[2], re.I)
            if not preco or dias < 15 or not mgb:
                continue
            g = num(mgb.group(1)) / (1000 if mgb.group(2).upper() == "MB" else 1)
            if (preco, str(dias)) in ja:
                continue
            out.append(registro("Vivo", "pre", "Vivo Pré %gGB (recarga de R$ %s)" % (g, fmt(preco)), preco=preco,
                                condicao="Por %d dias (tabela de renovação por saldo)" % dias, gb_total=g,
                                beneficios=cel[3] if len(cel) > 3 else "", chave="vivo-pre-saldo-%d-dias-%s" % (dias, fmt(preco))))
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
        # nome a partir do título interno (o campo "nome da oferta" às vezes vem vazio ou trocado, ex.: Família VIP = "TIM Black Plus")
        nome = re.sub(r"^\s*\d+\s*Card(\s*HOME)?\s*-\s*", "", titulo_interno, flags=re.I)
        nome = re.sub(r"\s*\[.*$", "", nome)
        nome = re.sub(r"\b(TOOGLE|TOGGLE)\b", "", nome, flags=re.I)
        nome = re.sub(r"\s+-\s+|\s+", " ", nome).strip(" -")
        nome = nome or limpa(_v(o, "field_nome_da_oferta")) or limpa(_v(o, "field_subtitle"))
        gbtxt = limpa(_v(o, "field_titulo")) or limpa(_v(o, "field_oferta_adicional"))
        preco = num(_v(o, "field_preco_card_oferta"))
        principal = limpa(_v(o, "field_preco_principal_7_1_3"))
        adicional = limpa(_v(o, "field_preco_adicional_original"))
        if preco is None:
            preco = num(principal)
        total = re.search(r"R\$\s*([\d.,]+)\s*/\s*m[eê]s no total", principal)
        pessoa = re.search(r"R\$\s*([\d.,]+)\s*/\s*m[eê]s por pessoa", principal)
        m = re.search(r"R\$\s*[\d.,]+\s*/?\s*([^R]{0,50})", principal)
        cond = limpa(m.group(1)) if m else ""
        cond = re.split(r"\s*(Incluso|Inclu[ií]do|Trazer|Benef|Conferir|Contratar|Assinatura|Sua recarga|B[ôo]nus|\d+\s*GB)", cond)[0].strip()
        if total:  # Família: preço do plano é o total; por pessoa vai na condição
            preco = num(total.group(1))
            cond = "total/mês" + ("; R$ %s por pessoa" % pessoa.group(1) if pessoa else "")
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
            # velocidade do que aparece no card (field_titulo, ex.: "700MEGA"); o título interno às vezes está
            # desatualizado (ex.: "600 MEGA PARAMOUNT" vendido como 700 Mega em SP, nov/26)
            vel = mega(gbtxt) or mega(nome) or mega(titulo_interno)
            vn = mega(nome)
            if vel and vn and vel != vn:
                rot = ("%g GIGA" % (vel / 1000)) if vel >= 1000 else ("%d MEGA" % vel)
                nome = re.sub(r"\d+(?:[.,]\d+)?\s*(MEGA|GIGA)", rot, nome, count=1, flags=re.I)
            out.append(registro("TIM", "fibra", nome if re.search(r"mega|giga", nome, re.I) else "%s %s" % (nome, gbtxt), preco=preco, condicao=cond[:80],
                                velocidade_mega=vel, beneficios="; ".join(filter(None, benef))[:500],
                                extra=json.dumps(extra, ensure_ascii=False), chave=slug("tim-fibra-" + extra["nid"])))
        else:
            out.append(registro("TIM", seg, nome if re.search(r"\d+\s*GB", nome, re.I) else "%s %s" % (nome, gbtxt), preco=preco, condicao=cond[:80],
                                gb_total=gb(gbtxt), gb_detalhe=info[:200], linhas=linhas,
                                beneficios="; ".join(filter(None, benef))[:500],
                                extra=json.dumps(extra, ensure_ascii=False), chave=slug("tim-%s-%s" % (seg, extra["nid"]))))
    return out


def tim_fit(html):
    """TIM Controle Fit (mensal e anual): aparece só como texto na página de Controle, fora do cadastro de ofertas.
    Ex.: 'TIM Controle Fit Anual 2.0 | Tenha 46GB por 12x R$30/mês'."""
    t = limpa(BeautifulSoup(html, "lxml").get_text(" "))
    out, vistos = [], set()
    for m in re.finditer(r"(TIM Controle Fit (Anual|Mensal)\s*[\d.]*)\s+Tenha\s+(\d+)\s*GB\s+por\s+(12x\s*)?R\$\s*([\d.,]+)\s*/\s*m[eê]s([^|]{0,60}?)(?:Saber mais|Contratar|$)", t, re.I):
        nome = re.sub(r"\s+", " ", m.group(1)).strip()
        if nome in vistos:
            continue
        vistos.add(nome)
        anual = m.group(2).lower() == "anual"
        cond = "12x no cartão (contrato anual)" if anual else "mês, cartão"
        out.append(registro("TIM", "lite" if anual else "controle", "%s %sGB" % (nome, m.group(3)), preco=num(m.group(5)),
                            condicao=cond[:80], gb_total=int(m.group(3)), chave=slug("tim-fit-" + nome)))
    return out


# ---------------------------------------------------------------- NuCel
def nucel(texto):
    """Página de produto do NuCel (nubank.com.br/nu/nucel): 'Escolha o plano ideal' com 'NN GB por R$ NN'.
    Preço público (sem desconto de Nubank+/Ultravioleta, que só aparece no app). Chave pela posição de preço
    (1 = mais barato), para o histórico seguir o degrau quando a franquia muda."""
    t = re.sub(r"\s+", " ", texto)
    achados = sorted({(num(p), int(g)) for g, p in re.findall(r"(\d+)\s*GB\s+por\s+R\$\s*([\d.,]+)", t, re.I)})
    out = []
    for i, (preco, gb) in enumerate(achados, 1):
        out.append(registro("NuCel", "controle", "NuCel %dGB" % gb, preco=preco, gb_total=gb,
                            condicao="mês, sem fidelidade (preço sem Nubank+)", chave="nucel-plano-%d" % i))
    return out
