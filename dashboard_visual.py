import streamlit as st 
import pandas as pd 
import time 
import re 
import requests 
from requests.auth import HTTPBasicAuth 
from datetime import datetime, timezone, timedelta 
import os 
import json 

from utils import check_password, make_api_request, send_slack_alert 

st.set_page_config(page_title="Monitor Operacional", page_icon="🚀", layout="wide")

if not check_password():
    st.stop()

try:
    APP_ID = st.secrets["INTERCOM_APP_ID"]
except KeyError:
    st.error("❌ Erro Crítico: 'INTERCOM_APP_ID' não encontrado no secrets.toml")
    st.stop()

TEAMS_IDS = ["2975006", "1972225"] 

NOMES_TIMES = {
    2975006: "Customer Success - Atendimento - Distribuição das conversas",
    1972225: "Customer Success"
}

META_AGENTES = 4
META_AIRCALL = 2
FUSO_BR = timezone(timedelta(hours=-3)) 

AGENTS_MAP = {
    "rhayslla.junca@produttivo.com.br": "5281911",
    "douglas.david@produttivo.com.br": "5586698",
    "aline.souza@produttivo.com.br": "5717251",
    "heloisa.atm.slv@produttivo.com.br": "7455039",
    "danielle.ghesini@produttivo.com.br": "7628368",
    "jenyffer.souza@produttivo.com.br": "8115775",
    "jessica.zaruvne@produttivo.com.br": "11020708"
}

@st.cache_data(ttl=60, show_spinner=False)
def get_admin_details(): 
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[admin['id']] = {
                'name': admin['name'],
                'is_away': admin.get('away_mode_enabled', False)
            }
    return dados

@st.cache_data(ttl=60, show_spinner=False)
def get_team_members(team_id):
    url = f"https://api.intercom.io/teams/{team_id}"
    data = make_api_request("GET", url)
    if data: return data.get('admin_ids', [])
    return []

@st.cache_data(ttl=60, show_spinner=False)
def count_conversations(admin_id, state):
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "state", "operator": "=", "value": state},
                {"field": "admin_assignee_id", "operator": "=", "value": admin_id}
            ]
        }
    }
    data = make_api_request("POST", url, json=payload)
    if data: return data.get('total_count', 0)
    return 0

@st.cache_data(ttl=60, show_spinner=False)
def get_team_queue_details(team_id):
    url = "https://api.intercom.io/conversations/search"
    
    # O Intercom exige que IDs sejam strings na busca
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "state", "operator": "=", "value": "open"},
                {"field": "team_assignee_id", "operator": "=", "value": str(team_id)} 
            ]
        },
        "pagination": {"per_page": 150} # Aumentado o limite para trazer mais dados
    }
    
    detalhes_fila = []
    data = make_api_request("POST", url, json=payload)
    
    if data:
        # Pega a primeira página de tickets
        for conv in data.get('conversations', []):
            # Validação mais segura do que "is None"
            if not conv.get('admin_assignee_id'):
                detalhes_fila.append({'id': conv['id']})
                
        # Varre as próximas páginas para garantir que nenhum ticket da fila fique de fora
        pages = data.get('pages', {})
        cursor = pages.get('next', {}).get('starting_after')
        
        limite_paginas = 0 # Prevenção de segurança
        while cursor and limite_paginas < 5:
            payload["pagination"]["starting_after"] = cursor
            data_page = make_api_request("POST", url, json=payload)
            
            if not data_page:
                break
                
            for conv in data_page.get('conversations', []):
                if not conv.get('admin_assignee_id'):
                    detalhes_fila.append({'id': conv['id']})
                    
            pages = data_page.get('pages', {})
            cursor = pages.get('next', {}).get('starting_after')
            limite_paginas += 1
            
    return detalhes_fila

