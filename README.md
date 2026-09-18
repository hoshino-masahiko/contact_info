# 従業員情報ポータル

CSVで従業員一覧を取り込み、従業員が自分の情報をWebで閲覧・編集し、DynamoDBに登録。
管理者は後日Excel（`.xlsx`）として出力できます。HTTPS化のため独自ドメイン（`portal.tokaiec.co.jp`）をCloudFront経由で配信します。

## 構成

- フロントエンド: S3静的Webホスティング + CloudFront（HTTPS配信、独自ドメイン）
- DNS/証明書: Route53（`portal` サブドメインのみ委任）+ ACM
- 認証: Amazon Cognito（ユーザー名 = 社員番号）
- API: API Gateway (HTTP API) + Lambda（Python 3.12）
- DB: DynamoDB（PK = `社員番号`）
- CSV取込: 管理者がS3の `incoming/` にアップロード → S3イベントでLambda起動 → DynamoDBへ登録 + 新規社員のCognitoユーザーを自動作成
- Excel出力: 管理者がLambdaを手動実行 → S3の `export/` にExcelブック（`.xlsx`）を生成
- 変更履歴: DynamoDB Streamsで登録・更新のたびに自動記録（誰が・いつ・何を変更したか）

> `tokaiec.co.jp` 本体のDNSゾーンはさくらインターネット側で管理されたままです。今回はサブドメイン `portal.tokaiec.co.jp` だけをRoute53に委任するので、メール等の既存レコードには影響しません。

## 事前準備

- AWS CLI（設定済み・デプロイ権限のあるプロファイル）
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.12
- さくらインターネットのレンタルサーバー コントロールパネルでNSレコードを追加できること

## デプロイ手順（3段階）

### ステージ1: Route53ホストゾーンの作成

```bash
cd employee-portal
aws cloudformation deploy \
  --template-file infra/hosted-zone.yaml \
  --stack-name employee-portal-hosted-zone \
  --region ap-northeast-1 \
  --tags Project=renrakusaki

aws cloudformation describe-stacks \
  --stack-name employee-portal-hosted-zone \
  --region ap-northeast-1 \
  --query "Stacks[0].Outputs"
```

`NameServers`（4件）と `HostedZoneId` が出力されます。控えてください。

### ステージ2: さくら側でNS委任 + DNS伝播待ち

さくらインターネットのコントロールパネルで `tokaiec.co.jp` のゾーン編集を開き、以下を追加します。

- ホスト名: `portal`
- 種別: `NS`
- 値: ステージ1で出力された4件のネームサーバーを1件ずつ登録

反映を待ってから委任できているか確認します（数分〜数時間かかることがあります）。

```bash
dig NS portal.tokaiec.co.jp
```

ステージ1で出力された4件のネームサーバーが返ってくれば完了です。**ここが確認できるまでステージ3には進まないでください**（ACM証明書のDNS検証が終わらず待ち続けてしまいます）。

### ステージ3: ACM証明書の発行（us-east-1固定）

CloudFrontで使う証明書は必ず `us-east-1` で発行する必要があります。

```bash
aws cloudformation deploy \
  --template-file infra/certificate.yaml \
  --stack-name employee-portal-certificate \
  --region us-east-1 \
  --parameter-overrides HostedZoneId=<ステージ1のHostedZoneId> \
  --tags Project=renrakusaki

aws cloudformation describe-stacks \
  --stack-name employee-portal-certificate \
  --region us-east-1 \
  --query "Stacks[0].Outputs"
```

NS委任が反映済みであれば数分でDNS検証が完了し `CREATE_COMPLETE` になります。`CertificateArn` を控えてください。

### ステージ4: 本体スタックのデプロイ

S3への直接アクセスを遮断するための秘密値を先に生成します（値自体はリポジトリに残らないので都度控えておいてください）。

```bash
openssl rand -hex 16
```

```bash
sam build
sam deploy --guided \
  --tags Project=renrakusaki \
  --parameter-overrides \
    HostedZoneId=<ステージ1のHostedZoneId> \
    AcmCertificateArn=<ステージ3のCertificateArn> \
    OriginVerifySecret=<生成した秘密値>
```

`--guided` で入力した内容（タグ含む）は `samconfig.toml` に保存されますが、`OriginVerifySecret` は `NoEcho` パラメータのため平文では保存されません。2回目以降のデプロイでも `--parameter-overrides OriginVerifySecret=<同じ値>` を明示的に指定してください（値を変えると、既存のCloudFrontキャッシュ内の古いRefererヘッダーとS3ポリシーの新しい秘密値が一時的に不整合になるため、変更する場合はCloudFrontの反映完了後にアクセス確認をしてください）。

