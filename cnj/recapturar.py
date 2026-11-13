"""Conserto automático do leitor do painel de saúde do CNJ.

Quando o cnj/saude_dados.py para de funcionar (o CNJ republicou o painel com outra estrutura),
este script:
  1. acha o link atual do Power BI na página do CNJ;
  2. abre o painel num navegador headless, clica em "Saúde Suplementar" e grava as consultas
     que o próprio painel faz;
  3. reconhece nelas as medidas que usamos (pelo nome antigo ou por palavras-chave);
  4. grava um templates_saude.json novo num arquivo temporário e testa: cards numéricos,
     série mensal com histórico e soma de casos novos do ano = card de casos novos do ano;
  5. só se o teste passar, substitui cnj/templates_saude.json.

Uso: python cnj/recapturar.py   -> imprime JSON {"ok": bool, "detalhe": ..., "mudancas": [...]}
"""
import copy
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

AQUI = pathlib.Path(__file__).parent
ATUAL = AQUI / "templates_saude.json"
PAGINA = "https://justica-em-numeros.cnj.jus.br/painel-saude/"
PADRAO = ("https://app.powerbi.com/view?r=eyJrIjoiZGFiMTIxNzAtNWY4ZC00OWQzLWIwOGMtOTYwNDgyY2VhOTY5Iiwid"
          "CI6ImFkOTE5MGU2LWM0NWQtNDYwMC1iYzVjLWVjYTU1NGNjZjQ5NyIsImMiOjJ9")

# chave lógica -> (nome antigo, teste por palavras-chave no nome em minúsculas)
REGRAS = {
    "pendentes": ("medidas_matéria.ultimo_mes_pendentes_temas",
                  lambda n: "pend" in n and "ultim" in n and "liq" not in n and "temp" not in n),
    "tempo_medio_pendente_dias": ("medidas_matéria.Temp_CP_Ind19_media_ultimo_ano_assunto",
                                  lambda n: "ind19" in n or ("temp_cp" in n and "cpl" not in n)),
    "tempo_medio_pendente_liquido_dias": ("medidas_matéria.Temp_CPL_Ind18_media_ultimo_ano_assunto",
                                          lambda n: "ind18" in n or "temp_cpl" in n),
    "baixados_no_ano": ("medidas_matéria.ano_atual_baixados_temas",
                        lambda n: "baixados" in n and "ano_atual" in n),
    "tempo_medio_primeira_baixa_dias": ("medidas_matéria.Temp_baixa_Ind16_media_ultimo_ano_assunto_temas",
                                        lambda n: "ind16" in n or ("temp" in n and "baixa" in n)),
    "casos_novos_no_ano": ("medidas_matéria.ano_atual_novos_temas",
                           lambda n: "novos" in n and "ano_atual" in n),
    "data": ("Medidas.Texto_data", lambda n: "texto_data" in n),
}


PAGINA_SAUDE = "fb5a27b946fb01e949ce"  # página "Temas Saúde" no relatório (se mudar, o script procura)


