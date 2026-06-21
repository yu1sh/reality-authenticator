# Reality Authenticator 仕様書（スペック書）

| 項目 | 内容 |
|---|---|
| 文書名 | Reality Authenticator クラウド IoT システム仕様書 |
| 対象企画 | IoT システム開発ⅡA 個人企画「Reality Authenticator」 |
| 版 | v1.2 / 完成実装基準版 |
| 作成日 | 2026-06-08 |
| 更新日 | 2026-06-16 |
| 開発環境 | Omarchy PC + Codex + Raspberry Pi + Azure |
| 想定成果物 | Web 画面、Raspberry Pi エッジプログラム、Azure Functions、証明レコード、QR 検証ページ |

---

## 1. 本仕様書の位置づけ

本仕様書は、企画書で定義された **Reality Authenticator** を、実際に開発可能な単位へ落とし込むための技術仕様書である。

v1.2 では、本番 MVP の通信経路を
`Web → Azure Functions → IoT Hub C2D → Raspberry Pi → Blob Storage / IoT Hub D2C → Azure Functions → Key Vault → Proof`
に固定する。HTTP の Evidence ingest と Proof issue はローカル開発・自動テスト専用であり、
Azure dev 環境では無効化する。本書内の旧フェーズ説明と競合する場合は、この v1.2 の規定を優先する。

企画書では、Raspberry Pi と Azure を用いて、利用者が現実世界で操作したことを、センサ、画像、音声、時刻、ハッシュ値、電子署名付き証明レコードとして記録するクラウド IoT システムが提案されている。本仕様書では、その内容を以下の観点で具体化する。

- システムの目的と非目的
- MVP と発展機能の分離
- ハードウェア構成
- クラウド構成
- データフロー
- API 仕様
- データベース仕様
- 証明レコード仕様
- ハッシュ、署名、チャレンジ方式
- UI 仕様
- 開発環境、リポジトリ構成、Codex への作業分解
- テスト仕様
- リスクと実装上の注意点

---

## 2. システム概要

### 2.1 システム名

**Reality Authenticator**

### 2.2 一文説明

登録済み Raspberry Pi 端末で取得した物理操作、センサ値、画像、音声、クラウド時刻、ファイルハッシュを統合し、Azure 上で電子署名付きの **現実証明レコード** を発行・検証するクラウド IoT システムである。

### 2.3 目的

本システムの目的は、成果物そのものではなく、**成果物が作成・提出・記録された周辺状況** を証明可能な形で保存することである。

具体的には、以下を実現する。

1. 登録済み端末からのみ証明操作を開始できる。
2. Azure 側で一度限りのランダムチャレンジを生成する。
3. 利用者が指定時間内に物理操作と音声入力を行う。
4. Raspberry Pi がセンサ値、画像、音声、操作ログを取得する。
5. 取得ファイルの SHA-256 ハッシュを計算する。
6. Azure 側で時刻、端末 ID、チャレンジ結果、センサ値、ハッシュ値を検証する。
7. 検証済みデータから証明レコードを作成する。
8. 証明レコードに Azure Key Vault の鍵で電子署名を付与する。
9. QR コード付きの検証ページで、証明内容と改ざん有無を確認できる。

### 2.4 非目的

本システムは、以下を目的としない。

| 項目 | 理由 |
|---|---|
| 法的な電子証明書の発行 | 本企画は法的効力を持つ電子証明書ではなく、電子署名付きの現実証明レコードを発行するプロトタイプである。 |
| 本人の法的身元確認 | マイナンバー、運転免許証、eKYC 等の本人確認は扱わない。 |
| 生体認証による本人特定 | プライバシー配慮のため、顔認証・声紋認証は MVP では行わない。 |
| AI を絶対に使っていないことの証明 | MVP では「登録端末上で物理的操作が行われたこと」を記録する。AI 不使用の完全証明は専用ソフトウェア連携を将来機能とする。 |
| 悪意ある利用者への完全対抗 | 端末の物理改造、センサ偽装、録音音声再生などを完全に防ぐものではない。 |

---

## 3. MVP と発展機能

### 3.1 MVP の範囲

MVP では、授業発表・デモで成立する最小構成を優先する。

#### MVP で必ず実装する機能

| ID | 機能 | 内容 |
|---|---|---|
| MVP-01 | 証明開始 | Web 画面から証明セッションを開始できる。 |
| MVP-02 | チャレンジ生成 | Azure Functions がランダムな操作指示を生成する。 |
| MVP-03 | 端末取得 | Raspberry Pi が Azure IoT Hub 経由でチャレンジを取得する。 |
| MVP-04 | ボタン操作記録 | 指定時間内の物理ボタン押下回数を記録する。 |
| MVP-05 | センサ値取得 | 温湿度、照度、音量などのセンサ値を最低 2 種類以上取得する。 |
| MVP-06 | 画像取得 | USB カメラまたは Pi Camera で静止画を 1 枚取得する。 |
| MVP-07 | 音声取得 | USB マイク等で短時間の音声ファイルを保存する。 |
| MVP-08 | ハッシュ計算 | 画像・音声・証明レコードの SHA-256 ハッシュを計算する。 |
| MVP-09 | クラウド送信 | Evidence Manifest を Azure IoT Hub 経由で送信する。画像・音声は Blob Storage に保存する。 |
| MVP-10 | 証明レコード生成 | Azure Functions が証明レコードを生成する。 |
| MVP-11 | 電子署名 | Azure Key Vault の鍵で証明レコードハッシュに署名する。 |
| MVP-12 | QR 検証ページ | QR コードから検証ページを開き、証明内容を確認できる。 |

### 3.2 MVP では簡略化する項目

| 項目 | MVP の扱い | 将来の扱い |
|---|---|---|
| 音声認識 | 音声ファイルを保存し、ハッシュで改ざん検知する。数字の自動認識は任意。 | Azure AI Speech 等で読み上げ数字を自動照合する。 |
| 端末へのクラウド指令 | Azure IoT Hub Cloud-to-Device Message に固定する。 | 複数端末向けの配信制御、再送、優先度制御を追加する。 |
| DB | Azure Table Storage を推奨する。 | Cosmos DB、PostgreSQL 等に拡張する。 |
| 認証 | デモ用の単一管理者・単一端末を前提にする。 | Microsoft Entra ID、ロール管理を追加する。 |
| 証明対象ファイル | デモでは画像・音声・センサログを対象にする。 | レポート、契約書、動画、作業ログ等を対象に拡張する。 |

### 3.3 発展機能

| ID | 発展機能 | 内容 |
|---|---|---|
| EXT-01 | 専用作成ソフトウェア連携 | レポート作成ソフト、画像編集ソフト、録音ソフト等と連携し、作業中の操作ログを証明対象に含める。 |
| EXT-02 | AI 不使用モード | 専用ソフトウェア利用中に外部 AI API、生成 AI アプリ、クリップボード貼付等を検知・制限する。 |
| EXT-03 | 音声チャレンジ自動照合 | 音声認識により、読み上げられた 4 桁数字とチャレンジを照合する。 |
| EXT-04 | 動画証明 | 静止画ではなく短時間動画と音声を同時に記録する。 |
| EXT-05 | 複数端末対応 | 複数 Raspberry Pi、複数利用者、複数教室・作業場所に対応する。 |
| EXT-06 | 証明レコード公開範囲制御 | 公開、限定公開、非公開、削除申請などの制御を実装する。 |
| EXT-07 | 監査ログ強化 | すべての検証・閲覧・再署名操作を監査ログに残す。 |

---

## 4. 用語定義

| 用語 | 定義 |
|---|---|
| Proof | 証明レコード。特定時点の物理操作、センサ値、画像、音声、ハッシュ、署名をまとめたデータ。 |
| Proof ID | 証明レコードの一意 ID。例: `RP-33333333-3333-4333-8333-333333333333`。 |
| Session | 証明開始から証明レコード発行までの一連の処理単位。 |
| Challenge | Azure が生成する一度限りの操作指示。例: 10 秒以内にボタンを 2 回押し、4821 と発声する。 |
| Anchor Device | 現実世界の操作を記録する登録済み端末。MVP では Raspberry Pi。 |
| Evidence | 証明の根拠となるファイルまたはデータ。画像、音声、センサ値、ボタンログなど。 |
| Evidence Manifest | Evidence の一覧、ハッシュ、保存先、取得時刻をまとめた JSON。 |
| Record Hash | 証明レコード本体から算出した SHA-256 ハッシュ。署名対象となる。 |
| Signature | Key Vault の秘密鍵で Record Hash に対して生成する電子署名。 |
| Verification Page | QR コードからアクセスできる証明確認ページ。 |
| Canonical JSON | キー順序、空白、文字コード差異によるハッシュ不一致を防ぐため、正規化した JSON 表現。 |

