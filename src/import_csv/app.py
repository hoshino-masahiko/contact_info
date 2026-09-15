import csv
import io
import os
import urllib.parse

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]  # CSVヘッダーのうちどの列を主キー（社員番号）とみなすか
BIRTH_DATE_ATTRIBUTE_NAME = os.environ["BIRTH_DATE_ATTRIBUTE_NAME"]  # 初期パスワード生成に使う生年月日列
USER_POOL_ID = os.environ["USER_POOL_ID"]

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito = boto3.client("cognito-idp")


def _ensure_cognito_user(employee_id, birth_date):
    """Cognitoに未登録の社員番号ならユーザーを作成する。初期パスワードは社員番号+生年月日。"""
    try:
        # まず存在確認。見つかれば何もせず終了（同じ社員番号を再取込しても二重作成しない）
        cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=employee_id)
        return None
    except ClientError as e:
        # 「ユーザーが存在しない」以外のエラー（権限不足など）はここで気づけるよう再送出する
        if e.response["Error"]["Code"] != "UserNotFoundException":
            raise

    if not birth_date:
        print(f"警告: 社員番号={employee_id} は生年月日が未設定のためCognitoユーザーを作成できません")
        return None

    initial_password = f"{employee_id}{birth_date}"
    # 1. まず「仮パスワード」としてユーザーを作成（この時点ではFORCE_CHANGE_PASSWORD状態）
    cognito.admin_create_user(
        UserPoolId=USER_POOL_ID,
        Username=employee_id,
        TemporaryPassword=initial_password,
        MessageAction="SUPPRESS",  # Cognito標準の招待メール送信をしない（送信先メールアドレスが無い前提のため）
    )
    # 2. 続けて同じ値を「本パスワード」として確定させる。これにより初回ログイン時の強制変更を発生させない。
    cognito.admin_set_user_password(
        UserPoolId=USER_POOL_ID,
        Username=employee_id,
        Password=initial_password,
        Permanent=True,
    )
    return initial_password


def handler(event, context):
    """S3の incoming/ プレフィックスへのアップロードをトリガーに自動実行される。
    アップロードされたCSV（UTF-8またはShift-JIS、タブまたはカンマ区切り、いずれも自動判定）を読み込み、
    行ごとにDynamoDBへ登録・更新し、必要ならCognitoユーザーも作成する。
    """
    created_users = []

    # S3イベントは複数ファイルの同時アップロードをまとめて1回のLambda呼び出しで通知することがあるため、
    # Recordsをループして全ファイルを処理する（通常は1ファイル=1レコード）
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])  # S3キーはURLエンコードされて渡ってくる

        obj = s3.get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read()
        # 文字コードを自動判定する。UTF-8（BOM付き含む）を優先的に試し、
        # UTF-8として解釈できない場合はShift-JIS（cp932、Excelの旧来のCSV保存形式）として読む。
        # UTF-8はバイト列の構造上「たまたま偶然デコードに成功してしまう」誤検出が起きにくいため、
        # 先にUTF-8を試す順番にしている。
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932")

        # 区切り文字（タブ or カンマ）をファイルの先頭部分から自動判定し、どちらの形式でも取り込めるようにする
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        except csv.Error:
            dialect = csv.excel_tab  # 判定できなければタブ区切りとして扱う

        # ヘッダー行の列名をキーとした辞書としてCSVの各行を読み込む。
        # 列名をコード側で決め打ちしていないので、CSVに新しい列を追加してもこの処理は無改修で動く。
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        row_count = 0
        for row in reader:
            employee_id = (row.get(PK_ATTRIBUTE_NAME) or "").strip()
            if not employee_id:
                continue  # 社員番号が空の行（空行など）はスキップ

            # CSVの列名をそのままDynamoDBの属性名として保存する（列名の変換・マッピングをしない設計）。
            # CSVの値はそのまま（空欄やスペースも含めて）採用する。空欄の列は空文字で上書きするため、
            # 結果として「その項目を削除した」のと見た目上は同じになる（運用ルール上の意図的な仕様）。
            item = {k: (v if v is not None else "") for k, v in row.items() if k}
            item[PK_ATTRIBUTE_NAME] = employee_id

            # 既存レコードとマージするのは、CSVに列そのものが存在しない属性（例: 本人がWeb画面で
            # 保存した際の「変更日時」）を保持するためだけ。CSVに存在する列は、値の有無に関わらず
            # 今回のCSVの内容で必ず上書きする。
            existing = table.get_item(Key={PK_ATTRIBUTE_NAME: employee_id}).get("Item") or {}
            merged_item = {**existing, **item}
            table.put_item(Item=merged_item)  # 同じ社員番号が既にあれば上書き（アップサート）
            row_count += 1

            birth_date = (row.get(BIRTH_DATE_ATTRIBUTE_NAME) or "").strip()
            initial_password = _ensure_cognito_user(employee_id, birth_date)
            if initial_password:
                created_users.append(employee_id)

        print(f"取込完了: {bucket}/{key} ({row_count}件)")

    if created_users:
        # 初期パスワードは「社員番号+生年月日」という規則で機械的に決まるため、
        # 値そのものはログに出さず、作成した社員番号の一覧だけを記録する。
        print(f"新規Cognitoユーザーを作成しました（初期パスワード=社員番号+生年月日）: {', '.join(created_users)}")

    return {"created_users_count": len(created_users)}
