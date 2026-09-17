import io
import os
from datetime import datetime, timedelta, timezone

import boto3
from openpyxl import Workbook

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]
DATA_BUCKET = os.environ["DATA_BUCKET"]

# 出力するExcelブックの列名・列順。DynamoDB内部の属性順（決まった並びを持たない）とは無関係に、
# ここで定義した通りの順番で出力される。取込時のCSVの並びと合わせてある。
# 新しい列を追加する場合はここにも追記しないと出力に含まれない（フロントエンドのFIELD_GROUPSと同様）。
HEADER = [
    "社員番号", "氏名", "生年月日", "郵便番号", "都道府県", "市区町村", "番地", "建物",
    "電話番号", "メールアドレス", "LINE ID",
    "氏名(緊急連絡先1)", "フリガナ(緊急連絡先1)", "続柄(緊急連絡先1)", "電話番号(緊急連絡先1)", "メールアドレス(緊急連絡先1)",
    "氏名(緊急連絡先2)", "フリガナ(緊急連絡先2)", "続柄(緊急連絡先2)", "電話番号(緊急連絡先2)", "メールアドレス(緊急連絡先2)",
]

JST = timezone(timedelta(hours=9))  # 出力ファイル名のタイムスタンプを日本時間にするため

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
    DynamoDBの全件をExcelブック（.xlsx）に書き出し、S3のexport/配下に保存する。
    """
    items = _scan_all_items()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADER)

    # 全セルを文字列（セル書式「文字列」）として書き込む。CSVで出力していた頃は、
    # 番地（例: 20-6）や電話番号（先頭の0）をExcelがファイルを開いた時点で
    # 日付や数値だと自動判定し、見た目を変換してしまっていた。xlsxはセルごとに
    # 型を明示できるため、文字列として保存すればExcelで直接開いてもWEBに
    # 入力された内容がそのまま表示される。
    for item in sorted(items, key=lambda i: i.get(PK_ATTRIBUTE_NAME, "")):
        values = [str(item.get(col, "")) for col in HEADER]
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            cell.number_format = "@"

    buffer = io.BytesIO()
    workbook.save(buffer)
    xlsx_bytes = buffer.getvalue()

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    key = f"export/employee-renrakusaki_{timestamp}.xlsx"
    s3.put_object(Bucket=DATA_BUCKET, Key=key, Body=xlsx_bytes, ContentType=XLSX_CONTENT_TYPE)

    print(f"出力完了: s3://{DATA_BUCKET}/{key} ({len(items)}件)")
    return {"bucket": DATA_BUCKET, "key": key, "count": len(items)}
