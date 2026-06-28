"""
합성(synthetic) 모의 문진 데이터 생성기.

사람이 매번 직접 채팅 치지 않고도, "학습자 역할 LLM"과 "환자 역할 LLM"이 자동으로
대화를 주고받게 해서 다양한 케이스 × 난이도 × 감정 × 학습자 실력 조합의 레포트를
대량으로 생성한다. PPI 판단용 프롬프트를 테스트/검증할 표본 데이터를 빠르게 확보하기 위함.

실행 전 준비: backend/.env에 OPENAI_API_KEY 설정 (서버를 따로 띄울 필요 없음 —
main.py의 함수들을 직접 import해서 사용한다).

사용법:
    cd backend
    python3 generate_synthetic_reports.py --count 5
    python3 generate_synthetic_reports.py --count 1 --case-id B01-pancreatic --skill 미흡
"""

import argparse
import asyncio
import random
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as app  # noqa: E402  (main.py의 함수/데이터를 그대로 재사용)


# ---------------------------------------------------------------------------
# 합성 학습자(의사 역할) 페르소나 — 실력 3단계
# ---------------------------------------------------------------------------
LEARNER_SKILL_PROMPTS = {
    "우수": (
        "당신은 SPIKES 프로토콜을 매우 잘 따르는 숙련된 의대생입니다. "
        "인사와 신원 확인, 동석자 확인을 빠뜨리지 않고, 환자의 감정을 적극적으로 묻고 "
        "이름 붙여줍니다. 의학 용어를 쉽게 풀어 설명하고, 환자가 화를 내거나 슬퍼해도 "
        "방어적으로 반응하지 않으며 충분히 공감한 뒤에야 다음 정보를 전달합니다. "
        "환자가 차트 밖의 세부사항을 물으면 '그 부분은 전문의와 상담 후 정해질 것'이라고 "
        "솔직하게 답합니다. 대화 마지막엔 요약하고 질문 기회를 준 뒤 마무리합니다."
    ),
    "보통": (
        "당신은 기본적인 절차는 지키지만 가끔 놓치는 평범한 의대생입니다. "
        "인사와 검사 결과 전달은 하지만, 동석자 확인이나 감정 확인 질문을 가끔 빠뜨립니다. "
        "공감 표현을 하긴 하지만 형식적일 때가 있고, 가끔 의학 용어를 그대로 씁니다. "
        "환자의 감정에 대체로 침착하게 반응하지만, 한두 번은 성급하게 다음 설명으로 "
        "넘어가기도 합니다."
    ),
    "미흡": (
        "당신은 환자와의 소통이 서툰 의대생입니다. 인사나 신원 확인을 건너뛰고 바로 "
        "검사 결과를 통보하듯 말합니다. 환자의 감정을 묻지 않고, 의학 용어를 그대로 "
        "사용합니다. 환자가 화를 내거나 슬퍼하면 당황해서 정보만 더 쏟아내거나, "
        "'그래도 치료하면 괜찮아질 거예요' 같은 성급한 안심을 시킵니다. 환자가 차트 밖의 "
        "구체적인 질문(약물명 등)을 하면 모르면서도 대충 둘러대며 답하려 합니다. "
        "마무리 없이 대화를 갑자기 끝내려 합니다."
    ),
}


def build_synthetic_learner_prompt(case: dict, skill: str) -> str:
    chart = case["chart_visible_to_learner"]
    chart_text = "\n".join(f"- {k}: {v}" for k, v in chart.items())
    return f"""{LEARNER_SKILL_PROMPTS[skill]}

당신은 지금 환자에게 나쁜 소식을 전달하는 CPX 모의 문진을 진행하는 중입니다.
아래는 당신(의료진)이 가진 차트 정보입니다:
{chart_text}

지시사항: {case['instruction_to_learner']}

규칙:
1. 한국어로, 의사가 말하듯 자연스럽게 2~3문장 정도로 답하세요.
2. 환자의 마지막 발화에 직접 반응하세요. 대화 흐름을 무시하고 차트 내용을 한꺼번에
   다 말하지 마세요 — 실제 대화처럼 단계적으로 진행하세요.
3. 당신이 먼저 인사하며 대화를 시작합니다 (예: "안녕하세요, 담당 의료진 OOO입니다.").
4. 대화가 충분히 진행되어(보통 8~14턴) 마무리할 시점이 되면, 요약하고 질문을 받은 뒤
   마무리 인사를 하세요.
"""


