import json
import os

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _employee_id_from_event(event):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    return claims.get("cognito:username") or claims.get("username")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    employee_id = _employee_id_from_event(event)
    if not employee_id:
        return _response(401, {"message": "認証情報が確認できません"})

    result = table.get_item(Key={PK_ATTRIBUTE_NAME: employee_id})
    item = result.get("Item")
    if not item:
        return _response(404, {"message": "従業員情報が見つかりません"})

    return _response(200, item)
