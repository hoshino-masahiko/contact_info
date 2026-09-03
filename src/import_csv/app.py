import csv
import io
import os
import urllib.parse

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
PK_ATTRIBUTE_NAME = os.environ["PK_ATTRIBUTE_NAME"]
BIRTH_DATE_ATTRIBUTE_NAME = os.environ["BIRTH_DATE_ATTRIBUTE_NAME"]
USER_POOL_ID = os.environ["USER_POOL_ID"]

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito = boto3.client("cognito-idp")


def _ensure_cognito_user(employee_id, birth_date):
    """Cognitoに未登録の社員番号ならユーザーを作成する。初期パスワードは社員番号+生年月日。"""
    try:
        cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=employee_id)
        return None
    except ClientError as e:
        if e.response["Error"]["Code"] != "UserNotFoundException":
            raise

    if not birth_date:
        print(f"警告: 社員番号={employee_id} は生年月日が未設定のためCognitoユーザーを作成できません")
        return None

    initial_password = f"{employee_id}{birth_date}"
    cognito.admin_create_user(
        UserPoolId=USER_POOL_ID,
        Username=employee_id,
        TemporaryPassword=initial_password,
        MessageAction="SUPPRESS",
    )
    return initial_password


def handler(event, context):
    created_users = []

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        obj = s3.get_object(Bucket=bucket, Key=key)
        text = obj["Body"].read().decode("cp932")

        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        except csv.Error:
            dialect = csv.excel_tab

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        row_count = 0
        for row in reader:
            employee_id = (row.get(PK_ATTRIBUTE_NAME) or "").strip()
            if not employee_id:
                continue

            item = {k: (v if v is not None else "") for k, v in row.items() if k}
            item[PK_ATTRIBUTE_NAME] = employee_id
            table.put_item(Item=item)
            row_count += 1

            birth_date = (row.get(BIRTH_DATE_ATTRIBUTE_NAME) or "").strip()
            initial_password = _ensure_cognito_user(employee_id, birth_date)
            if initial_password:
                created_users.append(employee_id)

        print(f"取込完了: {bucket}/{key} ({row_count}件)")

    if created_users:
        print(f"新規Cognitoユーザーを作成しました（初期パスワード=社員番号+生年月日）: {', '.join(created_users)}")

    return {"created_users_count": len(created_users)}