---

## 5. 利用者とユースケース

### 5.1 想定利用者

| 利用者 | 目的 |
|---|---|
| 学生 | レポート、制作物、実験記録などを作成した環境・時刻・操作を記録する。 |
| 教員 | 提出物に付属する証明レコードを確認する。 |
| クリエイター | 画像、音声、動画などの制作過程の一部を証明する。 |
| 管理者 | 端末登録、証明レコード管理、トラブル確認を行う。 |
| 第三者検証者 | QR コードから証明内容と改ざん有無を確認する。 |

### 5.2 ユースケース一覧

| ID | ユースケース | 主体 | 概要 |
|---|---|---|---|
| UC-01 | 証明を開始する | 利用者 | Web 画面で対象端末を選択し、証明開始を押す。 |
| UC-02 | チャレンジを実行する | 利用者 | 指定時間内にボタン押下と音声読み上げを行う。 |
| UC-03 | 証拠データを取得する | Raspberry Pi | センサ値、画像、音声、操作ログを取得する。 |
| UC-04 | 証明レコードを発行する | Azure Functions | 取得データを検証し、署名付き証明レコードを作成する。 |
| UC-05 | 証明内容を確認する | 教員・第三者 | QR コードから検証ページを開き、ハッシュ・署名・端末 ID を確認する。 |
| UC-06 | 失敗理由を確認する | 利用者・管理者 | タイムアウト、ボタン回数不一致、ファイル欠落などを確認する。 |

---

## 6. システム構成

### 6.1 全体構成

```text
[利用者ブラウザ]
    |
    | HTTPS
    v
[Azure Functions: Web/API]
    |          |                 |
    |          |                 +--> [Azure Key Vault: 署名鍵]
    |          |
    |          +--> [Azure Table Storage: Session/Proof/Device]
    |
    +--> [Blob Storage: 画像/音声/証明JSON/QR]

[Web画面: 証明開始]
    |
    | Session作成
    v
[Azure Functions]
    |
    | Azure IoT Hub C2D
    v
[Raspberry Pi: Edge Agent]
    |
    | GPIO / Camera / Microphone / Sensors
    v
[物理世界の操作・環境]

[Raspberry Pi]
    |
    | JSON Telemetry / Evidence Manifest
    v
[Azure IoT Hub]
    |
    | Trigger
    v
[Azure Functions: Validate & Issue]
```

### 6.2 構成要素

| 要素 | 役割 | MVP 実装方針 |
|---|---|---|
| Omarchy PC | 開発端末 | Codex、VS Code、Git、Azure CLI、Python、Node.js を利用する。 |
| Codex | 実装支援 | 機能単位でコード生成・修正・テスト作成を行う。秘密情報は渡さない。 |
| Raspberry Pi 4 | Anchor Device | GPIO、センサ、カメラ、マイクを制御し、証拠データを取得する。 |
| Grove センサ類 | 物理環境取得 | ボタン、温湿度、照度、音量などを取得する。Raspberry Pi 直結可否に注意する。 |
| Azure IoT Hub | データ受信 | Raspberry Pi から送信される Evidence Manifest を受信する。 |
| Azure Functions | API・検証・発行 | チャレンジ生成、検証、証明レコード生成、検証ページ配信を行う。 |
| Azure Key Vault | 署名鍵管理 | 秘密鍵をクラウド上で保護し、署名処理のみ実行する。 |
| Azure Blob Storage | ファイル保存 | 画像、音声、証明 JSON、QR コード画像を保存する。 |
| Azure Table Storage | メタデータ保存 | Device、Session、Proof、AuditLog を保存する。 |
| Web UI | 操作・閲覧 | 証明開始、状態確認、証明書表示、QR 表示を行う。 |

---

## 7. ハードウェア仕様

### 7.1 開発端末

| 項目 | 仕様 |
|---|---|
| OS | Omarchy |
| 主用途 | ローカル開発、Codex によるコード生成、Azure へのデプロイ、動作確認 |
| 必須ツール | Git、Python、uv または venv、Node.js、Azure CLI、Azure Functions Core Tools、VS Code または任意エディタ |
| 推奨 | Docker または Dev Container。ただし MVP では必須ではない。 |

### 7.2 エッジ端末

| 項目 | 仕様 |
|---|---|
| 本体 | Raspberry Pi 4 |
| OS | Raspberry Pi OS 系を推奨 |
| 言語 | Python |
| カメラ | USB カメラまたは Pi Camera |
| マイク | USB マイクを推奨 |
| ネットワーク | Wi-Fi または Ethernet |
| 電源 | 安定した USB-C 電源。低電圧警告が出ないもの。 |
| 保存 | microSD。証拠ファイルの一時保存領域を確保する。 |

### 7.3 センサ構成

#### 7.3.1 推奨センサ

| センサ | 用途 | 必須度 | 備考 |
|---|---|---|---|
| 物理ボタン | チャレンジ操作 | 必須 | GPIO 入力。プルアップ/プルダウンを明確化する。 |
| 温湿度センサ | 環境情報 | 推奨 | DHT 系、I2C 系など実装しやすいものを選ぶ。 |
| 照度センサ | 環境情報 | 推奨 | アナログの場合 ADC が必要。 |
| 音量センサ | 環境情報 | 任意 | アナログの場合 ADC が必要。音声ファイルとは別の環境値として扱う。 |
| カメラ | 現場画像 | 必須 | デモでは静止画 1 枚でよい。 |
| マイク | 読み上げ音声 | 必須 | USB マイクが実装容易。 |
| LED | 状態表示 | 任意 | 待機中、取得中、成功、失敗を表示する。 |

#### 7.3.2 Grove Beginner Kit 使用時の注意

Grove Beginner Kit for Arduino は Arduino 用を前提とした構成であり、Raspberry Pi に直接接続できないセンサが含まれる。特に Raspberry Pi にはアナログ入力がないため、照度センサや音量センサなどのアナログ値を扱う場合は、以下のいずれかを採用する。

| 方式 | 内容 | 推奨度 |
|---|---|---|
| A. ADC 追加方式 | MCP3008 / MCP3208 などを Raspberry Pi の SPI に接続し、アナログセンサを読む。 | 高 |
| B. Arduino 仲介方式 | Grove Beginner Kit の Arduino 互換ボードでセンサを読み、USB シリアルで Raspberry Pi に送る。 | 高 |
| C. Raspberry Pi 対応 Grove HAT 方式 | Grove Base HAT for Raspberry Pi 等を使う。 | 中 |
| D. デジタルセンサのみ方式 | GPIO ボタン、USB カメラ、USB マイク、I2C センサだけで MVP を構成する。 | 中 |

MVP では、実装難易度を下げるため、**物理ボタン + USB カメラ + USB マイク + 取得しやすい環境センサ 1〜2 種** で成立させる。

### 7.4 GPIO 割り当て案

実際の部品に合わせて変更可能とする。

| 用途 | GPIO | 備考 |
|---|---|---|
| 物理ボタン | GPIO17 | 内部プルアップを使用。押下時 LOW を推奨。 |
| 状態 LED | GPIO27 | 成功・失敗・取得中の表示用。 |
| DHT 系温湿度 | GPIO4 | 使用センサにより変更。 |
| SPI SCLK | GPIO11 | ADC 使用時。 |
| SPI MISO | GPIO9 | ADC 使用時。 |
| SPI MOSI | GPIO10 | ADC 使用時。 |
| SPI CE1 | GPIO7 | ADC 使用時。 |
| ADC CH0 | - | 照度センサ。 |
| ADC CH1 | - | 音量センサ。 |

---

## 8. ソフトウェア構成

### 8.1 リポジトリ構成

