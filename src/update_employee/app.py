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

    try:
        updates = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"message": "リクエストの形式が不正です"})

    if not isinstance(updates, dict):
        return _response(400, {"message": "リクエストの形式が不正です"})

    existing = table.get_item(Key={PK_ATTRIBUTE_NAME: employee_id}).get("Item")
    if not existing:
        return _response(404, {"message": "従業員情報が見つかりません"})

    # 社員番号（PK）はクライアントからの入力で変更させない
    updates.pop(PK_ATTRIBUTE_NAME, None)

    merged = {**existing, **updates, PK_ATTRIBUTE_NAME: employee_id}
    table.put_item(Item=merged)

    return _response(200, merged)
