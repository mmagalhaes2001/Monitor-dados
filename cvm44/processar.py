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
import planilha  # noqa: E402


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

    def entregou(t):
        return any(v["ticker"] == t and v["ref"] == ref and "Consolidada" in v["tipo"] for v in vistos.values())

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
        partes = ["%s (ref %s%s) às %s" % ("Consolidada" if "Consolidada" in d["tipo"] else "Individual", d["ref"],
                                           ", versão " + d["versao"] if d["versao"] != "1" else "", d["entrega"][-5:]) for d in ds]
        res = planilha.resumo(alvo["protocolo"]) if cons else ""
        pushes.append({"titulo": "CVM 44: %s entregou formulário" % t, "prio": "urgent", "tags": "rotating_light",
                       "click": alvo["link"],
                       "msg": "%s — %s.%s Entregue em %s. Toque para abrir o PDF. Excel atualizado: %s"
                              % (ds[0]["nome"], "; ".join(partes), (" " + res[0].upper() + res[1:] + ".") if res else "", alvo["entrega"][:10], EXCEL)})
    if falhas:
        pushes.append({"titulo": "CVM 44: falha ao ler formulário", "prio": "default", "tags": "warning", "click": CONSULTA,
                       "msg": "; ".join(falhas)[:800]})

    if ping:
        feitos = [t for t in tickers if entregou(t)]
        faltam = [t for t in tickers if not entregou(t)]
        pushes.append({"titulo": "Robô CVM 44 ok (%s)" % date.today().strftime("%d/%m"), "prio": "low", "tags": "robot", "click": CONSULTA,
                       "msg": "Ref %s — entregaram (%d): %s. Faltam (%d): %s. Sigo checando." % (ref, len(feitos), ", ".join(feitos) or "ninguém", len(faltam), ", ".join(faltam) or "ninguém")})

    if novos:
        salvar(est)
    print(json.dumps({"ok": True, "mudou": bool(novos), "pushes": pushes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
