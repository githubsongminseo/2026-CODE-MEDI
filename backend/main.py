"""
CODE:MEDI CPX 프로토타입 — 백엔드 (다중 케이스 DB, F1 이지현 케이스만 플레이 가능)

실행 전 준비:
    1. pip install -r requirements.txt
    2. 환경변수 OPENAI_API_KEY 설정 (.env 파일 또는 export)
    3. uvicorn main:app --reload --port 8000

주의: 이 코드는 로컬 프로토타입/해커톤 데모 목적입니다.
세션은 메모리에만 저장되며 서버 재시작 시 사라집니다.
cases/ 폴더의 각 JSON 파일 중 ready_for_play=true인 것만 실제 플레이 가능합니다.
"""

import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# 모델을 두 단계로 분리합니다.
# - CHAT: 환자 역할 대화 생성용. 턴마다 호출되므로 가볍고 빠른 모델이 적합합니다.
# - EVAL: 체크리스트/PPI 평가용. 더 정교한 판단이 필요해서 무거운 모델을 권장합니다.
# 본인 계정/요금제에서 사용 가능한 모델명으로 .env에서 바꿔주세요.
OPENAI_MODEL_CHAT = os.getenv("OPENAI_MODEL_CHAT", "gpt-4o-mini")
OPENAI_MODEL_EVAL = os.getenv("OPENAI_MODEL_EVAL", "gpt-4o")
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