def link_painel():
    try:
        req = urllib.request.Request(PAGINA, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        m = re.search(r"https://app\.powerbi\.com/view\?r=[A-Za-z0-9=_-]+", html)
        if m:
            return m.group(0) + f"&pageName={PAGINA_SAUDE}"
    except Exception:
        pass
    return PADRAO + f"&pageName={PAGINA_SAUDE}"


def capturar(url):
    from playwright.sync_api import sync_playwright
    caps = []

    def on_resp(r):
        if "querydata" in r.url and r.request.method == "POST":
            try:
                caps.append({"url": r.url.split("?")[0], "chave": r.request.headers.get("x-powerbi-resourcekey"),
                             "req": json.loads(r.request.post_data), "resp": r.json()})
            except Exception:
                pass

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("response", on_resp)
        pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            pg.wait_for_selector("text=/atualizado em/", state="attached", timeout=90_000)
        except Exception:
            pass
        pg.wait_for_timeout(8_000)
        botao = pg.locator("text=/Sa[úu]de Suplementar/ >> visible=true")
        # O relatório tem várias páginas (o painel de saúde é uma delas): avança até achar o botão
        for _ in range(20):
            if botao.count():
                break
            prox = pg.locator("button[aria-label='Next Page'], button[aria-label='Próxima página'], "
                              "button[aria-label*='Next'], button[aria-label*='Próxima']")
            if not prox.count():
                break
            prox.first.click(force=True)
            pg.wait_for_timeout(8_000)
        antes = len(caps)
        bb = botao.first.bounding_box(timeout=30_000)
        pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        pg.wait_for_timeout(20_000)
        b.close()
    return caps[antes:] or caps


def consultas(caps):
    """Lista (nomes do Select, consulta, modelId, version, From) de todas as consultas capturadas."""
    out = []
    for c in caps:
        for q in c["req"]["queries"]:
            sq = q["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"]
            nomes = [s.get("Name", "") for s in sq["Select"]]
            out.append((nomes, q, c["req"].get("modelId"), c["req"].get("version"), sq))
    return out


def montar(caps):
    qs = consultas(caps)
    novo = {"_config": {"url": caps[0]["url"], "chave": caps[0]["chave"], "nomes": {}}}
    mud = []
    for chave, (antigo, regra) in REGRAS.items():
        achado = None
        for nomes, q, mid, ver, sq in qs:
            if nomes and (nomes[0] == antigo):
                achado = (nomes[0], q, mid, ver)
                break
        if not achado:
            for nomes, q, mid, ver, sq in qs:
                if nomes and regra(nomes[0].lower()):
                    achado = (nomes[0], q, mid, ver)
                    mud.append(f"{chave}: {antigo} -> {nomes[0]}")
                    break
        if not achado:
            raise LookupError(f"não achei a consulta de {chave}")
        nome, q, mid, ver = achado
        novo[nome] = {"query": q, "modelId": mid, "version": ver, "cancelQueries": []}
        novo["_config"]["nomes"][chave] = nome

    # série mensal: candidatas = consultas com uma coluna (não medida) + soma de casos novos.
    # Ficam em novo["_candidatas_mensal"]; o main testa uma a uma (a anual também casa, a validação descarta).
    cands = []
    for nomes, q, mid, ver, sq in qs:
        cn = [n for n in nomes if re.search(r"Sum\(.*\.CN\)$", n)]
        bx = [n for n in nomes if n.startswith("Sum(") and ("TBaix" in n or "baix" in n.lower())]
        col = sq["Select"][0].get("Column", {})
        if cn and col:
            alias = col.get("Expression", {}).get("SourceRef", {}).get("Source")
            ent = next((f["Entity"] for f in sq["From"] if f["Name"] == alias), None)
            cands.append((0 if bx else 1, {
                "nome": nomes[0], "tpl": {"query": q, "modelId": mid, "version": ver, "cancelQueries": []},
                "cols_mensal": {"mes": nomes[0], "casos_novos": cn[0], "baixados": bx[0] if bx else ""},
                "col_data": col.get("Property"), "ent_data": ent}))
    if not cands:
        raise LookupError("não achei a série mensal")
    novo["_candidatas_mensal"] = [c for _, c in sorted(cands, key=lambda x: x[0])]

    # coluna do filtro de matéria (a que tem 'Suplementar' no Where)
    for nomes, q, mid, ver, sq in qs:
        for w in sq.get("Where", []):
            cond = w["Condition"].get("In")
            if cond and "Suplementar" in json.dumps(cond["Values"], ensure_ascii=False):
                novo["_config"]["col_materia"] = cond["Expressions"][0]["Column"]["Property"]
                break
        if "col_materia" in novo["_config"]:
            break
    return novo, mud


def validar(caminho):
    env = dict(os.environ, CNJ_TEMPLATES=str(caminho))
    r = subprocess.run([sys.executable, str(AQUI / "saude_dados.py")], capture_output=True, text=True,
                       env=env, timeout=300)
    d = json.loads(r.stdout or "{}")
    if "erro" in d or r.returncode:
        return False, d.get("erro", r.stderr[-300:])
    c = d["cards"]
    if not all(isinstance(v, (int, float)) and v > 0 for v in c.values()):
        return False, f"cards inválidos: {c}"
    if len(d["mensal"]) < 24:
        return False, f"série mensal curta ({len(d['mensal'])} meses)"
    ano = d["mensal"][-1]["mes"][:4]
    soma = sum(r["casos_novos"] or 0 for r in d["mensal"] if r["mes"].startswith(ano))
    if abs(soma - c["casos_novos_no_ano"]) > 0.005 * c["casos_novos_no_ano"]:
        return False, f"soma mensal {soma} != card {c['casos_novos_no_ano']}"
    if "atualizado" not in (d.get("data_texto") or ""):
        return False, f"frase de data estranha: {d.get('data_texto')}"
    return True, f"ok: {d['data_texto'][:40]}..., pendentes {c['pendentes']}"


def main():
    try:
        caps = capturar(link_painel())
        if not caps:
            raise RuntimeError("o painel não fez nenhuma consulta (não carregou?)")
        novo, mud = montar(caps)
        cands = novo.pop("_candidatas_mensal")
        ok, det = False, "nenhuma candidata de série mensal passou no teste"
        for c in cands:
            teste = copy.deepcopy(novo)
            teste[c["nome"]] = c["tpl"]
            cfg = teste["_config"]
            cfg["nomes"]["mensal"] = c["nome"]
            cfg["cols_mensal"], cfg["col_data"], cfg["ent_data"] = c["cols_mensal"], c["col_data"], c["ent_data"]
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(teste, f, ensure_ascii=False)
            ok, det = validar(f.name)
            if ok:
                if c["nome"] != "tbl_fato_materias_R.primeiro_dia":
                    mud.append(f"mensal: -> {c['nome']}")
                ATUAL.write_text(json.dumps(teste, ensure_ascii=False))
                break
        print(json.dumps({"ok": ok, "detalhe": det, "mudancas": mud}, ensure_ascii=False))
        sys.exit(0 if ok else 1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "detalhe": f"{type(e).__name__}: {e}"[:400], "mudancas": []}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
