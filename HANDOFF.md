# CODE:MEDI — 프로젝트 인계 가이드 (v3)

> 이 문서는 토큰/컨텍스트가 부족해 새 Claude 대화로 넘어갈 때 맥락을 빠르게 따라잡기 위한
> 문서입니다. **이 md와 `cpx-prototype/` 폴더 전체를 새 대화에 업로드**하면 이어서 작업할
> 수 있습니다. **이전 버전(v1/v2) 인계 문서 내용은 이 문서가 대체합니다 — 가장 큰 변화가
> 있었던 지점은 "3. 가장 중요한 전환점" 섹션을 꼭 읽으세요.**

---

## 1. 프로젝트 개요

- **해커톤**: CODE:MEDI — 의과대학 + SW대학 공동 해커톤. 대주제 "환자 진단을 위한 LLM 기반
  CPX 개발". 우리 팀 소주제: "나쁜 소식 전달하기" (Breaking Bad News).
- **목표**: 본과 실습생이 CPX "나쁜 소식 전달하기" 스테이션을 대비하는 LLM 기반 모의 문진
  학습 앱.

## 2. 평가 체계 (v3, 현재 기준)

CPX 실제 평가는 두 축: ① 관찰 교수의 체크리스트 O/X, ② 표준화 환자(SP)의 PPI(환자 관점
정성평가, Calgary-Cambridge 한국어 버전 6항목). **두 점수는 절대 안 섞고 완전 분리해서
표시**하는 게 사용자의 명시적 결정. 여기에 감정 반응 대응 평가가 체크리스트 축에 곁들여짐.

## 3. 가장 중요한 전환점 — 교수 피드백으로 인한 전면 재설계

이전(v1/v2) 버전은 F1~F8 케이스 패밀리, modifiers, C1~C9 후보 체크리스트, 11개 케이스로
된 비교적 일반적인 CPX 시뮬레이터였습니다. **교수님 피드백으로 다음과 같이 완전히
재설계되었습니다:**

### 3.1 무엇이, 왜 바뀌었는가
- **문제**: 발화가 질병 자체(의학 지식)에 너무 포인팅되어 있었음. 소주제가 "나쁜 소식
  전달"인데 일반적 문진처럼 흘러감.
- **해결**: 케이스를 "객관적으로 충격적인 진단" 6개로 제한, 체크리스트를 11개 핵심항목 +
  감정반응 5종×2개로 극단적으로 단순화, 환자가 차트 밖 깊은 의학 질문을 안 하게 제약.

### 3.2 새 6개 케이스 (전부 `backend/cases/`에 있고 ready_for_play=true)
| case_id | 질환 | 고정 초기반응 |
|---|---|---|
| B01-pancreatic | 췌장암 (박정환, 62세 남) | 우울 |
| B02-lung-cancer | 폐암/비소세포 (이수진, 55세 여, 비흡연) | 분노 |
| B03-leukemia | 급성 백혈병 (정민호, 23세 남) | 분노 |
| B04-glioblastoma | 교모세포종/악성뇌종양 (한미경, 48세 여) | 부정 |
| B05-breast-cancer | 전이성 유방암 4기 (최영아, 45세 여) | 협상 |
| B06-missed-abortion | 계류유산 (김지은, 32세 여) | 우울 |

**중요한 발견**: 노션 원본 마크다운에서 5번 케이스(최영아)의 헤더는 "교모세포종"이라고
잘못 적혀 있었음(4번 헤더를 복사하다 안 고친 오타로 보임) — 표 내용은 명백히 유방암
전이(BRCA, HER2, 호르몬수용체, 뼈전이)였음. **`case_title`을 "전이성 유방암(4기)"으로
정정해서 진행함.** 원작성자에게 확인 필요.

각 케이스의 `initial_emotion`(고정 초기반응)은 케이스 데이터의 "환자만 아는 정보(걱정거리)"
텍스트에서 직접 도출한 제 판단입니다 — 사용자가 준 두 예시(유산→우울, 백혈병/암→분노)는
명시적으로 확인된 것이고, 나머지(췌장암=우울, 폐암=분노, 교모세포종=부정, 유방암=협상)는
제가 걱정거리 내용을 보고 가장 자연스럽다고 판단해서 배정한 것 — **검증 필요.**