```text
reality-authenticator/
├── README.md
├── .gitignore
├── .env.example
├── docs/
│   ├── spec.md
│   ├── PLAN_PHASE_1.md ... PLAN_PHASE_8.md
│   ├── AZURE_DEPLOYMENT.md
│   └── RASPBERRY_PI_SETUP.md
├── packages/
│   └── reality-core/
│       ├── src/reality_core/
│       └── tests/
├── edge-agent/
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/
│   │   └── reality_edge/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── main.py
│   │       ├── cloud_client.py
│   │       ├── cloud_sync.py
│   │       ├── real_capture.py
│   │       ├── evidence.py
│   │       ├── blob_upload.py
│   │       └── hardware/
│   └── tests/
├── cloud-functions/
│   ├── function_app.py
│   ├── host.json
│   ├── local.settings.json.example
│   ├── requirements.txt
│   ├── reality_cloud/
│   ├── web/
│   └── tests/
├── integration-tests/
└── scripts/
    ├── azure/
    └── setup_raspberry_pi.sh
```

### 8.2 技術スタック

| 領域 | 技術 | 理由 |
|---|---|---|
| Edge | Python | Raspberry Pi の GPIO、カメラ、マイク制御が容易。 |
| Cloud API | Azure Functions / Python | 小規模な HTTP API とイベント処理に適する。 |
| IoT 通信 | Azure IoT Hub | 端末 ID 管理と IoT テレメトリ受信のため。 |
| Storage | Azure Blob Storage | 画像・音声・証明 JSON の保存に適する。 |
| DB | Azure Table Storage | MVP では安価で単純なキー・バリュー型保存で十分。 |
| Signing | Azure Key Vault | 秘密鍵をアプリケーションコードから分離できる。 |
| Web | Vanilla HTML/CSS/JavaScript | ビルド工程を持たず、Functions から直接配信できる。 |
| QR | Python qrcode など | 検証ページ URL を QR 化する。 |
| Hash | SHA-256 | ファイル改ざん検知用途として十分に一般的。 |
| Canonicalization | 独自のソート済み JSON | MVP では実装容易性を優先する。 |

---

## 9. データフロー仕様

### 9.1 正常系シーケンス

```text
1. 利用者が Web 画面で「証明開始」を押す。
2. Web は Azure Functions の StartSession API を呼び出す。
3. Azure Functions は session_id、challenge_nonce、challenge_text、expires_at を生成する。
4. Session テーブルに `created` で保存し、チャレンジ確定後に `challenge_issued` へ進める。
5. Azure Functions は IoT Hub C2D で対象端末へチャレンジを配信し、配信受付後に `waiting_device` へ進める。
6. Edge Agent はチャレンジ内容を表示または音声案内する。
7. 利用者は指定時間内にボタンを押し、数字を読み上げる。
8. Edge Agent は以下を取得する。
   - ボタン押下ログ
   - 温湿度・照度・音量などのセンサ値
   - 静止画
   - 音声
9. Edge Agent は画像・音声の SHA-256 を計算する。
10. Edge Agent は画像・音声を Blob Storage にアップロードする。
11. Edge Agent は Evidence Manifest を Azure IoT Hub に送信する。
12. Azure Functions は IoT Hub のイベントを受信する。
13. Azure Functions は Session、Device、Evidence を検証する。
14. 検証結果が成功なら Proof Record を作成する。
15. Proof Record から Canonical JSON を生成し、SHA-256 で Record Hash を計算する。
16. Azure Key Vault で Record Hash に署名する。
17. Proof Record、Signature、QR URL を保存する。
18. Web 画面に証明書と QR コードを表示する。
19. 第三者は QR コードから検証ページを開く。
20. 検証ページでハッシュ値、署名、端末 ID、取得時刻、検証結果を確認する。
```

### 9.2 状態遷移

```text
created
  ↓
challenge_issued
  ↓
waiting_device
  ↓
capturing
  ↓
evidence_uploaded
  ↓
validating
  ↓
verified
  ↓
proof_issued

上記の各状態から failed へ遷移できる。
```

### 9.3 失敗系

| 失敗コード | 条件 | 表示内容 | 記録 |
|---|---|---|---|
| ERR_SESSION_EXPIRED | チャレンジ期限切れ | 「指定時間内に操作が完了しませんでした」 | Session を failed にする。 |
| ERR_DEVICE_MISMATCH | Session の device_id と送信元 device_id が異なる | 「登録端末が一致しません」 | 監査ログに記録。 |
| ERR_BUTTON_COUNT | ボタン押下回数が一致しない | 「ボタン操作がチャレンジ条件と一致しません」 | button_events を保存。 |
| ERR_FILE_MISSING | 画像または音声がアップロードされていない | 「証拠ファイルが不足しています」 | Evidence status を failed にする。 |
| ERR_HASH_MISMATCH | Blob の再計算ハッシュと manifest のハッシュが異なる | 「ファイル改ざんまたは送信不整合を検出しました」 | Proof は発行しない。 |
| ERR_SIGNATURE_FAILED | Key Vault 署名に失敗 | 「証明レコードの署名に失敗しました」 | retryable として記録。 |
| ERR_DEVICE_DISABLED | Device が disabled | 「指定端末は無効化されています」 | Session を作成しない。 |
| ERR_DEVICE_COMMAND | C2D command の配信に失敗 | 「端末へチャレンジを配信できませんでした」 | Session を failed にする。 |
| ERR_EVIDENCE_CONFLICT | 同一 Session に異なる Manifest が到着 | 「異なる証拠が既に登録されています」 | 既存データを保持する。 |
| ERR_STORAGE_UNAVAILABLE | Blob または Table を利用できない | 「保存先へ接続できませんでした」 | 503 を返し、再試行可能とする。 |
| ERR_UNAUTHORIZED | 管理 API キーが不正 | 「管理者 API キーが正しくありません」 | 401 を返す。 |
| ERR_ENDPOINT_DISABLED | Azure でローカル専用 HTTP endpoint を呼んだ | 「この endpoint は無効です」 | 404 を返す。 |
| ERR_INTERNAL | 想定外エラー | 「内部エラーが発生しました」 | 詳細は管理者ログにのみ記録。 |

---

## 10. チャレンジ仕様

### 10.1 チャレンジの目的

チャレンジは、過去に録画・録音したデータの再利用を防ぐために使用する。毎回異なる操作指示を出し、その場で物理操作・音声入力を行わせることで、少なくとも **その時点で端末周辺に人間の操作があった可能性** を高める。

### 10.2 チャレンジ内容

MVP では以下の形式を採用する。

```json
{
  "challenge_type": "button_and_voice",
  "button_count": 2,
  "voice_code": "4821",
  "time_limit_seconds": 10,
  "instruction_ja": "10秒以内に物理ボタンを2回押し、4821と読み上げてください。"
}
```

### 10.3 生成ルール

| 項目 | 仕様 |
|---|---|
| button_count | 1〜3 の整数からランダムに選択する。 |
| voice_code | 0000〜9999 の 4 桁数字をランダム生成する。先頭 0 を許可する。 |
| time_limit_seconds | MVP では 10 秒固定。設定で変更可能にする。 |
| challenge_nonce | UUID v4 または 128 bit 以上のランダム値。 |
| expires_at | created_at + time_limit_seconds + 許容遅延。MVP では +5 秒の通信猶予を許容する。 |

### 10.4 検証ルール

| 検証項目 | MVP | 発展版 |
|---|---|---|
| ボタン回数 | 自動検証する。 | 同じ。 |
| ボタン押下時刻 | チャレンジ開始後、期限内に発生していることを検証する。 | 同じ。 |
| 音声ファイル存在 | 自動検証する。 | 同じ。 |
| 読み上げ数字 | MVP では手動確認または任意実装。 | 音声認識で自動照合する。 |
| センサ値 | 必須項目が欠落していないことを検証する。 | 異常値検知を追加する。 |
| 画像 | ファイル存在とハッシュ一致を検証する。 | 顔検出ではなく、人の存在や端末周辺状況の任意確認に留める。 |

---

## 11. ハッシュ・署名仕様

### 11.1 基本方針

本システムで扱うハッシュは、主に **改ざん検知** と **一意な証跡の固定** のために使用する。

