import json
import os
import boto3

dynamodb=boto3.resource("dynamodb")
table=dynamodb.Table(os.environ["TABLE_NAME"])
ALLOWED_ORIGIN=os.environ.get("ALLOWED_ORIGIN","*")

def lambda_handler(event, context):
    response=table.update_item(
        Key={"id":"visitors"},
        UpdateExpression="ADD visit_count :inc",
        ExpressionAttributeValues={":inc":1},
        ReturnValues="UPDATED_NEW",
    )

    new_count=int(response["Attributes"]["visit_count"])
    return{
        "statusCode":200,
        "headers":{
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        },
        "body":json.dumps({"visits":new_count}),
    }