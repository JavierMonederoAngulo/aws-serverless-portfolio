import json
import os
import time
import boto3

# Inicializamos el cliente de Bedrock en el Warm Start
bedrock = boto3.client('bedrock-runtime')
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
IS_COLD_START = True

# Cargamos el CV a memoria RAM solo una vez en el Cold Start
with open('cv.txt', 'r', encoding='utf-8') as file:
    CV_CONTEXT = file.read()

def lambda_handler(event, context):
    global IS_COLD_START
    try:
        raw_body = event.get('body') if isinstance(event, dict) else '{}'
        if raw_body is None:
            raw_body = '{}'
        try:
            body = json.loads(raw_body)
        except (ValueError, TypeError):
            return _build_response(400, {"error": "Invalid JSON payload"})

        if not isinstance(body, dict):
            return _build_response(400, {"error": "Invalid JSON payload"})

        # Extraemos y validamos la pregunta del frontend (1..500 chars tras strip)
        raw_question = body.get('question', '')
        if not isinstance(raw_question, str):
            return _build_response(400, {"error": "Question must be a string up to 500 characters"})

        user_message = raw_question.strip()
        if not user_message:
            return _build_response(400, {"error": "No question provided"})
        if len(user_message) > 500:
            return _build_response(400, {"error": "Question must be a string up to 500 characters"})

        # Validamos el historial opcional (0..6 mensajes, par, user/assistant alternos, 1..1000 chars)
        raw_history = body.get('history', [])
        if raw_history is None:
            raw_history = []
        if not isinstance(raw_history, list) or len(raw_history) > 6:
            return _build_response(400, {"error": "History must be a list of at most 6 messages"})
        if len(raw_history) % 2 != 0:
            return _build_response(400, {"error": "Invalid conversation history format"})

        messages = []
        for idx, item in enumerate(raw_history):
            if not isinstance(item, dict):
                return _build_response(400, {"error": "Invalid conversation history format"})
            expected_role = "user" if idx % 2 == 0 else "assistant"
            role = item.get('role')
            content = item.get('content')
            if role != expected_role or not isinstance(content, str):
                return _build_response(400, {"error": "Invalid conversation history format"})
            trimmed_content = content.strip()
            if not trimmed_content or len(trimmed_content) > 1000:
                return _build_response(400, {"error": "Invalid conversation history format"})
            messages.append({"role": role, "content": trimmed_content})

        messages.append({"role": "user", "content": user_message})

        # Prompt del Sistema: Define la personalidad, idioma y límites del agente
        system_prompt = f"""
        You are the AI portfolio assistant for Javier Monedero Angulo, an Information Systems Engineering student at UPM.
        Your goal is to help recruiters understand his profile based EXCLUSIVELY on this CV:
        <cv>
        {CV_CONTEXT}
        </cv>
        Rules:
        1. Always reply in the exact same language as the user's question (e.g., if the user writes in English, reply in English; if in Spanish, reply in Spanish; if in another language, reply in that language).
        2. Follow the main grammatical language of the user's sentence even when it includes English technical terms (such as AWS, CloudFront, or Serverless). If the input is ambiguous or consists only of acronyms or proper nouns, default to English.
        3. Keep your answer professional, enthusiastic, and concise (maximum 3 sentences).
        4. If asked about something not present in the CV, state in the user's language that you do not have that information and encourage them to contact Javier directly.
        5. Never invent skills, projects, or experience.
        """

        # Preparamos el payload en el formato que exige Claude 3 (Anthropic Messages API)
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "system": system_prompt,
            "messages": messages
        }

        # Invocamos al LLM de forma síncrona midiendo latencia real
        start_time = time.perf_counter()
        response = bedrock.invoke_model(
            modelId="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )
        latency_ms = max(0, int(round((time.perf_counter() - start_time) * 1000)))

        cold_start = IS_COLD_START
        IS_COLD_START = False

        response_body = json.loads(response['body'].read())
        ai_reply = response_body['content'][0]['text']

        usage = response_body.get('usage', {}) if isinstance(response_body, dict) else {}
        input_tokens = int(usage.get('input_tokens', 0))
        output_tokens = int(usage.get('output_tokens', 0))
        estimated_cost_usd = round((input_tokens * 1.0 + output_tokens * 5.0) / 1_000_000, 6)

        telemetry = {
            "latency_ms": latency_ms,
            "cold_start": cold_start,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost_usd,
        }

        return _build_response(200, {"reply": ai_reply, "telemetry": telemetry})

    except Exception as e:
        print(f"Error: {str(e)}") # Se guarda en CloudWatch Logs
        return _build_response(500, {"error": "Internal assistant error."})


def _build_response(status_code, body):
    # Función auxiliar para generar siempre CORS válido
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        },
        "body": json.dumps(body)
    }