### 3.3 핵심 설계 규칙 (전부 사용자가 명시한 요구사항)
1. **학습자가 먼저 대화를 시작**한다 ("안녕하세요. 담당 의료진 OOO입니다..."). 세션 시작 시
   `history`가 빈 배열로 시작하고, 환자의 사전 입력 대사가 없음 (이전 버전엔 환자가 먼저
   인사하는 `opening_line`이 있었는데 이번에 제거됨).
2. **환자의 초기 감정 반응은 부정/분노/협상/우울 중 정확히 1개로 고정**되고, 대화 중 이
   4개 사이의 전환은 금지된다 (같은 범주 안에서 강약만 변함). **수용은 "전환 가능한 5번째
   감정"이 아니라 별도의 엔드포인트 상태** — `convergence_to_acceptance` 필드로 따로 관리.
3. **감정 강도는 항상 평소보다 훨씬 크게** — 모든 케이스의 `initial_emotion.intensity_note`에
   이 내용이 명시되어 있음. 난이도(하/중/상)는 두 가지를 동시에 조절함:
   (a) **단서 명시성** — 지시문(괄호 표정/행동) 빈도, (b) **수용으로의 설득 저항도** — 학습자가
   몇 번이나 충분히 잘 대응해야 환자가 실제로 수용으로 넘어가는지. 하=쉽게 설득됨,
   상=반복적으로 충분히 공감/설명해야만 서서히 수용. 변수명 `DIFFICULTY_INSTRUCTIONS`(이전
   `DIFFICULTY_CUE_INSTRUCTIONS`에서 두 축을 포괄하도록 이름 변경됨)에 두 축이 함께 들어있음.
   케이스별 `convergence_to_acceptance.trigger_condition`(어떤 *종류*의 대응이 트리거가
   되는지)과 난이도별 설득저항도(그게 *몇 번* 충족되어야 하는지)가 같이 작동하도록 프롬프트에
   연결 문장을 넣어둠.
4. **환자는 차트 밖의 깊은 의학 질문(약물명, 시술 디테일, 통계)을 하지 않는다.** 가벼운
   걱정성 질문만. 같은 내용을 억지로 반복 질문하지 않는다 — 이해되면 더 캐묻지 않음. 이
   규칙은 모든 케이스 공통으로 `SHARED_BEHAVIOR_RULES` 문자열에 박혀있고, 각 케이스
   `patient_persona.shared_behavior_rules`에 들어가서 프롬프트에 항상 포함됨.
5. **환자의 행동이 학습자의 SPIKES 단계를 유도해야 함** — 각 케이스 `spikes_eliciting_hooks`
   필드에 "혼자 왔다는 걸 스스로 언급" 등 구체적 행동 지침 작성.
6. **엔드포인트**: 4단계(나쁜소식 전달 → 감정격화·수렴 → 간단 후속질문 → SPIKES 유도)가
   끝나고 환자가 더 궁금한 게 없으면 "네, 알겠습니다" 류로 스스로 마무리를 제안할 수 있음
   (또는 학습자가 먼저 마무리). **이 로직은 프롬프트 지침으로만 구현됨 — 백엔드 코드가
   "4단계 완료"를 직접 감지하지는 않음.** 실제로 일관되게 동작하는지 검증 필요.

### 3.4 체크리스트가 완전히 바뀜 (구조적으로 단순화)
이전: E1~E18(17개, E16 삭제됨) + 케이스별 후보 C1~C9 + 감정반응 5종×5~6개.
**현재**: E1-1~E1-4(첫멘트) + E2-1~E2-6(중간) + E3-1(마무리) = **11개 핵심항목만, 모든
케이스 공통, 케이스별 후보 체크리스트 없음** + 감정반응 5종×**2개**(부정D1-2/분노A1-2/
협상B1-2/우울DEP1-2/수용AC1-2). Critical Fail(CF1-8)과 PPI(6항목)는 변경 없음.

이전 버전의 모든 데이터(11개 케이스, E1-E18, C1-C9, F1-F8 체계)는 **삭제하지 않고**
`backend/cases_archive_v1/`, `backend/checklist_reference_v1_archive.json`에 보관함.

### 3.5 코드 구조 변경
- `pick_case_for_difficulty()` → `pick_random_case()`(완전 균등 랜덤) +
  `pick_different_case()`(추천용, 다른 케이스 보장) 로 분리. 난이도별 케이스 필터링 로직
  삭제 (모든 케이스가 균일하게 강렬해서 의미 없어짐).