async def run_synthetic_conversation(
    case_id: str, difficulty: str, initial_emotion: str, skill: str, max_turns: int = 10
) -> dict:
    """학습자 LLM과 환자 LLM이 max_turns만큼 자동으로 대화를 주고받는다."""
    case = app.ALL_CASES[case_id]
    learner_system_prompt = build_synthetic_learner_prompt(case, skill)
    patient_system_prompt = app.build_patient_system_prompt(case, difficulty, initial_emotion)

    history: list[dict] = []

    for turn in range(max_turns):
        # 학습자 턴 — 지금까지의 대화를 "환자가 한 말"처럼 보여주고 학습자 응답을 생성
        learner_transcript = app.format_transcript(
            [{"role": "patient" if h["role"] == "learner" else "learner", "text": h["text"]} for h in history]
        )
        learner_text = await app.call_openai(
            learner_system_prompt, learner_transcript or "(대화를 시작하세요)", app.OPENAI_MODEL_CHAT
        )
        history.append({"role": "learner", "text": learner_text})

        # 환자 턴
        patient_transcript = app.format_transcript(history)
        patient_text = await app.call_openai(patient_system_prompt, patient_transcript, app.OPENAI_MODEL_CHAT)
        history.append({"role": "patient", "text": patient_text})

    return {"case": case, "history": history}


async def evaluate_and_save(case: dict, difficulty: str, initial_emotion: str, history: list[dict], skill: str) -> str:
    """main.py의 평가 로직을 재사용해서 채점하고 레포트로 저장한다."""
    checklist_prompt = app.build_checklist_evaluator_prompt(case, app.CHECKLIST_REF, initial_emotion)
    ppi_prompt = app.build_ppi_evaluator_prompt(case, app.CHECKLIST_REF, initial_emotion)
    transcript_text = app.format_transcript(history)

    checklist_raw = await app.call_openai(checklist_prompt, transcript_text, app.OPENAI_MODEL_EVAL)
    ppi_raw = await app.call_openai(ppi_prompt, transcript_text, app.OPENAI_MODEL_EVAL)

    def safe_parse(raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            import json
            return json.loads(cleaned)
        except Exception:
            return {"_parse_error": True, "_raw": raw}

    checklist_axis = safe_parse(checklist_raw)
    ppi_axis = safe_parse(ppi_raw)
    weakness = app.analyze_weaknesses(checklist_axis)
    recommendation = app.build_recommendation(weakness, difficulty, case["case_id"], initial_emotion)

    report_id = app.save_report(
        session_id=f"synthetic-{uuid.uuid4()}",
        case=case,
        difficulty=difficulty,
        initial_emotion=initial_emotion,
        transcript=history,
        checklist_axis=checklist_axis,
        ppi_axis=ppi_axis,
        weakness=weakness,
        recommendation=recommendation,
        source="synthetic",
    )
    return report_id


async def main_async(count: int, case_id: str | None, skill: str | None, difficulty: str | None):
    for i in range(count):
        chosen_case_id = case_id or app.pick_random_case()
        chosen_difficulty = difficulty or random.choice(app.DIFFICULTY_LEVELS)
        chosen_emotion = random.choice(app.EMOTION_CATEGORIES)
        chosen_skill = skill or random.choice(list(LEARNER_SKILL_PROMPTS.keys()))

        print(f"[{i+1}/{count}] case={chosen_case_id} difficulty={chosen_difficulty} "
              f"emotion={chosen_emotion} skill={chosen_skill} ... 대화 생성 중")

        result = await run_synthetic_conversation(chosen_case_id, chosen_difficulty, chosen_emotion, chosen_skill)
        print(f"  대화 {len(result['history'])}턴 생성 완료, 평가 중...")

        report_id = await evaluate_and_save(
            result["case"], chosen_difficulty, chosen_emotion, result["history"], chosen_skill
        )
        print(f"  저장 완료 -> report_id={report_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="합성 모의문진 레포트 생성기")
    parser.add_argument("--count", type=int, default=3, help="생성할 레포트 개수")
    parser.add_argument("--case-id", type=str, default=None, help="특정 케이스로 고정 (예: B01-pancreatic)")
    parser.add_argument("--skill", type=str, default=None, choices=["우수", "보통", "미흡"], help="학습자 실력 고정")
    parser.add_argument("--difficulty", type=str, default=None, choices=["하", "중", "상"], help="난이도 고정")
    args = parser.parse_args()

    asyncio.run(main_async(args.count, args.case_id, args.skill, args.difficulty))