パスワード保存ではないため、画像・音声・証明レコードのハッシュに salt は付与しない。salt は、同じパスワードから同じハッシュが生成されることを防ぐための仕組みであり、ファイルの同一性検証では、同じファイルから同じハッシュが得られる必要がある。

ただし、リプレイ攻撃対策としては salt ではなく、**challenge_nonce、session_id、cloud timestamp** を証明レコードに含める。

### 11.2 ファイルハッシュ

| 対象 | アルゴリズム | 形式 |
|---|---|---|
| 画像 | SHA-256 | lowercase hex |
| 音声 | SHA-256 | lowercase hex |
| Evidence Manifest | SHA-256 | lowercase hex |
| Proof Record | SHA-256 | lowercase hex |

例:

```text
image_sha256 = sha256(image_bytes).hexdigest()
audio_sha256 = sha256(audio_bytes).hexdigest()
```

### 11.3 Record Hash

Record Hash は、schema 1.2 の署名前 Proof Record から生成する。

Record Hash の対象には、Proof の識別情報、Evidence Manifest のハッシュ、
チャレンジ結果、`signature_algorithm`、バージョン付き `key_id`、
`signed_at` を含める。これにより、署名方式、署名鍵、署名時刻の差し替えを
検知できる。

`record_hash`、`signature`、`verification_url` は Record Hash の対象外とする。
`record_hash` と `signature` は計算後に追加される値であり、
`verification_url` は証明内容ではなく検証導線であるためである。

#### Canonical JSON ルール

MVP では以下のルールで正規化する。

1. 文字コードは UTF-8。
2. JSON オブジェクトのキーを辞書順に並べる。
3. 不要な空白を入れない。
4. 日時は ISO 8601 形式に統一する。
5. 小数は必要以上に桁を増やさない。センサ値は記録時点で丸める。

Python 例:

