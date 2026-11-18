"""Monta a interface Streamlit da Central de Recrutamento."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

# Garante que a pasta do projeto esteja no sys.path antes de importar o agente.
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agent import MODELO_GROQ, PLANILHA_ID, executar_agente_rh  # type: ignore[reportMissingImports]
from google_tools import (
    CAMPOS_DA_PLANILHA,
    agendar_entrevista_com_meet,
    atualizar_agendamento_calendar,
    atualizar_campos_linha_planilha,
    listar_candidatos_planilha,
    registrar_candidato_planilha,
    _normalizar_campo,
)

# Configuração da página e carregamento do estilo CSS
st.set_page_config(
    page_title="Central de Recrutamento",
    page_icon="💼",
    layout="wide"
)

css_path = Path(__file__).with_name("styles.css")
if css_path.exists():
    st.markdown(f"<style>\n{css_path.read_text(encoding='utf-8')}\n</style>", unsafe_allow_html=True)

# Indicadores de configuração das integrações
groq_configurado = bool(os.environ.get("GROQ_API_KEY"))
google_configurado = os.path.exists("credentials.json")
planilha_configurada = bool(PLANILHA_ID)

# Barra lateral com resumo das integrações e modelo
with st.sidebar:
    st.markdown('<div class="brand-mark">TALENT WORKSPACE</div>', unsafe_allow_html=True)
    st.markdown("## Central de RH")
    st.caption("Assistente de recrutamento")
    st.divider()

    st.markdown("#### Integrações")
    integracoes = [
        ("Assistente de IA", groq_configurado),
        ("Google Workspace", google_configurado),
        ("Planilha de candidatos", planilha_configurada),
    ]
    for label, configurado in integracoes:
        estado = "Configurado" if configurado else "Verificar configuração"
        classe = "ok" if configurado else "off"
        st.markdown(
            f'<div class="status-line"><span class="status-dot {classe}"></span>'
            f'<span>{label}</span></div>',
            unsafe_allow_html=True
        )
        if not configurado:
            st.caption(estado)

    st.divider()
    st.caption("Modelo de IA")
    st.code(MODELO_GROQ, language=None)
    st.caption("Conectado via Groq Cloud")


def valor_do_campo(cabecalho, valores, campo):
    """Localiza os valores dos campos mesmo com variações ou acentuação."""
    aliases = CAMPOS_DA_PLANILHA[campo]
    for indice, titulo in enumerate(cabecalho):
        if _normalizar_campo(titulo) in aliases:
            return valores[indice] if indice < len(valores) else ""
    return ""


def horarios_futuros(data, agora, depois_de=None, ultimo_minuto=1435):
    """Gera horários futuros disponíveis para agendamento."""
    passo_minutos = 5
    primeiro_minuto = 0
    if data == agora.date():
        minuto_atual = agora.hour * 60 + agora.minute
        primeiro_minuto = (minuto_atual // passo_minutos + 1) * passo_minutos
    if depois_de is not None:
        primeiro_minuto = max(primeiro_minuto, depois_de.hour * 60 + depois_de.minute + passo_minutos)
    primeiro_minuto = ((primeiro_minuto + passo_minutos - 1) // passo_minutos) * passo_minutos
    return [
        f"{minuto // 60:02d}:{minuto % 60:02d}"
        for minuto in range(primeiro_minuto, ultimo_minuto + 1, passo_minutos)
    ]


# Cabeçalho Principal
st.markdown('<div class="eyebrow">OPERAÇÕES DE TALENT ACQUISITION</div>', unsafe_allow_html=True)
st.title("Gestão de recrutamento")
st.markdown(
    '<div class="page-subtitle">Histórico, candidatos e agendamentos em um só lugar.</div>',
    unsafe_allow_html=True
)

assistente_tab, solicitacao_tab, painel_tab = st.tabs(
    ["Assistente IA", "Agendar candidato", "Painel e histórico"]
)

with assistente_tab:
    st.subheader("Converse com o assistente")
    st.caption(
        "Peça para registrar um candidato ou agendar uma entrevista. "
        "Se faltarem informações, você pode enviá-las na próxima mensagem."
    )

    if "conversa_agente" not in st.session_state:
        st.session_state.conversa_agente = []

    for mensagem in st.session_state.conversa_agente:
        with st.chat_message(mensagem["role"]):
            st.markdown(mensagem["content"])

    with st.form("mensagem_agente", clear_on_submit=True):
        texto_usuario = st.text_area(
            "Sua solicitação",
            placeholder="Ex.: Registre a Ana Souza, ana@email.com, para a vaga de Analista.",
            height=100,
        )
        enviar_mensagem = st.form_submit_button("Enviar", type="primary")

    if enviar_mensagem:
        if not texto_usuario.strip():
            st.warning("Digite uma solicitação para conversar com o assistente.")
        else:
            historico = list(st.session_state.conversa_agente)
            st.session_state.conversa_agente.append(
                {"role": "user", "content": texto_usuario.strip()}
            )
            with st.spinner("O assistente está processando sua solicitação..."):
                resultados = executar_agente_rh(texto_usuario, historico)

            if any(tipo == "sucesso" for tipo, _ in resultados):
                st.session_state.pop("dados_planilha", None)

            resposta_agente = "\n\n".join(
                f"{'✅' if tipo == 'sucesso' else '⚠️' if tipo == 'erro' else ''} {conteudo}".strip()
                for tipo, conteudo in resultados
            )
            st.session_state.conversa_agente.append(
                {"role": "assistant", "content": resposta_agente}
            )
            st.rerun()

with solicitacao_tab:
    st.subheader("Agendar candidato")
    with st.form("nova_entrevista", clear_on_submit=True):
        nome = st.text_input("Nome completo")
        email = st.text_input("E-mail")
        vaga = st.text_input("Vaga")
        status = st.selectbox("Status", ["Em análise", "Aprovado", "Rejeitado"])
        col_data, col_inicio, col_fim = st.columns(3)
        fuso = timezone(timedelta(hours=-3))
        agora = datetime.now(fuso)
        data = col_data.date_input("Data", value=agora.date(), min_value=agora.date())
        horarios = horarios_futuros(data, agora)
        hora_inicio = col_inicio.selectbox("Hora início", horarios or ["09:00"])
        opcoes_fim = horarios_futuros(data, agora, depois_de=datetime.strptime(hora_inicio, "%H:%M").time())
        hora_fim = col_fim.selectbox("Hora fim", opcoes_fim or ["10:00"])
        enviar = st.form_submit_button("Agendar entrevista", type="primary")

    if enviar:
        if not nome.strip() or "@" not in email:
            st.error("Informe um nome válido e um e-mail correto.")
        elif not PLANILHA_ID:
            st.error("Configure PLANILHA_ID antes de registrar o candidato.")
        else:
            inicio = datetime.combine(data, datetime.strptime(hora_inicio, "%H:%M").time(), tzinfo=fuso)
            fim = datetime.combine(data, datetime.strptime(hora_fim, "%H:%M").time(), tzinfo=fuso)
            if fim <= inicio:
                st.error("O horário de término precisa ser posterior ao início.")
            else:
                try:
                    link = agendar_entrevista_com_meet(
                        nome.strip(), email.strip(), inicio.isoformat(), fim.isoformat()
                    )
                    registrar_candidato_planilha(
                        PLANILHA_ID,
                        nome.strip(),
                        email.strip(),
                        vaga.strip(),
                        status,
                        inicio.isoformat(),
                        fim.isoformat(),
                    )
                    st.success("Entrevista agendada e candidato registrado.")
                    st.link_button("Abrir Google Meet", link)
                    st.session_state.pop("dados_planilha", None)
                except Exception as erro:
                    st.error(f"Não foi possível concluir o agendamento: {erro}")

with painel_tab:
    st.subheader("Histórico de agendamentos")
    if not PLANILHA_ID:
        st.warning("Configure PLANILHA_ID para consultar e editar os registros.")
    else:
        if st.button("Atualizar histórico") or "dados_planilha" not in st.session_state:
            with st.spinner("Carregando registros da planilha..."):
                try:
                    st.session_state.dados_planilha = listar_candidatos_planilha(PLANILHA_ID)
                    st.session_state.erro_planilha = None
                except Exception as erro:
                    st.session_state.erro_planilha = str(erro)

        erro_planilha = st.session_state.get("erro_planilha")
        dados_planilha = st.session_state.get("dados_planilha")
        
        if erro_planilha:
            st.error(f"Não foi possível carregar a planilha: {erro_planilha}")
        elif dados_planilha:
            cabecalho = dados_planilha["cabecalho"]
            registros = dados_planilha["linhas"]
            
            total_agendados = sum(
                bool(valor_do_campo(cabecalho, registro["valores"], "data"))
                for registro in registros
            )
            total_analise = sum(
                "analise" in _normalizar_campo(valor_do_campo(cabecalho, registro["valores"], "status"))
                for registro in registros
            )

            metricas = st.columns(3)
            metricas[0].metric("Candidatos", len(registros))
            metricas[1].metric("Entrevistas com data", total_agendados)
            metricas[2].metric("Em análise", total_analise)

            busca_col, status_col = st.columns([2, 1])
            busca = busca_col.text_input("Buscar por nome, e-mail ou vaga", key="busca_historico")
            
            status_disponiveis = sorted({
                str(valor_do_campo(cabecalho, registro["valores"], "status"))
                for registro in registros
                if valor_do_campo(cabecalho, registro["valores"], "status")
            })
            status_filtro = status_col.selectbox("Filtrar status", ["Todos", *status_disponiveis])

            registros_filtrados = []
            for registro in registros:
                nome = valor_do_campo(cabecalho, registro["valores"], "nome")
                email = valor_do_campo(cabecalho, registro["valores"], "email")
                vaga = valor_do_campo(cabecalho, registro["valores"], "vaga")
                status = valor_do_campo(cabecalho, registro["valores"], "status")
                
                if status_filtro != "Todos" and status != status_filtro:
                    continue
                if busca and busca.casefold() not in f"{nome} {email} {vaga}".casefold():
                    continue
                    
                registros_filtrados.append({
                    "Nome": nome,
                    "E-mail": email,
                    "Vaga": vaga,
                    "Status": status,
                    "Data": valor_do_campo(cabecalho, registro["valores"], "data"),
                    "Horário": valor_do_campo(cabecalho, registro["valores"], "hora"),
                })

            st.dataframe(registros_filtrados, use_container_width=True, hide_index=True)

            if registros:
                st.divider()
                st.subheader("Editar agendamento")
                fuso = timezone(timedelta(hours=-3))
                agora = datetime.now(fuso)
                opcoes_agendamento = {}
                
                for registro in registros:
                    data_atual = valor_do_campo(cabecalho, registro["valores"], "data")
                    horario_atual = valor_do_campo(cabecalho, registro["valores"], "hora")
                    email_atual = valor_do_campo(cabecalho, registro["valores"], "email")
                    
                    if not data_atual or not horario_atual or not email_atual:
                        continue
                        
                    try:
                        try:
                            dia_atual = datetime.strptime(data_atual, "%d/%m/%Y").date()
                        except ValueError:
                            dia_atual = datetime.fromisoformat(data_atual).date()
                        hora_inicio_atual = datetime.strptime(
                            horario_atual.split("-")[0].strip(), "%H:%M"
                        ).time()
                    except ValueError:
                        continue
                        
                    inicio_registro = datetime.combine(dia_atual, hora_inicio_atual, tzinfo=fuso)
                    nome_atual = valor_do_campo(cabecalho, registro["valores"], "nome") or "Sem nome"
                    vaga_atual = valor_do_campo(cabecalho, registro["valores"], "vaga") or "Sem vaga"
                    status_atual = valor_do_campo(cabecalho, registro["valores"], "status") or "Sem status"
                    
                    rotulo = (
                        f"{nome_atual} · {email_atual} · {vaga_atual} · {status_atual} · "
                        f"{dia_atual.strftime('%d/%m/%Y')} · {horario_atual} · "
                        f"linha {registro['numero']}"
                    )
                    opcoes_agendamento[rotulo] = {
                        "registro": registro,
                        "inicio_atual": inicio_registro,
                    }

                if not opcoes_agendamento:
                    st.info("Não há entrevistas futuras com data, horário e e-mail para editar.")
                else:
                    escolha_agendamento = st.selectbox(
                        "Entrevista", list(opcoes_agendamento), key="selecao_agendamento"
                    )
                    agendamento_selecionado = opcoes_agendamento[escolha_agendamento]
                    registro_agendamento = agendamento_selecionado["registro"]
                    valores_agendamento = registro_agendamento["valores"]
                    horario_atual = valor_do_campo(cabecalho, valores_agendamento, "hora")
                    partes_horario = [parte.strip() for parte in horario_atual.split("-")]
                    
                    try:
                        hora_inicio_padrao = datetime.strptime(partes_horario[0], "%H:%M").time()
                        hora_fim_padrao = datetime.strptime(
                            partes_horario[1] if len(partes_horario) > 1 else partes_horario[0],
                            "%H:%M",
                        ).time()
                    except ValueError:
                        hora_inicio_padrao = datetime.strptime("09:00", "%H:%M").time()
                        hora_fim_padrao = datetime.strptime("10:00", "%H:%M").time()

                    data_col, inicio_col, fim_col = st.columns(3)
                    data_padrao = max(agendamento_selecionado["inicio_atual"].date(), agora.date())
                    data_nova = data_col.date_input(
                        "Data",
                        value=data_padrao,
                        min_value=agora.date(),
                        key=f"data_agendamento_{registro_agendamento['numero']}",
                    )
                    
                    opcoes_inicio = horarios_futuros(data_nova, agora, ultimo_minuto=1430)
                    if not opcoes_inicio:
                        st.info("Não há mais horários disponíveis hoje. Escolha outra data.")
                        salvar_agendamento = False
                    else:
                        inicio_padrao_texto = hora_inicio_padrao.strftime("%H:%M")
                        if inicio_padrao_texto not in opcoes_inicio:
                            inicio_padrao_texto = opcoes_inicio[0]
                            
                        hora_inicio_nova = inicio_col.selectbox(
                            "Hora início",
                            opcoes_inicio,
                            index=opcoes_inicio.index(inicio_padrao_texto),
                            key=f"inicio_agendamento_{registro_agendamento['numero']}_{data_nova.isoformat()}",
                        )
                        hora_inicio_valor = datetime.strptime(hora_inicio_nova, "%H:%M").time()
                        
                        opcoes_fim = horarios_futuros(
                            data_nova,
                            agora,
                            depois_de=hora_inicio_valor,
                        )
                        fim_padrao_texto = hora_fim_padrao.strftime("%H:%M")
                        if fim_padrao_texto not in opcoes_fim:
                            fim_padrao_texto = opcoes_fim[0]
                            
                        hora_fim_nova = fim_col.selectbox(
                            "Hora fim",
                            opcoes_fim,
                            index=opcoes_fim.index(fim_padrao_texto),
                            key=f"fim_agendamento_{registro_agendamento['numero']}_{data_nova.isoformat()}_{hora_inicio_nova}",
                        )
                        salvar_agendamento = st.button(
                            "Salvar agendamento",
                            type="primary",
                            key=f"salvar_agendamento_{registro_agendamento['numero']}",
                        )

                    if salvar_agendamento:
                        novo_inicio = datetime.combine(
                            data_nova, datetime.strptime(hora_inicio_nova, "%H:%M").time(), tzinfo=fuso
                        )
                        novo_fim = datetime.combine(
                            data_nova, datetime.strptime(hora_fim_nova, "%H:%M").time(), tzinfo=fuso
                        )
                        
                        if novo_inicio <= datetime.now(fuso):
                            st.error("A entrevista precisa começar em uma data e horário futuros.")
                        elif novo_fim <= novo_inicio:
                            st.error("O horário de término precisa ser posterior ao início.")
                        else:
                            campos_novos = {
                                "data": data_nova.strftime("%d/%m/%Y"),
                                "hora": f"{hora_inicio_nova} - {hora_fim_nova}",
                            }
                            campos_antigos = {
                                "data": valor_do_campo(cabecalho, valores_agendamento, "data"),
                                "hora": valor_do_campo(cabecalho, valores_agendamento, "hora"),
                            }
                            try:
                                atualizar_agendamento_calendar(
                                    valor_do_campo(cabecalho, valores_agendamento, "email"),
                                    agendamento_selecionado["inicio_atual"],
                                    novo_inicio,
                                    novo_fim,
                                    valor_do_campo(cabecalho, valores_agendamento, "nome"),
                                )
                                atualizar_campos_linha_planilha(
                                    PLANILHA_ID,
                                    registro_agendamento["numero"],
                                    campos_novos,
                                )
                                st.success("Agendamento atualizado no Google Calendar e na planilha.")
                                st.session_state.pop("dados_planilha", None)
                            except Exception as erro:
                                st.error(f"Não foi possível atualizar o agendamento: {erro}")