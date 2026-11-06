"""Resume a base de portabilidade numérica da Anatel (portabilidade.zip, dados abertos).

Uso: python anatel/portabilidade.py caminho/portabilidade.zip
Imprime um JSON com o último mês (AAAA-MM) e o total de portabilidades efetivadas na
telefonia móvel (SMP) nesse mês, no mês anterior e no mesmo mês do ano anterior.
"""
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict


def main(zip_path):
    tot = defaultdict(int)
    with zipfile.ZipFile(zip_path) as z:
        with z.open("CSV_PORTABILIDADE.csv") as f:
            r = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";")
            for row in r:
                if row.get("SG_SERVICO") == "SMP":
                    tot[row["AM_EFETIVACAO"]] += int(row["QT_PORTABILIDADE_EFETIVADA"] or 0)
    meses = sorted(tot)
    ult = meses[-1]
    ano, mes = ult.split("-")
    ant = meses[-2] if len(meses) > 1 else None
    a12 = f"{int(ano) - 1}-{mes}"
    print(json.dumps({
        "mes": ult,
        "smp": tot[ult],
        "smp_mes_anterior": tot.get(ant) if ant else None,
        "smp_ano_anterior": tot.get(a12),
    }))


if __name__ == "__main__":
    main(sys.argv[1])