```python
import json
import hashlib

canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### 11.4 電子署名

| 項目 | 仕様 |
|---|---|
| 鍵管理 | Azure Key Vault |
| 鍵種別 | RSA 3072 bit |
| 署名対象 | schema 1.2 unsigned payload の SHA-256 digest |
| 署名アルゴリズム | PS256 |
| 署名形式 | Base64URL 文字列 |
| 公開鍵情報 | key_id と public key metadata を証明レコードに含める。 |

### 11.5 検証ロジック

検証ページでは以下を確認する。

1. Proof Record を取得する。
2. schema 1.2 の規定フィールドから unsigned payload を再生成する。schema 1.0/1.1 は各旧仕様の署名境界を再現する。
3. Record Hash を再計算する。
4. 保存済み Record Hash と一致するか確認する。
5. Key Vault の公開鍵または保存済み公開鍵メタデータで署名を検証する。
6. Blob Storage 上の画像・音声を再取得できる場合、ハッシュを再計算して一致確認する。
7. すべて成功した場合のみ `VALID` と表示する。

---

## 12. データ仕様

新規 Table entity は大文字の `PartitionKey` を使用する。旧実装で保存された
`session`、`device` の lowercase PartitionKey は読み取り・更新互換のみ維持し、
新規作成には使用しない。

### 12.1 Device テーブル

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| PartitionKey | string | Yes | `DEVICE` 固定。 |
| RowKey | string | Yes | device_id。例: `raspi-anchor-01`。 |
| device_id | string | Yes | 端末 ID。 |
| display_name | string | Yes | Web 表示名。 |
| status | string | Yes | `active`, `disabled`。 |
| created_at | string | Yes | 登録日時。 |
| last_seen_at | string | No | 最終通信時刻。 |
| iot_hub_device_id | string | Yes | IoT Hub 上の device id。 |
| public_note | string | No | 端末説明。 |

### 12.2 Session テーブル

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| PartitionKey | string | Yes | `SESSION` 固定。 |
| RowKey | string | Yes | session_id。 |
| session_id | string | Yes | UUID。 |
| device_id | string | Yes | 対象端末。 |
| status | string | Yes | `created`, `challenge_issued`, `waiting_device`, `capturing`, `evidence_uploaded`, `validating`, `verified`, `proof_issued`, `failed`。Proof 発行予約は status を増やさず `proof_id` と署名メタデータで表現する。旧 `proof_issuing` は読み取り・再開互換のみ許可する。 |
| challenge_nonce | string | Yes | ランダム値。 |
| challenge_text | string | Yes | 表示用チャレンジ文。 |
| button_count | int | Yes | 必要なボタン押下回数。 |
| voice_code | string | Yes | 読み上げる 4 桁数字。 |
| created_at | string | Yes | Azure 側の作成時刻。 |
| expires_at | string | Yes | 有効期限。 |
| proof_id | string | No | 発行後の Proof ID。 |
| failure_code | string | No | 失敗時コード。 |

### 12.3 Evidence Manifest

```json
{
  "schema_version": "1.0",
  "session_id": "d4b4f6a0-0000-0000-0000-000000000000",
  "device_id": "raspi-anchor-01",
  "edge_started_at": "2026-06-08T15:00:01+09:00",
  "edge_finished_at": "2026-06-08T15:00:14+09:00",
  "button_events": [
    {"index": 1, "timestamp": "2026-06-08T15:00:05.120+09:00"},
    {"index": 2, "timestamp": "2026-06-08T15:00:06.430+09:00"}
  ],
  "sensors": {
    "temperature_c": 25.6,
    "humidity_percent": 42.8,
    "light_raw": 734,
    "sound_raw": 312
  },
  "files": {
    "image": {
      "blob_path": "evidence/d4b4f6a0-0000-0000-0000-000000000000/image.jpg",
      "sha256": "...",
      "content_type": "image/jpeg",
      "size_bytes": 214532
    },
    "audio": {
      "blob_path": "evidence/d4b4f6a0-0000-0000-0000-000000000000/audio.wav",
      "sha256": "...",
      "content_type": "audio/wav",
      "size_bytes": 541220
    }
  },
  "edge_version": "0.1.0"
}
```

### 12.4 Evidence テーブル

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| PartitionKey | string | Yes | `EVIDENCE` 固定。 |
| RowKey | string | Yes | session_id。 |
| status | string | Yes | `evidence_uploaded` または `failed`。 |
| failure_code | string | No | 失敗コード。 |
| manifest_hash | string | 成功時 | Canonical Manifest の SHA-256。 |
| evidence_bytes_verified | bool | 成功時 | Blob 実体を再ストリームして検証したか。 |
| verified_at | string | No | Blob 実体の検証時刻。 |
| image_blob_path | string | 成功時 | private Blob path。公開 API には返さない。 |
| image_sha256 | string | 成功時 | 画像 SHA-256。 |
| audio_blob_path | string | 成功時 | private Blob path。公開 API には返さない。 |
| audio_sha256 | string | 成功時 | 音声 SHA-256。 |
| canonical_json | string | Yes | 上記論理レコードの Canonical JSON。 |

Manifest 本体は private Blob
`evidence/{session_id}/manifest.json` に保存する。

### 12.5 Proof Record

```json
{
  "schema_version": "1.2",
  "proof_id": "RP-33333333-3333-4333-8333-333333333333",
  "evidence_id": "EV-0123456789abcdef0123456789abcdef",
  "session_id": "d4b4f6a0-0000-0000-0000-000000000000",
  "device_id": "raspi-anchor-01",
  "captured_at": "2026-06-08T15:00:14+09:00",
  "challenge": {
    "type": "button_and_voice",
    "nonce": "11111111-1111-4111-8111-111111111111",
    "instruction_ja": "10秒以内に物理ボタンを2回押し、4821と読み上げてください。",
    "button_count_required": 2,
    "button_count_actual": 2,
    "voice_code": "4821",
    "result": "verified",
    "voice_verification": "not_performed"
  },
  "manifest_hash": "...",
  "created_at": "2026-06-08T15:00:18+09:00",
  "signature_algorithm": "PS256",
  "key_id": "https://<vault>.vault.azure.net/keys/reality-proof-signing/<version>",
  "signed_at": "2026-06-08T15:00:18+09:00",
  "public_key": {
    "kty": "RSA",
    "n": "<Base64URL modulus>",
    "e": "AQAB",
    "bits": 3072
  },
  "record_hash": "...",
  "signature": "...",
  "verification_url": "https://<app>/verify/RP-33333333-3333-4333-8333-333333333333"
}
```

schema 1.2 の `public_key` は `signature_algorithm`、`key_id`、`signed_at` と同様に
Record Hash の対象とする。schema 1.0、1.1 は既存 Proof の検証互換性に限り維持する。

画像・音声のハッシュ、センサ値、Blob path は Evidence Manifest に保持し、
Proof Record の `manifest_hash` によって一括して改ざん検知対象とする。

Proof Table は `PartitionKey=PROOF`、`RowKey=proof_id` とし、`session_id`、
`device_id`、`record_hash`、`manifest_hash`、`signature_algorithm`、`key_id`、
`signed_at`、`created_at`、Proof JSON の private Blob path、`canonical_json`
を保持する。Proof JSON は `proofs/{proof_id}.json`、QR PNG は
`proofs/{proof_id}.png` に保存する。

### 12.6 AuditLog テーブル

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| PartitionKey | string | Yes | date。例: `20260608`。 |
| RowKey | string | Yes | UUID。 |
| event_type | string | Yes | `session_created`, `device_command_dispatched`, `device_heartbeat`, `device_status`, `session_status_updated`, `evidence_ingested`, `proof_issued`, `proof_verified`, `error`。 |
| session_id | string | No | 関連 session。 |
| proof_id | string | No | 関連 proof。 |
| device_id | string | No | 関連 device。 |
| created_at | string | Yes | イベント時刻。 |
| message | string | No | 人間向け概要。 |
| detail | object | No | 詳細。秘密情報は含めず、`canonical_json` 内に保存する。 |
| canonical_json | string | Yes | AuditLog 全体の Canonical JSON。 |

---

## 13. API 仕様

### 13.1 POST `/api/sessions/start`

証明セッションを開始する。

Azure dev では `X-Admin-Api-Key` が必須である。ローカル互換モードに限り
`ALLOW_LOCAL_DEVICE_HTTP=true` と `X-Device-Api-Key` の組み合わせを許可する。

#### Request

```json
{
  "device_id": "raspi-anchor-01"
}
```

#### Response

```json
{
  "session_id": "d4b4f6a0-0000-0000-0000-000000000000",
  "device_id": "raspi-anchor-01",
  "challenge": {
    "instruction_ja": "10秒以内に物理ボタンを2回押し、4821と読み上げてください。",
    "button_count": 2,
    "voice_code": "4821",
    "time_limit_seconds": 10
  },
  "expires_at": "2026-06-08T15:00:15+09:00"
}
```

### 13.2 IoT Hub device command

Raspberry Pi は Azure IoT Hub の Cloud-to-Device Message から、自端末向けの
未処理セッション、チャレンジ、Blob SAS upload target を取得する。
`command_id` は `session_id` と同じ値とし、端末は処理済み ID をローカルに永続化して
再実行を防ぐ。端末は IoT Hub の device identity で認証する。
upload または D2C telemetry が一時失敗して同じ未完了 command が再送された場合は、
同一 challenge の既存 Manifest と媒体を再利用し、Blob を同一内容で再 PUT して
処理を収束させる。処理済み command は再取得・再アップロードしない。

```json
{
  "message_type": "start_session",
  "command_id": "<session_id>",
  "session_id": "<session_id>",
  "device_id": "raspi-anchor-01",
  "challenge": {},
  "expires_at": "...",
  "upload": {
    "mode": "sas_url",
    "image": {},
    "audio": {}
  }
}
```

端末からの D2C telemetry は `heartbeat`、`device_status`、
`evidence_manifest` の 3 種とする。Cloud は JSON 内の device_id ではなく、
IoT Hub が付与した connection device ID を送信元識別に使用する。

### 13.3 POST `/api/evidence/ingest`

本APIは Azure IoT Hub のイベントを受けた Functions 内部処理との共通入口、
およびローカル開発・自動テスト専用とする。本番MVPの Raspberry Pi は
Evidence Manifest を IoT Hub 経由で送信し、このHTTP APIへ直接送信しない。

#### Request

`Evidence Manifest` と同じ。

#### Response

```json
{
  "accepted": true,
  "session_id": "d4b4f6a0-0000-0000-0000-000000000000",
  "status": "evidence_uploaded"
}
```

### 13.4 POST `/api/proofs/issue`

証明レコード発行処理を明示的に起動するローカル開発・自動テスト専用 API。
Azure dev では無効化し、本番経路では D2C Manifest 受理後に内部処理として自動実行する。

#### Request

```json
{
  "session_id": "d4b4f6a0-0000-0000-0000-000000000000"
}
```

#### Response

```json
{
  "issued": true,
  "proof_id": "RP-33333333-3333-4333-8333-333333333333",
  "verification_url": "https://<app>/verify/RP-33333333-3333-4333-8333-333333333333"
}
```

### 13.5 GET `/api/proofs/{proof_id}`

証明レコードを取得する。

#### Response

公開可能な Proof projection を返す。Session ID、Evidence ID、nonce、voice code、
Blob path、内部エラーは返さない。センサ要約、画像・音声 SHA-256、Record Hash、
署名情報は返す。

### 13.6 管理 API

以下は `X-Admin-Api-Key` 必須とする。

- `GET /api/devices`
- `GET /api/sessions/{session_id}`
- `GET /api/admin/proofs/{proof_id}`

### 13.7 GET `/verify/{proof_id}`

人間向けの検証ページを返す。

表示項目:

- 検証ステータス: `VALID` / `INVALID` / `WARNING`
- Proof ID
- Device ID
- Captured At
- Issued At
- Challenge
- Result
- Sensor Summary
- Image SHA-256
- Audio SHA-256
- Record Hash
- Signature Algorithm
- Key ID
- 注意文: 法的な電子証明書ではないこと

### 13.8 POST `/api/proofs/{proof_id}/verify`

署名とハッシュを再検証する。

#### Response

```json
{
  "proof_id": "RP-33333333-3333-4333-8333-333333333333",
  "valid": true,
  "status": "VALID",
  "checks": {
    "proof_identity": true,
    "manifest_hash": true,
    "record_hash": true,
    "signature": true,
    "image_hash": true,
    "audio_hash": true,
    "device_status": true
  }
}
```

`VALID` はすべての検証が成功した場合のみ使用する。ローカル署名 stub、媒体未検証、
端末状態未検証、Key Vault 一時障害は `WARNING` とする。ハッシュ不一致、署名不一致、
disabled device は `INVALID` とする。`valid` は `status=VALID` の場合だけ `true` とし、
`WARNING` と `INVALID` では `false` とする。

---

## 14. Web UI 仕様

### 14.1 画面一覧

| 画面 | URL | 役割 |
|---|---|---|
| ホーム | `/` | システム概要と開始ボタンを表示する。 |
| 証明開始 | `/start` | 対象端末を選択し、証明を開始する。 |
| セッション状態 | `/session/{session_id}` | チャレンジ内容、進行状況、失敗理由を表示する。 |
| 証明書表示 | `/proof/{proof_id}` | 発行済み証明書を表示する。 |
| QR 検証 | `/verify/{proof_id}` | 第三者向け検証ページ。 |

### 14.2 ホーム画面

表示内容:

- システム名: Reality Authenticator
- 説明: 物理操作とクラウド署名による現実証明レコード
- `証明を開始する` ボタン
- 注意書き:
  - 法的な電子証明書ではない
  - 本人確認は行わない
  - 画像・音声を取得するため周囲の同意に注意する

### 14.3 証明開始画面

表示内容:

- 管理者 API キー入力
- 登録端末一覧
- 選択中端末のステータス
- 証明開始ボタン

操作:

1. 利用者が端末を選ぶ。
2. `証明開始` を押す。
3. `POST /api/sessions/start` を呼ぶ。
4. チャレンジ画面へ遷移する。

管理者 API キーはブラウザの `sessionStorage` のみに保持し、Cookie、
Local Storage、HTML、ログには保存しない。

### 14.4 セッション状態画面

表示内容:

- Challenge text
- 残り時間
- Session status
- Device status
- Evidence upload status
- エラー発生時の失敗理由

状態更新:

- 1〜2 秒間隔で API をポーリングする。
- `proof_issued` になったら証明書画面へ移動する。

### 14.5 証明書画面

表示内容:

```text
Reality Proof Certificate
Proof ID: RP-33333333-3333-4333-8333-333333333333
Device: raspi-anchor-01
Captured At: 2026-06-08 15:00:14 JST
Challenge: 10秒以内に物理ボタンを2回押し、4821と読み上げ
Result: Verified
Sensor: Temp 25.6℃, Humidity 42.8%, Light 734, Sound 312, Button 2
Image SHA-256: ...
Audio SHA-256: ...
Record Hash: ...
Signature: Signed by Reality Anchor
QR Code: 検証ページへのリンク
```

### 14.6 検証ページ

第三者が閲覧するため、管理者向け情報や内部エラー詳細は表示しない。

表示すべき注意文:

```text
このページは、Reality Authenticator により発行された電子署名付き現実証明レコードの検証結果です。
本レコードは、登録済み端末で取得されたセンサ値、画像、音声、時刻、ハッシュ値、電子署名を確認するためのものであり、法的な本人確認または法的効力を持つ電子証明書ではありません。
```

---

## 15. Raspberry Pi Edge Agent 仕様

### 15.1 役割

Edge Agent は、Raspberry Pi 上で動作する Python プログラムであり、以下を担当する。

1. Azure から自端末向けチャレンジを取得する。
2. 物理ボタン操作を監視する。
3. センサ値を取得する。
4. カメラで静止画を撮影する。
5. マイクで音声を録音する。
6. ファイルの SHA-256 を計算する。
7. Blob Storage にファイルをアップロードする。
8. Evidence Manifest を Azure に送信する。
9. 成功・失敗状態をローカルログに出力する。

### 15.2 起動方式

MVP では CLI 起動とする。

```bash
cd edge-agent
python -m reality_edge.main
```

発展版では systemd service として常駐させる。

### 15.3 設定ファイル

`.env` 例:

```env
DEVICE_ID=raspi-anchor-01
IOT_HUB_DEVICE_CONNECTION_STRING=<device connection string>
IOT_HEARTBEAT_SECONDS=60
CAMERA_DEVICE=/dev/video0
AUDIO_DEVICE=default
EVIDENCE_DIR=/home/pi/reality-evidence
BUTTON_GPIO=17
LED_GPIO=27
```

### 15.4 Edge Agent の内部モジュール

| モジュール | 役割 |
|---|---|
| `config.py` | 環境変数・設定ファイル読み込み。 |
| `cloud_client.py` / `cloud_sync.py` | ローカル開発用 HTTP 同期。Azure dev の本番経路では使用しない。 |
| `iot_agent.py` | IoT Hub C2D 常駐受信、heartbeat、重複排除、D2C telemetry 送信。 |
| `hardware/button.py` | GPIO ボタン入力監視。チャタリング対策を含む。 |
| `hardware/sensors.py` | Grove USB シリアルから温湿度、照度、音量を取得する。 |
| `hardware/camera.py` | `rpicam-still` による静止画撮影。 |
| `hardware/microphone.py` | `arecord` による音声録音。 |
| `hardware/status.py` | 撮影・録音中と成功・失敗を GPIO LED で表示する。 |
| `blob_upload.py` | 短時間 SAS URL を使用した private Blob へのアップロード。 |
| `evidence.py` | Evidence Manifest 生成。 |
| `dry_run.py` / `real_capture.py` | dry-run と実機で共通形式の capture/manifest を生成する。 |
| `main.py` | 全体制御。 |

SHA-256 と Canonical JSON は `packages/reality-core` を Edge と Cloud で共有する。

### 15.5 チャタリング対策

物理ボタンはチャタリングが発生するため、以下を実装する。

| 項目 | 仕様 |
|---|---|
| debounce_ms | 150〜300 ms。MVP 推奨値は 200 ms。 |
| 押下判定 | 前回押下から debounce_ms 未満のイベントは無視する。 |
| ログ | 有効押下のみ `button_events` に記録する。 |

### 15.6 ローカル保存

Edge Agent は、アップロード前の証拠ファイルを一時保存する。

```text
~/reality-evidence/
└── <session_id>/
    ├── image.jpg
    ├── audio.wav
    ├── manifest.json
    └── edge.log
