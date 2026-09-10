import csv
import io
import os
from datetime import datetime, timedelta, timezone

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]
DATA_BUCKET = os.environ["DATA_BUCKET"]

# 出力するCSVの列名・列順。DynamoDB内部の属性順（決まった並びを持たない）とは無関係に、
# ここで定義した通りの順番で出力される。取込時のCSVの並びと合わせてある。
# 新しい列を追加する場合はここにも追記しないと出力に含まれない（フロントエンドのFIELD_GROUPSと同様）。
HEADER = [
    "社員番号", "氏名", "生年月日", "郵便番号", "都道府県", "市町村", "番地", "建物",
    "携帯番号_個人", "メールアドレス", "LINE ID",
    "緊急連絡先名1", "フリガナ1", "続柄1", "緊急電話番号1", "緊急メールアドレス",
    "緊急連絡先名2", "フリガナ2", "続柄2", "緊急電話番号2", "緊急メールアドレス2",
]

JST = timezone(timedelta(hours=9))  # 出力ファイル名のタイムスタンプを日本時間にするため

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


def _scan_all_items():
    """DynamoDBのScanは一度に取得できる件数に上限があるため、
    LastEvaluatedKeyが返ってこなくなるまでページングして全件集める。
    """
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
    """管理者がLambdaコンソール等から手動実行する。S3イベントのような自動トリガーは設定していない。
    DynamoDBの全件をCSVに書き出し、S3のexport/配下に保存する。
    """
    items = _scan_all_items()

    # タブ区切り・CRLF改行で、取込元のCSVと同じ形式に合わせて出力する
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\r\n")
    writer.writerow(HEADER)
    # 社員番号順に並べ替えてから出力（DynamoDBのScan結果は順序を保証しないため）
    for item in sorted(items, key=lambda i: i.get(PK_ATTRIBUTE_NAME, "")):
        writer.writerow([item.get(col, "") for col in HEADER])

    # 取込側と同じくShift-JIS（cp932）で書き出す。変換できない文字は落とさず「?」等に置換する。
    csv_bytes = buffer.getvalue().encode("cp932", errors="replace")

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    key = f"export/employees_{timestamp}.csv"
    s3.put_object(Bucket=DATA_BUCKET, Key=key, Body=csv_bytes, ContentType="text/csv")

    print(f"出力完了: s3://{DATA_BUCKET}/{key} ({len(items)}件)")
    return {"bucket": DATA_BUCKET, "key": key, "count": len(items)}
