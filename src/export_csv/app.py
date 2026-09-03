import csv
import io
import os
from datetime import datetime, timedelta, timezone

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]
DATA_BUCKET = os.environ["DATA_BUCKET"]

HEADER = [
    "社員番号", "氏名", "生年月日", "郵便番号", "都道府県", "市町村", "番地", "建物",
    "電話番号", "メールアドレス",
    "緊急連絡先名1", "続柄1", "緊急電話番号1", "緊急メールアドレス",
    "緊急連絡先名2", "続柄2", "緊急電話番号2", "緊急メールアドレス2",
]

JST = timezone(timedelta(hours=9))

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


def _scan_all_items():
    items = []
    kwargs = {}
    while True:
        result = table.scan(**kwargs)
        items.extend(result.get("Items", []))
        if "LastEvaluatedKey" not in result:
            break
        kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
    return items


def handler(event, context):
    items = _scan_all_items()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\r\n")
    writer.writerow(HEADER)
    for item in sorted(items, key=lambda i: i.get(PK_ATTRIBUTE_NAME, "")):
        writer.writerow([item.get(col, "") for col in HEADER])

    csv_bytes = buffer.getvalue().encode("cp932", errors="replace")

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    key = f"export/employees_{timestamp}.csv"
    s3.put_object(Bucket=DATA_BUCKET, Key=key, Body=csv_bytes, ContentType="text/csv")

    print(f"出力完了: s3://{DATA_BUCKET}/{key} ({len(items)}件)")
    return {"bucket": DATA_BUCKET, "key": key, "count": len(items)}
