# Module boundary proposal

이 문서는 `.py` 모듈 500줄 가이드를 넘지 않도록 하기 위한 선제 분리안이다.

## 우선 관찰 대상

- `telegram_pair/orchestrator.py` (~378줄)
- `telegram_pair/telegram_app.py` (~355줄)

둘 다 아직 제한을 넘지는 않았지만, 다음 기능 추가 시 400줄 경고 구간에 더 깊게 들어갈 가능성이 높다.

## 1) `telegram_pair/orchestrator.py` 분리안

현재 책임 후보:
- 메시지 라우팅 결과 해석
- 단일/브로드캐스트 실행 순서 제어
- 컨텍스트 조립
- 실패 메시지 및 후속 프롬프트 주입

권장 분리 방향:

### A. `telegram_pair/orchestration/context_builder.py`
- 최근 대화/context.md 로드
- bot1 출력 주입 텍스트 생성
- broadcast 2차 호출용 입력 조립

### B. `telegram_pair/orchestration/execution.py`
- 단일 bot 실행
- broadcast 순차 실행
- 실패를 후속 단계용 note로 변환

### C. `telegram_pair/orchestration/formatters.py`
- 사용자 노출용 상태/실패 메시지 포맷
- 로그용 route/result 요약 문자열

### D. `telegram_pair/orchestrator.py`
- 얇은 facade 유지
- 외부 API와 의존성 wiring만 담당

## 2) `telegram_pair/telegram_app.py` 분리안

현재 책임 후보:
- Telegram runtime 객체
- update dedup
- update → inbound model 변환
- reply 송신
- progress notice 관리
- slash command 처리

권장 분리 방향:

### A. `telegram_pair/telegram/updates.py`
- Telegram message/update 파싱
- inbound message 변환
- bot-authored message 필터링

### B. `telegram_pair/telegram/dedup.py`
- `DedupCache` 보관
- TTL 기반 중복 제거 로직

### C. `telegram_pair/telegram/sender.py`
- reply 전송
- send 실패 로깅/예외 경계
- progress notice 송신/정리

### D. `telegram_pair/telegram/commands.py`
- `/model ...` 명령 파싱
- 일반 slash command ignore 판정

### E. `telegram_pair/telegram_app.py`
- aiogram/runtime wiring
- registry 구성과 고수준 orchestration만 담당

## 분리 기준

아래 중 2개 이상 충족 시 실제 분리를 우선 고려한다.

- 파일이 400줄 이상 도달
- private helper 함수가 빠르게 증가
- Telegram/CLI/도메인 로직이 한 파일에 혼재
- 테스트 파일 하나가 지나치게 많은 fixture와 시나리오를 포함

## 실행 순서 제안

1. 순수 함수부터 분리 (`formatters`, `commands`, `context_builder`)
2. 상태 보유 객체 분리 (`DedupCache`, progress helper)
3. 마지막으로 facade 파일을 얇게 정리

이 순서를 따르면 공개 API 변경 없이 점진적 리팩터링이 쉽다.
