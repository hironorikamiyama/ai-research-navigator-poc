# AI Research Navigator PoC

生成AIに「答え」を直接求めるのではなく、

1. AIに調査計画を作らせる
2. AI自身にその計画をレビューさせる
3. 人間が一次情報を確認する
4. 確認結果をJSONとして記録する

という流れを試すためのPython製PoCです。

> AIに作らせて、AIにも疑わせて、最後は人間が判断する。

---

## このPoCで検証したいこと

生成AIは技術調査を高速化できます。

一方で、

- 情報が最新とは限らない
- 実在しない資料名やバージョンを挙げる可能性がある
- 正しそうに見える情報でも一次情報との照合が必要
- 調査結果だけでなく「何を確認すべきか」の設計も重要

という問題があります。

そこで本PoCでは、AIを「答えを決める存在」ではなく、

**調査候補を整理するナビゲーター**

として利用します。

---

# 全体フロー

```text
調査テーマ
   ↓
PLAN
AIが調査計画を生成
   ↓
data/research_plan.json
   ↓
REVIEW
AI自身が調査計画をレビュー
   ↓
data/reviewed_research_plan.json
   ↓
VERIFY
一次情報照合用データを生成
   ↓
data/verification.json
   ↓
人間が一次情報を確認
   ↓
MATCH / MISMATCH / UNCERTAIN
   ↓
人間が最終判断
```

役割分担は次のように考えています。

```text
AI
→ 調査候補を作る
→ 調査計画をレビューする

Python
→ 各工程を制御する
→ JSONを検証する
→ APIエラーを処理する
→ 検証結果を保持する

人間
→ 一次情報を確認する
→ 情報の鮮度・正確性を判断する
→ 最終的な採用判断を行う
```

---

# 現在実装しているStage

## PLAN

Gemini APIを使って調査計画を生成します。

```bash
python research_navigator.py \
  --stage plan \
  --topic "Python 3.14で追加・変更された主要仕様を公式情報から調査したい"
```

生成先：

```text
data/research_plan.json
```

調査テーマから最大5件程度の調査質問を作成します。

例：

```json
{
  "question": "...",
  "why": "...",
  "preferred_primary_source": "..."
}
```

---

## REVIEW

既存の `research_plan.json` を読み込み、
Geminiに調査計画そのものをレビューさせます。

```bash
python research_navigator.py \
  --stage review \
  --topic "Python 3.14で追加・変更された主要仕様を公式情報から調査したい"
```

生成先：

```text
data/reviewed_research_plan.json
```

各質問は次のいずれかに分類します。

```text
KEEP
MODIFY
REMOVE
```

主なレビュー観点：

- 調査範囲が広すぎないか
- 質問が重複していないか
- 重要な観点が不足していないか
- 未確認情報を事実として扱っていないか
- 古いモデル名・SDK・API名などを前提としていないか
- 一次情報候補が本当に存在するか
- AIが確認すべき事実と、人間が判断すべき内容が混ざっていないか

必要に応じて新しい調査質問も追加します。

---

## VERIFY

REVIEW済みの調査項目から、
一次情報照合用の `verification.json` を生成します。

```bash
python research_navigator.py \
  --stage verify \
  --topic "Python 3.14で追加・変更された主要仕様を公式情報から調査したい"
```

生成先：

```text
data/verification.json
```

検証項目の例：

```json
{
  "question": "...",
  "original_question": "...",
  "review_decision": "MODIFY",
  "verification_target": "...",
  "primary_source": "...",
  "evidence": "...",
  "status": "MATCH",
  "human_review_required": false,
  "human_note": "..."
}
```

---

# Verification Status

一次情報との照合結果は4種類で管理します。

| Status | 意味 |
|---|---|
| `UNVERIFIED` | まだ一次情報を確認していない |
| `MATCH` | 一次情報と照合し、主張を確認できた |
| `MISMATCH` | 一次情報と一致しなかった |
| `UNCERTAIN` | 一次情報を確認しても断定できない |

重要なのは、

**AI自身にMATCH/MISMATCHの最終判断を任せない**

ことです。

最終的な検証結果は人間が一次情報を確認して入力します。

---

# VERIFYの再実行

`verification.json` がすでに存在する場合、
既存の検証結果を保持したままマージします。

保持対象：

```text
verification_target
primary_source
evidence
status
human_review_required
human_note
```

そのため、一度人間が確認した結果が
`--stage verify` の再実行によって消えることはありません。

新しい調査項目だけが、

```text
UNVERIFIED
```

として追加されます。

実行例：

```text
=== Verification Status ===
MATCH: 7
MISMATCH: 0
UNCERTAIN: 0
UNVERIFIED: 0
```

---

# ALL

PLAN → REVIEW を連続実行します。

```bash
python research_navigator.py \
  --stage all \
  --topic "調査したいテーマ"
```

現在、VERIFYは自動実行していません。

これは意図的な仕様です。