@st.cache_data(ttl=60, show_spinner=False)
def get_daily_stats(team_id, ts_inicio, minutos_recente=30):
    url = "https://api.intercom.io/conversations/search"
    ts_corte_recente = int(time.time()) - (minutos_recente * 60)

    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": ts_inicio},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "pagination": {"per_page": 150}
    }
    
    data = make_api_request("POST", url, json=payload)
    
    stats_periodo = {}
    stats_30min = {}
    detalhes_por_agente = {} 
    total_periodo = 0
    total_recente = 0
    
    if data:
        conversas = data.get('conversations', [])
        total_periodo = len(conversas)
        for conv in conversas: 
            aid = str(conv.get('admin_assignee_id')) if conv.get('admin_assignee_id') else "FILA"
            stats_periodo[aid] = stats_periodo.get(aid, 0) + 1
            
            if aid not in detalhes_por_agente: detalhes_por_agente[aid] = []
            
            detalhes_por_agente[aid].append({
                'id': conv['id'],
                'created_at': conv['created_at'],
                'link': f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{conv['id']}"
            })
            
            if conv['created_at'] > ts_corte_recente:
                stats_30min[aid] = stats_30min.get(aid, 0) + 1
                total_recente += 1
                
    return total_periodo, total_recente, stats_periodo, stats_30min, detalhes_por_agente

@st.cache_data(ttl=60, show_spinner=False) 
def get_latest_conversations(team_id, ts_inicio, limit=10):
    url = "https://api.intercom.io/conversations/search"
    payload = {
        "query": {
            "operator": "AND",
            "value": [
                {"field": "created_at", "operator": ">", "value": ts_inicio},
                {"field": "team_assignee_id", "operator": "=", "value": team_id}
            ]
        },
        "sort": { "field": "created_at", "order": "descending" },
        "pagination": {"per_page": limit}
    }
    data = make_api_request("POST", url, json=payload)
    if data: return data.get('conversations', [])
    return []

@st.cache_data(ttl=60, show_spinner=False)
def get_aircall_stats(ts_inicio):
    """Busca chamadas Aircall e retorna: Stats por Agente, Totais e DETALHES (Link de Áudio)."""
    
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        return {}, 0, {}

    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    params = {
        "from": ts_inicio,
        "order": "desc",
        "per_page": 50,
        "direction": "inbound" 
    }
    
    stats_agente = {} 
    detalhes_ligacoes = {} 
    total_atendidas = 0
    page = 1
    
    while True:
        params['page'] = page
        try:
            response = requests.get(url, auth=auth, params=params)
            if response.status_code != 200:
                break
                
            data = response.json()
            calls = data.get('calls', [])
            
            if not calls:
                break
                
            for call in calls:
                status = call.get('status', '')
                direcao = call.get('direction', '')
                
                # Regra nova: Ignora qualquer ligação que não seja de entrada (inbound)
                if direcao != 'inbound':
                    continue
                
                # Filtra apenas o que foi efetivamente atendido (done e sem motivo de perda)
                if status != 'done' or bool(call.get('missed_call_reason')):
                    continue
                    
                emails_envolvidos = set()
                
                for campo in ['user', 'transferred_by', 'transferred_to']:
                    obj = call.get(campo)
                    if obj and isinstance(obj, dict) and obj.get('email'):
                        emails_envolvidos.add(obj.get('email').lower())
                        
                for u in call.get('users', []):
                    if isinstance(u, dict) and u.get('email'):
                        emails_envolvidos.add(u['email'].lower())
                
                emails_da_equipa = [e for e in emails_envolvidos if e in AGENTS_MAP]
                
                if not emails_da_equipa:
                    continue 

                total_atendidas += 1
                
                for email in emails_da_equipa:
                    intercom_id = AGENTS_MAP[email]
                    stats_agente[intercom_id] = stats_agente.get(intercom_id, 0) + 1
                    
                    if intercom_id not in detalhes_ligacoes: 
                        detalhes_ligacoes[intercom_id] = []
                    
                    ids_ja_registados = [item['id'] for item in detalhes_ligacoes[intercom_id]]
                    if call['id'] not in ids_ja_registados:
                        detalhes_ligacoes[intercom_id].append({
                            'id': call['id'],
                            'started_at': call.get('started_at', 0),
                            'link': f"https://assets.aircall.io/calls/{call['id']}/recording", 
                            'number': call.get('raw_digits', 'Desconhecido')
                        })
                            
            if data.get('meta', {}).get('next_page_link'):
                page += 1
            else:
                break
        except Exception as e:
            print(f"Erro Aircall: {e}")
            break
            
    return stats_agente, total_atendidas, detalhes_ligacoes

