import json
import os
from datetime import datetime, timedelta, timezone

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]
UPDATED_AT_ATTRIBUTE_NAME = "変更日時"  # 保存の都度サーバー側で上書きする属性名

JST = timezone(timedelta(hours=9))  # UTC+9。日本時間で「変更日時」を記録するために使う

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _employee_id_from_event(event):
    """ログイン中の社員番号をCognito IDトークンのクレームから取り出す（get_employeeと同じ仕組み）"""
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    return claims.get("cognito:username") or claims.get("username")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    """PUT /me: ログイン中の従業員自身のレコードを更新する。
    承認フローはなく、送られてきた内容をそのままDynamoDBへ即時反映する。
    """
    employee_id = _employee_id_from_event(event)
    if not employee_id:
        return _response(401, {"message": "認証情報が確認できません"})

    try:
        updates = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"message": "リクエストの形式が不正です"})

    if not isinstance(updates, dict):
        return _response(400, {"message": "リクエストの形式が不正です"})

    # 既存の全項目を読み込む。フロントエンドは「変更した項目だけ」を送ってくる想定なので、
    # 既存データに上書きマージする形で完全な項目を組み立てる（部分更新ではなくput_itemで丸ごと書き直す）。
    existing = table.get_item(Key={PK_ATTRIBUTE_NAME: employee_id}).get("Item")
    if not existing:
        return _response(404, {"message": "従業員情報が見つかりません"})

    # 社員番号（PK）と変更日時はクライアントからの入力で変更させない
    # （リクエストボディに紛れ込んでいても無視し、以下で必ずサーバー側の値で上書きする）
    updates.pop(PK_ATTRIBUTE_NAME, None)
    updates.pop(UPDATED_AT_ATTRIBUTE_NAME, None)

    merged = {**existing, **updates, PK_ATTRIBUTE_NAME: employee_id}
    # 保存の瞬間の日本時間を「年月日 時:分」形式で記録。画面はこの文字列をそのまま表示する。
    merged[UPDATED_AT_ATTRIBUTE_NAME] = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    table.put_item(Item=merged)

    # 更新後の全項目（変更日時込み）を返す。フロントエンドはこれをそのまま画面に反映する。
    return _response(200, merged)