```

アップロード成功後も、デモ中は削除しない。発展版では保存期間を設定する。

---

## 16. Azure Functions 仕様

### 16.1 Function 一覧

| Function | Trigger | 役割 |
|---|---|---|
| StartSession | HTTP | セッション作成とチャレンジ生成。 |
| DispatchDeviceCommand | StartSession 内部処理 | IoT Hub C2D で Edge Agent へチャレンジを配信する。 |
| ProcessTelemetry | Event Hubs trigger | IoT Hub D2C telemetry を受信し、端末 ID を照合する。 |
| IngestEvidence | 内部処理 / HTTP | 本番は ProcessTelemetry から実行し、HTTPはローカル開発・テストに限定する。 |
| IssueProof | 内部処理 / HTTP | 本番は Manifest 受理後に自動実行し、HTTPはローカル開発・テストに限定する。 |
| GetProof | HTTP | 証明レコードを返す。 |
| VerifyProof | HTTP | ハッシュ・署名検証を行う。 |
| RenderVerifyPage | HTTP | 検証ページ HTML を返す。 |

### 16.2 StartSession 詳細

処理:

1. Device Table で device_id が登録済みかつ active か確認する。
2. cryptographic random で challenge を生成する。
3. session_id を生成する。
4. Session Table に保存する。
5. Blob upload 用 SAS URL を生成する。
6. IoT Hub C2D message で command を端末へ配信する。
7. Session status を `waiting_device` に更新し、Web に challenge を返す。

### 16.3 IngestEvidence 詳細

処理:

1. manifest の schema_version を確認する。
2. session_id が存在するか確認する。
3. device_id が session と一致するか確認する。
4. session が期限切れでないか確認する。
5. 必須フィールドがあるか確認する。
6. Blob ファイル存在を確認する。
7. Blob の SHA-256 を再計算し、manifest と比較する。
8. button_events を検証する。
9. Session status を `evidence_uploaded` または `failed` に更新する。
10. status を `validating`、`verified` と進め、成功時は IssueProof を自動実行する。

### 16.4 IssueProof 詳細

処理:

1. Session と Evidence Manifest を読み込む。
2. 検証結果を確定する。
3. Proof ID を採番する。
4. Proof Record を作成する。
5. Canonical JSON を生成する。
6. Record Hash を計算する。
7. Key Vault で署名する。
8. Proof Record に signature、key_id、verify_url を追加する。
9. Proof Table と Blob に保存する。
10. QR コードを生成して Blob に保存する。
11. Session に proof_id を保存し、status を `proof_issued` にする。

---

## 17. Azure リソース仕様

### 17.1 必須リソース

| リソース | 用途 | 名前例 |
|---|---|---|
| Resource Group | 関連リソース管理 | `rg-reality-auth-dev` |
| Storage Account | Blob + Table | `strealityauthdev` |
| Blob Container | 画像・音声保存 | `evidence` |
| Blob Container | 証明 JSON・QR 保存 | `proofs` |
| Table | Device | `RealityDevices` |
| Table | Session | `RealitySessions` |
| Table | Evidence | `RealityEvidence` |
| Table | Proof | `RealityProofs` |
| Table | AuditLog | `RealityAuditLogs` |
| Function App | API / 検証処理 | `func-reality-auth-dev` |
| IoT Hub | 端末データ受信 | `iot-reality-auth-dev` |
| Key Vault | 署名鍵管理 | `kv-reality-auth-dev` |
| Application Insights | ログ・監視 | `appi-reality-auth-dev` |

### 17.2 環境分離

MVP では `dev` のみでよい。

発展版では以下を分ける。

| 環境 | 用途 |
|---|---|
| local | Omarchy PC 上でのローカル開発。 |
| dev | Azure 上の開発・デモ環境。 |
| prod | 本番相当。授業では不要。 |

### 17.3 シークレット管理

| 秘密情報 | 保存場所 | Git 管理 |
|---|---|---|
| IoT Hub connection string | Raspberry Pi の `.env` | 禁止 |
| Function App settings | Azure App Settings | 禁止 |
| Storage connection string | Azure App Settings | 禁止 |
| Key Vault key | Key Vault 内 | コードから直接取得禁止 |
| Device API key | ローカル開発用 `.env` のみ。Azure dev には設定しない。 | 禁止 |
| Admin API key | Azure App Settings | 禁止 |
| IoT Hub device connection string | Raspberry Pi の `.env` | 禁止 |

`.env.example` にはダミー値のみ記載する。

---

## 18. セキュリティ仕様

### 18.1 セキュリティ方針

本システムのセキュリティ目標は、以下である。

1. 証明レコードの改ざんを検知できること。
2. 画像・音声ファイルの差し替えを検知できること。
3. 秘密鍵をアプリケーションコードや Git リポジトリに置かないこと。
4. 未登録端末から証明レコードを発行できないこと。
5. 検証ページで必要以上の個人情報を公開しないこと。
6. Azure dev の管理 API を Admin API key なしで利用できないこと。
7. Azure dev で HTTP Evidence ingest / Proof issue を利用できないこと。

### 18.2 主要対策

| 脅威 | 対策 |
|---|---|
| 証明 JSON の改ざん | Record Hash と電子署名で検知する。 |
| 画像・音声の差し替え | SHA-256 ハッシュで検知する。 |
| 過去データの再利用 | challenge_nonce、voice_code、button_count、expires_at を使う。 |
| 偽端末からの送信 | device_id と API key / IoT Hub 認証を確認する。 |
| 秘密鍵漏えい | Key Vault で署名し、秘密鍵を取得しない。 |
| QR URL の推測 | Proof ID に連番だけでなくランダム suffix を付ける選択肢を用意する。 |
| 個人情報の過剰公開 | 検証ページでは画像・音声の直接公開を避け、必要なら限定公開にする。 |

### 18.3 Proof ID 採番

Proof ID は UUID v4 を使用し、`RP-` prefix を付与する。

```text
RP-33333333-3333-4333-8333-333333333333
```
連番は使用せず、公開URLの推測耐性と分散発行時の一意性を確保する。

### 18.4 プライバシー仕様

画像・音声は個人情報を含み得るため、以下を守る。

1. 撮影・録音中であることを UI と LED で明示する。
2. デモでは自分または許可を得た範囲のみ撮影・録音する。
3. 検証ページで画像・音声を無条件公開しない。
4. Blob は原則 private とし、必要時のみ短時間 SAS URL を発行する。
5. 証明書画面にはハッシュ値とメタデータを中心に表示する。

---

## 19. 非機能要件

| ID | 分類 | 要件 |
|---|---|---|
| NFR-01 | 性能 | 証明開始から証明書発行まで、通常 30 秒以内を目標にする。 |
| NFR-02 | 可用性 | 授業デモ中に単一端末・単一ユーザーで連続 3 回実行できる。 |
| NFR-03 | 保守性 | Edge、Cloud、Web をディレクトリで分離し、機能単位でテスト可能にする。 |
| NFR-04 | 移植性 | Edge Agent は Raspberry Pi OS 上で動作する。Omarchy PC では GPIO なしの dry-run が可能。 |
| NFR-05 | 観測性 | セッション作成、証拠受信、証明発行、失敗理由をログに残す。 |
| NFR-06 | セキュリティ | 秘密情報を Git に含めない。Key Vault で署名鍵を管理する。 |
| NFR-07 | プライバシー | 画像・音声を公開しない設計を基本とする。 |
| NFR-08 | デモ容易性 | 失敗時にも理由が画面に表示され、発表中に説明できる。 |

---

## 20. ローカル開発仕様

### 20.1 Omarchy PC 側セットアップ

必要なもの:

```bash
# 例。実際のパッケージ管理方法に合わせて調整する。
git --version
python --version
node --version
az version
func --version
```

推奨ディレクトリ:

```bash
mkdir -p ~/dev
cd ~/dev
git clone <repo-url> reality-authenticator
cd reality-authenticator
```

### 20.2 Python 仮想環境

Edge:

```bash
cd edge-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Cloud Functions:

