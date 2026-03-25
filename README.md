# Telegram Pair

하나의 그룹 채팅 안에서 두 개의 로컬 코딩 CLI를 텔레그램 봇처럼 감싸 운영하는 로컬 우선 Telegram 오케스트레이션 레이어입니다.

## 현재 스캐폴드

이 단계에서는 프로젝트 뼈대와 타입이 있는 런타임/설정 기본 요소를 먼저 마련해, 이후 라우팅, 오케스트레이션, Telegram 런타임 구현이 안정적인 인터페이스 위에 올라가도록 구성합니다.

## 런타임 기준

- Python 3.10 이상
- aiogram 3.x
- 로컬 `claude`, `codex` CLI 설치 및 인증 완료

## 아키텍처 요약

- 하나의 Python 프로세스가 두 Telegram 봇 토큰을 함께 관리합니다.
- 하나의 공용 오케스트레이터가 메시지를 무시할지, 한 봇으로만 보낼지, 두 봇 모두에게 브로드캐스트할지 결정합니다.
- 기본 `context.md` 설정을 기준으로 채팅별 context 파일을 분리 저장합니다.
- `; message` 와 두 봇 동시 멘션은 두 봇을 병렬로 실행합니다.
- `; seq message` 와 `; seq: message` 는 priority 1 봇을 먼저 실행하고, 그 출력을 priority 2 봇 후속 입력에 주입합니다.
- `; team message` 와 `; team: message` 는 두 봇을 먼저 병렬 실행한 뒤 priority 2 봇이 최종 통합 답변을 생성합니다.

## 빠른 시작

1. 가상환경을 만들고 활성화합니다.
2. editable 모드로 패키지를 설치합니다.
   - `pip install -e .[dev]`
3. `.env.example`을 `telegram_pair/` 디렉터리의 `.env`로 복사합니다. 이 파일은 실행 시 자동으로 로드되며, 대신 셸에서 환경 변수를 직접 export해도 됩니다.
4. 실제 로컬 래퍼 경로가 다르다면 `CLAUDE_CLI_EXECUTABLE`, `CODEX_CLI_EXECUTABLE` 값을 맞게 지정합니다.
5. 추가 `codex exec` 옵션이 꼭 필요하지 않다면 `CODEX_CLI_ARGS`는 비워둡니다. 래퍼가 `exec`는 자동으로 붙입니다.
6. 그룹 채팅에서 일반 `; 메시지` 브로드캐스트를 쓰려면 두 Telegram 봇 모두 privacy mode를 꺼둡니다.

## 실제 유저 시나리오 예시

```text
user: ; 배포 후 로그인 실패가 간헐적으로 발생해. 원인 후보를 먼저 나눠서 봐줘
bot: [ClaudeCodeBot] 인증 토큰 만료 처리와 사용자 에러 메시지 노출이 서로 다르게 흘러가고 있을 가능성이 큽니다. 401 응답 시점, 재로그인 유도 여부, 세션 만료 로그를 같이 보는 게 좋습니다.
bot: [CodexPairBot] 클라이언트에서 refresh 요청이 겹치면서 이전 토큰으로 API를 한 번 더 치는 경쟁 상태일 수 있습니다. auth client의 refresh 중복 방지와 재시도 흐름부터 확인하는 게 가장 빠릅니다.
user: @CodexPairBot 바로 수정 들어갈 수 있게 최소 수정안만 적어줘
bot: [CodexPairBot] refresh를 single-flight로 묶는 안이 가장 작습니다. refresh promise를 공유하고, 실패하면 대기 요청을 정리하고, 성공 시 원래 요청을 한 번만 재시도하게 두면 됩니다.
user: @ClaudeCodeBot 이 수정안으로 갈 때 운영 리스크도 같이 말해줘
bot: [ClaudeCodeBot] refresh endpoint 장애 시 대기 중인 요청이 한꺼번에 실패할 수 있습니다. timeout, 강제 로그아웃 기준, refresh 시작과 실패 로그를 같이 두지 않으면 운영 중 추적이 어려워집니다.
```

## 두 봇이 서로 대화하는 예시

