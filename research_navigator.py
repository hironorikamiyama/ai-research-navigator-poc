import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors
from google.genai import types


# ============================================================
# Path / Model settings
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

PLAN_PROMPT_PATH = BASE_DIR / "prompts" / "plan.txt"
REVIEW_PROMPT_PATH = BASE_DIR / "prompts" / "review.txt"

PLAN_OUTPUT_PATH = BASE_DIR / "data" / "research_plan.json"
REVIEW_OUTPUT_PATH = BASE_DIR / "data" / "reviewed_research_plan.json"

VERIFICATION_OUTPUT_PATH = (
    BASE_DIR / "data" / "verification.json"
)

MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)

DEFAULT_TOPIC = (
    "PythonからGoogle Gemini APIを利用する場合、"
    "2026年現在どのAPI・モデル・SDKを選択すべきか"
)

MAX_RETRIES = 3
API_TIMEOUT_MS = 60_000


# ============================================================
# CLI arguments
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Geminiを使って調査計画を生成し、"
            "調査計画をセルフレビューします。"
        )
    )

    parser.add_argument(
        "--topic",
        type=str,
        default=DEFAULT_TOPIC,
        help=(
            "調査したいテーマ。"
            "未指定の場合はデフォルトテーマを使用します。"
        ),
    )

    parser.add_argument(
        "--stage",
        choices=[
            "plan",
            "review",
            "verify",
            "all",
        ],
        default="all",
        help=(
            "実行する工程。"
            "plan=調査計画生成のみ、"
            "review=既存調査計画のレビューのみ、"
            "verify=検証記録の生成、"
            "all=plan→reviewを連続実行。"
        ),
    )

    return parser.parse_args()


