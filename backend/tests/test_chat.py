import io
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


BACKEND_SRC = Path(__file__).resolve().parent.parent / "src"
CHAT_PATH = BACKEND_SRC / "chat.py"


def _load_chat_module(allowed_origin="https://d3vjauql06bl7n.cloudfront.net"):
    """Load backend/src/chat.py with mocked boto3 client and real in-memory cv.txt."""
    if "boto3" not in sys.modules:
        try:
            import boto3  # noqa: F401
        except ModuleNotFoundError:
            fake_boto3 = types.ModuleType("boto3")
            fake_boto3.client = MagicMock()
            sys.modules["boto3"] = fake_boto3

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


def _mock_bedrock_reply(mock_bedrock, text, input_tokens=1050, output_tokens=45):
    payload_bytes = json.dumps(
        {
            "content": [{"text": text}],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }
    ).encode("utf-8")
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
        body = json.loads(response["body"])
        self.assertEqual(body["reply"], expected_reply)
        self.assertIn("telemetry", body)

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
        body = json.loads(response["body"])
        self.assertEqual(body["reply"], expected_reply)
        self.assertIn("telemetry", body)

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

    # =====================================================================
    # User Story 1: Stateless Multi-Turn Memory & Backward Compatibility
    # =====================================================================

    def test_single_turn_without_history_or_empty_history_is_backward_compatible(self):
        chat_module, mock_bedrock = _load_chat_module()

        for payload in [
            {"question": "What projects has Javier built?"},
            {"question": "What projects has Javier built?", "history": []},
        ]:
            _mock_bedrock_reply(mock_bedrock, "Javier built three main projects.")
            event = {"body": json.dumps(payload)}
            response = chat_module.lambda_handler(event, None)

            self.assertEqual(response["statusCode"], 200)
            body = json.loads(response["body"])
            self.assertEqual(body["reply"], "Javier built three main projects.")

            sent_payload = json.loads(mock_bedrock.invoke_model.call_args.kwargs["body"])
            self.assertEqual(
                sent_payload["messages"],
                [{"role": "user", "content": "What projects has Javier built?"}],
            )

    def test_multiturn_history_concatenates_prior_turns_before_current_question(self):
        chat_module, mock_bedrock = _load_chat_module()
        expected_reply = (
            "In that first project, he used n8n in Docker on Ubuntu Server, "
            "Microsoft Graph API, and Google Gemini."
        )
        _mock_bedrock_reply(mock_bedrock, expected_reply)

        history = [
            {"role": "user", "content": "What projects has Javier built?"},
            {
                "role": "assistant",
                "content": "He built an email classification engine, this AWS portfolio, and a homelab.",
            },
            {"role": "user", "content": "Tell me more about the first one."},
            {
                "role": "assistant",
                "content": "It classifies and routes 2,000+ emails using an Orchestrator-Worker architecture.",
            },
        ]
        question = "  What technologies did he use in that project?  "
        event = {"body": json.dumps({"question": question, "history": history})}
        response = chat_module.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["reply"], expected_reply)

        sent_payload = json.loads(mock_bedrock.invoke_model.call_args.kwargs["body"])
        self.assertEqual(
            sent_payload["messages"],
            history + [{"role": "user", "content": question.strip()}],
        )

    def test_malformed_or_non_object_json_returns_400_with_cors(self):
        chat_module, mock_bedrock = _load_chat_module()

        for bad_event in [{"body": "{not-valid-json"}, {"body": "[]"}, {"body": '"text"'}]:
            response = chat_module.lambda_handler(bad_event, None)
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(
                response["headers"]["Access-Control-Allow-Origin"],
                "https://d3vjauql06bl7n.cloudfront.net",
            )
            self.assertIn("error", json.loads(response["body"]))

        mock_bedrock.invoke_model.assert_not_called()

    # =====================================================================
    # User Story 2: Live FinOps & Performance Telemetry (Cold/Warm Start)
    # =====================================================================

    def test_telemetry_reports_cold_then_warm_start_and_finops_cost(self):
        chat_module, mock_bedrock = _load_chat_module()

        # First invocation -> Cold Start
        _mock_bedrock_reply(
            mock_bedrock,
            "First reply from cold container.",
            input_tokens=1045,
            output_tokens=68,
        )
        event_1 = {"body": json.dumps({"question": "What projects has Javier built?"})}
        response_1 = chat_module.lambda_handler(event_1, None)
        self.assertEqual(response_1["statusCode"], 200)
        body_1 = json.loads(response_1["body"])

        telemetry_1 = body_1["telemetry"]
        self.assertIsInstance(telemetry_1["latency_ms"], int)
        self.assertGreaterEqual(telemetry_1["latency_ms"], 0)
        self.assertIs(telemetry_1["cold_start"], True)
        self.assertEqual(telemetry_1["input_tokens"], 1045)
        self.assertEqual(telemetry_1["output_tokens"], 68)
        # (1045 * 1.0 + 68 * 5.0) / 1_000_000 = 1385 / 1_000_000 = 0.001385
        self.assertEqual(telemetry_1["estimated_cost_usd"], 0.001385)

        # Second invocation on same loaded module -> Warm Start
        _mock_bedrock_reply(
            mock_bedrock,
            "Second reply from warm container.",
            input_tokens=1150,
            output_tokens=51,
        )
        event_2 = {
            "body": json.dumps(
                {
                    "question": "Tell me more about the first one.",
                    "history": [
                        {"role": "user", "content": "What projects has Javier built?"},
                        {"role": "assistant", "content": "First reply from cold container."},
                    ],
                }
            )
        }
        response_2 = chat_module.lambda_handler(event_2, None)
        self.assertEqual(response_2["statusCode"], 200)
        body_2 = json.loads(response_2["body"])

        telemetry_2 = body_2["telemetry"]
        self.assertIs(telemetry_2["cold_start"], False)
        self.assertEqual(telemetry_2["input_tokens"], 1150)
        self.assertEqual(telemetry_2["output_tokens"], 51)
        # (1150 * 1.0 + 51 * 5.0) / 1_000_000 = 1405 / 1_000_000 = 0.001405
        self.assertEqual(telemetry_2["estimated_cost_usd"], 0.001405)

    # =====================================================================
    # User Story 3: Abuse Protection & Input Validation Limits (HTTP 400)
    # =====================================================================

    def test_question_validation_rejects_whitespace_non_string_or_over_500_chars(self):
        chat_module, mock_bedrock = _load_chat_module()

        invalid_questions = [
            "   \t\n  ",
            12345,
            ["list-not-string"],
            "a" * 501,
        ]
        for q in invalid_questions:
            event = {"body": json.dumps({"question": q})}
            response = chat_module.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(
                response["headers"]["Access-Control-Allow-Origin"],
                "https://d3vjauql06bl7n.cloudfront.net",
            )
            self.assertIn("error", json.loads(response["body"]))

        mock_bedrock.invoke_model.assert_not_called()

        # Exactly 500 characters after trimming must be accepted
        _mock_bedrock_reply(mock_bedrock, "Accepted 500 char question.")
        valid_500 = "  " + ("x" * 500) + "  "
        ok_response = chat_module.lambda_handler(
            {"body": json.dumps({"question": valid_500})}, None
        )
        self.assertEqual(ok_response["statusCode"], 200)

    def test_history_validation_rejects_invalid_length_roles_or_message_size(self):
        chat_module, mock_bedrock = _load_chat_module()

        valid_turn = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        invalid_histories = [
            "not-a-list",
            {"role": "user", "content": "not-a-list"},
            # Over 6 messages (4 turns = 8 messages)
            valid_turn * 4,
            # Odd number of messages (ends with user instead of assistant)
            [{"role": "user", "content": "Only one message"}],
            # Starts with assistant instead of user
            [
                {"role": "assistant", "content": "Wrong start"},
                {"role": "user", "content": "Second"},
            ],
            # Two consecutive user roles
            [
                {"role": "user", "content": "First"},
                {"role": "user", "content": "Second"},
            ],
            # Invalid role name
            [
                {"role": "system", "content": "Injected system prompt"},
                {"role": "assistant", "content": "Reply"},
            ],
            # Empty content after trimming
            [
                {"role": "user", "content": "   "},
                {"role": "assistant", "content": "Reply"},
            ],
            # Message content exceeding 1000 characters
            [
                {"role": "user", "content": "Normal question"},
                {"role": "assistant", "content": "y" * 1001},
            ],
            # Element not a dict
            ["raw-string-item", "second-item"],
        ]

        for bad_history in invalid_histories:
            event = {
                "body": json.dumps(
                    {"question": "Valid follow-up?", "history": bad_history}
                )
            }
            response = chat_module.lambda_handler(event, None)
            self.assertEqual(
                response["statusCode"],
                400,
                msg=f"Expected 400 for history: {bad_history}",
            )
            self.assertEqual(
                response["headers"]["Access-Control-Allow-Origin"],
                "https://d3vjauql06bl7n.cloudfront.net",
            )
            self.assertIn("error", json.loads(response["body"]))

        mock_bedrock.invoke_model.assert_not_called()

        # Exactly 6 messages (3 turns) with 1000-char content must be accepted
        _mock_bedrock_reply(mock_bedrock, "Valid 6-message history reply.")
        max_valid_history = [
            {"role": "user", "content": "u" * 1000},
            {"role": "assistant", "content": "a" * 1000},
        ] * 3
        ok_response = chat_module.lambda_handler(
            {
                "body": json.dumps(
                    {"question": "Follow-up?", "history": max_valid_history}
                )
            },
            None,
        )
        self.assertEqual(ok_response["statusCode"], 200)

    # =====================================================================
    # User Story 4: CV Knowledge Base Architectural Coherence
    # =====================================================================

    def test_cv_context_documents_ram_cold_start_and_no_rag_or_prompt_caching(self):
        cv_text = (BACKEND_SRC / "cv.txt").read_text(encoding="utf-8")
        cv_lower = cv_text.lower()

        self.assertIn("ram", cv_lower)
        self.assertIn("cold start", cv_lower)
        self.assertIn("1,000 tokens", cv_lower)
        self.assertIn("2,048", cv_lower)
        self.assertIn("prompt caching", cv_lower)
        self.assertIn("adr 01", cv_lower)
        self.assertIn("adr 02", cv_lower)
        self.assertIn("adr 03", cv_lower)
        self.assertIn("adr 04", cv_lower)
        self.assertNotIn("injected\n  from s3", cv_lower)


if __name__ == "__main__":
    unittest.main()