デプロイ完了後、以下のOutputsが表示されるので控えてください。

- `PortalURL`（従業員がアクセスするHTTPSのURL）
- `WebsiteURL`（S3直アクセス用・動作確認用、HTTPのまま）
- `WebsiteBucketName`
- `DataBucketName`
- `ApiUrl`
- `UserPoolClientId`
- `Region`

## タグによるコスト検索・削除

3つのスタック（`employee-portal-hosted-zone` / `employee-portal-certificate` / 本体スタック）すべてに `--tags Project=renrakusaki` を付けてデプロイすることで、CloudFormationがスタック内のタグ対応リソース（DynamoDB、S3、Lambda、CloudFront、ACM証明書、Route53ホストゾーンなど）に自動で同じタグを継承させます。個々のリソースにタグ定義を書く必要はありません。

- **コスト確認**: [Cost Explorer](https://console.aws.amazon.com/cost-management/home) でタグ `Project = renrakusaki` でフィルタすれば、この一式にかかった費用だけを確認できます（初回はタグをコスト配分タグとして有効化する必要があります: 請求ダッシュボード → コスト配分タグ）。
- **削除**: [Resource Groups](https://console.aws.amazon.com/resource-groups/) でタグ `Project = renrakusaki` を条件にグループを作れば、関連リソースを一覧できます。ただし実際の削除は3つのCloudFormationスタックを `aws cloudformation delete-stack` する（本体 → certificate → hosted-zone の順）のが安全です。

なお、Route53のレコードセットやCognitoのアプリクライアントなど、CloudFormation上そもそもタグに対応していないリソース種別が一部あります（これらは親リソース経由で管理されるため、単体では課金対象にもならないものがほとんどです）。

## 月額コストの目安（利用者100〜200人・分散アクセスの規模）

すべて概算です。実際の請求はCost Explorerで確認してください。

| サービス | 目安 | 備考 |
|---|---|---|
| Route53 ホストゾーン | $0.50/月 | 固定費（クエリ課金はほぼ$0） |
| CloudFront | ほぼ$0 | 無料利用枠（データ転送1TB/月・リクエスト1,000万件/月）内に収まる想定 |
| S3 | ほぼ$0 | 数十KB〜数MBの静的ファイル・CSVのみ |
| API Gateway (HTTP API) | ほぼ$0 | 月間数千リクエスト程度なら$0.01未満 |
| Lambda | ほぼ$0 | 無料利用枠（100万リクエスト/月）内に収まる想定 |
| DynamoDB (オンデマンド) | ほぼ$0 | 200件程度の読み書きなら数セント未満 |
| Cognito | $0 | 50,000 MAUまで無料利用枠 |
| ACM証明書 | $0 | 無料 |
| **合計目安** | **$0.5〜1/月程度**（≒ 数十円〜150円程度） | ほぼRoute53ホストゾーンの固定費のみ |

利用者数・アクセス頻度がこの規模である限り、コストはほぼRoute53の固定費$0.50/月に張り付く想定です。為替レートで円換算額は変動します。

CloudFrontディストリビューションの作成には数分〜十数分かかります。

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

ブラウザで `PortalURL`（`https://portal.tokaiec.co.jp`）を開くと画面が表示されます。

## 従業員CSVの取込

タブ区切り・Shift-JISのCSV（1列目が社員番号）を `incoming/` にアップロードすると自動で取り込まれます。

```bash
aws s3 cp "連絡先.txt" s3://<DataBucketName>/incoming/employees.csv
```

取込処理は以下を行います。

- 各行を社員番号キーでDynamoDBに登録（同じ社員番号があれば上書き更新）
- 社員番号に対応するCognitoユーザーが未登録なら自動作成
  - **パスワード = 社員番号 + 生年月日（例: 社員番号467・生年月日19770807 → `46719770807`）**
  - このパスワードは作成時点で本パスワードとして確定します（初回ログイン時の変更要求はありません）
  - 生年月日が未入力の行はCognitoユーザーを作成しません（`ImportCsvFunction` のログに警告が出ます）

パスワードは社員番号と生年月日から一意に決まるため、従業員自身に個別連絡する必要はありません（本人が知っている情報のみで組み立てられます）。ただしパスワードは推測可能な値なので、この点を踏まえた運用にしてください。

## 従業員のログイン・編集

1. `PortalURL`（`https://portal.tokaiec.co.jp`）にアクセスし、社員番号 + パスワード（社員番号+生年月日）でログイン
2. 自分の情報が表示されるので、変更があれば編集して「登録する」を押すとDynamoDBに反映されます（承認フローなし・即時反映）

## Excel出力（管理者が手動実行）

```bash
aws lambda invoke --function-name employee-renrakusaki-ExportCsv /dev/stdout
```

DynamoDBの全件をExcelブック（`.xlsx`）として `s3://<DataBucketName>/export/employee-renrakusaki_<日時>.xlsx` に出力します。全列を文字列（セル書式「文字列」）で書き込むため、番地（例: 20-6）や電話番号（先頭の0）などもExcelで直接開いた時点でWEBに入力された内容のまま表示されます（CSVで出力していた頃は、Excelが列の値を日付や数値だと自動判定して見た目を変換してしまう問題がありました）。取込用CSVとは別形式のため、出力したファイルをそのまま`incoming/`へ再アップロードして再取込することはできません。

```bash
aws s3 cp s3://<DataBucketName>/export/employee-renrakusaki_20260917_154006.xlsx ./employee-renrakusaki_export.xlsx
```

`src/export_csv/` には`app.py`と一緒に依存ライブラリ`openpyxl`（および`et_xmlfile`）本体を同梱しています（`aws cloudformation package`はcodeUriディレクトリをそのままzip化するだけで`pip install`は行わないため）。この関数のコードだけを差し替える場合は、`app.py`単体ではなく`src/export_csv/`フォルダ全体をzip化してください。

## 変更履歴（誰が・いつ・何を変更したか）

`EmployeeTable`への書き込み（本人によるWeb編集・CSV取込のどちらも）は、DynamoDB Streams経由で`RecordHistoryFunction`が自動的に検知し、`EmployeeHistoryTable`（PK=`社員番号`、SK=`変更ID`）へ1件ずつ記録します。承認フローと違い、この記録は自動・事後参照専用で、書き込み自体を止めたり差し戻したりはしません。

- **変更元**: `Web(本人)`（本人がポータルで保存した場合）または`CSV取込`（管理者がCSVをアップロードした場合）
- **変更内容**: 変更前・変更後の値を項目ごとに記録（変化がなかった項目は含まれない）
- **操作種別**: `新規登録`（初回登録時）または`更新`

閲覧は管理者がDynamoDBコンソールの「項目を探索」、または以下のようにCLIで社員番号ごとに照会します。

```bash
aws dynamodb query \
  --table-name <HistoryTableNameの値> \
  --key-condition-expression "#pk = :v" \
  --expression-attribute-names '{"#pk":"社員番号"}' \
  --expression-attribute-values '{":v":{"S":"467"}}' \
  --region ap-northeast-1
```

閲覧（`GET /me`）操作は対象外です（誰がいつ見たかは記録していません）。

## 運用上の注意（このまま本番利用する場合の検討事項）

- **S3直アクセス制限**: 対応済みです。CloudFrontが秘密のRefererヘッダー（`OriginVerifySecret`）を付けてS3へ転送し、S3バケットポリシーはそのヘッダーを持つリクエストのみ許可します。`WebsiteURL`（S3直URL・HTTP）に直接アクセスするとAccess Deniedになります。
- **初期パスワードの配布**: 社員番号と生年月日から機械的に決まるため配布作業は不要ですが、推測可能な値である点を踏まえ、社外に公開しない運用（社内ネットワーク限定の告知など）を推奨します。
- **監査ログ**: 対応済みです（上記「変更履歴」参照）。ただし閲覧（GET）操作までは記録していません。
- **【重要・既知の不具合】新規Lambdaリソースの日本語環境変数が文字化けすることがある**: デプロイ元のWindows端末のコードページ問題により、`template.yaml`内の`\uXXXX`エスケープが、**新規に作成するLambda関数の環境変数**に対してだけ正しく解決されず、文字化けした値で作成されてしまう事象を確認しています（2026-09-18、`RecordHistoryFunction`追加時に発覚。DynamoDBテーブルの属性名や、既存Lambda関数の環境変数は影響を受けませんでした）。今後、日本語の環境変数を持つ新しいLambda関数を追加する際は、デプロイ後に必ず`aws lambda get-function-configuration`の結果をboto3等（aws-cliの`--output text`はこのマシンでは信用できないため）で確認し、文字化けしていないか検証してください。`RecordHistoryFunction`自体は、この問題を回避するため環境変数に依存せず実行時にDynamoDB Streamsのイベントから属性名を直接読み取る設計にしてあります。
