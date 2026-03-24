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

예를 들어, 로그인 오류 대응 방향을 같은 Telegram 그룹에서 빠르게 비교하는 흐름은 아래처럼 보일 수 있습니다.

```text
user: ; 로그인 오류가 간헐적으로 나는데, 재현 원인과 수정 방향을 각각 제안해줘
bot: [ClaudeCodeBot] 세션 만료 처리와 프론트엔드 에러 표시가 분리돼 있을 가능성이 큽니다. 우선 인증 만료 로그와 401 응답 시점을 같이 확인해보세요.
bot: [CodexPairBot] Claude 답변 기준으로 보면, 백엔드 401 자체보다 클라이언트의 토큰 갱신 경쟁 상태일 수도 있습니다. refresh 요청 중복 여부와 retry 로직을 같이 점검하는 편이 낫습니다.
user: @CodexPairBot 그럼 지금 바로 테스트 코드까지 붙일 수 있는 수정안만 추려줘
bot: [CodexPairBot] auth client의 refresh 단일화부터 가는 안이 가장 빠릅니다. 이 경우 단위 테스트는 중복 refresh 호출 방지와 만료 직후 재시도 성공 케이스 두 개를 먼저 추가하면 됩니다.
user: @ClaudeCodeBot 방금 안의 리스크도 짚어줘
bot: [ClaudeCodeBot] refresh 단일화는 효과적이지만, 실패 시 전체 요청이 대기열에 묶일 수 있습니다. 타임아웃과 refresh 실패 후 강제 로그아웃 기준을 함께 정해야 안전합니다.
```

이런 식으로 한 그룹에서 브로드캐스트 질문과 개별 멘션 후속 질문을 섞어 쓰면, 초안과 보완 의견을 같은 맥락에서 이어서 볼 수 있습니다.

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
