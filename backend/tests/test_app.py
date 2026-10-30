import importlib.util
import json
import os
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch


BACKEND_SRC = Path(__file__).resolve().parent.parent / "src"
APP_PATH = BACKEND_SRC / "app.py"


def _load_app_module(
    table_name="portfolio-visitor-counter",
    allowed_origin="https://d3vjauql06bl7n.cloudfront.net",
):
    """Load backend/src/app.py with mocked boto3 DynamoDB resource and table."""
    if "boto3" not in sys.modules:
        try:
            import boto3  # noqa: F401
        except ModuleNotFoundError:
            fake_boto3 = types.ModuleType("boto3")
            fake_boto3.resource = MagicMock()
            fake_boto3.client = MagicMock()
            sys.modules["boto3"] = fake_boto3
    elif not hasattr(sys.modules["boto3"], "resource"):
        sys.modules["boto3"].resource = MagicMock()

    mock_table = MagicMock()
    mock_dynamodb = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    env_vars = {
        "TABLE_NAME": table_name,
        "ALLOWED_ORIGIN": allowed_origin,
    }
    with patch.dict(os.environ, env_vars, clear=False):
        with patch("boto3.resource", return_value=mock_dynamodb) as mock_resource_factory:
            spec = importlib.util.spec_from_file_location("app", APP_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

    mock_resource_factory.assert_called_once_with("dynamodb")
    mock_dynamodb.Table.assert_called_once_with(table_name)
    return module, mock_table


class TestVisitHandler(unittest.TestCase):
    def test_dynamodb_table_initialized_at_module_load(self):
        app_module, mock_table = _load_app_module()
        self.assertIs(app_module.table, mock_table)
        self.assertEqual(
            app_module.ALLOWED_ORIGIN,
            "https://d3vjauql06bl7n.cloudfront.net",
        )

    def test_atomic_increment_success_returns_200_with_visits_and_cors(self):
        app_module, mock_table = _load_app_module()
        mock_table.update_item.return_value = {
            "Attributes": {"visit_count": Decimal(142)}
        }

        response = app_module.lambda_handler({}, None)

        mock_table.update_item.assert_called_once_with(
            Key={"id": "visitors"},
            UpdateExpression="ADD visit_count :inc",
            ExpressionAttributeValues={":inc": 1},
            ReturnValues="UPDATED_NEW",
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Origin"],
            "https://d3vjauql06bl7n.cloudfront.net",
        )
        self.assertEqual(json.loads(response["body"]), {"visits": 142})

    def test_dynamodb_exception_returns_500_in_english_with_cors(self):
        app_module, mock_table = _load_app_module()
        mock_table.update_item.side_effect = RuntimeError(
            "DynamoDB ProvisionedThroughputExceededException"
        )

        response = app_module.lambda_handler({}, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Origin"],
            "https://d3vjauql06bl7n.cloudfront.net",
        )
        self.assertEqual(
            json.loads(response["body"]),
            {"error": "Internal server error."},
        )


if __name__ == "__main__":
    unittest.main()
