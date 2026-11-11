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

## Planos das operadoras (Vivo, Claro, TIM)

- Robô: `.github/workflows/alerta-planos.yml` (tópico ntfy `mm-planos-5a4d74767443`), todo dia às 07:23.
- Coleta pré, controle, pós, família e fibra nas 27 capitais direto dos sites (navegador), uma operadora por máquina em paralelo.
- Histórico por vigência em `planos/dados/historico.csv` (cada mudança de preço, GB, condição, benefício ou selo abre uma nova linha);
  log de cada página lida em `planos/dados/coletas.csv`.
- Planilha: `planos/planos_operadoras.xlsx` (abas Atual, Preços por praça, Mudanças, Histórico, Coletas), vai anexa no push e no e-mail.
- Scripts: `planos/coletar.py` (navega), `planos/extrair.py` (lê os cards), `planos/historico.py`, `planos/planilha.py`, `planos/avisar.py`.