```bash
cd cloud-functions
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 20.3 Dry-run モード

Omarchy PC では GPIO が存在しないため、Edge Agent に dry-run モードを用意する。

```bash
python -m reality_edge.main --dry-run
```

Dry-run では以下を行う。

- 通常は決定論的なダミー button events を生成し、`--interactive` 指定時はキーボード入力で代替する。
- センサ値をダミー値で生成する。
- 画像はテスト用ファイルを使用する。
- 音声はテスト用 WAV を使用する。
- Azure への送信処理は実行可能にする。

---

## 21. Codex を使った開発方針

### 21.1 Codex に渡す基本方針

Codex には、巨大な一括実装ではなく、機能単位で依頼する。

避けるべき依頼:

```text
Reality Authenticator を全部作ってください。
```

推奨する依頼:

```text
edge-agent/src/reality_edge/hashing.py に、指定ファイルの SHA-256 を計算する関数を実装してください。
テストは edge-agent/tests/test_hashing.py に pytest で作成してください。
既存の公開 API は変更しないでください。
```

### 21.2 Codex 作業単位

| 順序 | タスク | 成果物 |
|---|---|---|
| 1 | リポジトリ雛形作成 | ディレクトリ、README、.gitignore、.env.example |
| 2 | 共通ハッシュ処理 | `hashing.py`、テスト |
| 3 | Canonical JSON | `canonical_json.py`、テスト |
| 4 | Edge dry-run | ダミーセンサ、ダミーファイル、manifest 生成 |
| 5 | StartSession API | Function 実装、Session 保存 |
| 6 | IoT Hub command | Edge へのチャレンジ配信 |
| 7 | Evidence upload | Blob upload、manifest 送信 |
| 8 | IngestEvidence | manifest 検証、hash 照合 |
| 9 | Key Vault signing | 署名処理、ローカル fallback |
| 10 | Proof issue | Proof Record 生成、QR 生成 |
| 11 | Web UI | Start、Session、Proof、Verify 画面 |
| 12 | Raspberry Pi 実センサ接続 | GPIO、カメラ、マイク実装 |
| 13 | 統合テスト | デモ手順で確認 |

### 21.3 Codex 用プロンプト雛形

```text
あなたはこのリポジトリの実装担当です。
目的は Reality Authenticator の MVP を完成させることです。
以下の仕様を守って、指定ファイルだけを変更してください。

対象:
- <変更対象ファイル>

実装内容:
- <実装したい機能>

制約:
- 秘密情報をコードに書かない。
- .env.example にはダミー値だけを書く。
- 既存テストを壊さない。
- 可能なら pytest を追加する。
- 型ヒントを付ける。
- エラー時は例外または明示的な戻り値で扱う。