def build_verification_template(
    topic: str,
    research_plan: dict[str, Any],
    review_result: dict[str, Any],
    existing_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    review_result から verification.json のテンプレートを作成する。

    existing_verification がある場合は、
    同一 question の既存検証結果をマージして保持する。
    """

    existing_map: dict[str, dict[str, Any]] = {}

    if existing_verification:
        for item in existing_verification.get(
            "verifications",
            [],
        ):
            question = item.get("question")

            if isinstance(question, str) and question:
                existing_map[question] = item

    verifications: list[dict[str, Any]] = []

    reviewed_questions = review_result.get(
        "reviewed_questions",
        [],
    )

    for item in reviewed_questions:
        decision = item.get(
            "decision",
            "",
        )

        if decision == "REMOVE":
            continue

        original_question = item.get(
            "original_question",
            "",
        )

        revised_question = item.get(
            "revised_question",
            "",
        )

        question = (
            revised_question
            if revised_question
            else original_question
        )

        base_item = {
            "question": question,
            "original_question": original_question,
            "review_decision": decision,
            "verification_target": "",
            "primary_source": "",
            "evidence": "",
            "status": "UNVERIFIED",
            "human_review_required": True,
            "human_note": "",
        }

        existing_item = existing_map.get(
            question
        )

        if existing_item:
            base_item["verification_target"] = (
                existing_item.get(
                    "verification_target",
                    "",
                )
            )

            base_item["primary_source"] = (
                existing_item.get(
                    "primary_source",
                    "",
                )
            )

            base_item["evidence"] = (
                existing_item.get(
                    "evidence",
                    "",
                )
            )

            base_item["status"] = (
                existing_item.get(
                    "status",
                    "UNVERIFIED",
                )
            )

            base_item["human_review_required"] = (
                existing_item.get(
                    "human_review_required",
                    True,
                )
            )

            base_item["human_note"] = (
                existing_item.get(
                    "human_note",
                    "",
                )
            )

        verifications.append(
            base_item
        )

    additional_questions = review_result.get(
        "additional_questions",
        [],
    )

    for item in additional_questions:
        question = item.get(
            "question",
            "",
        )

        base_item = {
            "question": question,
            "original_question": "",
            "review_decision": "ADDED",
            "verification_target": "",
            "primary_source": "",
            "evidence": "",
            "status": "UNVERIFIED",
            "human_review_required": True,
            "human_note": item.get(
                "why",
                "",
            ),
        }

        existing_item = existing_map.get(
            question
        )

        if existing_item:
            base_item["verification_target"] = (
                existing_item.get(
                    "verification_target",
                    "",
                )
            )

            base_item["primary_source"] = (
                existing_item.get(
                    "primary_source",
                    "",
                )
            )

            base_item["evidence"] = (
                existing_item.get(
                    "evidence",
                    "",
                )
            )

            base_item["status"] = (
                existing_item.get(
                    "status",
                    "UNVERIFIED",
                )
            )

            base_item["human_review_required"] = (
                existing_item.get(
                    "human_review_required",
                    True,
                )
            )

            base_item["human_note"] = (
                existing_item.get(
                    "human_note",
                    base_item["human_note"],
                )
            )

        verifications.append(
            base_item
        )

    return {
        "topic": topic,
        "verification_policy": {
            "statuses": [
                "UNVERIFIED",
                "MATCH",
                "MISMATCH",
                "UNCERTAIN",
            ],
            "primary_source_required": True,
            "final_judgment_by_human": True,
        },
        "verifications": verifications,
    }


def validate_verification_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    verifications = data.get(
        "verifications"
    )

    if not isinstance(
        verifications,
        list,
    ):
        raise ValueError(
            "verifications が配列ではありません。"
        )

    allowed_statuses = {
        "UNVERIFIED",
        "MATCH",
        "MISMATCH",
        "UNCERTAIN",
    }

    required_keys = {
        "question",
        "original_question",
        "review_decision",
        "verification_target",
        "primary_source",
        "evidence",
        "status",
        "human_review_required",
        "human_note",
    }

    for index, item in enumerate(
        verifications,
        start=1,
    ):
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                f"verifications[{index}] が"
                "オブジェクトではありません。"
            )

        missing = (
            required_keys
            - item.keys()
        )

        if missing:
            raise ValueError(
                f"verifications[{index}] に"
                "必須項目がありません: "
                f"{sorted(missing)}"
            )

        status = item.get(
            "status"
        )

        if status not in allowed_statuses:
            raise ValueError(
                f"verifications[{index}] の"
                f"status が不正です: {status}"
            )

    return data


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            f"必要なファイルが存在しません: {path}"
        )

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSONファイルを解析できません: {path}"
        ) from exc


# ============================================================
# Prompt loading
# ============================================================

def load_plan_prompt(topic: str) -> str:
    """
    調査計画生成用プロンプトを読み込む。

    plan.txt は既存仕様どおり str.format() を利用するため、
    JSON例などのリテラル {} は {{ }} と記述する。
    """
    template = PLAN_PROMPT_PATH.read_text(
        encoding="utf-8"
    )

    return template.format(
        topic=topic,
    )


def load_review_prompt(
    topic: str,
    research_plan: dict[str, Any],
) -> str:
    """
    セルフレビュー用プロンプトを読み込む。

    review.txt 内にはJSON例が含まれるため、
    str.format() ではなくプレースホルダーだけを
    replace() する。

    これによりJSONの {} をエスケープする必要がない。
    """
    template = REVIEW_PROMPT_PATH.read_text(
        encoding="utf-8"
    )

    plan_json = json.dumps(
        research_plan,
        ensure_ascii=False,
        indent=2,
    )

    prompt = template.replace(
        "{topic}",
        topic,
    )

    prompt = prompt.replace(
        "{research_plan}",
        plan_json,
    )

    return prompt


# ============================================================
# Gemini API
# ============================================================

def create_client() -> genai.Client:
    return genai.Client(
        http_options=types.HttpOptions(
            timeout=API_TIMEOUT_MS,
        )
    )


def call_gemini(prompt: str) -> str:
    """
    Gemini APIを呼び出す。

    503 / 504等:
        一時的なサーバーエラーとして再試行。

    499:
        CANCELLEDとして再試行。

    429:
        Free Tier等のクォータ超過として即終了。

    その他のClientError:
        リトライせず終了。
    """
    client = create_client()

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
            )

            if not response.text:
                raise RuntimeError(
                    "Geminiからテキストレスポンスを"
                    "取得できませんでした。"
                )

            return response.text.strip()

        except errors.ServerError as exc:
            status = getattr(
                exc,
                "code",
                "UNKNOWN",
            )

            if attempt >= MAX_RETRIES:
                raise RuntimeError(
                    "Gemini APIへの接続に失敗しました。"
                    f"最大リトライ回数 {MAX_RETRIES} 回に"
                    "到達しました。"
                    f" 最終ステータス: {status}"
                ) from exc

            wait_seconds = attempt * 10

            print(
                "[Retry] "
                "Gemini APIでサーバーエラーが発生しました。"
                f" status={status}"
                f" {wait_seconds}秒後に再試行します。"
                f" ({attempt}/{MAX_RETRIES})"
            )

            time.sleep(wait_seconds)

        except errors.ClientError as exc:
            status = getattr(
                exc,
                "code",
                "UNKNOWN",
            )

            # Free Tier / Rate limit / Quota exceeded
            if status == 429:
                raise RuntimeError(
                    "Gemini APIの利用上限に達しました。"
                    "Free Tierのクォータを確認してください。"
                    "時間経過またはクォータリセット後に"
                    "再実行してください。"
                ) from exc

            # CANCELLED
            if status == 499:
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(
                        "Gemini APIの処理が繰り返し"
                        "キャンセルされました。"
                        f"最大リトライ回数 "
                        f"{MAX_RETRIES} 回に到達しました。"
                    ) from exc

                wait_seconds = attempt * 10

                print(
                    "[Retry] "
                    "Gemini APIの処理がキャンセルされました。"
                    f" status={status}"
                    f" {wait_seconds}秒後に再試行します。"
                    f" ({attempt}/{MAX_RETRIES})"
                )

                time.sleep(wait_seconds)
                continue

            # 400 / 401 / 403 / 404等は再試行しない
            raise RuntimeError(
                "Gemini APIでクライアントエラーが"
                "発生しました。"
                f" status={status}"
            ) from exc

    raise RuntimeError(
        "Gemini APIの呼び出しに失敗しました。"
    )


# ============================================================
# Research plan validation
# ============================================================

def parse_research_plan(
    raw_text: str,
) -> dict[str, Any]:
    try:
        data = json.loads(raw_text)

    except json.JSONDecodeError as exc:
        raise ValueError(
            "GeminiのレスポンスをJSONとして"
            "解析できませんでした。\n"
            f"Raw response:\n{raw_text}"
        ) from exc

    questions = data.get(
        "research_questions"
    )

    if not isinstance(
        questions,
        list,
    ):
        raise ValueError(
            "research_questions が"
            "配列ではありません。"
        )

    if not questions:
        raise ValueError(
            "research_questions が空です。"
        )

    if len(questions) > 5:
        raise ValueError(
            "research_questions が"
            f"5件を超えています: {len(questions)}件"
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
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                f"research_questions[{index}] が"
                "オブジェクトではありません。"
            )

        missing = (
            required_keys
            - item.keys()
        )

        if missing:
            raise ValueError(
                f"research_questions[{index}] に"
                "必須項目がありません: "
                f"{sorted(missing)}"
            )

    return data


# ============================================================
# Review validation
# ============================================================

def parse_review_result(
    raw_text: str,
) -> dict[str, Any]:
    try:
        data = json.loads(raw_text)

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Geminiのセルフレビュー結果を"
            "JSONとして解析できませんでした。\n"
            f"Raw response:\n{raw_text}"
        ) from exc

    review_summary = data.get(
        "review_summary"
    )

    if not isinstance(
        review_summary,
        str,
    ):
        raise ValueError(
            "review_summary が"
            "文字列ではありません。"
        )

    reviewed_questions = data.get(
        "reviewed_questions"
    )

    if not isinstance(
        reviewed_questions,
        list,
    ):
        raise ValueError(
            "reviewed_questions が"
            "配列ではありません。"
        )

    required_keys = {
        "original_question",
        "decision",
        "reason",
        "revised_question",
    }

    allowed_decisions = {
        "KEEP",
        "MODIFY",
        "REMOVE",
    }

    for index, item in enumerate(
        reviewed_questions,
        start=1,
    ):
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                f"reviewed_questions[{index}] が"
                "オブジェクトではありません。"
            )

        missing = (
            required_keys
            - item.keys()
        )

        if missing:
            raise ValueError(
                f"reviewed_questions[{index}] に"
                "必須項目がありません: "
                f"{sorted(missing)}"
            )

        decision = item.get(
            "decision"
        )

        if decision not in allowed_decisions:
            raise ValueError(
                f"reviewed_questions[{index}] の"
                "decision が不正です: "
                f"{decision}"
            )

    additional_questions = data.get(
        "additional_questions"
    )

    if not isinstance(
        additional_questions,
        list,
    ):
        raise ValueError(
            "additional_questions が"
            "配列ではありません。"
        )

    return data


# ============================================================
# File output
# ============================================================

def save_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ============================================================
# Console output
# ============================================================

def print_research_plan(
    research_plan: dict[str, Any],
) -> None:
    print()
    print("=== Research Plan ===")

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


def print_review_result(
    review_result: dict[str, Any],
) -> None:
    print()
    print("=== Self Review ===")

    print()
    print(
        "Summary: "
        f"{review_result['review_summary']}"
    )

    for index, item in enumerate(
        review_result[
            "reviewed_questions"
        ],
        start=1,
    ):
        print()

        print(
            f"Review {index}: "
            f"{item['decision']}"
        )

        print(
            "Original: "
            f"{item['original_question']}"
        )

        print(
            "Reason: "
            f"{item['reason']}"
        )

        revised = item.get(
            "revised_question",
            "",
        )

        if revised:
            print(
                "Revised: "
                f"{revised}"
            )

    additional_questions = (
        review_result.get(
            "additional_questions",
            [],
        )
    )

    if additional_questions:
        print()
        print(
            "=== Additional Questions ==="
        )

        for index, item in enumerate(
            additional_questions,
            start=1,
        ):
            print()

            print(
                f"Additional {index}: "
                f"{item.get('question', '')}"
            )

            print(
                "Why: "
                f"{item.get('why', '')}"
            )


# ============================================================
# Main
# ============================================================


def run_plan_stage(
    topic: str,
) -> dict[str, Any]:
    print()
    print("=== Stage: PLAN ===")

    print(
        "[PLAN 1/3] "
        "Geminiへ調査計画を依頼します..."
    )

    prompt = load_plan_prompt(
        topic
    )

    raw_plan = call_gemini(
        prompt
    )

    print(
        "[PLAN 2/3] "
        "調査計画JSONを検証します..."
    )

    research_plan = parse_research_plan(
        raw_plan
    )

    print(
        "[PLAN 3/3] "
        "調査計画を保存します..."
    )

    save_json(
        PLAN_OUTPUT_PATH,
        research_plan,
    )

    print_research_plan(
        research_plan
    )

    print()
    print(
        f"Saved: {PLAN_OUTPUT_PATH}"
    )

    return research_plan


def run_review_stage(
    topic: str,
    research_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    print()
    print("=== Stage: REVIEW ===")

    if research_plan is None:
        print(
            "[REVIEW 1/4] "
            "既存の調査計画を読み込みます..."
        )

        research_plan = load_json(
            PLAN_OUTPUT_PATH
        )

        # 保存済みJSONも再度構造検証する
        research_plan = parse_research_plan(
            json.dumps(
                research_plan,
                ensure_ascii=False,
            )
        )

    else:
        print(
            "[REVIEW 1/4] "
            "直前に生成した調査計画を使用します..."
        )

    print(
        "[REVIEW 2/4] "
        "セルフレビュー用プロンプトを作成します..."
    )

    review_prompt = load_review_prompt(
        topic,
        research_plan,
    )

    print(
        "[REVIEW 3/4] "
        "Geminiへ調査計画レビューを依頼します..."
    )

    raw_review = call_gemini(
        review_prompt
    )

    review_result = parse_review_result(
        raw_review
    )

    print(
        "[REVIEW 4/4] "
        "レビュー結果を保存します..."
    )

    save_json(
        REVIEW_OUTPUT_PATH,
        review_result,
    )

    print_review_result(
        review_result
    )

    print()
    print(
        f"Saved: {REVIEW_OUTPUT_PATH}"
    )

    return review_result


def run_verify_stage(
    topic: str,
) -> dict[str, Any]:
    print()
    print("=== Stage: VERIFY ===")

    print(
        "[VERIFY 1/5] "
        "既存の調査計画を読み込みます..."
    )

    research_plan = load_json(
        PLAN_OUTPUT_PATH
    )

    research_plan = parse_research_plan(
        json.dumps(
            research_plan,
            ensure_ascii=False,
        )
    )

    print(
        "[VERIFY 2/5] "
        "既存のセルフレビュー結果を読み込みます..."
    )

    review_result = load_json(
        REVIEW_OUTPUT_PATH
    )

    review_result = parse_review_result(
        json.dumps(
            review_result,
            ensure_ascii=False,
        )
    )

    existing_verification = None

    if VERIFICATION_OUTPUT_PATH.exists():
        print(
            "[VERIFY 3/5] "
            "既存のverification.jsonを読み込みます..."
        )

        existing_verification = load_json(
            VERIFICATION_OUTPUT_PATH
        )

        existing_verification = (
            validate_verification_data(
                existing_verification
            )
        )

    else:
        print(
            "[VERIFY 3/5] "
            "既存のverification.jsonはありません。"
            "新規作成します..."
        )

    print(
        "[VERIFY 4/5] "
        "検証テンプレートを生成・マージします..."
    )

    verification_data = (
        build_verification_template(
            topic=topic,
            research_plan=research_plan,
            review_result=review_result,
            existing_verification=existing_verification,
        )
    )

    verification_data = (
        validate_verification_data(
            verification_data
        )
    )

    print(
        "[VERIFY 5/5] "
        "verification.jsonを保存します..."
    )

    save_json(
        VERIFICATION_OUTPUT_PATH,
        verification_data,
    )

    matched = 0
    mismatched = 0
    uncertain = 0
    unverified = 0

    for item in verification_data.get(
        "verifications",
        [],
    ):
        status = item.get(
            "status"
        )

        if status == "MATCH":
            matched += 1

        elif status == "MISMATCH":
            mismatched += 1

        elif status == "UNCERTAIN":
            uncertain += 1

        else:
            unverified += 1

    print()
    print(
        f"Saved: {VERIFICATION_OUTPUT_PATH}"
    )

    print()
    print(
        "=== Verification Status ==="
    )
    print(
        f"MATCH: {matched}"
    )
    print(
        f"MISMATCH: {mismatched}"
    )
    print(
        f"UNCERTAIN: {uncertain}"
    )
    print(
        f"UNVERIFIED: {unverified}"
    )

    print()
    print(
        "既存の検証結果は保持し、"
        "新しい調査項目のみUNVERIFIEDとして追加しました。"
    )

    return verification_data

def run() -> None:
    args = parse_args()

    topic = args.topic
    stage = args.stage

    print(
        "=== AI Research Navigator PoC v2 ==="
    )
    print(
        f"[Model] {MODEL}"
    )
    print(
        f"[Topic] {topic}"
    )
    print(
        f"[Stage] {stage}"
    )

    if stage == "plan":
        run_plan_stage(
            topic
        )

    elif stage == "review":
        run_review_stage(
            topic
        )

    elif stage == "all":
        research_plan = run_plan_stage(
            topic
        )

        run_review_stage(
            topic,
            research_plan,
        )
    elif stage == "verify":
        run_verify_stage(
            topic
        )

    print()
    print(
        "=== Completed ==="
    )


def main() -> None:
    try:
        run()

    except (
        RuntimeError,
        ValueError,
        OSError,
    ) as exc:
        print()
        print(
            "=== ERROR ==="
        )
        print(
            str(exc)
        )

        raise SystemExit(1)

    except KeyboardInterrupt:
        print()
        print()
        print(
            "=== CANCELLED ==="
        )
        print(
            "ユーザーによって処理が中断されました。"
        )

        raise SystemExit(130)


if __name__ == "__main__":
    main()
