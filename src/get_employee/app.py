import json
import os

import boto3

# SAMテンプレート（template.yaml）のEnvironment Variablesから注入される値
TABLE_NAME = os.environ["TABLE_NAME"]  # DynamoDBテーブルの物理名
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]  # DynamoDBのパーティションキー名（"社員番号"）

# Lambda実行環境が再利用される限り使い回されるので、ハンドラーの外で1回だけ作る
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _employee_id_from_event(event):
    """API GatewayのJWTオーソライザーが検証済みのCognito IDトークンから、
    ログイン中の社員番号（Cognitoのユーザー名と同じ）を取り出す。
    ここでの認証チェックは不要（API Gateway側で既にトークンの署名・有効期限を検証済み）。
    """
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    return claims.get("cognito:username") or claims.get("username")


def _response(status_code, body):
    """API Gateway (HTTP API) が期待するレスポンス形式に整形する。
    ensure_ascii=False にしないと日本語が \\uXXXX エスケープされてしまう。
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    """GET /me: ログイン中の従業員自身のレコードをDynamoDBから1件取得して返す。
    社員番号はリクエストのパラメータではなくIDトークンから決まるため、
    他人の社員番号を指定して覗き見ることはできない。
    """
    employee_id = _employee_id_from_event(event)
    if not employee_id:
        return _response(401, {"message": "認証情報が確認できません"})

    # パーティションキー（社員番号）を指定して1件取得。項目が丸ごとJSONとして返る。
    result = table.get_item(Key={PK_ATTRIBUTE_NAME: employee_id})
    item = result.get("Item")
    if not item:
        return _response(404, {"message": "従業員情報が見つかりません"})

    return _response(200, item)