VERIFYでは人間による一次情報確認を前提としているため、

```text
PLAN
↓
REVIEW
```

と、

```text
VERIFY
↓
人間による確認
```

を分離しています。

---

# セットアップ

## 1. リポジトリ取得

```bash
git clone git@github.com:hironorikamiyama/ai-research-navigator-poc.git
cd ai-research-navigator-poc
```

## 2. 仮想環境作成

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShellの場合：

```powershell
.venv\Scripts\Activate.ps1
```

## 3. 依存パッケージインストール

```bash
pip install -r requirements.txt
```

現在利用している主なSDK：

```text
google-genai
```

## 4. Gemini API Key

環境変数にAPIキーを設定します。

例：

```bash
export GEMINI_API_KEY="YOUR_API_KEY"
```

利用モデルは環境変数から変更できます。

```bash
export GEMINI_MODEL="gemini-3.6-flash"
```

未指定の場合はコード内のデフォルトモデルを使用します。

---

# ディレクトリ構成

```text
ai-research-navigator-poc/
├── data/
│   ├── research_plan.json
│   ├── reviewed_research_plan.json
│   └── verification.json
│
├── prompts/
│   ├── plan.txt
│   └── review.txt
│
├── results/
│   └── .gitkeep
│
├── .gitignore
├── README.md
├── requirements.txt
└── research_navigator.py
```

---

# APIエラー対応

Gemini APIでは、一時的な混雑や利用上限などにより
APIエラーが発生する場合があります。

PoCでは以下のようなエラーを想定しています。

```text
429 RESOURCE_EXHAUSTED
499 CANCELLED
503 UNAVAILABLE
504 DEADLINE_EXCEEDED
```

503 / 504などの一時的なサーバーエラーについては
アプリケーション側でリトライします。

一方、429のクォータ超過については
無制限に再試行せず、利用上限として扱います。

例：

```text
=== ERROR ===
Gemini APIの利用上限に達しました。
Free Tierのクォータを確認してください。
時間経過またはクォータリセット後に再実行してください。
```

---

# PoCで確認できたこと

今回の実験では、AIが生成した調査計画の中に、

- 未確認のPEP番号
- 具体的な機能名
- JIT
- free-threading
- 公式資料名

などが含まれるケースがありました。

REVIEW工程では、

**「その情報を調査前から事実として扱ってよいのか？」**

という観点からMODIFY判定が行われました。

その後、人間が一次情報を確認した結果、
今回検証した項目については実際に公式情報で確認できました。

つまり、

```text
MODIFY
≠
その情報は間違っている
```

です。

MODIFYは、

```text
まだ確認していないので、
一度検証対象に戻す
```

という意味でも使われます。

この違いは本PoCで得られた重要なポイントです。

---

# 設計思想

このPoCでは、

```text
AIの回答
=
正解
```

とは扱いません。

また、

```text
AIの回答
=
全部疑うべきもの
```

とも考えていません。

重要なのは、

```text
候補はAI
確認は一次情報
判断は人間
```

という役割分担です。

AIに作らせて、
AIにも疑わせて、
最後は人間が判断する。

それをコードとして試しているのが
AI Research Navigator PoCです。

---

# 現在の到達点

現在、以下まで実装・動作確認済みです。

- [x] 調査テーマの動的指定
- [x] Gemini APIによる調査計画生成
- [x] JSON形式の検証
- [x] AIによるセルフレビュー
- [x] PLAN / REVIEW / VERIFYのStage分離
- [x] APIエラー処理
- [x] 一時エラーのリトライ
- [x] 一次情報照合用JSON生成
- [x] Verification Status管理
- [x] 人間による一次情報確認
- [x] 検証結果の再実行時マージ
- [x] 検証済みデータの保持

---

# 今後の検討

今後は、必要に応じて以下を検討します。

- 一次情報候補URLの補助取得
- verification_target生成支援
- 調査結果のMarkdownレポート化
- VERIFY結果の差分表示
- テストコード追加
- CLI構成の整理
- 調査履歴管理
- 複数テーマの保存
- 自動取得と人間確認の境界整理

ただし、一次情報確認まで完全自動化すると、

**「AIの出力を別のAIが確認しただけ」**

になる可能性があります。

そのため、自動化範囲については
今後も慎重に設計します。

---

# Version

現在のPoCでは、

```text
PLAN
→ REVIEW
→ VERIFY
```

まで実装しています。

初期版：

```text
v1.0.0
```

以降、動的topic指定、セルフレビュー、Stage分離、
VERIFY、検証結果マージを追加しています。

---

# Repository

GitHub:

https://github.com/hironorikamiyama/ai-research-navigator-poc

---

## 最後に

生成AIを使った調査で重要なのは、

**AIが答えを出せるか**

だけではありません。

それ以上に、

**AIが出した情報を、自分で検証できる仕組みを持てるか**

が重要だと考えています。

> AIに作らせて、AIにも疑わせて、最後は人間が判断する。
