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
    "社員番号", "氏名", "生年月日", "郵便番号", "都道府県", "市区町村", "番地", "建物",
    "電話番号", "メールアドレス", "LINE ID",
    "氏名(緊急連絡先1)", "フリガナ(緊急連絡先1)", "続柄(緊急連絡先1)", "電話番号(緊急連絡先1)", "メールアドレス(緊急連絡先1)",
    "氏名(緊急連絡先2)", "フリガナ(緊急連絡先2)", "続柄(緊急連絡先2)", "電話番号(緊急連絡先2)", "メールアドレス(緊急連絡先2)",
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

    # カンマ区切り・CRLF改行で出力する（正式に確定した取込用CSVと同じ形式に合わせる。
    # 拡張子.csvはカンマ区切りが前提のため、タブ区切りにするとExcelで開いた際に
    # 列が分割されず1列にまとまってしまう）
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n")
    writer.writerow(HEADER)
    # 社員番号順に並べ替えてから出力（DynamoDBのScan結果は順序を保証しないため）
    for item in sorted(items, key=lambda i: i.get(PK_ATTRIBUTE_NAME, "")):
        writer.writerow([item.get(col, "") for col in HEADER])

    # 取込側と同じくUTF-8（BOM付き）で書き出す。BOMがあることでExcelがロケールに関わらず
    # UTF-8だと確実に認識できる。これにより出力したCSVをそのまま再取込しても文字コードが揺れない。
    csv_bytes = buffer.getvalue().encode("utf-8-sig")

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    key = f"export/employees_{timestamp}.csv"
    s3.put_object(Bucket=DATA_BUCKET, Key=key, Body=csv_bytes, ContentType="text/csv")

    print(f"出力完了: s3://{DATA_BUCKET}/{key} ({len(items)}件)")
    return {"bucket": DATA_BUCKET, "key": key, "count": len(items)}