```text
user: ; 주문 취소 플로우를 다시 설계해야 해. 이번에는 서로 답을 이어받으면서 정리해줘
bot: [ClaudeCodeBot] 먼저 취소 가능 상태를 분리해야 합니다. 결제 대기 중 취소, 결제 완료 후 취소, 출고 시작 후 취소 불가를 나누지 않으면 사용자 안내와 환불 기준이 섞입니다.
bot: [CodexPairBot] ClaudeCodeBot가 나눈 상태 기준으로 구현하면 order state machine을 먼저 고정하는 게 맞습니다. 특히 결제 완료 후 취소는 refund job을 비동기로 보내고 주문 상태는 cancel_requested로 잠깐 유지하는 편이 안전합니다.
bot: [ClaudeCodeBot] 그 구조라면 운영 쪽에서는 cancel_requested가 오래 머무는 주문을 따로 추적해야 합니다. 환불 지연과 실제 취소 실패를 같은 화면에서 보지 않으면 CS 대응이 늦어질 수 있습니다.
bot: [CodexPairBot] 맞습니다. 그래서 refund job 결과를 주문 타임라인에 기록하고, 일정 시간 이상 cancel_requested면 alert를 보내는 보조 조건이 필요합니다. ClaudeCodeBot가 말한 운영 분리를 코드에서는 상태 전이 로그로 받치면 됩니다.
user: @ClaudeCodeBot 지금 CodexPairBot 안에서 사용자 문구만 더 다듬어줘
bot: [ClaudeCodeBot] 사용자에게는 "주문 취소 요청을 접수했고 환불 처리 상태를 확인 중입니다"처럼 즉시 성공과 최종 환불 완료를 분리해 보여주는 편이 안전합니다. 취소 불가 상태에서는 출고 진행 때문에 제한된다는 이유를 함께 주는 것이 좋습니다.
user: @CodexPairBot 방금 둘이 맞춘 안 기준으로 최소 구현 단계만 적어줘
bot: [CodexPairBot] 1. 주문 상태별 취소 가능 조건 고정. 2. cancel_requested 중간 상태 추가. 3. 환불 job과 결과 반영 로직 연결. 4. 상태 전이 로그 기록. 5. 장기 대기 주문 alert 추가.
```

## 트리거 예시

- `@ClaudeCodeBot hello`
- `@CodexPairBot hello`
- `; compare two approaches`
- `@ClaudeCodeBot @CodexPairBot compare two approaches`
- `; seq compare then critique two approaches`
- `; team compare two approaches`
- `; team: compare two approaches`

## 운영 메모

- 봇이 작성한 메시지는 다시 오케스트레이션을 트리거하면 안 됩니다.
- 병렬/팀 응답은 best-effort 방식입니다. 한 봇이 실패해도 다른 봇은 계속 응답해야 합니다.
- team 모드는 한 1차 응답이 실패해도 실패 노트를 포함해 최종 통합 단계를 계속 시도합니다.
- context는 채팅별 append-only 로그로 저장되며, 각 채팅은 자기 기록만 다시 주입받습니다.
- 기본 채팅별 경로는 `<context parent>/<context stem>/chat_<chat_id>.md` 입니다.
- 필요하면 `TELEGRAM_PAIR_CHAT_CONTEXT_PATH_TEMPLATE`로 채팅별 경로 규칙을 바꿀 수 있습니다.
- 세미콜론 브로드캐스트를 일반 그룹 메시지에서 동작시키려면 두 봇의 Telegram privacy mode를 비활성화해야 합니다.

## 실패 동작

- 실행 파일 누락, 타임아웃, 0이 아닌 CLI 종료 코드는 봇 단위로 명확한 실패 메시지로 드러나야 합니다.
- Telegram 전송 실패는 전체 프로세스를 죽이지 말고 로그로 남겨야 합니다.
- 중복으로 들어온 그룹 업데이트는 `(chat_id, message_id)` 기준으로 중복 제거해야 합니다.

## 환경 변수

전체 목록은 `.env.example`을 참고하면 됩니다. 중요한 항목은 아래와 같습니다.