- `WEAKNESS_CATEGORY_MAP`을 새 E1-1~E3-1 코드로 재작성. 매핑: E1-1~E1-4/E3-1→"면담구조",
  E2-1/E2-3/E2-6→"감정대응", E2-2/E2-4→"정보전달", E2-5→"정보탐색". 감정코드(D/A/B/DEP/AC
  접두사)는 그대로 "감정대응"으로 일괄 처리(기존 로직 재사용).
- `build_recommendation(weakness, difficulty, current_case_id)` — **시그니처에
  `current_case_id` 추가됨**. 가능하면 지금 한 케이스와 **다른 초기반응 감정**을 가진
  케이스를 추천하도록 바뀜 (이전엔 케이스가 1개뿐이라 항상 같은 케이스 추천이었음, 이제
  6개라 실제로 다른 케이스/다른 감정 추천이 동작함 — 단위테스트로 확인함).
- `build_patient_system_prompt(case, difficulty)` — persona 읽는 필드가 완전히 바뀜:
  `emotional_arc_required_beats`(리스트, 구버전) → `initial_emotion` + `convergence_to_
  acceptance`(둘 다 단일 dict, 신버전). `shared_behavior_rules`, `spikes_eliciting_hooks`
  필드 추가 반영.
- `build_checklist_evaluator_prompt()` — candidate(C1) 관련 코드 전부 제거. 출력 JSON에서
  `candidate_results` 키 자체가 없어짐(이전엔 있었음). `emotion_response`에
  `reached_acceptance`(bool) 필드 추가.
- `/api/session/start` — `StartSessionRequest`에 `case_id: str | None` 추가(지정하면 강제
  시작, 추천 재도전 버튼이 이걸 사용). `history`를 빈 배열로 시작(이전엔 환자 opening_line
  하나 미리 넣어뒀음). `StartSessionResponse`에서 `opening_line`, `candidate_labels` 제거.
- 프론트엔드: 난이도 선택 화면은 그대로지만 "당신이 먼저 인사하며 시작하세요" 안내로 바뀜.
  리포트 화면의 "② 케이스 후보 체크리스트" 섹션 통째로 제거, 감정반응 섹션이 ②로 승격.
  추천 재도전 버튼이 이제 `case_id`까지 백엔드에 같이 보내서 실제로 다른 케이스로 감.

### 3.6 초기 감정이 질병(케이스)과 완전히 독립적으로 랜덤화됨 (가장 최근 변경)
처음엔 "췌장암=우울, 폐암=분노" 식으로 질병마다 감정이 고정되어 있었음. **이제는 케이스
선택과 감정 선택이 완전히 독립된 두 번의 랜덤 추첨**으로 바뀜 — 같은 췌장암 케이스도
매번 부정/분노/협상/우울 중 아무거나로 시작할 수 있음.

- 각 케이스 파일의 `patient_persona.initial_emotion`(단일 dict) →
  `initial_emotion_variants`(4개 키: 부정/분노/협상/우울, 각각 `{intensity_note,
  example_lines}`)로 구조 변경. 6개 케이스 × 4개 변형 = 24개를 전부 새로 작성함 — 각
  변형은 그 케이스의 "환자만 아는 정보(걱정거리)"를 해당 감정 톤으로 번역한 것.
- `no_switch_rule`, `ppi_personality_note`의 감정-종속 부분은 더 이상 JSON에 저장하지 않고
  `main.py`가 런타임에 실제 선택된 감정으로 문자열을 생성함 (`build_patient_system_prompt`,
  `build_ppi_evaluator_prompt` 참고).
- 각 케이스의 `convergence_to_acceptance.trigger_condition`도 특정 감정에 종속된 표현
  (예: "슬픔을 인정", "분노의 부당함")을 전부 "감정을 인정"처럼 중립적으로 바꿔서, 어떤
  감정이 뽑혀도 자연스럽게 적용되도록 함.
- API: `StartSessionRequest`에 `initial_emotion` 필드 추가(지정 안 하면
  `random.choice(EMOTION_CATEGORIES)`로 랜덤). 세션에 `initial_emotion`을 저장하고
  `/api/turn`, `/api/evaluate` 양쪽에 전달.
- `build_recommendation()` 시그니처에 `current_emotion` 인자 추가 — 이제 "다른 케이스를
  찾아서 그 케이스의 감정을 보고 추천"하는 게 아니라, **감정 자체를 직접 다르게 추천**함
  (케이스는 `pick_different_case`로 그냥 다른 거 하나 고름, 감정은 나머지 3개 중 랜덤).
