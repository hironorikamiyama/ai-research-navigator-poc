import json
import os
from pathlib import Path
from typing import Any

from google import genai


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "plan.txt"
OUTPUT_PATH = BASE_DIR / "data" / "research_plan.json"

# PoCなので環境変数で変更可能にしておく。
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

DEFAULT_TOPIC = (
    "PythonからGoogle Gemini APIを利用する場合、"
    "2026年現在どのAPI・モデル・SDKを選択すべきか"
)


def load_prompt(topic: str) -> str:
    """プロンプトテンプレートを読み込み、調査テーマを埋め込む。"""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(topic=topic)


def call_gemini(prompt: str) -> str:
    """Geminiへ調査計画の生成を依頼する。"""
    client = genai.Client()

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    if not response.text:
        raise RuntimeError("Geminiからテキストレスポンスを取得できませんでした。")

    return response.text.strip()


def parse_research_plan(raw_text: str) -> dict[str, Any]:
    """GeminiのレスポンスをJSONとして解析し、最低限の構造を確認する。"""
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

    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"research_questions[{index}] がオブジェクトではありません。"
            )

        missing = required_keys - item.keys()

        if missing:
            raise ValueError(
                f"research_questions[{index}] に"
                f"必須項目がありません: {sorted(missing)}"
            )

    return data


def save_research_plan(plan: dict[str, Any]) -> None:
    """調査計画をJSONファイルとして保存する。"""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    topic = DEFAULT_TOPIC

    print("=== AI Research Navigator PoC v1 ===")
    print(f"[Model] {MODEL}")
    print(f"[Topic] {topic}")
    print()

    prompt = load_prompt(topic)

    print("[1/3] Geminiへ調査計画を依頼します...")
    raw_response = call_gemini(prompt)

    print("[2/3] JSONレスポンスを検証します...")
    research_plan = parse_research_plan(raw_response)

    print("[3/3] 調査計画を保存します...")
    save_research_plan(research_plan)

    print()
    print("=== Research Plan ===")

    for index, item in enumerate(
        research_plan["research_questions"],
        start=1,
    ):
        print()
        print(f"Q{index}: {item['question']}")
        print(f"Why: {item['why']}")
        print(
            "Primary source: "
            f"{item['preferred_primary_source']}"
        )

    print()
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()