- `TELEGRAM_TOKEN_CLAUDE`
- `TELEGRAM_TOKEN_CODEX`
- `CLAUDE_CLI_EXECUTABLE`
- `CODEX_CLI_EXECUTABLE`
- `TELEGRAM_PAIR_WORKSPACE_DIR`
- `TELEGRAM_PAIR_CONTEXT_PATH` (선택)
- `TELEGRAM_PAIR_CHAT_CONTEXT_PATH_TEMPLATE` (선택)
- `TELEGRAM_PAIR_TIMEOUT_SECONDS`
- `TELEGRAM_PAIR_MAX_CONTEXT_TURNS`
- `TELEGRAM_PAIR_DEDUP_TTL_SECONDS`

## 예정 디렉터리 구조

```text
telegram_pair/
├── pyproject.toml
├── README.md
├── .env.example
├── telegram_pair/
│   ├── __init__.py
│   ├── config.py
│   └── models.py
└── tests/
```

## 진행 UX

- 봇은 Claude/Codex 실행이 설정된 지연 시간(기본값: 10초)보다 길어질 때만 채팅방에 진행 중 안내 메시지를 보냅니다.
- 런타임 로그에는 라우팅 결정, CLI 시작/종료 시점, 실행 시간 정보가 함께 남습니다.
- `/start` 같은 Telegram 슬래시 명령은 무시하고, `/help` 와 `/model ...` 은 앱 제어 명령으로 처리합니다.

## TODO

### MVP

- [ ] Gemini CLI 연동 추가
- [ ] OpenCode CLI 연동 추가
- [ ] 2봇 고정 구조를 N봇 일반화 구조로 확장
- [ ] OpenClaw식 채팅별 CLI 세션 재사용 도입
- [ ] `codex` 우선 `resume` 경로와 세션 저장소(JSON or SQLite) 구현
- [ ] `/health` 명령으로 CLI 설치/인증/모델 상태 점검 지원
- [ ] `/status`, `/jobs` 명령으로 실행 중 작업 상태 조회 지원
- [ ] `/cancel`, `/cancel latest` 등 실행 취소 지원
- [x] 채팅별 context 분리 저장 지원
- [ ] short-term memory와 long-term memory를 분리해 관리하는 메모리 계층 추가

### Next

- [ ] 특정 봇 집합만 대상으로 실행하는 라우팅 문법 추가
- [ ] `; seq` 체인을 다단계 봇 파이프라인으로 확장
- [ ] `; team`에서 최종 통합 담당 봇을 지정할 수 있게 개선
- [ ] `.md` context를 transcript/fallback 역할로 축소하고, 정상 경로는 세션 resume 우선으로 전환
- [ ] `/session status|reset` 명령 추가
- [ ] `/rerun`, `/retry` 등 최근 작업 재실행 지원
- [ ] 장기 대화 자동 요약 및 context 압축 지원
- [ ] workspace별 context 분리 및 전환 지원
- [ ] 실행 로그 구조화 및 성능/실패율 관측 강화
- [ ] 대화/export 결과를 Markdown 등으로 저장하는 기능 추가

### Later

- [ ] 봇별 역할 프리셋(설계/구현/리뷰/요약) 지원
- [ ] consensus/diff 등 다중 봇 비교 결과 전용 모드 추가
- [ ] 안전 모드(read-only, patch-only 등) 지원

## 개발 가드레일

- `python -m telegram_pair.module_size_guard` 로 Python 모듈 크기를 점검할 수 있습니다.
- 400줄 이상은 경고, 500줄 초과는 실패입니다.
- editable 설치 환경에서는 `telegram-pair-module-size` 엔트리포인트도 사용할 수 있습니다.
- 사전 분리안은 `docs/module-boundaries.md` 를 참고하면 됩니다.

## Telegram에서 모델 제어

지원 명령:

- `/help`
- `/model status`
- `/model claude <model>`
- `/model codex <model>`
- `/model all <model>`
- `/model reset claude|codex|all`

## 구현 가이드

- OpenClaw식 세션 재사용 구현 가이드: [docs/openclaw-session-guide.md](/home/wy/workspace/telegram_pair/docs/openclaw-session-guide.md)