@st.cache_data(ttl=60, show_spinner=False)
def get_aircall_users_status():
    """Busca o status atual de disponibilidade dos usuários no Aircall usando o endpoint dedicado."""
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        return {}

    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    # 1. Mapeia os IDs internos do Aircall para os IDs do Intercom usando o e-mail
    aircall_id_to_intercom = {}
    page = 1
    
    while True:
        try:
            response = requests.get("https://api.aircall.io/v1/users", auth=auth, params={"per_page": 50, "page": page})
            if response.status_code != 200: 
                break
                
            data = response.json()
            for u in data.get('users', []):
                email = str(u.get('email', '')).lower().strip()
                if email in AGENTS_MAP:
                    aircall_id = u.get('id')
                    aircall_id_to_intercom[aircall_id] = AGENTS_MAP[email]
                    
            if not data.get('meta', {}).get('next_page_link'): 
                break
            page += 1
        except Exception as e:
            print(f"Erro ao buscar usuários no Aircall: {e}")
            break
            
    # 2. Busca o status em tempo real no endpoint específico de availabilities
    status_agentes = {}
    page = 1
    
    while True:
        try:
            res_avail = requests.get("https://api.aircall.io/v1/users/availabilities", auth=auth, params={"per_page": 50, "page": page})
            if res_avail.status_code != 200: 
                break
            
            data_avail = res_avail.json()
            for u in data_avail.get('users', []):
                ac_id = u.get('id')
                
                # Se o ID recebido pertence a um agente do nosso mapa
                if ac_id in aircall_id_to_intercom:
                    intercom_id = aircall_id_to_intercom[ac_id]
                    
                    # Pega o status exato e garante formatação correta
                    status = str(u.get('availability', 'offline')).lower().strip()
                    status_agentes[intercom_id] = status
                    
            if not data_avail.get('meta', {}).get('next_page_link'): 
                break
            page += 1
        except Exception as e:
            print(f"Erro ao buscar disponibilidades no Aircall: {e}")
            break
            
    return status_agentes

