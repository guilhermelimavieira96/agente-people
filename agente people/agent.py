"""Interpreta pedidos dos usuários e executa ações no Google."""

import json
import os
import unicodedata

from dotenv import load_dotenv
from openai import OpenAI

from google_tools import agendar_entrevista_com_meet, registrar_candidato_planilha

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODELO_GROQ = "openai/gpt-oss-20b"
PLANILHA_ID = os.getenv("PLANILHA_ID")

client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if GROQ_API_KEY else None

FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "agendar_entrevista_com_meet",
            "description": "Agendar uma entrevista no Google Calendar com link do Google Meet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string"},
                    "email_candidato": {"type": "string"},
                    "data_hora_inicio": {"type": "string", "description": "Data/hora ISO 8601."},
                    "data_hora_fim": {"type": "string", "description": "Data/hora ISO 8601."},
                },
                "required": ["nome_candidato", "email_candidato", "data_hora_inicio", "data_hora_fim"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_candidato_planilha",
            "description": "Registrar informações do candidato na planilha do Google Sheets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "email": {"type": "string"},
                    "vaga": {"type": "string"},
                    "status": {"type": "string"},
                    "data_hora_inicio": {"type": "string"},
                    "data_hora_fim": {"type": "string"},
                },
                "required": ["nome", "email"],
            },
        },
    },
]

PROMPT = (
    "Você é um agente de recrutamento e conversa em português. "
    "Quando o usuário pedir para registrar ou adicionar um candidato, colete nome e e-mail "
    "e use registrar_candidato_planilha se PLANILHA_ID estiver disponível. "
    "Vaga e status são opcionais; não exija data ou horário para um registro simples. "
    "Só agende uma entrevista se o usuário pedir um agendamento. Nesse caso, colete nome, "
    "e-mail, início e fim; não invente dados ausentes. Quando PLANILHA_ID estiver disponível, "
    "registre também o candidato após agendar a entrevista."
)


def normalizar(texto):
    """Remove acentos e converte para minúsculas."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(letra for letra in sem_acento if not unicodedata.combining(letra)).lower()


def executar_agente_rh(mensagem_usuario, historico=None):
    """Interpreta a mensagem e executa as ferramentas solicitadas."""
    if client is None:
        return [("erro", "Configure GROQ_API_KEY para usar o agente.")]
    if not isinstance(mensagem_usuario, str) or not mensagem_usuario.strip():
        return [("erro", "Informe uma solicitação válida.")]

    try:
        mensagens = [{"role": "system", "content": PROMPT}]
        if historico:
            mensagens.extend(
                {"role": item["role"], "content": item["content"]}
                for item in historico
                if item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
            )
        mensagens.append({"role": "user", "content": mensagem_usuario.strip()})

        resposta = client.chat.completions.create(
            model=MODELO_GROQ,
            messages=mensagens,
            tools=FERRAMENTAS,
            tool_choice="auto",
        )
        mensagem = resposta.choices[0].message
        tool_calls = mensagem.tool_calls or []

        if not tool_calls:
            return [("texto", mensagem.content or "Não foi possível interpretar a solicitação.")]

        resultados = []
        for chamada in tool_calls:
            nome = chamada.function.name
            args = json.loads(chamada.function.arguments or "{}")

            if nome == "agendar_entrevista_com_meet":
                resultado = agendar_entrevista_com_meet(
                    args["nome_candidato"],
                    args["email_candidato"],
                    args["data_hora_inicio"],
                    args["data_hora_fim"],
                )
                resultados.append(("sucesso", f"Entrevista agendada: {resultado}"))
            elif nome == "registrar_candidato_planilha":
                if not PLANILHA_ID:
                    resultados.append(("erro", "Configure PLANILHA_ID."))
                else:
                    resultado = registrar_candidato_planilha(
                        PLANILHA_ID,
                        args["nome"],
                        args["email"],
                        args.get("vaga", ""),
                        args.get("status", "Em análise"),
                        args.get("data_hora_inicio"),
                        args.get("data_hora_fim"),
                    )
                    resultados.append(("sucesso", resultado))
            else:
                resultados.append(("erro", f"Ferramenta desconhecida: {nome}"))

        return resultados
    except (json.JSONDecodeError, KeyError, ValueError) as erro:
        return [("erro", f"Não foi possível processar os dados: {erro}")]
    except Exception as erro:
        return [("erro", f"Falha ao executar o agente: {erro}")]