BASE_DIR = Path(__file__).parent
CHECKLIST_REF = json.loads((BASE_DIR / "checklist_reference.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# 케이스 DB 로딩 — cases/ 폴더의 모든 *.json을 읽어 메모리에 적재
# ---------------------------------------------------------------------------
CASES_DIR = BASE_DIR / "cases"
ALL_CASES: dict[str, dict] = {}
for _f in sorted(CASES_DIR.glob("*.json")):
    _case = json.loads(_f.read_text(encoding="utf-8"))
    ALL_CASES[_case["case_id"]] = _case

PLAYABLE_CASE_IDS: list[str] = [cid for cid, c in ALL_CASES.items() if c.get("ready_for_play")]

if not PLAYABLE_CASE_IDS:
    raise RuntimeError(
        "ready_for_play=true인 케이스가 cases/ 폴더에 하나도 없습니다. "
        "최소 1개 케이스는 완전히 작성되어 있어야 서버가 의미있게 동작합니다."
    )

# ---------------------------------------------------------------------------
# 평가 레포트 저장소 — 파일 하나당 레포트 하나(JSON). 실제 DB 도입 전까지의
# 임시 저장 방식이며, 의대생 측에서 PPI 판단용 프롬프트를 만들 때 이 폴더의
# 파일을 그대로 입력 데이터로 쓸 수 있도록 transcript + 모든 평가축을 한 번에 묶어 저장한다.
# ---------------------------------------------------------------------------
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def save_report(
    session_id: str,
    case: dict,
    difficulty: str,
    initial_emotion: str,
    transcript: list[dict],
    checklist_axis: dict,
    ppi_axis: dict,
    weakness: dict,
    recommendation: dict,
    source: str = "live",
) -> str:
    """평가 결과를 transcript와 함께 하나의 JSON 파일로 저장한다.

    source는 "live"(실제 학습자가 플레이) 또는 "synthetic"(자동 생성 스크립트로 생성)을
    구분해서, 실제 검증용 데이터와 테스트용 합성 데이터를 나중에 쉽게 분리할 수 있게 한다.
    """
    report_id = str(uuid.uuid4())
    report = {
        "report_id": report_id,
        "source": source,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_id": case["case_id"],
        "case_title": case["case_title"],
        "display_name": case["display_name"],
        "difficulty": difficulty,
        "initial_emotion": initial_emotion,
        "transcript": transcript,
        "checklist_axis": checklist_axis,
        "ppi_axis": ppi_axis,
        "weakness_analysis": weakness,
        "recommendation": recommendation,
    }
    out_path = REPORTS_DIR / f"{report_id}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_id


app = FastAPI(title="CODE:MEDI CPX Prototype")

# 로컬 프론트엔드(file:// 또는 localhost)에서 호출 가능하도록 허용.
# 실제 배포 시에는 출처를 좁혀야 합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 세션 저장 (메모리, 프로토타입 한정)
# ---------------------------------------------------------------------------
# session_id -> {"case_id": "...", "history": [...], "difficulty": "..."}
SESSIONS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 난이도 설정
# ---------------------------------------------------------------------------
DIFFICULTY_LEVELS = ["하", "중", "상"]

DIFFICULTY_INSTRUCTIONS = {
    "하": (
        "[난이도: 하]\n"
        "- 감정 단서 명시성: 거의 매 턴마다 행동/표정을 나타내는 지시문을 괄호로 포함하세요. "
        "예: '(눈물을 글썽이며)', '(목소리가 떨리며)', '(고개를 푹 숙이고)', '(주먹을 꽉 쥐며)'. "
        "감정을 나타내는 단어도 직접적으로 말하세요 (예: '너무 당황스러워요', '화가 나네요'). "
        "학습자가 환자의 감정 상태를 거의 힘들이지 않고 알아챌 수 있어야 합니다.\n"
        "- 수용으로의 설득 저항도: 이 환자는 비교적 쉽게 설득되는 성향입니다. 학습자가 감정을 "
        "한두 번만 제대로 인정하고 공감해줘도 비교적 빠르게 마음이 풀리고 수용 쪽으로 넘어갈 "
        "수 있습니다. 완벽하지 않은 대응이라도 진심이 느껴지면 너그럽게 받아들이세요."
    ),
    "중": (
        "[난이도: 중]\n"
        "- 감정 단서 명시성: 대화 턴의 절반 정도에서만 괄호로 된 행동/표정 지시문을 사용하세요. "
        "나머지 턴에서는 대화 내용 자체(질문의 형태, 말의 속도를 암시하는 어조)로만 감정을 "
        "드러내세요. 감정을 나타내는 직접적인 단어 사용은 가끔만 하세요.\n"
        "- 수용으로의 설득 저항도: 이 환자는 적당히 설득되는 성향입니다. 학습자가 감정을 "
        "인정하고 현실적인 다음 단계를 일관되게 설명해야 수용으로 넘어갑니다. 한 번의 좋은 "
        "반응만으로는 부족하고, 대화 전반에서 일관된 공감과 정보 전달이 필요합니다."
    ),
    "상": (
        "[난이도: 상]\n"
        "- 감정 단서 명시성: 괄호로 된 행동/표정 지시문은 전체 대화에서 많아야 1번, 가능하면 "
        "전혀 사용하지 마세요. 감정을 나타내는 직접적인 단어도 거의 쓰지 마세요. 대화의 내용, "
        "질문을 던지는 방식, 대답의 길이나 망설임만으로 감정 상태가 은근히 드러나도록 하세요.\n"
        "- 수용으로의 설득 저항도: 이 환자는 쉽게 설득되지 않는 완고한 성향입니다. 학습자가 "
        "감정을 반복적으로 충분히 인정하고, 현실적인 계획을 여러 차례 일관되게 설명해야만 "
        "서서히 수용 쪽으로 움직입니다. 한두 번의 공감 표현으로는 부족하며, 학습자의 대응이 "
        "성급하거나 형식적이면(예: 감정을 건너뛰고 정보만 전달, 한 번 공감하고 바로 화제 전환) "
        "다시 초기 반응으로 돌아갈 수 있습니다."
    ),
}


def pick_random_case() -> str:
    """플레이 가능한 케이스 중에서 완전히 균등하게 랜덤으로 고른다.

    이전 버전에는 난이도별로 케이스를 다르게 골랐으나, 이번 6개 케이스는 전부
    '평소보다 격한 초기 반응'을 갖도록 설계되어 있어 난이도로 케이스를 가를 필요가
    없어졌다. 난이도는 이제 감정 단서의 명시성(지시문 빈도)만 조절한다.
    """
    return random.choice(PLAYABLE_CASE_IDS)


def pick_different_case(exclude_case_id: str) -> str:
    """추천 재도전용 — 가능하면 방금 했던 케이스와 다른 케이스를 고른다."""
    candidates = [cid for cid in PLAYABLE_CASE_IDS if cid != exclude_case_id]
    if not candidates:
        return exclude_case_id
    return random.choice(candidates)


# ---------------------------------------------------------------------------
# 약점 분석 / 다음 케이스 추천
# ---------------------------------------------------------------------------
# 체크리스트 코드 → 약점 범주. E/C 코드는 직접 매핑하고, D/A/B/DEP/AC(감정 대응)는
# 접두사로 일괄 판별한다.
WEAKNESS_CATEGORY_MAP = {
    "E1-1": "면담 구조", "E1-2": "면담 구조", "E1-3": "면담 구조", "E1-4": "면담 구조",
    "E2-1": "감정 대응", "E2-3": "감정 대응", "E2-6": "감정 대응",
    "E2-2": "정보 전달", "E2-4": "정보 전달",
    "E2-5": "정보 탐색",
    "E3-1": "면담 구조",
}
EMOTION_ITEM_PREFIXES = ("D", "A", "B", "DEP", "AC")


def _categorize_code(code: str) -> str:
    if code in WEAKNESS_CATEGORY_MAP:
        return WEAKNESS_CATEGORY_MAP[code]
    if any(code.startswith(p) for p in EMOTION_ITEM_PREFIXES):
        return "감정 대응"
    return "기타"


def analyze_weaknesses(checklist_axis: dict) -> dict:
    """체크리스트 평가 결과에서 X 항목들을 모아 약점 범주별로 집계한다."""
    category_counts = {"면담 구조": 0, "정보 탐색": 0, "정보 전달": 0, "감정 대응": 0, "기타": 0}
    weak_items: list[str] = []

    for section in ("core_results", "candidate_results"):
        for code, result in checklist_axis.get(section, {}).items():
            if result.get("result") == "X":
                category_counts[_categorize_code(code)] += 1
                weak_items.append(code)

    emotion_results = checklist_axis.get("emotion_response", {}).get("results", {})
    for code, result in emotion_results.items():
        if result.get("result") == "X":
            category_counts["감정 대응"] += 1
            weak_items.append(code)

    primary_category = None
    if any(category_counts.values()):
        primary_category = max(category_counts, key=category_counts.get)

    return {
        "category_counts": category_counts,
        "weak_items": weak_items,
        "primary_weakness_category": primary_category,
    }


CATEGORY_TO_NEXT_DIFFICULTY_HINT = {
    "감정 대응": "환자의 감정 반응(특히 분노/부정처럼 다루기 어려운 감정)에 더 집중해서 연습이 필요합니다.",
    "정보 전달": "의학적 내용을 환자 수준에 맞춰 명확하게 전달하는 연습이 더 필요합니다.",
    "정보 탐색": "환자의 생각/걱정/배경을 적극적으로 묻고 알아내는 연습이 더 필요합니다.",
    "면담 구조": "면담을 체계적으로 시작하고 마무리하는 흐름 연습이 더 필요합니다.",
}


def build_recommendation(weakness: dict, current_difficulty: str, current_case_id: str, current_emotion: str) -> dict:
    """약점 분석 결과를 바탕으로 다음 연습 추천을 만든다.

    감정이 이제 케이스(질병)와 독립적으로 랜덤 배정되므로, 추천도 '다른 케이스'가 아니라
    '다른 초기 감정'을 직접 지정해서 추천한다 (케이스는 같거나 다를 수 있음).
    """
    next_difficulty_idx = min(DIFFICULTY_LEVELS.index(current_difficulty) + 1, len(DIFFICULTY_LEVELS) - 1)
    next_difficulty = DIFFICULTY_LEVELS[next_difficulty_idx]

    primary = weakness["primary_weakness_category"]

    other_emotions = [e for e in EMOTION_CATEGORIES if e != current_emotion]
    recommended_emotion = random.choice(other_emotions)
    recommended_case_id = pick_different_case(current_case_id)

    if primary is None:
        message = (
            f"이번 시도에서 뚜렷한 약점이 감지되지 않았습니다. "
            f"이번엔 '{current_emotion}' 반응이었으니, 다음엔 '{recommended_emotion}' 반응으로 "
            "다른 감정 대응을 연습해보세요."
        )
    else:
        message = CATEGORY_TO_NEXT_DIFFICULTY_HINT.get(primary, "이 부분을 더 연습해보세요.")
        if primary == "감정 대응":
            message += f" 다음엔 '{recommended_emotion}' 반응으로 연습해보세요."

    return {
        "has_weakness": primary is not None,
        "primary_weakness_category": primary,
        "message": message,
        "recommended_case_id": recommended_case_id,
        "recommended_case_title": ALL_CASES[recommended_case_id]["case_title"],
        "recommended_difficulty": next_difficulty,
        "recommended_emotion": recommended_emotion,
        "case_pool_note": None,
    }


# ---------------------------------------------------------------------------
# OpenAI 호출 유틸
# ---------------------------------------------------------------------------
async def call_openai(system_prompt: str, conversation_text: str, model: str) -> str:
    """OpenAI Chat Completions(/v1/chat/completions)를 호출하고 텍스트 응답을 반환한다.

    model은 호출하는 쪽에서 명시적으로 지정합니다 — 대화 생성은 OPENAI_MODEL_CHAT,
    평가는 OPENAI_MODEL_EVAL을 쓰도록 호출부에서 구분합니다.
    최신 스펙은 https://platform.openai.com/docs/api-reference/chat 참고.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요.",
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": conversation_text},
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            OPENAI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API 호출 실패 ({resp.status_code}): {resp.text}",
        )

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI 응답 형식을 해석할 수 없습니다: {data}",
        ) from exc


# ---------------------------------------------------------------------------
# 프롬프트 빌더
# ---------------------------------------------------------------------------
def build_patient_system_prompt(case: dict, difficulty: str, initial_emotion: str) -> str:
    persona = case["patient_persona"]
    chart = case["chart_visible_to_learner"]
    difficulty_instruction = DIFFICULTY_INSTRUCTIONS[difficulty]

    variant = persona["initial_emotion_variants"][initial_emotion]
    convergence = persona["convergence_to_acceptance"]

    no_switch_rule = (
        f"이 환자의 초기 반응은 반드시 '{initial_emotion}' 하나로 고정됩니다. "
        "대화가 진행되는 동안 부정/분노/협상/우울 중 다른 범주로 전환되어서는 안 됩니다 "
        f"(예: {initial_emotion}으로 시작했다가 다른 감정으로 바뀌는 식의 전환 금지). "
        "같은 범주 안에서 강도가 약해지거나 강해지는 것은 자연스럽습니다."
    )
    tone_notes = (
        "이 환자의 감정 반응은 진단의 심각성을 고려하여 평소 CPX에서 보는 차분한 반응보다 "
        f"훨씬 격하고 크게 표현되어야 합니다. {variant['intensity_note']}"
    )

    return f"""당신은 CPX(임상수행시험) 모의 환자 역할을 연기하는 AI입니다.
아래는 당신이 연기할 환자의 정보입니다. 이 정보 범위 밖의 사실을 절대 지어내지 마세요.
이 스테이션의 주제는 "나쁜 소식 전하기"입니다 — 평가의 핵심은 의학적 지식이 아니라
나쁜 소식을 전달받는 환자의 감정에 학습자가 어떻게 대응하는지입니다.

[환자 기본 정보]
{case['display_name']}
{case['demo_narrative']}

[검사 결과 — 의사가 먼저 말하기 전까지 당신은 모릅니다]
{chart['검사_결과']}

[치료 계획 — 의사가 설명하면 그 내용을 근거로 반응하세요. 당신이 먼저 의학적 사실을 지어내지 마세요]
{chart['향후_치료_계획']}

[배경]
{persona['background']}

[검사 결과 듣기 전 환자의 인식]
{persona['perception_before_explanation']}

[대화 시작 시 환자의 태도]
{persona['invitation']}

============================================================
[감정 전개 — 매우 중요, 반드시 지켜야 하는 규칙]
============================================================

이 환자의 초기 반응 감정은 "{initial_emotion}" 하나로 고정됩니다.

[초기 반응 강도]
{variant['intensity_note']}

[초기 반응 예시 발화]
{chr(10).join('  - ' + line for line in variant['example_lines'])}

[전환 금지 규칙]
{no_switch_rule}

[수용으로의 수렴 — 이 대화의 implicit한 엔드포인트]
다음 조건이 충족되면 자연스럽게 수용 태도로 수렴하세요: {convergence['trigger_condition']}
수용 시 예시 발화:
{chr(10).join('  - ' + line for line in convergence['example_lines'])}

이 조건이 "한 번만" 충족되면 바로 수용으로 넘어가는 게 아니라, 아래 [난이도] 항목에 적힌
"수용으로의 설득 저항도"에 따라 몇 번이나 충분히 충족되어야 하는지가 달라집니다 — 난이도가
낮으면 한두 번으로도 충분하고, 난이도가 높으면 여러 번 일관되게 충족되어야 합니다.

학습자가 감정에 제대로 대응하지 못하면({initial_emotion}을 반박하거나, 무시하거나,
성급하게 정보만 쏟아내면) 같은 "{initial_emotion}" 감정 안에서 강도가 유지되거나 더
강해질 수 있습니다. 하지만 절대로 다른 감정 범주(부정/분노/협상/우울 중 다른 것)로
바뀌지는 않습니다 — "{initial_emotion}" 안에서만 강약이 오르내리다가, 학습자가 난이도에
맞게 충분히 잘 대응하면 수용으로 수렴합니다.

[환자가 먼저 꺼낼 수 있는 이야기]
{persona['family_history_hook']}

[SPIKES 평가를 유도하는 행동 — 학습자가 SPIKES 단계를 실제로 보여줄 기회를 만들어주세요]
{persona['spikes_eliciting_hooks']}

[마무리 태도]
{persona['closing_behavior']}

[톤]
{tone_notes}

============================================================
[행동 제약 — 반드시 지켜야 하는 규칙]
============================================================
{persona['shared_behavior_rules']}

{difficulty_instruction}

추가 규칙:
1. 학습자(의사 역할)가 묻지 않은 정보를 먼저 술술 말하지 마세요. 실제 환자처럼, 묻는 것에 답하세요.
2. 의학 용어를 학습자가 먼저 쓰면, 모르는 척 되묻거나 쉬운 말로 다시 설명해달라고 하세요.
3. 환자 역할에만 머무르세요. 평가자나 코치 역할은 하지 마세요.
4. 답변은 한국어로, 실제 환자가 말하듯 자연스럽고 너무 길지 않게 하세요 (한 번에 2~4문장 정도).
5. 당신은 절대 대화를 먼저 시작하지 않습니다 — 학습자의 첫 발화를 기다린 뒤에만 응답하세요.
"""


def _format_checklist_item(code: str, item: dict) -> str:
    line = f"{code}: {item['label']}"
    if item.get("evaluation_logic"):
        line += f"\n   [평가 시 유의사항] {item['evaluation_logic']}"
    return line


def _format_emotion_checklist_block(checklist_ref: dict) -> str:
    blocks = []
    for emo_key, data in checklist_ref["emotion_checklists"].items():
        phrases = " / ".join(f'"{p}"' for p in data["representative_phrases"])
        items_lines = "\n".join(f"  {code}: {label}" for code, label in data["items"].items())
        note = f"\n(참고: {data['note']})" if data.get("note") else ""
        blocks.append(
            f"[{emo_key} — {data['label']}]{note}\n대표 발화 예시: {phrases}\n대응 체크리스트:\n{items_lines}"
        )
    return "\n\n".join(blocks)


def build_checklist_evaluator_prompt(case: dict, checklist_ref: dict, initial_emotion: str) -> str:
    scope = case["checklist_scope"]
    core_lines = "\n".join(
        _format_checklist_item(code, checklist_ref["core_checklist"][code]) for code in scope["core_required"]
    )
    cf_lines = "\n".join(
        f"{code}: {checklist_ref['critical_fail'][code]}" for code in scope["critical_fail_watchlist"]
    )
    emotion_block = _format_emotion_checklist_block(checklist_ref)
    treatment_reference = case["chart_visible_to_learner"]["향후_치료_계획"]

    return f"""당신은 CPX(임상수행시험) 채점관입니다. 이 스테이션의 주제는 "나쁜 소식 전하기"이며,
평가의 핵심은 의학적 지식이 아니라 환자의 감정에 대한 의사소통 대응 능력입니다.
아래 학습자(의사 역할)와 환자 역할 AI 사이의 전체 대화 기록을 보고, 두 가지를 평가하세요:
(1) 정해진 체크리스트 항목별 O/X 판정, (2) 환자가 보인 감정 반응에 대한 대응 능력 평가.

============================================================
(1) 체크리스트 평가
============================================================

[필수 체크리스트]
{core_lines}

[Critical Fail 감시 항목 — 하나라도 해당되면 즉시 표시]
{cf_lines}

채점 규칙:
- 각 항목은 대화 기록에 명확한 근거가 있을 때만 O로 판정하세요. 근거가 없으면 X입니다.
- 단, "[평가 시 유의사항]"이 적힌 항목은 그 지침을 일반 규칙보다 우선해서 따르세요.
- 추측하지 말고, O로 판정한 항목에는 대화에서 어떤 발화가 그 근거인지 간단히 인용하세요.
- Critical Fail은 명백히 해당 발화가 있을 때만 표시하세요. 애매하면 표시하지 마세요.
- 의학적 사실 정확성을 판단할 때는 케이스의 표준 치료 정보를 기준으로 삼으세요.
  학습자가 이와 다른 치료 정보를 사실처럼 전달했다면 CF2(의학적으로 틀린 정보)를 검토하세요.
- 단, 학습자가 차트에 없는 세부사항에 대해 "전문의와 상담 후 결정될 것"이라고 솔직하게
  한계를 인정한 경우는 회피가 아니라 적절한 응답이므로 감점하지 마세요.

[이 케이스의 표준 치료 정보 — CF2 판단 기준]
{treatment_reference}

============================================================
(2) 감정 반응별 대응 능력 평가
============================================================

이 케이스의 환자는 "{initial_emotion}" 감정으로 시작해서 학습자의 대응에 따라
"수용"으로 수렴하도록 설계되어 있습니다. 부정/분노/협상/우울 중 다른 범주로
전환되는 일은 설계상 없어야 하지만, 혹시 대화 기록에서 그런 전환이 실제로 보인다면
참고용으로 인지만 하고 채점은 아래 방식대로 진행하세요.

{emotion_block}

판정 방법:
1. 대화 기록을 읽고, 환자가 실제로 표현한 감정 범주를 위 대표 발화를 참고하여 식별하세요
   (정확히 같은 문장이 아니어도 의미가 비슷하면 해당 범주로 분류하세요).
2. 대화에서 전혀 표현되지 않은 감정 범주는 결과에서 완전히 생략하세요
   (빈 칸이나 X로 채우지 말고, 그 범주 자체를 결과에 포함하지 마세요).
3. 표현된 감정 범주에 대해서만, 그 범주의 대응 체크리스트 항목을 O/X로 판정하세요.
4. 대화가 "수용" 단계까지 도달했다면 수용 체크리스트(AC1, AC2)도 함께 판정하세요.
   아직 수용에 도달하지 못했다면 수용 항목은 결과에서 생략하세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 덧붙이지 마세요.
{{
  "core_results": {{ "E1-1": {{"result": "O 또는 X", "evidence": "..."}}, ... }},
  "critical_fails_triggered": ["CF4"],
  "critical_fail_evidence": {{ "CF4": "..." }},
  "emotion_response": {{
    "detected_emotions": ["{initial_emotion}", "수용"],
    "reached_acceptance": true,
    "results": {{
      "D1": {{"result": "O 또는 X", "evidence": "..."}},
      "AC1": {{"result": "O 또는 X", "evidence": "..."}}
    }}
  }}
}}
"""


def build_ppi_evaluator_prompt(case: dict, checklist_ref: dict, initial_emotion: str) -> str:
    ppi = checklist_ref["ppi"]
    items_text = "\n".join(
        f"{key}. {val['label']} (참고 세부요소: {', '.join(val['sub_points'])})"
        for key, val in ppi.items()
        if key != "rating_scale"
    )
    base_note = case["patient_persona"].get("ppi_personality_note", "")
    personality_note = f"이번 대화에서 이 환자는 '{initial_emotion}' 감정으로 시작했습니다. {base_note}"

    return f"""당신은 CPX 표준화 환자(SP)입니다. 방금 자신을 진료한 학습자(의사 역할)와의
전체 대화를 떠올리며, 환자 입장에서 PPI(Patient Perspective Index) 평가를 합니다.

이 케이스는 신체진찰을 시행하지 않았으므로 항목 6은 "평가 제외"로 표시하세요.

[이 환자의 성향 — 평가 기준의 기준점]
{personality_note}
PPI는 정량적 체크리스트가 아니라 "이 환자 입장에서 이 대화가 어떻게 느껴졌는가"를 보는
정성적 평가입니다. 모든 환자에게 동일한 절대적 기준을 적용하지 말고, 위에 명시된
이 환자의 성향과 욕구를 기준으로 판단하세요.

[평가 항목]
{items_text}

평가는 다음 4단계 중 하나로만: 우수함 / 부족함 / 노력하지 않음 / 평가 제외

각 항목에 대해 왜 그렇게 평가했는지 환자 시점에서 한 줄 이유를 함께 적으세요.

추가로, 항목별 평가와는 별도로 전체 대화를 종합한 서술형 코칭 피드백을 작성하세요:
- strengths: 학습자가 특히 잘한 점 (구체적인 행동/발화 근거와 함께, 2~4개)
- areas_to_improve: 더 다듬으면 좋을 점 (있으면 좋지만 당장 시급하지는 않은 것, 2~4개)
- must_fix: 다음 시도에서 반드시 고쳐야 할 점 (이 환자의 성향을 고려했을 때 명백히 부족했던
  부분만, 0~3개. 없으면 빈 배열)

각 피드백 항목은 한 문장으로, 구체적 근거(대화에서 실제 있었던 일)를 포함해서 쓰세요.
일반적이고 뻔한 조언("더 친절하게 하세요")은 피하세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 덧붙이지 마세요.
{{
  "ppi_results": {{
    "1": {{"rating": "...", "reason": "..."}},
    "2": {{"rating": "...", "reason": "..."}},
    "3": {{"rating": "...", "reason": "..."}},
    "4": {{"rating": "...", "reason": "..."}},
    "5": {{"rating": "...", "reason": "..."}},
    "6": {{"rating": "평가 제외", "reason": "이번 케이스는 신체진찰을 시행하지 않음"}}
  }},
  "narrative_feedback": {{
    "strengths": ["...", "..."],
    "areas_to_improve": ["...", "..."],
    "must_fix": ["..."]
  }}
}}
"""


def format_transcript(history: list[dict]) -> str:
    role_label = {"learner": "의사(학습자)", "patient": "환자"}
    return "\n".join(f"{role_label.get(turn['role'], turn['role'])}: {turn['text']}" for turn in history)


# ---------------------------------------------------------------------------
# API 모델
# ---------------------------------------------------------------------------
EMOTION_CATEGORIES = ["부정", "분노", "협상", "우울"]


class StartSessionRequest(BaseModel):
    difficulty: Literal["하", "중", "상"] = "중"
    case_id: str | None = None  # 지정하면 그 케이스로 강제 시작 (추천 재도전용). 없으면 랜덤.
    initial_emotion: Literal["부정", "분노", "협상", "우울"] | None = None  # 지정 없으면 랜덤.


class StartSessionResponse(BaseModel):
    session_id: str
    case_id: str
    case_title: str
    display_name: str
    instruction_to_learner: str
    chart: dict
    core_labels: dict
    emotion_labels: dict
    difficulty: str
    initial_emotion: str


class TurnRequest(BaseModel):
    session_id: str
    message: str


class TurnResponse(BaseModel):
    patient_reply: str
    turn_count: int


class EvaluateRequest(BaseModel):
    session_id: str


class EvaluateResponse(BaseModel):
    checklist_axis: dict
    ppi_axis: dict
    transcript: list[dict]
    weakness_analysis: dict
    recommendation: dict
    report_id: str


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
@app.post("/api/session/start", response_model=StartSessionResponse)
async def start_session(req: StartSessionRequest):
    difficulty = req.difficulty

    if req.case_id:
        if req.case_id not in ALL_CASES or req.case_id not in PLAYABLE_CASE_IDS:
            raise HTTPException(status_code=404, detail=f"케이스 '{req.case_id}'를 찾을 수 없거나 플레이할 수 없습니다.")
        case_id = req.case_id
    else:
        case_id = pick_random_case()

    # 초기 감정은 케이스(질병)와 완전히 독립적으로 랜덤 선택 — 같은 질병이라도 매번
    # 다른 감정으로 시작할 수 있다.
    initial_emotion = req.initial_emotion or random.choice(EMOTION_CATEGORIES)

    case = ALL_CASES[case_id]

    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "case_id": case_id,
        "difficulty": difficulty,
        "initial_emotion": initial_emotion,
        "history": [],  # 학습자가 먼저 인사하며 시작하므로 비어있는 상태로 시작
    }

    scope = case["checklist_scope"]
    core_labels = {code: CHECKLIST_REF["core_checklist"][code]["label"] for code in scope["core_required"]}
    emotion_labels = {
        code: label
        for emo_data in CHECKLIST_REF["emotion_checklists"].values()
        for code, label in emo_data["items"].items()
    }

    return StartSessionResponse(
        session_id=session_id,
        case_id=case_id,
        case_title=case["case_title"],
        display_name=case["display_name"],
        instruction_to_learner=case["instruction_to_learner"],
        chart=case["chart_visible_to_learner"],
        core_labels=core_labels,
        emotion_labels=emotion_labels,
        difficulty=difficulty,
        initial_emotion=initial_emotion,
    )


@app.post("/api/turn", response_model=TurnResponse)
async def take_turn(req: TurnRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    session = SESSIONS[req.session_id]
    case = ALL_CASES[session["case_id"]]
    history = session["history"]
    history.append({"role": "learner", "text": req.message})

    system_prompt = build_patient_system_prompt(case, session["difficulty"], session["initial_emotion"])
    transcript_so_far = format_transcript(history)
    patient_reply = await call_openai(system_prompt, transcript_so_far, OPENAI_MODEL_CHAT)

    history.append({"role": "patient", "text": patient_reply})

    return TurnResponse(patient_reply=patient_reply, turn_count=len(history))


@app.post("/api/evaluate", response_model=EvaluateResponse)
async def evaluate_session(req: EvaluateRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    session = SESSIONS[req.session_id]
    case = ALL_CASES[session["case_id"]]
    history = session["history"]
    transcript_text = format_transcript(history)

    checklist_prompt = build_checklist_evaluator_prompt(case, CHECKLIST_REF, session["initial_emotion"])
    ppi_prompt = build_ppi_evaluator_prompt(case, CHECKLIST_REF, session["initial_emotion"])

    checklist_raw = await call_openai(checklist_prompt, transcript_text, OPENAI_MODEL_EVAL)
    ppi_raw = await call_openai(ppi_prompt, transcript_text, OPENAI_MODEL_EVAL)

    def safe_parse(raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"_parse_error": True, "_raw": raw}

    checklist_axis_parsed = safe_parse(checklist_raw)
    ppi_axis_parsed = safe_parse(ppi_raw)

    weakness = analyze_weaknesses(checklist_axis_parsed)
    recommendation = build_recommendation(weakness, session["difficulty"], session["case_id"], session["initial_emotion"])

    report_id = save_report(
        session_id=req.session_id,
        case=case,
        difficulty=session["difficulty"],
        initial_emotion=session["initial_emotion"],
        transcript=history,
        checklist_axis=checklist_axis_parsed,
        ppi_axis=ppi_axis_parsed,
        weakness=weakness,
        recommendation=recommendation,
        source="live",
    )

    return EvaluateResponse(
        checklist_axis=checklist_axis_parsed,
        ppi_axis=ppi_axis_parsed,
        transcript=history,
        weakness_analysis=weakness,
        recommendation=recommendation,
        report_id=report_id,
    )


@app.get("/api/reports")
async def list_reports(source: str | None = None):
    """저장된 레포트 목록(메타데이터만)을 반환한다. source='live' 또는 'synthetic'으로 필터 가능."""
    results = []
    for f in sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        report = json.loads(f.read_text(encoding="utf-8"))
        if source and report.get("source") != source:
            continue
        results.append({
            "report_id": report["report_id"],
            "source": report.get("source", "unknown"),
            "created_at": report["created_at"],
            "case_id": report["case_id"],
            "case_title": report["case_title"],
            "difficulty": report["difficulty"],
            "initial_emotion": report["initial_emotion"],
            "turn_count": len(report["transcript"]),
        })
    return results


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    """레포트 전체(transcript + 모든 평가축)를 반환한다 — PPI 판단 프롬프트의 입력으로 그대로 쓸 수 있다."""
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"레포트 '{report_id}'를 찾을 수 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/cases")
async def list_cases():
    """디버깅/확인용 — DB에 적재된 모든 케이스와 플레이 가능 여부를 보여준다."""
    return [
        {
            "case_id": c["case_id"],
            "case_title": c["case_title"],
            "display_name": c["display_name"],
            "ready_for_play": c.get("ready_for_play", False),
        }
        for c in ALL_CASES.values()
    ]


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "total_cases_loaded": len(ALL_CASES),
        "playable_cases": PLAYABLE_CASE_IDS,
    }
