"""Integrações com Google Calendar e Google Sheets."""

import os
import unicodedata
import uuid
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
]

CAMPOS_DA_PLANILHA = {
    "nome": {"nome", "nomecandidato", "candidato"},
    "vaga": {"vaga", "cargo"},
    "data": {"data", "dataentrevista"},
    "hora": {"hora", "horario", "horarioentrevista"},
    "email": {"email", "emailcandidato", "e-mail"},
    "status": {"status", "situacao", "situacao_candidato"},
}


def _normalizar_campo(texto):
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    texto_limpo = "".join(char for char in sem_acento if not unicodedata.combining(char)).lower()
    return "".join(char for char in texto_limpo if char.isalnum())


def autenticar_google():
    """Carrega ou cria credenciais OAuth do Google."""
    credenciais = None
    if os.path.exists("token.json"):
        credenciais = Credentials.from_authorized_user_file("token.json", SCOPES)

    if credenciais and credenciais.expired and credenciais.refresh_token:
        try:
            credenciais.refresh(Request())
        except RefreshError:
            credenciais = None

    if not credenciais or not credenciais.valid:
        if not os.path.exists("credentials.json"):
            raise FileNotFoundError("Arquivo credentials.json não encontrado.")
        fluxo = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        credenciais = fluxo.run_local_server(port=0)

    with open("token.json", "w", encoding="utf-8") as arquivo_token:
        arquivo_token.write(credenciais.to_json())
    return credenciais


def agendar_entrevista_com_meet(nome_candidato, email_candidato, data_hora_inicio, data_hora_fim):
    servico = build("calendar", "v3", credentials=autenticar_google())
    evento = {
        "summary": f"Entrevista com {nome_candidato}",
        "description": "Entrevista de alinhamento com o time de People.",
        "start": {"dateTime": data_hora_inicio, "timeZone": "America/Sao_Paulo"},
        "end": {"dateTime": data_hora_fim, "timeZone": "America/Sao_Paulo"},
        "attendees": [{"email": email_candidato}],
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    evento_criado = servico.events().insert(
        calendarId="primary", body=evento, conferenceDataVersion=1, sendUpdates="all"
    ).execute()
    return evento_criado.get("hangoutLink") or evento_criado.get("htmlLink") or "Agendado"


def listar_candidatos_planilha(id_planilha):
    servico = build("sheets", "v4", credentials=autenticar_google())
    metadados = servico.spreadsheets().get(spreadsheetId=id_planilha).execute()
    folhas = metadados.get("sheets", [])
    if not folhas:
        raise ValueError("A planilha não possui abas.")

    titulo = folhas[0]["properties"]["title"]
    ultima_coluna = "Z"
    resposta = servico.spreadsheets().values().get(
        spreadsheetId=id_planilha, range=f"'{titulo}'!A1:{ultima_coluna}"
    ).execute()
    linhas = resposta.get("values", [])
    cabecalho = linhas[0] if linhas else []
    registros = [{"numero": indice, "valores": valores} for indice, valores in enumerate(linhas[1:], start=2) if any(valores)]
    return {"cabecalho": cabecalho, "linhas": registros, "aba": titulo}


def registrar_candidato_planilha(id_planilha, nome, email, vaga="", status="Em análise", data_hora_inicio=None, data_hora_fim=None):
    servico = build("sheets", "v4", credentials=autenticar_google())
    dados = listar_candidatos_planilha(id_planilha)
    cabecalho = dados["cabecalho"]
    aba = dados["aba"]

    colunas = {}
    for indice, titulo in enumerate(cabecalho):
        titulo_normalizado = _normalizar_campo(titulo)
        for campo, aliases in CAMPOS_DA_PLANILHA.items():
            if titulo_normalizado in aliases:
                colunas[campo] = indice

    if not cabecalho:
        raise ValueError("Adicione um cabeçalho na primeira linha da planilha.")

    dados_linha = {"nome": nome, "email": email, "vaga": vaga, "status": status}
    if data_hora_inicio:
        try:
            inicio = datetime.fromisoformat(data_hora_inicio)
            dados_linha["data"] = inicio.strftime("%d/%m/%Y")
            hora = inicio.strftime("%H:%M")
            if data_hora_fim:
                fim = datetime.fromisoformat(data_hora_fim)
                hora += f" - {fim.strftime('%H:%M')}"
            dados_linha["hora"] = hora
        except ValueError as erro:
            raise ValueError("Formato de data/hora inválido. Use YYYY-MM-DDTHH:MM:SS.") from erro

    largura = max(len(cabecalho), max(colunas.values(), default=-1) + 1)
    valores = [""] * largura
    for campo, valor in dados_linha.items():
        if campo in colunas:
            valores[colunas[campo]] = str(valor)

    servico.spreadsheets().values().append(
        spreadsheetId=id_planilha,
        range=f"'{aba}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [valores]},
    ).execute()
    return "Candidato registrado com sucesso na planilha."


def atualizar_campos_linha_planilha(id_planilha, numero_linha, campos):
    dados = listar_candidatos_planilha(id_planilha)
    cabecalho = dados["cabecalho"]
    aba = dados["aba"]
    atualizacoes = []

    for campo, valor in campos.items():
        aliases = CAMPOS_DA_PLANILHA[campo]
        indice = None
        for posicao, titulo in enumerate(cabecalho):
            if _normalizar_campo(titulo) in aliases:
                indice = posicao
                break
        if indice is not None:
            coluna = chr(ord("A") + indice) if indice < 26 else ""
            if coluna:
                atualizacoes.append({
                    "range": f"'{aba}'!{coluna}{numero_linha}",
                    "values": [[str(valor)]],
                })

    if not atualizacoes:
        return

    servico = build("sheets", "v4", credentials=autenticar_google())
    servico.spreadsheets().values().batchUpdate(
        spreadsheetId=id_planilha,
        body={"valueInputOption": "USER_ENTERED", "data": atualizacoes},
    ).execute()


def atualizar_agendamento_calendar(email, inicio_antigo, novo_inicio, novo_fim, nome_candidato=""):
    servico = build("calendar", "v3", credentials=autenticar_google())
    margem = inicio_antigo.replace(minute=max(0, inicio_antigo.minute - 30))
    fim_busca = inicio_antigo.replace(hour=min(23, inicio_antigo.hour + 12))
    eventos = servico.events().list(
        calendarId="primary",
        timeMin=margem.isoformat(),
        timeMax=fim_busca.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])

    for evento in eventos:
        participantes = evento.get("attendees", [])
        corresponde_email = any(p.get("email", "").lower() == email.lower() for p in participantes)
        corresponde_nome = not nome_candidato or nome_candidato.lower() in evento.get("summary", "").lower()
        if corresponde_email or corresponde_nome:
            evento["start"] = {"dateTime": novo_inicio.isoformat(), "timeZone": "America/Sao_Paulo"}
            evento["end"] = {"dateTime": novo_fim.isoformat(), "timeZone": "America/Sao_Paulo"}
            servico.events().patch(
                calendarId="primary", eventId=evento["id"], body=evento, sendUpdates="all"
            ).execute()
            return True
    raise LookupError("Agendamento correspondente não encontrado no Google Calendar.")
