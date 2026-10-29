import json
import os
import boto3

# Inicializamos el cliente de Bedrock en el Warm Start
bedrock = boto3.client('bedrock-runtime')
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

# Cargamos el CV a memoria RAM solo una vez en el Cold Start
with open('cv.txt', 'r', encoding='utf-8') as file:
    CV_CONTEXT = file.read()

def lambda_handler(event, context):
    try:
        # Extraemos la pregunta del frontend
        body = json.loads(event.get('body', '{}'))
        user_message = body.get('question', '')

        if not user_message:
            return _build_response(400, {"error": "No question provided"})

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
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }

        # Invocamos al LLM de forma síncrona
        response = bedrock.invoke_model(
            modelId="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )

        response_body = json.loads(response['body'].read())
        ai_reply = response_body['content'][0]['text']

        return _build_response(200, {"reply": ai_reply})

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