# Monitor-dados

Robôs (GitHub Actions) que avisam no app **ntfy** quando sai dado mensal novo.

## Anatel — acessos (móvel e banda larga fixa)

- Robô: `.github/workflows/alerta-anatel-acessos.yml` (tópico ntfy `mm-anatel-1972ee28a387`).
- Vigia a data dos zips de dados abertos da Anatel a cada 5 min e, quando muda, gera a planilha de market share por grupo econômico em `resultados/anatel/anatel_acessos_AAAA-MM.xlsx`.
- Script: `anatel/acessos.py` (dá para rodar no PC: `pip install -r anatel/requirements.txt` e `python anatel/acessos.py`).

Fonte (a mesma base que o painel de acessos da Anatel oferece para download):
- Móvel: https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_telefonia_movel.zip
- Banda larga fixa: https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_banda_larga_fixa.zip
- Catálogo: https://dados.gov.br/dados/conjuntos-dados/acessos-autorizadas-smp e https://dados.gov.br/dados/conjuntos-dados/acessos---banda-larga-fixa

## Comex Stat

- Robô: `.github/workflows/alerta-comexstat.yml` (tópico ntfy `mm-comex-c9e146ff0ec1`).