- `checklist_scope.emotion_checklists_expected`는 이제 케이스 파일에서 의미 없는
  placeholder(`["(런타임에 결정됨)", "수용"]`)로 남아있음 — 실제 값은 세션의
  `initial_emotion`을 코드가 직접 사용함. 이 필드를 보고 헷갈리지 말 것.

### 3.7 차트 중복 제거
`chart_visible_to_learner`의 `나이_성별`(예: "45세 여성")과 `기본_정보`(예: "45세 여성,
배우자·자녀와 거주...")가 앞부분이 겹쳐서 사용자에게 같은 정보가 두 번 보였음. 모든
케이스의 `기본_정보`에서 나이/성별 접두사를 제거해서 중복 없앰.

### 3.8 레포트 영속 저장 + 합성 데이터 생성기 (가장 최근 추가)
의대생 측이 "실제 연극배우가 PPI를 판단하는 프롬프트"를 별도로 만들 예정인데, 그 입력으로
쓸 수 있게 평가 결과를 transcript와 함께 저장해야 한다는 요구사항.

- `save_report()` — `/api/evaluate` 끝에서 호출됨. transcript + checklist_axis + ppi_axis +
  weakness_analysis + recommendation을 한 JSON으로 묶어 `backend/reports/{uuid}.json`에 저장.
  `source` 필드로 "live"(실제 학습자)/"synthetic"(자동생성) 구분.
- `GET /api/reports`, `GET /api/reports/{id}` — 목록/상세 조회.
- **`generate_synthetic_reports.py`** — 사람이 매번 채팅 안 치고도 테스트 데이터를 만들 수
  있게, "학습자 역할 LLM"(우수/보통/미흡 3단계 실력 페르소나)과 기존 "환자 역할 LLM"을
  자동으로 맞대화시켜서 레포트를 대량 생성하는 CLI 스크립트. `main.py`의 함수들을 그대로
  import해서 재사용함(코드 중복 없음). 실제 OpenAI 호출이 필요해서 이 환경에서는 실행 테스트를
  못 했고, 문법 검증 + 모듈 import + 프롬프트 생성 로직만 단위테스트로 확인함.

### 3.9 모델 2단계 분리 + 평가 전용 도구 추가
- `OPENAI_MODEL`(단일) → `OPENAI_MODEL_CHAT`(대화, 기본 gpt-4o-mini) /
  `OPENAI_MODEL_EVAL`(평가, 기본 gpt-4o)로 분리. `call_openai(system_prompt, text, model)`이
  이제 model을 명시적으로 받음 — 모든 호출부(`/api/turn`은 CHAT, `/api/evaluate`의 체크리스트+PPI
  둘 다 EVAL, `generate_synthetic_reports.py`도 동일 원칙)에서 의도적으로 골라 씀.
- **`evaluate_transcript.py`** — 새 CLI 도구. 이미 가진 transcript(JSON)를 입력받아 평가만
  다시 돌리고 레포트로 저장. `generate_synthetic_reports.py`처럼 대화 자체를 새로 만드는 게
  아니라, 사람이 과거에 캡처해둔 대화를 정식 평가 파이프라인에 통과시키고 싶을 때 씀.
- **레포트 교체**: 이전 ALS(N01-als) 레포트는 구버전 시스템 결과라 삭제하고, 새로 캡처된
  B05-breast-cancer(최영아, 협상→수용) 대화로 교체함. 단, 이번엔 transcript만 저장했고
  실제 평가(체크리스트/PPI 호출)는 OpenAI 네트워크 제약으로 이 환경에서 실행하지 못함 —
  사용자가 `evaluate_transcript.py`를 직접 돌려서 완성해야 함. `reports/` 안의
  `*_input_transcript.json`(평가 스크립트 입력용)과 `*_transcript.md`(대본 형태) 둘 다 있음.


### 3.10 케이스 7~10번 추가 (총 10개로 확장)
노션에서 추가로 4개 케이스를 받아 B07~B10으로 추가함. B01~B06과 동일한 스키마
(initial_emotion_variants 4종, 9필드 차트, 공통 행동제약)를 따름.
- **B07-recurrence**(대장암 재발) — **처음으로 `prior_encounter_context.has_prior_diagnosis: true`인
  케이스**. 1년 전 수술+항암 완료 후 재발이라 "초진"이 아님. 다른 9개는 전부 초진(false).
- **B08-hiv**(HIV 확진) — 비밀보장/파트너 통보 이슈가 있는 케이스. 원래 이 대화의 맨 첫
  레퍼런스 자료(CPX 책)에 있던 HIV 케이스와 주제가 겹침.
- **B09-breast-cancer-early**(유방암 초기) — B05(전이성/4기)와 대비되는 비전이·수술전
  단계. 환자 이름이 "이수진"으로 B02(폐암)와 동명이인 — 의도된 건지 원작성자 확인은 안 됨,
  case_id로 구분되니 기능상 문제는 없음.
- **B10-down-syndrome**(태아 다운증후군) — 산모가 환자. **비지시적 상담(non-directive
  counseling)이 핵심** — 임신 지속 여부에 대해 학습자가 특정 방향을 유도하면 안 됨. 이
  요구사항은 `spikes_eliciting_hooks`/`chart_visible_to_learner.유의사항`에 텍스트로
  반영했지만, 별도의 Critical Fail 코드는 추가하지 않음(기존 CF1-8 중 들어맞는 게 없어서
  — 필요하면 나중에 CF9 같은 걸 새로 만들어야 함).
- 10개 모두 무결성 검증(스코프-레퍼런스 일치, persona 필수필드, 4감정변형 존재) 통과,
  30회 반복 호출로 10개 케이스가 다 랜덤 풀에 고르게 섞이는 것도 확인함.

### 3.11 PPI 종합 레포트 — 진행 중, 입력 대기
사용자가 "의대생이 만든 실제 PPI 평가 프롬프트"를 적용해서, 현재 리포트(체크리스트=교수
관점 + 우리 AI의 PPI 추정)에 **세 번째 축**(실제 연극배우 관점 PPI)을 추가하고 싶어함.
**그 프롬프트 텍스트 자체는 아직 전달받지 못함** — 다음 대화에서 텍스트나 파일로 받으면:
1. `build_actor_ppi_prompt()` 추가 (받은 프롬프트 그대로 사용, 임의로 지어내지 않을 것)
2. `/api/evaluate`에 세 번째 OpenAI 호출(EVAL 모델) 추가
3. `save_report()`/`EvaluateResponse`에 `actor_ppi_axis` 필드 추가
4. 프론트엔드에 세 번째 섹션 추가
이 작업은 아직 코드에 반영되지 않았음 — 다음 세션에서 이어서 할 것.

## 4. 파일 구조
```
cpx-prototype/
  README.md
  HANDOFF.md                          # 이 파일
  backend/
    main.py
    cases/                            # B01~B10 (10개), 전부 ready_for_play=true
    cases_archive_v1/                 # 이전 11개 (F1-001-leejihyun, N01~N10) — 보관용
    checklist_reference.json          # 새 체계 (core 11 + emotion 5×2 + CF8 + PPI6)
    checklist_reference_v1_archive.json  # 이전 체계 — 보관용
    generate_synthetic_reports.py     # 합성 대화+레포트 자동 생성
    evaluate_transcript.py            # 기존 transcript 평가만 재실행
    reports/                          # 평가 레포트 DB
    requirements.txt
    .env.example
  frontend/
    index.html
```

### main.py 주요 함수 (이름으로 찾으면 됨)
- `ALL_CASES`, `PLAYABLE_CASE_IDS` — 케이스 DB (6개)
- `EMOTION_CATEGORIES` — `["부정","분노","협상","우울"]`, 세션 시작 시 여기서 랜덤 선택
- `pick_random_case()`, `pick_different_case(exclude_case_id)`
- `build_patient_system_prompt(case, difficulty, initial_emotion)` — initial_emotion이
  이제 함수 인자 (케이스 데이터의 `initial_emotion_variants[initial_emotion]`을 조회)
- `build_checklist_evaluator_prompt(case, checklist_ref, initial_emotion)`
- `build_ppi_evaluator_prompt(case, checklist_ref, initial_emotion)`
- `analyze_weaknesses(checklist_axis)` — E1-1~E3-1 코드 매핑 사용
- `build_recommendation(weakness, difficulty, current_case_id, current_emotion)` —
  감정을 직접 다르게 추천
- `call_openai(system_prompt, conversation_text, model)` — model 인자 필수, 호출부가
  `OPENAI_MODEL_CHAT`/`OPENAI_MODEL_EVAL` 중 명시적으로 골라서 넘김
- `save_report(...)` — transcript+평가축을 묶어서 `reports/`에 저장, report_id 반환
- 엔드포인트: `POST /api/session/start` (body: `{difficulty, case_id?, initial_emotion?}`),
  `POST /api/turn`, `POST /api/evaluate`(응답에 `report_id` 포함), `GET /api/cases`,
  `GET /api/reports`, `GET /api/reports/{id}`, `GET /api/health`
- `generate_synthetic_reports.py` — 별도 CLI 스크립트, main.py 함수 재사용해서 학습자+환자
  LLM 자동 대화 생성 (대화는 CHAT 모델, 평가는 EVAL 모델)
- `evaluate_transcript.py` — 별도 CLI 스크립트, 이미 가진 transcript JSON을 입력받아
  평가만 재실행 (역시 EVAL 모델 사용)

## 5. 테스트된 것 / 안 된 것

**테스트됨 (이 환경에서 직접 확인):**
- 6개 케이스 전부 로딩, JSON 무결성(스코프-레퍼런스 코드 일치)
- `/api/session/start` — 빈 history로 시작, 특정 case_id 강제 지정, 잘못된 case_id 404
- `analyze_weaknesses`/`build_recommendation` — 가짜 데이터로 단위테스트, 다른 감정의
  케이스가 실제로 추천됨을 확인 (분노 케이스 후 협상 케이스 추천됨)
- 프론트엔드 JS 문법

**테스트 안 됨 (사용자가 직접 확인 필요):**
- 실제 OpenAI 호출 전체 (`/api/turn`, `/api/evaluate`)
- **가장 중요**: "전환 금지 규칙"(부정→분노 등으로 안 바뀌는지)이 실제 대화에서 지켜지는지
- "차트 밖 깊은 질문 안 하기" 제약이 실제로 지켜지는지
- "수용 도달 시 스스로 마무리 제안" 엔드포인트 동작이 실제로 일어나는지
- 6개 케이스 각각의 감정 강도가 의도대로 "평소보다 격하게" 표현되는지

## 6. 다음에 할 일 / 확인이 필요한 것
1. **5번 케이스(최영아) 라벨 오타 정정을 원작성자에게 확인.**
2. **10개 케이스 × 4개 감정변형(총 40개)의 intensity_note/example_lines 내용이 적절한지
   검증** — 전부 제가 "환자만 아는 정보(걱정거리)"에서 추론해서 작성한 것이라(초기 6개의
   부정/분노 예시 2개만 사용자가 명시적으로 확인해준 것이었음), 의대생 원작성자 검토 권장.
3. 엔드포인트(4단계 완료) 감지를 백엔드 로직으로도 보강할지 검토.
4. 실제 대화로 전환금지/차트밖질문금지 규칙이 잘 지켜지는지 다회 테스트.
5. 이전 v1 시스템(11개 케이스, F1-F8)을 완전히 폐기할지, 별도 모드로 유지할지는 아직
   결정 안 됨 — 현재는 archive 폴더에 보관만 되어 있고 로드되지 않음.
6. **PPI 종합 레포트(3.11 참고) — 의대생이 만든 실제 PPI 프롬프트를 받아서 적용하는 작업이
   아직 시작 전.** 다음 대화에서 그 프롬프트 텍스트/파일을 받으면 바로 진행.
7. B10(다운증후군)의 "비지시적 상담" 요구사항을 정식 Critical Fail 코드로 추가할지 검토
   (현재는 텍스트 지침으로만 반영, CF1-8 중 정확히 맞는 코드가 없음).

## 7. 사용자(민서)의 작업 스타일
- 매우 꼼꼼하게 스코프 통제, 구체적 코드/데이터/화면 선호, 직접 로컬에서 FastAPI+브라우저로
  테스트, 비용에 민감(Anthropic→Gemini→OpenAI 이동), API 키 복사 실수가 잦았음.
- **이번 전환점에서 중요한 패턴**: 교수 피드백처럼 외부 평가자의 의견이 들어오면 기존 구조를
  과감히 재설계하는 것을 주저하지 않음 — 점진적 패치보다 구조적 재작업을 선호하는 경향.
- 노션에서 케이스 데이터를 받아오는 패턴이 반복됨(이번이 2번째) — 다음에도 노션 export
  zip이 올 가능성 있음. 압축 두 번 풀어야 함(`ExportBlock-...zip` 안에 또 zip).
