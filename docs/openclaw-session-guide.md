# OpenClaw-Style Session Reuse Guide

이 문서는 `telegram_pair`를 현재의 "매 요청마다 새 CLI 프로세스 + markdown context restack" 방식에서, OpenClaw 계열처럼 "세션 식별자 저장 + resume 호출 우선" 구조로 확장하는 구현 가이드입니다.

## 목표

- 채팅별로 CLI 네이티브 세션을 재사용한다.
- 가능할 때는 `.md` context restack 대신 `resume`을 우선 사용한다.
- 네이티브 세션이 없거나 깨졌을 때는 현재 방식으로 안전하게 fallback 한다.
- `claude` / `codex` / 향후 다른 CLI를 공통 추상화로 다룬다.

## 현재 구조 요약

- [`telegram_pair/orchestrator.py`](/home/wy/workspace/telegram_pair/telegram_pair/orchestrator.py) 가 최근 context를 읽고 prompt를 조립한다.
- [`telegram_pair/context_manager.py`](/home/wy/workspace/telegram_pair/telegram_pair/context_manager.py) 가 채팅별 `.md` 로그를 source of truth로 관리한다.
- [`telegram_pair/cli_wrapper.py`](/home/wy/workspace/telegram_pair/telegram_pair/cli_wrapper.py) 는 매 요청마다 `create_subprocess_exec(...)` 로 CLI를 새로 띄운다.
- [`telegram_pair/models.py`](/home/wy/workspace/telegram_pair/telegram_pair/models.py) 의 `CliRequest` / `CliResult` 에는 세션 개념이 없다.

이 구조는 단순하고 안정적이지만, CLI가 제공하는 대화 연속성, tool state, resume 기능을 활용하지 못한다.

## 목표 아키텍처

핵심은 `.md` 로그를 버리는 것이 아니라 역할을 분리하는 것이다.

- 네이티브 세션 상태의 source of truth: CLI 세션 ID 저장소
- 사용자 가시성/감사 로그: 기존 markdown context
- fallback prompt 재구성: 기존 markdown context

즉 정상 경로는 `resume`, 복구 경로는 `.md` restack 으로 간다.

## 구현 단계

### 1. 세션 저장소 도입

새 파일 예시:

- `telegram_pair/session_store.py`

역할:

- `(chat_id, bot_name)` 기준 현재 세션 정보를 읽고 쓴다.
- 최소 필드:
  - `session_id`
  - `transport_kind` (`resume`, `none`)
  - `created_at`
  - `updated_at`
  - `last_message_id`
  - `last_model`
  - `broken` 여부

권장 저장 위치:

- `<workspace>/sessions/chat_<chat_id>/<bot_name>.json`

초기에는 JSON 파일이면 충분하다. SQLite는 동시성/조회 요구가 커질 때로 미뤄도 된다.

### 2. 모델 확장

[`telegram_pair/models.py`](/home/wy/workspace/telegram_pair/telegram_pair/models.py) 변경 항목:

- `CliRequest` 에 아래 필드를 추가
  - `session_id: str | None = None`
  - `resume: bool = False`
  - `capture_session_id: bool = False`
  - `supports_structured_output: bool = False`
- `CliResult` 에 아래 필드를 추가
  - `session_id: str | None = None`
  - `session_reused: bool = False`
  - `session_broken: bool = False`
  - `raw_payload: str = ""`

이 확장은 `orchestrator` 가 "새 세션 생성인지", "resume 시도인지", "실패 후 fallback 할지"를 판단하는 데 필요하다.

### 3. BotConfig에 세션 전략 추가

[`telegram_pair/config.py`](/home/wy/workspace/telegram_pair/telegram_pair/config.py) 의 `BotConfig` 에 CLI별 세션 전략을 넣는다.

권장 필드:

- `session_mode: str = "stateless"`
- `session_start_args: tuple[str, ...] = ()`
- `session_resume_args: tuple[str, ...] = ()`
- `session_output_format: str = "text"`

예시 방향:

- Codex:
  - 시작: `exec --skip-git-repo-check --json`
  - 재개: `exec resume <session_id> --json`
- Claude:
  - CLI가 공식 session/resume 인자를 제공하면 그 규약 사용
  - 없으면 `session_mode="stateless"` 로 유지

중요한 점은 "모든 봇이 동일한 resume 기능을 가진다"라고 가정하지 않는 것이다.

### 4. CLI 래퍼를 세션 인지형으로 재구성

[`telegram_pair/cli_wrapper.py`](/home/wy/workspace/telegram_pair/telegram_pair/cli_wrapper.py) 는 현재 단순 text output 전제다. OpenClaw식으로 가려면 `argv` 생성과 응답 파싱을 분리해야 한다.

권장 내부 함수:

- `_build_start_argv(request)`
- `_build_resume_argv(request)`
- `_build_stdin_payload(request)`
- `_parse_cli_result(request, stdout, stderr, exit_code)`
- `_extract_session_id(request, stdout, stderr)`

권장 동작:

1. `request.resume=True` 이고 `session_id` 가 있으면 resume argv 생성
2. resume 성공 시 `CliResult.session_reused=True`
3. resume 실패가 "세션 없음/만료/손상" 류면 `session_broken=True` 로 표시
4. 상위 레이어가 새 세션 시작으로 fallback

여기서 핵심은 CLI별 파서를 둘 수 있게 만드는 것이다. 한 함수에서 `codex`, `claude`, 향후 `gemini` 까지 분기하는 구조는 빠르게 비대해진다.

권장 리팩터링:

- `telegram_pair/cli_backends/`
  - `base.py`
  - `codex_backend.py`
  - `claude_backend.py`

이 구조로 가면 OpenClaw의 backend descriptor 개념과 비슷한 확장성이 생긴다.

