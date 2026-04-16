# 🚀 Monitor Operacional (Tempo Real)

Este projeto é um painel de monitoramento ao vivo (Dashboard) desenvolvido em Python (Streamlit). Ele integra dados do **Intercom** (atendimento por texto) e **Aircall** (atendimento por voz) para dar visibilidade instantânea sobre a operação.

Abaixo está a explicação simples de como o sistema funciona e o que você encontra nele:

---

## 1. 📊 Painel Principal (Monitor Operacional)
**Arquivo:** `dashboard_visual.py`

Esta é a tela principal do sistema, que se atualiza automaticamente a cada 60 segundos. Ela é projetada para ficar aberta numa TV ou segundo monitor da gestão e da equipe. O que você encontra aqui:

* **Métricas Globais (Topo da tela):**
  * **Fila de Espera:** Avisa na hora quantos clientes estão parados aguardando o primeiro atendimento.
  * **Volume Geral:** Quantos chamados entraram hoje (ou nas últimas 48h) e um recorte de quantos chegaram só nos últimos 30 minutos.
  * **Ligações:** Conta em tempo real quantas chamadas telefônicas já foram atendidas no dia.
  * **Agentes Online:** Compara quem está logado com a "Meta" de pessoas que deveriam estar trabalhando.

* **Performance da Equipe (Tabela Central):** * Lista todos os agentes e mostra quem está 🟢 Online ou 🔴 Ausente.
  * Revela quem está com muitos chamados acumulados (marca com um ⚠️ quem tem 10+ tickets).
  * Revela quem está "apagando incêndio" (marca com um ⚡ quem pegou 3+ tickets em apenas 30 minutos).

* **Detalhamento e Auditoria:** * Clicando no nome de um atendente, abre-se uma gaveta com o histórico exato do que ele está fazendo: links diretos para ler os tickets dele no Intercom e links diretos para escutar as gravações das chamadas no Aircall.

* **Últimas Atribuições:** * Um "Feed" (estilo linha do tempo) mostrando os chamados que acabaram de entrar, os assuntos e com quem caíram.

---

## 2. 🔔 Sistema de Alertas Inteligentes (Slack)
**Arquivo de apoio:** `utils.py`

Mais do que apenas mostrar dados na tela, o sistema possui um "Robô Vigia" que manda mensagens automaticamente no grupo do Slack da empresa caso note algum problema:
* 🔥 **Crítico na Fila:** Avisa imediatamente se tiver cliente esperando sem atendimento.
* 📉 **Falta de Pessoal:** Alerta se a equipe online cair abaixo da meta necessária.
* ⚠️ **Gargalo / Sobrecarga:** Notifica se alguém juntar mais de 10 chamados em aberto.
* ⚡ **Pico de Demanda:** Notifica se alguém receber muitos tickets (3+) em menos de 30 minutos.

---

## ⚙️ Acesso e Segurança
O painel é protegido por uma tela de login. Além disso, todas as integrações com os sistemas da empresa (Intercom, Aircall e Slack) não ficam expostas no código, sendo puxadas de um "cofre" virtual seguro de senhas.
