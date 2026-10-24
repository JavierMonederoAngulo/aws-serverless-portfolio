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

        # Prompt del Sistema: Define la personalidad y límites del agente
        system_prompt = f"""
        Eres el asistente virtual de IA de Javier, un estudiante de Ingeniería de Sistemas de la UPM. 
        Tu objetivo es ayudar a reclutadores a entender su perfil basándote EXCLUSIVAMENTE en este CV:
        <cv>
        {CV_CONTEXT}
        </cv>
        Reglas:
        1. Responde de forma profesional, breve (máximo 3 frases) y entusiasta.
        2. Si te preguntan algo que no está en el CV, di que no tienes esa información pero anímalos a contactar con Javier.
        3. Nunca inventes habilidades ni experiencia.
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
        return _build_response(500, {"error": "Error interno del asistente."})


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