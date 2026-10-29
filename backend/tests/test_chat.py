import io
import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


BACKEND_SRC = Path(__file__).resolve().parent.parent / "src"
CHAT_PATH = BACKEND_SRC / "chat.py"


def _load_chat_module(allowed_origin="https://d3vjauql06bl7n.cloudfront.net"):
    """Load backend/src/chat.py with mocked boto3 client and real in-memory cv.txt."""
    mock_bedrock = MagicMock()
    with patch.dict(os.environ, {"ALLOWED_ORIGIN": allowed_origin}, clear=False):
        with patch("boto3.client", return_value=mock_bedrock) as mock_client_factory:
            cwd = os.getcwd()
            try:
                os.chdir(BACKEND_SRC)
                spec = importlib.util.spec_from_file_location("chat", CHAT_PATH)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                os.chdir(cwd)
    mock_client_factory.assert_called_once_with("bedrock-runtime")
    return module, mock_bedrock


def _mock_bedrock_reply(mock_bedrock, text):
    payload_bytes = json.dumps({"content": [{"text": text}]}).encode("utf-8")
    mock_bedrock.invoke_model.return_value = {"body": io.BytesIO(payload_bytes)}


class TestChatHandler(unittest.TestCase):
    # =====================================================================
    # Foundational Tests: Warm-start context loading & HTTP error handling
    # =====================================================================

    def test_cv_context_loaded_once_at_module_init(self):
        chat_module, _ = _load_chat_module()
        expected_cv = (BACKEND_SRC / "cv.txt").read_text(encoding="utf-8")
        self.assertEqual(chat_module.CV_CONTEXT, expected_cv)
        self.assertGreater(len(chat_module.CV_CONTEXT), 100)

    def test_empty_or_missing_question_returns_400_with_cors(self):
        chat_module, mock_bedrock = _load_chat_module()

        for event in [{"body": "{}"}, {"body": json.dumps({"question": ""})}, {}]:
            response = chat_module.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(response["headers"]["Content-Type"], "application/json")
            self.assertEqual(
                response["headers"]["Access-Control-Allow-Origin"],
                "https://d3vjauql06bl7n.cloudfront.net",
            )
            self.assertEqual(
                json.loads(response["body"]), {"error": "No question provided"}
            )

        mock_bedrock.invoke_model.assert_not_called()

    def test_bedrock_exception_returns_500_in_english_with_cors(self):
        chat_module, mock_bedrock = _load_chat_module()
        mock_bedrock.invoke_model.side_effect = RuntimeError("Bedrock throttling error")

        event = {"body": json.dumps({"question": "What projects has Javier built?"})}
        response = chat_module.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Origin"],
            "https://d3vjauql06bl7n.cloudfront.net",
        )
        self.assertEqual(
            json.loads(response["body"]), {"error": "Internal assistant error."}
        )

    # =====================================================================
    # Bilingual & Multilingual Prompt Rules (English, Spanish & Fallback)
    # =====================================================================

    def test_english_question_invokes_bedrock_with_english_system_prompt(self):
        chat_module, mock_bedrock = _load_chat_module()
        expected_reply = (
            "Javier built an autonomous GenAI email classification engine, "
            "this serverless AWS portfolio, and a remote gaming homelab."
        )
        _mock_bedrock_reply(mock_bedrock, expected_reply)

        question = "What projects has Javier built?"
        event = {"body": json.dumps({"question": question})}
        response = chat_module.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Origin"],
            "https://d3vjauql06bl7n.cloudfront.net",
        )
        self.assertEqual(json.loads(response["body"]), {"reply": expected_reply})

        mock_bedrock.invoke_model.assert_called_once()
        call_kwargs = mock_bedrock.invoke_model.call_args.kwargs
        self.assertEqual(
            call_kwargs["modelId"], "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

        sent_payload = json.loads(call_kwargs["body"])
        self.assertEqual(sent_payload["max_tokens"], 300)
        self.assertEqual(
            sent_payload["messages"], [{"role": "user", "content": question}]
        )

        system_prompt = sent_payload["system"]
        self.assertIn("<cv>", system_prompt)
        self.assertIn("</cv>", system_prompt)
        self.assertIn(chat_module.CV_CONTEXT, system_prompt)
        self.assertIn("maximum 3 sentences", system_prompt.lower())
        self.assertIn("never invent", system_prompt.lower())
        self.assertIn("contact javier", system_prompt.lower())
        self.assertIn("same language", system_prompt.lower())

    def test_spanish_question_passes_user_message_and_language_matching_rule(self):
        chat_module, mock_bedrock = _load_chat_module()
        expected_reply = (
            "Javier ha desarrollado un motor autónomo de clasificación de correos con IA, "
            "este portfolio serverless en AWS y un homelab de streaming."
        )
        _mock_bedrock_reply(mock_bedrock, expected_reply)

        question = "¿Qué proyectos ha desarrollado Javier?"
        event = {"body": json.dumps({"question": question})}
        response = chat_module.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"reply": expected_reply})

        sent_payload = json.loads(mock_bedrock.invoke_model.call_args.kwargs["body"])
        self.assertEqual(
            sent_payload["messages"], [{"role": "user", "content": question}]
        )
        self.assertIn("same language", sent_payload["system"].lower())

    def test_system_prompt_handles_code_switching_and_english_fallback(self):
        chat_module, mock_bedrock = _load_chat_module()
        _mock_bedrock_reply(
            mock_bedrock,
            "Javier uses AWS S3, CloudFront, Lambda, DynamoDB, API Gateway, and Bedrock.",
        )

        event = {"body": json.dumps({"question": "AWS?"})}
        response = chat_module.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        sent_payload = json.loads(mock_bedrock.invoke_model.call_args.kwargs["body"])
        system_prompt_lower = sent_payload["system"].lower()

        self.assertTrue(
            "grammatical" in system_prompt_lower
            or "technical terms" in system_prompt_lower
        )
        self.assertTrue(
            "default to english" in system_prompt_lower
            or "ambiguous" in system_prompt_lower
        )


if __name__ == "__main__":
    unittest.main()