### 5. Orchestrator에 resume-first 정책 추가

[`telegram_pair/orchestrator.py`](/home/wy/workspace/telegram_pair/telegram_pair/orchestrator.py) 에서 `_run_bot(...)` 직전에 세션 저장소를 조회한다.

권장 흐름:

1. `(chat_id, bot.name)` 에 대한 기존 세션 조회
2. 세션이 있으면 `resume=True` 로 실행
3. 성공하면 세션 `updated_at` 갱신
4. resume 실패가 세션 손상 계열이면 저장소에서 `broken=True` 처리
5. 같은 요청을 새 세션 시작 방식으로 1회 재시도
6. 새 응답에서 session id 를 얻었으면 저장
7. 두 경로 모두 실패하면 기존 오류 응답 노출

주의:

- `; seq`, `; team` 에서도 세션은 "채팅 + 봇" 단위로 분리한다.
- 이전 봇 출력을 다음 봇에 주입하는 broadcast/team 프롬프트는 그대로 유지해도 된다.
- 다만 동일 채팅에서 두 봇이 병렬 실행되므로 세션 저장소 갱신은 원자적이어야 한다.

### 6. ContextManager 역할 축소

[`telegram_pair/context_manager.py`](/home/wy/workspace/telegram_pair/telegram_pair/context_manager.py) 는 삭제 대상이 아니다. 역할을 아래로 축소한다.

- Telegram transcript 보존
- resume 불가 시 fallback prompt 재구성
- 요약/내보내기/감사 추적

권장 변경:

- 세션이 살아 있을 때는 `load_recent_context_text(...)` 를 전체 길이로 항상 넣지 않는다.
- 대신 신규 세션 시작 시에만 최근 `N`턴을 prompt 에 넣는다.
- 옵션으로 `TELEGRAM_PAIR_FORCE_CONTEXT_RESTACK=true` 를 두면 디버깅이 쉬워진다.

이렇게 해야 네이티브 세션 재사용의 토큰 절감 효과가 생긴다.

### 7. 세션 무효화 명령 추가

사용자 제어가 필요하다.

권장 명령:

- `/session status`
- `/session reset claude`
- `/session reset codex`
- `/session reset all`

이 명령은 특정 채팅의 세션만 지워야 한다. 전역 초기화로 가면 그룹 간 격리가 깨진다.

### 8. 테스트 추가

추가가 필요한 테스트:

- [`tests/test_cli_wrapper.py`](/home/wy/workspace/telegram_pair/tests/test_cli_wrapper.py)
  - resume argv 생성
  - session id 파싱
  - resume 실패 후 fallback 플래그
- `tests/test_session_store.py`
  - 저장/조회/손상 처리
- [`tests/test_orchestrator.py`](/home/wy/workspace/telegram_pair/tests/test_orchestrator.py)
  - 기존 세션이 있을 때 resume 우선 실행
  - resume 실패 시 새 세션 생성으로 1회 재시도
  - 새 session id 저장
- 통합 테스트
  - 채팅 A/B 가 서로 다른 세션을 유지하는지 검증

## 권장 구현 순서

1. `session_store.py` 와 관련 모델 추가
2. `CliRequest` / `CliResult` 확장
3. `cli_wrapper.py` 에서 Codex 한정 session capture/resume 구현
4. `orchestrator.py` 에 resume-first + fallback 연결
5. `/session ...` 명령 추가
6. Claude 등 다른 backend 확장

이 순서가 좋은 이유는 Codex부터 end-to-end 수직 슬라이스를 먼저 완성할 수 있기 때문이다.

## Codex 우선 구현안

현재 코드에서 가장 현실적인 1차 목표는 "Codex만 OpenClaw식 세션 재사용"이다.

이유:

- 현재도 [`telegram_pair/cli_wrapper.py`](/home/wy/workspace/telegram_pair/telegram_pair/cli_wrapper.py) 에 Codex 전용 분기가 이미 있다.
- Codex는 시작 커맨드와 prompt 전달 방식이 다른 CLI보다 더 명확하게 구분돼 있다.
- 기존 `codex exec ... <prompt>` 호출부를 세션-aware 로 바꾸기가 쉽다.

권장 1차 범위:

- `CodexPairBot` 만 `session_mode="resume"`
- `ClaudeCodeBot` 는 기존 stateless 유지
- README/USAGE 에 "Codex만 세션 재사용, Claude는 추후 확장" 명시

## 실패 처리 원칙

- resume 실패가 곧 사용자 오류는 아니다.
- 세션 손상은 내부적으로 표시하고, 새 세션 생성 재시도를 먼저 한다.
- 새 세션 생성도 실패했을 때만 Telegram에 실패 메시지를 보낸다.
- `.md` transcript 저장은 성공/실패와 무관하게 유지하되, 세션 관련 메타는 별도 JSON 저장소에 둔다.

## 현재 방식 대비 장단점

장점:

- 대화 연속성 품질 개선
- 긴 대화에서 토큰/지연 감소
- CLI의 네이티브 tool state 활용 가능
- OpenClaw류 시스템과 더 비슷한 운영 모델 확보

단점:

- CLI별 backend 차이를 흡수해야 한다.
- 세션 만료/손상/모델 변경 시 복구 로직이 필요하다.
- 단순 markdown stack보다 디버깅 경로가 하나 더 생긴다.

## 최소 완료 기준

아래가 되면 1차 구현 완료로 볼 수 있다.

- Codex 채팅별 세션이 파일로 저장된다.
- 동일 채팅의 후속 요청은 resume 를 먼저 시도한다.
- resume 실패 시 새 세션 생성으로 자동 fallback 한다.
- 다른 채팅의 Codex 세션과 섞이지 않는다.
- 기존 `.md` transcript 흐름은 유지된다.
