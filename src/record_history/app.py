import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer

HISTORY_TABLE_NAME = os.environ["HISTORY_TABLE_NAME"]
# 「誰が書き込んだか」は、書き込み側（UpdateEmployeeFunction=Web本人 / ImportCsvFunction=CSV取込）が
# 保存の都度セットするこの属性から読み取る。DynamoDB Streams自体はAPIの呼び出し元までは教えてくれないため。
ACTOR_ATTRIBUTE_NAME = "最終更新元"

JST = timezone(timedelta(hours=9))

dynamodb = boto3.resource("dynamodb")
history_table = dynamodb.Table(HISTORY_TABLE_NAME)
deserializer = TypeDeserializer()


def _deserialize(image):
    """DynamoDB Streamsが渡す低レベルのAttributeValue形式(例: {"S": "値"})を、
    通常のPythonの値(str・Decimalなど)に変換する。
    """
    if not image:
        return {}
    return {k: deserializer.deserialize(v) for k, v in image.items()}


def _to_jsonable(value):
    """DynamoDBのDecimal型はjson.dumpsできないため、変更内容をJSON文字列化する前に変換する。"""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def handler(event, context):
    """EmployeeTableのDynamoDB Streamsをトリガーに自動実行される。
    登録(INSERT)・更新(MODIFY)のたびに、変更前後の内容をEmployeeHistoryTableへ記録する。
    誰が(社員番号+最終更新元)・いつ・どの項目を・どう変更したかを、後から追跡できるようにするため。
    """
    for record in event["Records"]:
        event_name = record["eventName"]
        if event_name not in ("INSERT", "MODIFY"):
            continue  # レコード削除(REMOVE)は現状の運用では発生しないため対象外

        ddb = record["dynamodb"]
        keys = _deserialize(ddb.get("Keys"))
        # EmployeeTableはパーティションキーのみ(ソートキーなし)の単純な構成なので、
        # Keysには常にちょうど1件だけ入っている。属性名を環境変数として持ち回らず、
        # ここで実際のイベントから直接読み取ることで、環境変数側の文字コード起因の
        # 不一致を気にせず済むようにしている。
        pk_attribute_name, employee_id = next(iter(keys.items()))
        old_image = _deserialize(ddb.get("OldImage"))
        new_image = _deserialize(ddb.get("NewImage"))

        actor = new_image.get(ACTOR_ATTRIBUTE_NAME) or "不明"

        # 社員番号(パーティションキー)と最終更新元(このLambdaが読むためだけの内部マーカー)自体は
        # 「変更された項目」として記録する対象から除く
        changed_keys = (set(old_image) | set(new_image)) - {pk_attribute_name, ACTOR_ATTRIBUTE_NAME}
        changes = []
        for key in sorted(changed_keys):
            old_value = old_image.get(key, "")
            new_value = new_image.get(key, "")
            if old_value != new_value:
                changes.append({
                    "項目": key,
                    "変更前": _to_jsonable(old_value),
                    "変更後": _to_jsonable(new_value),
                })

        now = datetime.now(JST)
        # ソートキーは「時刻+eventIDの先頭8文字」。同一社員番号への短時間での連続更新でも
        # 一意になるようにするため(時刻だけだと同一ミリ秒の衝突がありうる)。
        history_id = f"{now.strftime('%Y-%m-%dT%H:%M:%S.%f')}#{record['eventID'][:8]}"

        history_table.put_item(Item={
            pk_attribute_name: employee_id,
            "変更ID": history_id,
            "変更日時": now.strftime("%Y-%m-%d %H:%M:%S"),
            "操作種別": "新規登録" if event_name == "INSERT" else "更新",
            "変更元": actor,
            "変更内容": json.dumps(changes, ensure_ascii=False),
        })

    return {"processed": len(event["Records"])}