完了条件:
- <期待するテスト結果>
```

---

## 22. テスト仕様

### 22.1 単体テスト

| ID | 対象 | テスト内容 |
|---|---|---|
| UT-01 | hash_file | 同じファイルで同じ SHA-256 が返る。 |
| UT-02 | hash_file | 存在しないファイルで明示的な例外が出る。 |
| UT-03 | canonical_json | キー順序が違っても同じ canonical string になる。 |
| UT-04 | challenge | button_count が 1〜3 の範囲になる。 |
| UT-05 | challenge | voice_code が 4 桁文字列になる。 |
| UT-06 | button validation | 指定回数と一致したら成功。 |
| UT-07 | button validation | 回数不一致なら失敗。 |
| UT-08 | proof hash | 署名前 record から record_hash が生成される。 |
| UT-09 | signature verify | テスト鍵で署名検証が成功する。 |

### 22.2 統合テスト

| ID | 内容 | 期待結果 |
|---|---|---|
| IT-01 | StartSession API を呼ぶ | session_id と challenge が返る。 |
| IT-02 | Edge dry-run で IoT Hub 経由の evidence を送る | evidence_uploaded になる。 |
| IT-03 | 正常な manifest を送る | proof_issued になる。 |
| IT-04 | 画像ハッシュを改ざんする | ERR_HASH_MISMATCH になる。 |
| IT-05 | button_count を間違える | ERR_BUTTON_COUNT になる。 |
| IT-06 | 期限切れ後に送信する | ERR_SESSION_EXPIRED になる。 |
| IT-07 | QR 検証ページを開く | VALID と表示される。 |
| IT-08 | Blob が欠落した Manifest を送る | ERR_FILE_MISSING になり Proof を発行しない。 |
| IT-09 | disabled Device の Proof を検証する | INVALID になる。 |
| IT-10 | Key Vault 検証が一時的に利用不能 | WARNING になり内部詳細を公開しない。 |
| IT-11 | 同じ C2D command を再送する | Edge が永続化済み command_id を検出し、再取得しない。 |

IT-07 の `VALID` は Azure dev の PS256・媒体再ストリーム成功時を指す。
ローカル署名 stub または媒体未検証のローカル E2E は `WARNING` を正解とする。

### 22.3 実機テスト

| ID | 内容 | 期待結果 |
|---|---|---|
| DT-01 | Raspberry Pi で Edge Agent 起動 | エラーなく IoT Hub command を待機し、60秒間隔で heartbeat を送る。 |
| DT-02 | Web から証明開始 | Pi がチャレンジを取得する。 |
| DT-03 | ボタン 2 回押下 | button_events が 2 件記録される。 |
| DT-04 | カメラ撮影 | image.jpg が保存される。 |
| DT-05 | 音声録音 | audio.wav が保存される。 |
| DT-06 | Blob upload | Blob に画像・音声が保存される。 |
| DT-07 | 証明書発行 | Proof Record と QR が作成される。 |

### 22.4 デモ受け入れ条件

以下をすべて満たしたら MVP 完了とする。

1. Web 画面から証明開始できる。
2. Raspberry Pi が Azure IoT Hub 経由でチャレンジを取得できる。
3. 物理ボタン操作が記録される。
4. センサ値が 2 種類以上記録される。
5. 画像と音声が保存される。
6. 画像と音声の SHA-256 が Evidence Manifest に含まれ、その Manifest Hash が証明レコードに含まれる。
7. Record Hash が作成される。
8. Azure dev では Key Vault PS256 で署名できる。ローカル開発用鍵は WARNING 表示とする。
9. QR コードから検証ページを開ける。
10. 検証ページに `VALID` と証明内容が表示される。
11. AuditLog と Application Insights に主要イベントが記録される。
12. 指定 Raspberry Pi 実機で 30 秒以内の正常実行を 3 回連続で成功できる。

---

## 23. 実装優先順位

### 23.1 最優先

1. ハッシュ計算
2. 証明レコード JSON
3. StartSession API
4. Edge dry-run
5. Blob upload
6. Proof issue
7. Verify page

### 23.2 次点

1. 実機ボタン
2. 実機カメラ
3. 実機マイク
4. センサ値取得
5. 監査ログ
6. セッション状態画面

### 23.3 後回し

1. 音声認識
2. 複数ユーザー認証
3. 専用ソフトウェア連携
4. AI 不使用検知
5. 生体認証

---

## 24. 実装スケジュール案

| フェーズ | 期間目安 | 内容 | 完了条件 |
|---|---|---|---|
| Phase 0 | 0.5 日 | リポジトリ作成、仕様整理、Azure リソース方針決定 | README と spec が存在する。 |
| Phase 1 | 1 日 | Edge dry-run、hash、manifest 作成 | ローカルで manifest.json を生成できる。 |
| Phase 2 | 1〜2 日 | StartSession、端末command、Table Storage | Web/API から session を作れる。 |
| Phase 3 | 1〜2 日 | Blob upload、evidence ingest、hash 検証 | 画像・音声を保存し検証できる。 |
| Phase 4 | 1 日 | Proof Record、record_hash、署名、QR | 証明レコードを発行できる。 |
| Phase 5 | 1 日 | Web UI、検証ページ | QR から検証ページを表示できる。 |
| Phase 6 | 1〜2 日 | Raspberry Pi 実機接続 | ボタン、カメラ、マイク、センサが動作する。 |
| Phase 7 | 0.5〜1 日 | デモ調整、失敗時対応、発表用ログ | 連続 3 回成功する。 |
| Phase 8 | 1〜2 日 | Key Vault PS256署名、schema 1.2、Azureデプロイ強化 | 公開鍵メタデータを署名対象に含め、バージョン付きKey IDで署名・検証できる。 |

---

## 25. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| Grove センサが Raspberry Pi に直結できない | センサ値取得が遅れる | ADC 追加、Arduino 仲介、またはデジタルセンサのみで MVP を構成する。 |
| 音声認識が不安定 | チャレンジ自動検証に失敗 | MVP では音声ファイル保存とハッシュ検証に留める。 |
| Key Vault 実装に時間がかかる | 署名機能が遅れる | 開発用ローカル鍵 fallback を用意し、最終版で Key Vault に差し替える。 |
| Azure IoT Hub が複雑 | 送信処理が遅れる | IoT Hubを早期に構築し、ローカルでは同一処理をHTTPでテストできるよう分離する。 |
| 画像・音声のプライバシー問題 | デモ公開が難しくなる | 検証ページではハッシュ中心にし、ファイル自体は private にする。 |
| Wi-Fi 不安定 | デモ失敗 | 事前に有線 LAN またはスマホテザリング代替を準備する。 |
| 時刻ずれ | 期限検証で失敗 | Azure 時刻を基準にし、Edge 時刻は参考値にする。 |
| 証明の過大主張 | 企画の信頼性低下 | 「AI 不使用の完全証明ではない」「法的証明ではない」と明記する。 |

---

## 26. 将来拡張: 専用ソフトウェア連携

MVP では、物理操作と周辺データから「その時点で人間が端末周辺で操作したこと」を記録する。しかし、AI を人間が操作して成果物を作った場合、本システムだけでは AI 利用を否定できない。

そのため、将来構想として、証明対象ファイルを作成する専用ソフトウェアと本システムを連携させる。

### 26.1 専用ソフトウェア連携の目的

- 証明対象ファイルがどのソフトウェア上で作成されたかを記録する。
- 作業中の操作ログ、保存履歴、編集履歴を記録する。
- 外部生成 AI の利用、貼り付け、API 呼び出しなどを検知または制限する。
- Raspberry Pi による物理チャレンジと、PC 上の作業ログを同じ Proof Record に結合する。

### 26.2 将来の証明対象

| 対象 | 例 |
|---|---|
| レポート | Markdown、PDF、Word 変換前の編集ログ |
| 画像 | 専用画像編集ソフト内の操作ログ |
| 音声 | 録音ソフト内の録音開始・停止ログ |
| 契約情報 | 入力画面、承認操作、タイムスタンプ |
| プログラム | エディタ操作、Git commit、実行ログ |

### 26.3 追加レコード例

```json
{
  "software_attestation": {
    "app_name": "Reality Writer",
    "app_version": "0.1.0",
    "workspace_id": "ws-abc123",
    "file_sha256": "...",
    "edit_started_at": "2026-06-08T14:30:00+09:00",
    "edit_finished_at": "2026-06-08T15:00:00+09:00",
    "paste_events_count": 0,
    "external_ai_api_detected": false,
    "signed_by_app": "..."
  }
}
```

この拡張により、Reality Authenticator は単なる「その場の現実証明」から、**制作過程の真正性を補強するシステム** に発展できる。

---

## 27. まとめ

本仕様では、Reality Authenticator を現実に実装するために、MVP と発展機能を分離した。

MVP の中核は、以下である。

1. Azure が一度限りのランダムチャレンジを生成し、IoT Hub経由で端末へ配信する。
2. Raspberry Pi が物理操作、センサ値、画像、音声を取得し、Evidence ManifestをIoT Hub経由で送信する。
3. 画像・音声・証明レコードを SHA-256 で固定する。
4. Azure Key Vault の鍵で証明レコードに電子署名する。
5. QR コード付き検証ページで、改ざん検知可能な証明内容を確認する。

重要なのは、本システムを過大に表現しないことである。MVP が証明できるのは、**登録済み端末で、特定時刻に、指定された物理チャレンジに対応した記録が作成されたこと** である。法的な本人確認や AI 不使用の完全証明は行わない。

その限界を明示したうえで、将来的に専用ソフトウェア連携を追加すれば、レポート、画像、音声、契約情報などの制作過程の真正性をより強く補強できる。
