#!/usr/bin/env python3
"""Compara a consulta da CVM com o estado salvo e diz o que avisar.

Uso: python cvm44/processar.py [--teste] [--ping]
Lê/escreve estado/cvm44.json. Imprime JSON:
  {"ok": bool, "erro": str, "mudou": bool, "pushes": [{"titulo","prio","tags","click","msg"}]}
--teste: não grava estado; gera um push de teste com o resumo da consulta.
--ping : além do normal, gera o aviso diário "robô ok" com quem já entregou o mês.
"""
import json, os, subprocess, sys
from datetime import date

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
ESTADO = os.path.join(RAIZ, "estado", "cvm44.json")
CONSULTA = "https://www.rad.cvm.gov.br/ENETWeb/frmConsultaExternaCVM.aspx"
EXCEL = "https://github.com/mmagalhaes2001/Monitor-dados/raw/main/cvm44/negociacoes_cvm44.xlsx"
sys.path.insert(0, AQUI)
import planilha, analise  # noqa: E402


def juntar_pngs(pngs, saida):
    """Empilha os gráficos (insiders + recompra) num PNG só."""
    if len(pngs) == 1: return pngs[0]
    try:
        from PIL import Image
        ims = [Image.open(p) for p in pngs]
        w = max(i.width for i in ims); h = sum(i.height for i in ims)
        out = Image.new("RGB", (w, h), "white"); y = 0
        for i in ims: out.paste(i, (0, y)); y += i.height
        out.save(saida); return saida
    except Exception:
        return pngs[0]


def mes_ref():
    """Mês de referência cujo formulário vence agora: o mês anterior, como MM/AAAA."""
    h = date.today()
    m, a = (12, h.year - 1) if h.month == 1 else (h.month - 1, h.year)
    return "%02d/%d" % (m, a)


def carregar():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"vistos": {}}


