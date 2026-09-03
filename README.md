# 従業員情報ポータル

CSVで従業員一覧を取り込み、従業員が自分の情報をWebで閲覧・編集し、DynamoDBに登録。
管理者は後日CSVとして出力できます。

## 構成

- フロントエンド: S3静的Webホスティング（`frontend/`）
- 認証: Amazon Cognito（ユーザー名 = 社員番号）
- API: API Gateway (HTTP API) + Lambda（Python 3.12）
- DB: DynamoDB（PK = `社員番号`）
- CSV取込: 管理者がS3の `incoming/` にアップロード → S3イベントでLambda起動 → DynamoDBへ登録 + 新規社員のCognitoユーザーを自動作成
- CSV出力: 管理者がLambdaを手動実行 → S3の `export/` にCSVを生成

## 事前準備

- AWS CLI（設定済み・デプロイ権限のあるプロファイル）
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.12

## デプロイ手順

```bash
cd employee-portal
sam build
sam deploy --guided
```

`sam deploy --guided` の対話で環境名などを入力すると、初回はスタック名・リージョンなどを保存する `samconfig.toml` が作られます。デプロイ完了後、以下のOutputsが表示されるので控えてください。

- `WebsiteURL`
- `WebsiteBucketName`
- `DataBucketName`
- `ApiUrl`
- `UserPoolClientId`
- `Region`

## フロントエンドの設定・公開

`frontend/config.js` を、デプロイ時のOutputsの値で書き換えます。

```js
window.APP_CONFIG = {
  region: "ap-northeast-1",       // Region の値
  userPoolClientId: "xxxxxxxx",   // UserPoolClientId の値
  apiBaseUrl: "https://xxxx.execute-api.ap-northeast-1.amazonaws.com", // ApiUrl の値
};
```

書き換えたら、S3にアップロードします。

```bash
aws s3 sync frontend/ s3://<WebsiteBucketName>/
```

ブラウザで `WebsiteURL` を開くと画面が表示されます。

## 従業員CSVの取込

タブ区切り・Shift-JISのCSV（1列目が社員番号）を `incoming/` にアップロードすると自動で取り込まれます。

```bash
aws s3 cp "連絡先.txt" s3://<DataBucketName>/incoming/employees.csv
```

取込処理は以下を行います。

- 各行を社員番号キーでDynamoDBに登録（同じ社員番号があれば上書き更新）
- 社員番号に対応するCognitoユーザーが未登録なら自動作成
  - **初期パスワード = 社員番号 + 生年月日（例: 社員番号467・生年月日19770807 → `46719770807`）**
  - 生年月日が未入力の行はCognitoユーザーを作成しません（`ImportCsvFunction` のログに警告が出ます）

初期パスワードは社員番号と生年月日から一意に決まるため、従業員自身に個別連絡する必要はありません（本人が知っている情報のみで組み立てられます）。ただし推測可能な値なので、初回ログイン時のパスワード変更（フロントエンドで強制表示）を必ず行わせてください。

## 従業員のログイン・編集

1. `WebsiteURL` にアクセスし、社員番号 + 初期パスワードでログイン
2. 初回ログイン時は新しいパスワードの設定を求められます
3. 自分の情報が表示されるので、変更があれば編集して「登録する」を押すとDynamoDBに反映されます（承認フローなし・即時反映）

## CSV出力（管理者が手動実行）

```bash
aws lambda invoke --function-name <ExportCsvFunction名> /dev/stdout
```

DynamoDBの全件をタブ区切り・Shift-JISのCSVとして `s3://<DataBucketName>/export/employees_<日時>.csv` に出力します。ダウンロードは以下の通りです。

```bash
aws s3 cp s3://<DataBucketName>/export/employees_20260101_120000.csv ./employees_export.csv
```

## 運用上の注意（このまま本番利用する場合の検討事項）

- **HTTPS化**: 現状S3静的WebホスティングのエンドポイントはHTTPのみです。ログイン情報を扱うため、CloudFront + ACM証明書でHTTPS化することを推奨します。
- **初期パスワードの配布**: 現状CloudWatch Logsへの出力のみです。人数が増える場合は、SES経由の個別メール送信など、より安全な配布方法への変更を検討してください。
- **監査ログ**: 現在は変更履歴を保持していません。誰がいつ何を変更したかを残したい場合は、更新時にDynamoDB Streamsで履歴テーブルに書き出す構成を追加できます。
