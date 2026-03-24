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
- 하나의 공용 `context.md` 파일이 로컬 파일시스템에 대화 기록을 저장합니다.
- 브로드캐스트 모드에서는 우선순위 1번 봇을 먼저 실행하고, 그 출력을 2번 봇 입력에 주입합니다.

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
user: ; 새 결제 플로우에서 실패 복구 전략을 먼저 정리해줘. 서로 이어서 보완해봐
bot: [ClaudeCodeBot] 우선 결제 승인 실패, 승인 성공 후 후처리 실패, 중복 결제 요청을 분리해서 봐야 합니다. 각 경우마다 사용자에게 보일 문구와 롤백 기준이 달라집니다.
bot: [CodexPairBot] ClaudeCodeBot가 나눈 세 가지 축에 동의합니다. 구현은 idempotency key를 모든 결제 시작 요청에 강제하고, 후처리 실패는 재시도 작업 큐로 넘겨 결제 승인 상태와 분리하는 쪽이 안전합니다.
bot: [ClaudeCodeBot] 그러면 운영 기준은 더 선명해집니다. 승인 완료인데 후처리만 실패한 건 환불보다 복구 작업 우선으로 두고, 중복 요청은 같은 key면 기존 결과를 재사용하도록 명시하면 됩니다.
bot: [CodexPairBot] 코드 레벨에서는 payment service에 request key 저장소와 recovery worker를 두 축으로 추가하면 됩니다. 사용자 응답은 즉시 실패/성공만 내리고, 복구 진행 여부는 내부 이벤트와 로그로 추적하는 구조가 가장 단순합니다.
user: @CodexPairBot 방금 정리한 구조 기준으로 최소 구현 순서만 적어줘
bot: [CodexPairBot] 1. 결제 요청에 idempotency key 강제. 2. 승인 결과 저장과 후처리 상태 분리. 3. 후처리 실패 재시도 워커 추가. 4. 중복 key 재요청 시 저장된 결과 반환. 5. 실패 로그와 운영 알림 연결.
```

## 트리거 예시

- `@ClaudeCodeBot hello`
- `@CodexPairBot hello`
- `; compare two approaches`
- `@ClaudeCodeBot @CodexPairBot propose then refine`

## 운영 메모

- 봇이 작성한 메시지는 다시 오케스트레이션을 트리거하면 안 됩니다.
- 브로드캐스트 응답은 best-effort 방식입니다. 1번 봇이 실패해도, 2번 봇은 실패 안내를 주입받은 상태로 계속 실행돼야 합니다.
- `context.md`는 일반 동작 기준으로 공용 append-only 로그처럼 사용됩니다.
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
- `/start` 같은 Telegram 슬래시 명령은 무시하고, `/model ...`은 앱 제어 명령으로 처리합니다.

## Telegram에서 모델 제어

지원 명령:

- `/model status`
- `/model claude <model>`
- `/model codex <model>`
- `/model all <model>`
- `/model reset claude|codex|all`
