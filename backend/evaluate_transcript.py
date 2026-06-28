"""
이미 가지고 있는 대화 transcript(JSON 파일)를 입력받아, 실제 평가 로직
(체크리스트+감정반응+PPI+약점분석+추천)을 돌리고 레포트로 저장한다.

새로 대화를 생성하는 게 아니라, "이미 끝난 대화를 다시 채점만 하고 싶을 때" 쓰는 도구.
예: 스크린샷에서 옮긴 과거 대화를 정식으로 평가해서 DB(reports/)에 넣고 싶을 때.

입력 transcript JSON 형식 (위 28af8607..._input_transcript.json 참고):
{
  "case_id": "B05-breast-cancer",
  "difficulty": "중",          // 모르면 null 가능 — 이 경우 --difficulty로 직접 지정해야 함
  "initial_emotion": "협상",   // 모르면 null 가능 — 이 경우 --initial-emotion으로 직접 지정해야 함
  "transcript": [ {"role": "learner"|"patient", "text": "..."}, ... ]
}

사용법:
    cd backend
    python3 evaluate_transcript.py --input reports/28af8607-105b-4481-ae82-c930776590c1_input_transcript.json
    # difficulty/initial_emotion이 파일에 없거나 덮어쓰고 싶으면:
    python3 evaluate_transcript.py --input <파일> --difficulty 중 --initial-emotion 협상
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as app  # noqa: E402


async def evaluate_and_save(case_id: str, difficulty: str, initial_emotion: str, transcript: list[dict]) -> str:
    if case_id not in app.ALL_CASES:
        raise ValueError(f"case_id '{case_id}'를 cases/ 폴더에서 찾을 수 없습니다.")
    case = app.ALL_CASES[case_id]

    checklist_prompt = app.build_checklist_evaluator_prompt(case, app.CHECKLIST_REF, initial_emotion)
    ppi_prompt = app.build_ppi_evaluator_prompt(case, app.CHECKLIST_REF, initial_emotion)
    transcript_text = app.format_transcript(transcript)

    print("체크리스트 평가 호출 중 (EVAL 모델)...")
    checklist_raw = await app.call_openai(checklist_prompt, transcript_text, app.OPENAI_MODEL_EVAL)
    print("PPI 평가 호출 중 (EVAL 모델)...")
    ppi_raw = await app.call_openai(ppi_prompt, transcript_text, app.OPENAI_MODEL_EVAL)

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

    checklist_axis = safe_parse(checklist_raw)
    ppi_axis = safe_parse(ppi_raw)
    weakness = app.analyze_weaknesses(checklist_axis)
    recommendation = app.build_recommendation(weakness, difficulty, case_id, initial_emotion)

    report_id = app.save_report(
        session_id=f"manual-eval-{case_id}",
        case=case,
        difficulty=difficulty,
        initial_emotion=initial_emotion,
        transcript=transcript,
        checklist_axis=checklist_axis,
        ppi_axis=ppi_axis,
        weakness=weakness,
        recommendation=recommendation,
        source="live",
    )
    return report_id


def main():
    parser = argparse.ArgumentParser(description="기존 대화 transcript를 평가하고 레포트로 저장")
    parser.add_argument("--input", required=True, help="transcript JSON 파일 경로")
    parser.add_argument("--difficulty", default=None, choices=["하", "중", "상"], help="난이도 (파일에 없으면 필수)")
    parser.add_argument("--initial-emotion", default=None, choices=["부정", "분노", "협상", "우울"],
                         help="초기 감정 (파일에 없으면 필수)")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    case_id = data["case_id"]
    difficulty = args.difficulty or data.get("difficulty")
    initial_emotion = args.initial_emotion or data.get("initial_emotion")
    transcript = data["transcript"]

    if not difficulty:
        print("오류: difficulty가 파일에도 없고 --difficulty로도 지정되지 않았습니다.")
        sys.exit(1)
    if not initial_emotion:
        print("오류: initial_emotion이 파일에도 없고 --initial-emotion으로도 지정되지 않았습니다.")
        sys.exit(1)

    print(f"case_id={case_id}, difficulty={difficulty}, initial_emotion={initial_emotion}, "
          f"대화 {len(transcript)}턴 평가 시작")

    report_id = asyncio.run(evaluate_and_save(case_id, difficulty, initial_emotion, transcript))
    print(f"\n완료 — report_id={report_id}")
    print(f"확인: reports/{report_id}.json")


if __name__ == "__main__":
    main()
