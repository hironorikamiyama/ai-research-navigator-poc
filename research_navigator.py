import time

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors, types


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "plan.txt"
OUTPUT_PATH = BASE_DIR / "data" / "research_plan.json"

REVIEW_PROMPT_PATH = BASE_DIR / "prompts" / "review.txt"
REVIEW_OUTPUT_PATH = BASE_DIR / "data" / "reviewed_research_plan.json"

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

DEFAULT_TOPIC = (
    "PythonからGoogle Gemini APIを利用する場合、"
    "2026年現在どのAPI・モデル・SDKを選択すべきか"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a research plan with Gemini."
    )

    parser.add_argument(
        "--topic",
        type=str,
        default=DEFAULT_TOPIC,
        help=(
            "調査したいテーマ。"
            "未指定の場合はDEFAULT_TOPICを使用します。"
        ),
    )

    return parser.parse_args()


def load_review_prompt(
    topic: str,
    research_plan: dict[str, Any],
) -> str:
    template = REVIEW_PROMPT_PATH.read_text(
        encoding="utf-8"
    )

    return template.format(
        topic=topic,
        research_plan=json.dumps(
            research_plan,
            ensure_ascii=False,
            indent=2,
        ),
    )


def load_review_prompt(
    topic: str,
    research_plan: dict[str, Any],
) -> str:
    template = REVIEW_PROMPT_PATH.read_text(
        encoding="utf-8"
    )

    return template.format(
        topic=topic,
        research_plan=json.dumps(
            research_plan,
            ensure_ascii=False,
            indent=2,
        ),
    )


def save_review_result(
    review_result: dict[str, Any],
) -> None:
    REVIEW_OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REVIEW_OUTPUT_PATH.write_text(
        json.dumps(
            review_result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_prompt(topic: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(topic=topic)


def call_gemini(prompt: str) -> str:
    client = genai.Client(
        http_options=types.HttpOptions(
            timeout=60_000,
        )
    )

    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
            )

            if not response.text:
                raise RuntimeError(
                    "Geminiからテキストレスポンスを取得できませんでした。"
                )

            return response.text.strip()

        except errors.ServerError as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    "Gemini APIへの接続に失敗しました。"
                    f"最大リトライ回数 {max_retries} 回に到達しました。"
                    f" 最終ステータス: {exc.code}"
                ) from exc

            wait_seconds = attempt * 10

            print(
                f"[Retry] Gemini APIでサーバーエラーが発生しました。"
                f" status={exc.code}"
                f" {wait_seconds}秒後に再試行します。"
                f" ({attempt}/{max_retries})"
            )

            time.sleep(wait_seconds)

        except errors.ClientError as exc:
            if exc.code == 429:
                raise RuntimeError(
                    "Gemini APIの利用上限に達しました。"
                    "Free Tierのクォータを確認してください。"
                    "時間経過またはクォータリセット後に再実行してください。"
                ) from exc
                    
            if exc.code != 499:
                raise

            if attempt >= max_retries:
                raise RuntimeError(
                    "Gemini APIの処理が繰り返しキャンセルされました。"
                    f"最大リトライ回数 {max_retries} 回に到達しました。"
                    f" 最終ステータス: {exc.code}"
                ) from exc

            wait_seconds = attempt * 10

            print(
                f"[Retry] Gemini APIの処理がキャンセルされました。"
                f" status={exc.code}"
                f" {wait_seconds}秒後に再試行します。"
                f" ({attempt}/{max_retries})"
            )

            time.sleep(wait_seconds)

    raise RuntimeError(
        "Gemini APIの呼び出しに失敗しました。"
    )


def parse_research_plan(raw_text: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "GeminiのレスポンスをJSONとして解析できませんでした。\n"
            f"Raw response:\n{raw_text}"
        ) from exc

    questions = data.get("research_questions")

    if not isinstance(questions, list):
        raise ValueError(
            "research_questions が配列ではありません。"
        )

    if not questions:
        raise ValueError(
            "research_questions が空です。"
        )

    if len(questions) > 5:
        raise ValueError(
            f"research_questions が5件を超えています: {len(questions)}件"
        )

    required_keys = {
        "question",
        "why",
        "preferred_primary_source",
    }

    for index, item in enumerate(
        questions,
        start=1,
    ):
        if not isinstance(item, dict):
            raise ValueError(
                f"research_questions[{index}] "
                "がオブジェクトではありません。"
            )

        missing = required_keys - item.keys()

        if missing:
            raise ValueError(
                f"research_questions[{index}] に"
                f"必須項目がありません: {sorted(missing)}"
            )

    return data


def save_research_plan(
    plan: dict[str, Any],
) -> None:
    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            plan,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    try:
        args = parse_args()
        topic = args.topic

        print("=== AI Research Navigator PoC v2 ===")
        print(f"[Model] {MODEL}")
        print(f"[Topic] {topic}")
        print()

        prompt = load_prompt(topic)

        print("[1/6] Geminiへ調査計画を依頼します...")
        raw_response = call_gemini(prompt)

        print(
            "[2/6] JSONレスポンスを検証します..."
        )
        research_plan = parse_research_plan(
            raw_response
        )

        print(
            "[3/6] 調査計画を保存します..."
        )
        save_research_plan(research_plan)

        print()
        print("=== Research Plan ===")

        print()
        print("[4/6] セルフレビュー用プロンプトを作成します...")

        review_prompt = load_review_prompt(
            topic,
            research_plan,
        )

        print("[5/6] Geminiへ調査計画レビューを依頼します...")

        raw_review = call_gemini(
            review_prompt
        )

        print("[6/6] レビュー結果を保存します...")

        review_result = parse_review_result(
            raw_review
        )

        save_review_result(
            review_result
        )

        print()
        print("=== Review Summary ===")
        print(
            review_result["review_summary"]
        )

        print()
        print(
            f"Saved: {REVIEW_OUTPUT_PATH}"
        )

        for index, item in enumerate(
            research_plan[
                "research_questions"
            ],
            start=1,
        ):
            print()
            print(
                f"Q{index}: "
                f"{item['question']}"
            )
            print(
                f"Why: "
                f"{item['why']}"
            )
            print(
                "Primary source: "
                f"{item['preferred_primary_source']}"
            )

        print()
        print(
        f"Saved: {OUTPUT_PATH}"
        )

    except RuntimeError as exc:
        print()
        print("=== ERROR ===")
        print(str(exc))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
