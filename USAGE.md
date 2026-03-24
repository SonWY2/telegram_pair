# USAGE

`telegram_pair`는 로컬에 설치된 `claude` / `codex` CLI를 텔레그램 그룹 채팅에서 사용할 수 있게 래핑한 프로그램입니다.

## 1. 전제 조건

다음이 준비되어 있어야 합니다.

- Python **3.10+**
- `claude` CLI 설치 및 인증 완료
- `codex` CLI 설치 및 인증 완료
- 텔레그램 봇 2개 생성
- 두 봇 모두 같은 그룹 채팅에 초대됨
- `; 메시지` 브로드캐스트를 쓰려면 **두 봇의 privacy mode를 꺼야 함**

## 2. 설치

프로젝트 루트에서:

```bash
cd telegram_pair
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## 3. 환경 변수 설정

예제 파일:

```bash
cp .env.example .env
```

이 프로그램은 **현재 작업 디렉터리의 `.env`를 자동으로 읽습니다.**
다만, 쉘에 이미 export된 환경변수가 있으면 그 값이 우선합니다.

자동 로드를 쓰지 않고 직접 export해도 됩니다:

```bash
export TELEGRAM_TOKEN_CLAUDE='...'
export TELEGRAM_TOKEN_CODEX='...'
export CLAUDE_CLI_EXECUTABLE='claude'
export CODEX_CLI_EXECUTABLE='codex'
```

## 4. 주요 환경 변수

기본값은 `.env.example` 기준입니다.

### 필수

- `TELEGRAM_TOKEN_CLAUDE`
- `TELEGRAM_TOKEN_CODEX`
- `CLAUDE_CLI_EXECUTABLE`
- `CODEX_CLI_EXECUTABLE`

### 선택

- `CLAUDE_BOT_NAME` — 기본값: `ClaudeCodeBot`
- `CODEX_BOT_NAME` — 기본값: `CodexPairBot`
- `CLAUDE_CLI_ARGS` — 기본값: `-p`
- `CODEX_CLI_ARGS` — 기본값: 빈 값 (wrapper가 `codex exec`를 자동 사용)
- `CLAUDE_MENTION_ALIASES` — 예: `@ClaudeCodeBot`
- `CLAUDE_MODEL` — 시작 시 Claude 기본 모델 override (선택)
- `CODEX_MENTION_ALIASES` — 예: `@CodexPairBot`
- `CODEX_MODEL` — 시작 시 Codex 기본 모델 override (선택)
- `TELEGRAM_PAIR_WORKSPACE_DIR` — 기본값: `./runtime`
- `TELEGRAM_PAIR_CONTEXT_PATH` — 기본값: `<workspace>/context.md`
- `TELEGRAM_PAIR_TIMEOUT_SECONDS` — 기본값: `180`
- `TELEGRAM_PAIR_MAX_CONTEXT_TURNS` — 기본값: `12`
- `TELEGRAM_PAIR_DEDUP_TTL_SECONDS` — 기본값: `300`
- `TELEGRAM_PAIR_PROGRESS_NOTICE_DELAY_SECONDS` — 기본값: `10` (이 시간 이상 걸릴 때만 진행 메시지 전송)
- `TELEGRAM_PAIR_TARGET_CHAT_ID` — 특정 그룹/채팅만 처리하고 싶을 때 사용
- `TELEGRAM_PAIR_LOG_LEVEL` — 기본값: `INFO`

## 5. 실행 전 점검

### 5.1 CLI 경로 확인

```bash
which claude
which codex
```

CLI 이름이 다르면 `.env`에서 다음 값을 바꾸세요.

```bash
CLAUDE_CLI_EXECUTABLE=/actual/path/to/claude
CODEX_CLI_EXECUTABLE=/actual/path/to/codex
```

### 5.2 privacy mode

텔레그램 그룹에서 `; 메시지`를 일반 메시지로 쓰려면 두 봇 모두 privacy mode를 꺼야 합니다.

### 5.4 Codex 인자 주의

`codex`는 기본 진입이 대화형 CLI입니다.
이 프로젝트는 내부적으로 `codex exec` 형태로 실행하므로 보통 아래처럼 두는 것이 맞습니다.

```bash
CODEX_CLI_EXECUTABLE=codex
CODEX_CLI_ARGS=
```

`CODEX_CLI_ARGS=-p` 는 잘못된 설정입니다.
Codex에서 `-p`는 print가 아니라 `--profile` 이므로, 값 없이 넣으면 실행 오류가 납니다.

### 5.3 대상 채팅 제한이 필요한 경우

한 그룹에서만 동작하게 하려면:

```bash
export TELEGRAM_PAIR_TARGET_CHAT_ID=-1001234567890
```

## 6. 실행

```bash
cd telegram_pair
source .venv/bin/activate
python -m telegram_pair.main
```

프로그램이 시작되면:

- workspace 디렉토리를 생성하고
- `context.md` 경로를 준비하고
- 두 Telegram Bot polling loop를 동시에 실행합니다
- 각 메시지는 단일 Orchestrator를 거쳐 처리됩니다

## 7. 메시지 사용 규칙

### 7.1 단일 응답

Claude만 호출:

```text
@ClaudeCodeBot 이 함수 리팩터링해줘
```

Codex만 호출:

```text
@CodexPairBot 이 테스트 실패 원인 찾아줘
```

### 7.2 브로드캐스트

두 봇 순차 호출:

```text
; 이 구현의 구조를 먼저 제안하고 그 다음 개선안까지 내줘
```

또는 dual mention:

```text
@ClaudeCodeBot @CodexPairBot 먼저 설계하고 그 다음 비판적으로 보완해줘
```

## 7.3 진행 상태 알림

요청이 실제 작업으로 들어간 뒤, 기본적으로 **10초 이상** 계속 실행 중일 때만 봇이 진행 메시지를 보냅니다.

예:

```text
⏳ ClaudeCodeBot 작업을 시작합니다...
```

브로드캐스트면 Codex 차례에서 추가로:

```text
⏳ CodexPairBot 작업을 시작합니다... (이전 봇 응답 반영)
```

짧게 끝나는 작업은 이 진행 메시지가 생략됩니다. 지연값은 `TELEGRAM_PAIR_PROGRESS_NOTICE_DELAY_SECONDS`로 조절할 수 있습니다.

터미널 로그에도 route / CLI 시작 / CLI 종료 / 소요시간이 기록됩니다.

## 7.4 Telegram 제어 명령

일반 Telegram 명령은 무시됩니다.

예:
- `/start`
- `/help`
- `/start@botname`

하지만 아래 앱 제어 명령은 처리됩니다:

```text
/model status
/model claude sonnet
/model codex gpt-5.4
/model all gpt-5.4
/model reset claude
```

`/model` 명령은 현재 프로세스용 모델 override를 바꾸고, workspace 아래 `bot_models.json`에 저장됩니다.

## 8. 실제 동작 방식

브로드캐스트 시 실행 순서:

1. priority 1 봇 실행
2. priority 1 응답을 텔레그램으로 전송
3. priority 1 응답을 메모리에 보관
4. priority 2 봇 실행 시 다음 컨텍스트를 함께 주입
   - 원본 사용자 메시지
   - 최근 `context.md`
   - priority 1 출력 또는 실패 노트
5. priority 2 응답을 텔레그램으로 전송

## 9. 무시되는 메시지

다음은 처리되지 않습니다.

- 봇이 보낸 메시지
- 텍스트/캡션이 없는 업데이트
- 트리거가 없는 일반 메시지
- Telegram 슬래시 명령(`/start`, `/help`, `/start@bot`)
- mention 제거 후 빈 문자열이 되는 메시지
- `TELEGRAM_PAIR_TARGET_CHAT_ID`와 다른 채팅에서 온 메시지

## 10. context.md

기본적으로 대화 기록은 아래에 저장됩니다.

```text
<workspace>/context.md
```

예: `.env.example` 기본값이면:

```text
telegram_pair/runtime/context.md
```

저장 내용:

- human turn
- bot turn
- chat_id / message_id 메타데이터
- UTC timestamp

CLI 호출 시 최근 `N`개 turn만 컨텍스트로 재주입됩니다.
`N`은 `TELEGRAM_PAIR_MAX_CONTEXT_TURNS`로 조절합니다.

## 11. 중복 처리 방지

같은 그룹 메시지가 두 봇 polling 경로로 동시에 들어와도 `(chat_id, message_id)` 기준으로 dedup 됩니다.

즉:

- 같은 human 메시지 → 실제 처리 1회
- 답장은 필요 봇 수만큼만 전송

TTL은 `TELEGRAM_PAIR_DEDUP_TTL_SECONDS`로 조절합니다.

## 12. 로그

로그 레벨 설정:

```bash
export TELEGRAM_PAIR_LOG_LEVEL=DEBUG
```

실행 시 표준 출력으로 로깅됩니다.

## 13. 테스트

전체 테스트:

```bash
cd telegram_pair
python -m pytest tests -q
```

컴파일 확인:

```bash
cd telegram_pair
python -m compileall telegram_pair
```

현재 검증 기준 예시:

- router 규칙
- prompt 조립
- CLI timeout / non-zero exit
- context manager 저장/로드
- orchestrator p1 → p2 주입
- telegram dedup
- runtime integration

## 14. 자주 겪는 문제

### 14.1 `CLI executable ... was not found`

원인:
- `claude` 또는 `codex` 실행 파일 경로가 다름

해결:

```bash
which claude
which codex
```

찾은 경로를 `.env`에 반영하세요.

### 14.2 `.env`를 만들었는데도 값이 반영되지 않는 것 같음

원인 후보:
- 현재 디렉터리가 `telegram_pair/`가 아님
- 쉘에 이미 같은 이름의 환경변수가 export되어 있어서 `.env` 값이 덮어쓰이지 않음

해결:

```bash
cd telegram_pair
python -m telegram_pair.main
```

또는 현재 셸 환경변수를 먼저 확인하세요.

### 14.3 `; 메시지`가 반응하지 않음

원인 후보:
- Telegram privacy mode가 켜져 있음
- `TELEGRAM_PAIR_TARGET_CHAT_ID`가 다른 채팅으로 제한되어 있음

### 14.4 봇 하나만 답하거나 에러 메시지가 뜸

원인 후보:
- 해당 CLI 인증 만료
- timeout
- 잘못된 CLI 인자(특히 `CODEX_CLI_ARGS=-p`)
- non-zero exit

이 경우 텔레그램에는 bot-scoped 에러 메시지가 표시됩니다.

### 14.5 응답이 길어서 잘리는 것 같음

프로그램은 Telegram 메시지 길이 제한(4096자)에 맞춰 자동 분할 전송합니다.

## 15. 운영 팁

- 처음에는 테스트용 그룹에서만 실행하세요.
- `TELEGRAM_PAIR_TARGET_CHAT_ID`를 설정하면 실수로 다른 채팅을 처리하지 않습니다.
- `runtime/context.md`를 주기적으로 백업하면 대화 흐름을 추적하기 쉽습니다.
- Claude는 보통 `CLAUDE_CLI_ARGS=-p`를 사용합니다.
- Claude 응답에 `bkit Feature Usage` 라인이 나오면 그 줄부터 뒤는 자동으로 잘라냅니다.
- Codex는 보통 `CODEX_CLI_ARGS=`(빈 값)으로 두고 wrapper가 `codex exec`를 자동 호출하게 두는 편이 안전합니다.

## 16. 최소 실행 예시

```bash
cd telegram_pair
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# .env 수정
python -m telegram_pair.main
```

이후 텔레그램 그룹에서:

```text
; 간단한 파이썬 CLI 설계해줘
```

## 17. 종료

실행 중인 프로세스를 종료하려면 일반적으로 `Ctrl+C`를 사용하면 됩니다.