def salvar(est):
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main():
    teste = "--teste" in sys.argv
    ping = "--ping" in sys.argv
    r = json.loads(subprocess.run([sys.executable, os.path.join(AQUI, "checar.py"), "45"],
                                  capture_output=True, text=True, timeout=120).stdout or "{}")
    if not r.get("ok"):
        print(json.dumps({"ok": False, "erro": r.get("erro", "sem resposta"), "mudou": False, "pushes": []}, ensure_ascii=False))
        return

    est = carregar()
    vistos = est.setdefault("vistos", {})
    primeira = not vistos
    novos = [d for d in r["docs"] if d["protocolo"] and d["protocolo"] not in vistos]
    pushes = []
    tickers = [e["ticker"] for e in __import__("csv").DictReader(open(os.path.join(AQUI, "empresas.csv"), encoding="utf-8"), delimiter=";")]
    ref = mes_ref()

    def entregou(t, qual):
        return any(v["ticker"] == t and v["ref"] == ref and (("Consolidada" in v["tipo"]) == (qual == "C")) for v in vistos.values())

    def mapa():
        """Quem já entregou o mês de referência: ambos / só um / nenhum."""
        ambos = [t for t in tickers if entregou(t, "C") and entregou(t, "I")]
        parcial = ["%s (%s)" % (t, "só consolidado" if entregou(t, "C") else "só individual")
                   for t in tickers if entregou(t, "C") != entregou(t, "I")]
        nenhum = [t for t in tickers if not entregou(t, "C") and not entregou(t, "I")]
        return ambos, parcial, nenhum

    if teste:
        pushes.append({"titulo": "Teste CVM 44", "prio": "high", "tags": "test_tube", "click": CONSULTA,
                       "msg": "Leitura ok: %d formulários nos últimos 45 dias, %d novos em relação ao estado. Último: %s %s (%s)."
                       % (len(r["docs"]), len(novos), r["docs"][-1]["ticker"], r["docs"][-1]["ref"], r["docs"][-1]["entrega"]) if r["docs"] else "Leitura ok, nenhum formulário no período."})
        print(json.dumps({"ok": True, "mudou": False, "pushes": pushes}, ensure_ascii=False))
        return

    if primeira:
        for d in r["docs"]:
            vistos[d["protocolo"]] = d
        planilha.processar(r["docs"]); planilha.gerar()
        salvar(est)
        print(json.dumps({"ok": True, "mudou": True, "pushes": [], "info": "primeira leitura: %d guardados" % len(r["docs"])}, ensure_ascii=False))
        return

    # Baixa e lê os novos; regenera o Excel
    falhas = []
    if novos:
        try:
            _, falhas = planilha.processar(novos); planilha.gerar()
        except Exception as e:
            falhas.append("planilha: " + str(e)[:100])

    # Agrupa novos por empresa: um push por empresa, clique abre a Consolidada (ou a que houver)
    por_t = {}
    for d in novos:
        por_t.setdefault(d["ticker"], []).append(d)
        vistos[d["protocolo"]] = d
    for t, ds in por_t.items():
        cons = [d for d in ds if "Consolidada" in d["tipo"]]
        alvo = cons[0] if cons else ds[0]
        partes, analises, nivel, pngs = [], [], "baixa", []
        ordem = {"baixa": 0, "media": 1, "alta": 2}
        for d in ds:
            tipo = "Consolidado/insiders" if "Consolidada" in d["tipo"] else "Individual/recompra"
            partes.append("%s (ref %s%s) às %s" % (tipo, d["ref"], ", versão " + d["versao"] if d["versao"] != "1" else "", d["entrega"][-5:]))
            try:
                png = os.path.join(RAIZ, "estado", "grafico_%s.png" % d["protocolo"])
                a = analise.analisar(d["protocolo"], png)
                if a["texto"]: analises.append(a["texto"])
                if ordem[a["nivel"]] > ordem[nivel]: nivel = a["nivel"]
                if a["png"]: pngs.append(a["png"])
            except Exception as e:
                falhas.append("análise %s: %s" % (d["protocolo"], str(e)[:80]))
        tag = {"alta": "RELEVANTE", "media": "atenção", "baixa": "rotina"}[nivel]
        pushes.append({"titulo": "CVM 44 · %s · %s" % (t, tag),
                       "prio": {"alta": "urgent", "media": "high", "baixa": "default"}[nivel],
                       "tags": {"alta": "rotating_light", "media": "eyes", "baixa": "page_facing_up"}[nivel],
                       "click": alvo["link"],
                       "msg": "%s — %s. %s. Entregue %s. Toque para abrir o PDF. Excel: %s"
                              % (ds[0]["nome"], "; ".join(partes), " | ".join(analises) or "sem movimentação", alvo["entrega"][:10], EXCEL),
                       "anexo": juntar_pngs(pngs, os.path.join(RAIZ, "estado", "grafico_%s.png" % t)) if pngs else ""})
    if falhas:
        pushes.append({"titulo": "CVM 44: falha ao ler formulário", "prio": "default", "tags": "warning", "click": CONSULTA,
                       "msg": "; ".join(falhas)[:800]})

    if ping:
        ambos, parcial, nenhum = mapa()
        msg = "Ref %s — entregaram os 2 formulários (%d): %s." % (ref, len(ambos), ", ".join(ambos) or "ninguém")
        if parcial: msg += " Parcial (%d): %s." % (len(parcial), ", ".join(parcial))
        msg += " Faltam (%d): %s. Sigo checando." % (len(nenhum), ", ".join(nenhum) or "ninguém")
        pushes.append({"titulo": "Robô CVM 44 ok (%s)" % date.today().strftime("%d/%m"), "prio": "low", "tags": "robot", "click": CONSULTA, "msg": msg})

    if novos:
        salvar(est)
    print(json.dumps({"ok": True, "mudou": bool(novos), "pushes": pushes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