@st.fragment(run_every=60)
def atualizar_painel():
    st.title("🚀 Monitor Operacional (Tempo Real)") 

    if "ultimo_alerta_ts" not in st.session_state: 
        st.session_state["ultimo_alerta_ts"] = 0

    col_filtro, _ = st.columns([1, 3])
    with col_filtro: 
        periodo_selecionado = st.radio(
            "📅 Período de Análise:", 
            ["Hoje (Desde 00:00)", "Últimas 48h"], 
            horizontal=True
        )

    st.markdown("---")

    now = datetime.now(FUSO_BR)
    if "Hoje" in periodo_selecionado:
        ts_inicio = int(now.replace(hour=0, minute=0, second=0).timestamp())
        texto_volume = "Volume (Dia / 30min)"
    else:
        ts_inicio = int((now - timedelta(hours=48)).timestamp())
        texto_volume = "Volume (48h / 30min)"

    admins = get_admin_details()
    
    ids_time_set = set()
    fila = []
    vol_periodo = 0
    vol_rec = 0
    stats_periodo = {}
    stats_rec = {}
    detalhes_agente = {}
    ultimas_temp = []

    for t_id in TEAMS_IDS:
        ids_time_set.update(get_team_members(t_id))
        
        fila_do_time = get_team_queue_details(t_id)
        nome_do_time = NOMES_TIMES.get(t_id, f"Time {t_id}")
        
        for ticket in fila_do_time:
            ticket['nome_time'] = nome_do_time
            
        fila.extend(fila_do_time)
        
        vp, vr, sp, sr, da = get_daily_stats(t_id, ts_inicio)
        vol_periodo += vp
        vol_rec += vr
        
        for aid, val in sp.items(): stats_periodo[aid] = stats_periodo.get(aid, 0) + val
        for aid, val in sr.items(): stats_rec[aid] = stats_rec.get(aid, 0) + val
        
        for aid, lista in da.items():
            if aid not in detalhes_agente: detalhes_agente[aid] = []
            detalhes_agente[aid].extend(lista)
            
        ultimas_temp.extend(get_latest_conversations(t_id, ts_inicio, 10))

    ids_time = list(ids_time_set)
    ultimas = sorted(ultimas_temp, key=lambda x: x['created_at'], reverse=True)[:10]

    stats_aircall, total_atendidas, detalhes_calls = get_aircall_stats(ts_inicio)

    status_aircall_agentes = get_aircall_users_status()
    
    # --- NOVO: Mapeamento visual para o status do Aircall ---
    mapa_status_aircall = {
        'available': '🟢 Disp.',
        'on_mobile': '📱 Mobile',
        'in_call': '📞 Em Chamada',
        'ringing': '🔔 Chamando',
        'after_call_work': '📝 Pós-chamada',
        'offline': '🔴 Offline',
        'on_a_break': '☕ Pausa',
        'out_for_lunch': '🍽️ Almoço',
        'doing_back_office': '💻 Backoffice',
        'do_not_disturb': '⛔ Ocupado',
        'in_training': '🎓 Treinamento'
    }

    online = 0
    online_aircall = 0
    tabela = []
    
    lista_sobrecarga = []
    lista_alta_demanda = []
    
    for mid in ids_time:
        sid = str(mid)
        info = admins.get(sid, {'name': f'ID {sid}', 'is_away': True})
        
        if not info['is_away']: online += 1
        emoji = "🔴" if info['is_away'] else "🟢"
        
        abertos = count_conversations(mid, 'open')
        pausados = count_conversations(mid, 'snoozed')
        volume_recente = stats_rec.get(sid, 0)
        
        ligacoes = stats_aircall.get(sid, 0)
        
        # --- Pega o status do agente no Aircall e formata ---
        status_ac_puro = status_aircall_agentes.get(sid, 'offline')
        status_ac_format = mapa_status_aircall.get(status_ac_puro, f'⚪ {status_ac_puro}')
        
        # --- NOVO: Conta se o agente está online no Aircall (Disponível ou Em Chamada) ---
        if status_ac_puro in ['available', 'in_call', 'on_mobile']:
            online_aircall += 1
        
        alerta = "⚠️" if abertos >= 10 else ""
        raio = "⚡" if volume_recente >= 3 else ""
        
        if abertos >= 10:
            lista_sobrecarga.append(f"{info['name']} ({abertos})")
            
        if volume_recente >= 3:
            lista_alta_demanda.append(f"{info['name']} ({volume_recente})")
            
        tabela.append({
            "Status Int.": emoji,               # Renomeado para não confundir
            "Status Aircall": status_ac_format, # Nova Coluna
            "Agente": info['name'],
            "Abertos": f"{abertos} {alerta}",
            "📞 Aircall": ligacoes, 
            "Volume Período": stats_periodo.get(sid, 0),
            "Recente (30m)": f"{volume_recente} {raio}",
            "Pausados": pausados
        })

    tabela = sorted(tabela, key=lambda x: x['Agente'])
    tabela = sorted(tabela, key=lambda x: x['Status Int.'], reverse=True)

    msg_alerta = []
    
    if len(fila) > 0:
        msg_alerta.append(f"🔥 *CRÍTICO:* Existem *{len(fila)} clientes* aguardando na fila!")
    
    if online < META_AGENTES:
        msg_alerta.append(f"⚠️ *ATENÇÃO INTERCOM:* Equipe abaixo da meta! Apenas *{online}/{META_AGENTES}* online.")

    # --- NOVO: Alerta de equipe abaixo da meta no Aircall ---
    if online_aircall < META_AIRCALL:
        msg_alerta.append(f"📞 *ATENÇÃO AIRCALL:* Equipe de telefonia abaixo da meta! Apenas *{online_aircall}/{META_AIRCALL}* online.")

    if lista_sobrecarga:
        nomes = ", ".join(lista_sobrecarga)
        msg_alerta.append(f"⚠️ *SOBRECARGA:* Agentes com 10+ tickets: {nomes}")

    if lista_alta_demanda:
        nomes = ", ".join(lista_alta_demanda)
        msg_alerta.append(f"⚡ *ALTA DEMANDA:* Agentes a todo vapor (3+ em 30m): {nomes}")

    ARQUIVO_CONTROLE = "ultimo_alerta.json" 
    TEMPO_RESFRIAMENTO = 600
    agora = time.time()
    
    ultimo_envio_geral = 0
    if os.path.exists(ARQUIVO_CONTROLE):
        try:
            with open(ARQUIVO_CONTROLE, "r") as f:
                dados = json.load(f)
                ultimo_envio_geral = dados.get("timestamp", 0)
        except:
            pass 

    if msg_alerta and (agora - ultimo_envio_geral > TEMPO_RESFRIAMENTO):
        try:
            with open(ARQUIVO_CONTROLE, "w") as f:
                json.dump({"timestamp": agora}, f)
        except Exception as e:
            print(f"Erro ao salvar arquivo de controle: {e}")

        texto_final = "*🚨 Alerta Monitor Suporte*\n" + "\n".join(msg_alerta)
        send_slack_alert(texto_final)
            
        st.toast("🔔 Alerta enviado para o Slack!", icon="📨")

    # --- NOVO: Mudamos para 6 colunas para caber a nova métrica ---
    c1, c2, c3, c4, c5, c6 = st.columns(6) 
    
    c1.metric("Fila de Espera", len(fila), "Aguardando", delta_color="inverse")
    c2.metric(texto_volume, f"{vol_periodo} / {vol_rec}")
    
    c3.metric("📞 Ligações (Atendidas)", f"{total_atendidas}")
    
    c4.metric("Online Intercom", online, f"Meta: {META_AGENTES}")
    
    # --- NOVO: Métrica do Aircall na tela ---
    c5.metric("Online Aircall", online_aircall, f"Meta: {META_AIRCALL}")
    
    c6.metric("Atualizado", datetime.now(FUSO_BR).strftime("%H:%M:%S"))

    if len(fila) > 0:
        st.error("🔥 **CRÍTICO: Clientes aguardando na fila!**")
        links_md = ""
        for item in fila:
            c_id = item['id']
            t_nome = item.get('nome_time', 'Geral')
            
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            links_md += f"[**{t_nome}** #{c_id}]({link}) &nbsp;&nbsp; "
        st.markdown(links_md, unsafe_allow_html=True)

    if online < META_AGENTES:
        st.warning(f"⚠️ **Atenção Intercom:** Equipe abaixo da meta!")
        
    # --- NOVO: Aviso vermelho no dashboard se o Aircall cair ---
    if online_aircall < META_AIRCALL:
        st.warning(f"📞 **Atenção Aircall:** Equipe de telefonia abaixo da meta ({online_aircall}/{META_AIRCALL})!")

    st.markdown("---")

    c_left, c_right = st.columns([2, 1])

    with c_left:
        st.subheader("Performance da Equipe")
        st.dataframe(
            pd.DataFrame(tabela), 
            use_container_width=True, 
            hide_index=True,
            column_order=[
                "Status Int.", 
                "Status Aircall", 
                "Agente", 
                "Abertos", 
                "📞 Aircall", 
                "Volume Período", 
                "Recente (30m)", 
                "Pausados"
            ]
        )
        
        st.markdown("---")
        st.subheader("🕵️ Detalhe dos Tickets por Agente")
        
        if len(ids_time) > 0:
            cols = st.columns(3)
            ordem_nomes = [t['Agente'] for t in tabela]
            
            ids_time_ordenados = sorted(ids_time, key=lambda mid: 
                ordem_nomes.index(admins.get(str(mid), {}).get('name', '')) 
                if admins.get(str(mid), {}).get('name', '') in ordem_nomes else 999
            )

            for i, mid in enumerate(ids_time_ordenados):
                sid = str(mid)
                nome = admins.get(sid, {}).get('name', 'Desconhecido')
                tickets = detalhes_agente.get(sid, [])
                
                qtd_calls = stats_aircall.get(sid, 0)
                calls_agente = detalhes_calls.get(sid, []) 
                
                with cols[i % 3]:
                    with st.expander(f"{nome} (T: {len(tickets)} | C: {qtd_calls})"):
                        
                        if tickets:
                            st.caption("📨 **Tickets Intercom**")
                            tickets_sorted = sorted(tickets, key=lambda x: x['created_at'], reverse=True)
                            for t in tickets_sorted:
                                hora = datetime.fromtimestamp(t['created_at'], tz=FUSO_BR).strftime('%H:%M')
                                st.markdown(f"⏰ {hora} - [Abrir Ticket]({t['link']})")
                        
                        if calls_agente:
                            if tickets: st.markdown("---") 
                            st.caption("📞 **Ligações Aircall**")
                            
                            calls_sorted = sorted(calls_agente, key=lambda x: x['started_at'], reverse=True)
                            
                            for c in calls_sorted:
                                hora = datetime.fromtimestamp(c['started_at'], tz=FUSO_BR).strftime('%H:%M')
                                st.markdown(f"🎧 **{hora}** - [Ouvir Ligação]({c['link']})")
                                
                        if not tickets and not calls_agente:
                            st.caption("Sem atividades no período.")
        else:
            st.info("Nenhum agente encontrado no time.")

    with c_right:
        st.subheader("Últimas Atribuições")
        hist_dados = []
        for conv in ultimas:
            dt_obj = datetime.fromtimestamp(conv['created_at'], tz=FUSO_BR)
            hora_fmt = dt_obj.strftime('%d/%m %H:%M')
            
            adm_id = conv.get('admin_assignee_id')
            nome_agente = "Sem Dono"
            if adm_id:
                nome_agente = admins.get(str(adm_id), {}).get('name', 'Desconhecido')
            
            subject = conv.get('source', {}).get('subject', '')
            if not subject:
                body = conv.get('source', {}).get('body', '')
                clean_body = re.sub(r'<[^>]+>', ' ', body).strip()
                if not clean_body and ('<img' in body or '<figure' in body):
                    subject = "📷 [Imagem/Anexo]"
                elif not clean_body:
                    subject = "(Sem texto)"
                else:
                    subject = clean_body[:60] + "..." if len(clean_body) > 60 else clean_body
            
            c_id = conv['id']
            link = f"https://app.intercom.com/a/inbox/{APP_ID}/inbox/conversation/{c_id}"
            
            hist_dados.append({
                "Data/Hora": hora_fmt,
                "Assunto": subject, 
                "Agente": nome_agente,
                "Link": link
            })
        
        if hist_dados:
            st.data_editor(
                pd.DataFrame(hist_dados),
                column_config={
                    "Link": st.column_config.LinkColumn("Ticket", display_text="Abrir"),
                    "Assunto": st.column_config.TextColumn("Resumo", width="large")
                },
                hide_index=True,
                disabled=True,
                use_container_width=True,
                key=f"hist_{int(time.time())}" 
            )
        else:
            st.info("Sem conversas no período.")

    st.markdown("---")
    with st.expander("ℹ️ **Legenda e Ações**"):
        st.markdown("""
        **💬 Intercom (Tickets)**
        * 🟢/🔴 **Status Int.:** Online ou Ausente (Away).
        * ⚠️ **Sobrecarga:** Agente com 10+ tickets abertos.
        * ⚡ **Alta Demanda:** Agente recebeu 3+ tickets em 30min.
        
        **📞 Aircall (Telefonia)**
        * 🟢 **Disp. / 📱 Mobile:** Online e disponível para receber ligações.
        * 📞 **Em Chamada / 🔔 Chamando:** Atualmente em atendimento.
        * 📝 **Pós-chamada:** Finalizando o registro do atendimento anterior.
        * 🔴 **Offline / ☕ Pausa / 🍽️ Almoço / ⛔ Ocupado:** Indisponível para receber chamadas.
        """)

atualizar_painel()








