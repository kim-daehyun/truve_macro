# Truve 매크로 데이터 수집기

Truve 티켓팅 플로우를 자동으로 실행하면서, 매크로 탐지용 **BE / FE 학습 데이터**를 쌓기 위한 수집기입니다.

브라우저는 Playwright headed 모드로 실행되며, 실제로 브라우저 창이 열리고 로그인부터 공연 선택, 캡차, 대기열, 좌석 선택, 결제, Toss iframe 처리까지 화면에서 보입니다.

현재 버전의 핵심은 다음 두 가지입니다.

- `--behavior-type bot|human` 하나로 전체 행동 성향을 제어
- `seatmap` 단계에서 실제 `mousemove`와 클릭이 발생하도록 하여 FE raw data를 남김

## 현재 버전 요약

- 예전 `--scenario`, `--level` 중심 구조는 제거되었습니다.
- 지금은 `--behavior-type bot` 또는 `--behavior-type human`으로만 전체 흐름을 제어합니다.
- `bot`은 더 짧은 체류시간, 적은 탐색, 높은 teleport 성향을 목표로 합니다.
- `human`은 더 자연스러운 속도, 더 연속적인 마우스 이동, 더 긴 seatmap 체류를 목표로 합니다.
- 좌석 수는 `--seat-count-mode random`이면 매 run마다 1~4석 랜덤으로 선택됩니다.

## 설치

```bash
git clone https://github.com/HOHK0923/truve-5team-test-macro.git
cd truve-5team-test-macro
pip install -r requirements.txt
playwright install chromium
```

## 환경 설정

`.env.example`을 `.env`로 복사해 사용하시면 됩니다.

```bash
cp .env.example .env
```

예시:

```env
TRUVE_BASE_URL=https://front-nu-tawny.vercel.app
TRUVE_TEST_ACCOUNTS=[{"email":"your@email.com","password":"yourpass"}]
TRUVE_SHOW_ID=1
TRUVE_SCHEDULE_ID=1
```

또는 CLI에서 직접 계정을 넣을 수 있습니다.

```bash
python main.py --email your@email.com --password 'yourpass'
```

주의:

- `--password`는 프로세스 목록에 노출될 수 있으니 `.env` 사용을 권장합니다.

## 실행 예시

봇형 데이터 20회:

```bash
python main.py --behavior-type bot --behavior-runs 20 --email 'your_email' --password 'your_pw'
```

사람형 데이터 10회:

```bash
python main.py --behavior-type human --behavior-runs 10 --email 'your_email' --password 'your_pw'
```

좌석 수를 매 run마다 1~4 랜덤으로:

```bash
python main.py --behavior-type bot --behavior-runs 30 --seat-count-mode random
```

좌석 수를 고정 2매로:

```bash
python main.py --behavior-type human --behavior-runs 5 --seat-count-mode fixed --seat-count 2
```

무통장 결제 + 현금영수증 발급안함:

```bash
python main.py \
  --behavior-type bot \
  --behavior-runs 20 \
  --pay-method VIRTUAL_ACCOUNT \
  --bank 신한 \
  --cash-receipt 발급안함
```

카드 결제:

```bash
python main.py \
  --behavior-type human \
  --behavior-runs 5 \
  --pay-method CARD \
  --card-company 삼성
```

특정 회차 날짜/시간 지정:

```bash
python main.py \
  --behavior-type human \
  --behavior-runs 3 \
  --schedule-date 2026-04-15 \
  --schedule-time 19:00
```

태그 부여:

```bash
python main.py --behavior-type bot --behavior-runs 20 --tag batch-bot-001
```

## 행동 타입

### `bot`

- 목적: 명확한 봇형 FE/BE 패턴 생성
- 특징: 빠른 요청, 짧은 seatmap 체류, 적은 탐색, 높은 teleport 성향
- seatmap 체류시간 목표:
  - 1매: 약 `180~320ms`
  - 2매: 약 `250~420ms`
  - 3매: 약 `320~560ms`
  - 4매: 약 `420~800ms`

### `human`

- 목적: 실제 사용자에 가까운 자연스러운 FE/BE 패턴 생성
- 특징: 더 자연스러운 타이핑, 연속적인 마우스 이동, 더 긴 seatmap 체류
- seatmap 체류시간 목표:
  - 1매: 약 `1000~1850ms`
  - 2매: 약 `1500~2700ms`
  - 3매: 약 `2050~3600ms`
  - 4매: 약 `2700~4700ms`

행동 타입 비교표는 아래 명령으로 확인할 수 있습니다.

```bash
python main.py --info
```

## 주요 CLI 옵션

### 기본 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--behavior-type` | 행동 라벨 (`bot`, `human`) | `bot` |
| `--behavior-runs` | 행동 타입 기준 반복 횟수 | 없음 |
| `--runs` | 반복 횟수 (`--behavior-runs` 미지정 시 사용) | `1` |
| `--retry` | 실패 시 재시도 횟수 override | behavior 기본값 |
| `--tag` | 출력 데이터에 기록할 태그 | 없음 |
| `--url` | 대상 URL | `.env` 또는 기본 URL |
| `--show-id` | 공연 ID | `1` |
| `--schedule-id` | 회차 ID | `1` |
| `--email` | 로그인 이메일 | `.env` 값 |
| `--password` | 로그인 비밀번호 | `.env` 값 |
| `--output` | 출력 디렉토리 | `./output` |
| `--info` | 현재 행동 타입 비교표 출력 후 종료 | off |

### 예약자 정보

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--applicant-name` | 예약자 이름 | `테스트봇` |
| `--applicant-birth` | 생년월일 (`YYYYMMDD`) | `20000101` |
| `--applicant-phone` | 전화번호 | `01062971082` |

### 좌석 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--seat-grade` | `VIP`, `R`, `S`, `A`, `any` | `any` |
| `--seat-section` | 좌석 구역 문자열 | `any` |
| `--seat-count` | 고정 좌석 수 1~4 | `2` |
| `--seat-count-mode` | `random` 또는 `fixed` | `random` |

### 결제 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--pay-method` | `CARD`, `VIRTUAL_ACCOUNT` | `VIRTUAL_ACCOUNT` |
| `--card-company` | 카드사 | `삼성` |
| `--bank` | 무통장 입금 은행 | `신한` |
| `--cash-receipt` | `소득공제`, `지출증빙`, `발급안함` | `발급안함` |

### 회차 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--schedule-date` | `YYYY-MM-DD` 또는 `any` | `any` |
| `--schedule-time` | `HH:MM` 또는 `any` | `any` |

## 현재 자동화 플로우

```text
1. 로그인 확인
2. 공연 상세 페이지 이동
3. 날짜 / 회차 선택
4. 예매하기 + 캡차
5. 대기열 통과
6. seatmap 좌석 선택
7. 결제 페이지 진입
8. 예약자 정보 / 수령방법 / 결제수단 입력
9. Toss iframe 처리
10. 결과 저장
```

## 저장되는 데이터

현재 버전은 로컬 CSV/JSON 출력 기준으로 아래 데이터를 저장합니다.

### BE 쪽

- `req_intervals_ms`
- `req_interval_mean_ms`
- `req_interval_std_ms`
- `queue_poll_intervals_ms`
- `queue_poll_count`
- `retry_count`
- `retry_intervals_ms`
- `api_call_sequence`
- `seat_view_to_hold_ms`
- `seat_hold_attempts`
- `selected_seat_ids`
- `behavior_type`
- `is_bot`

### FE 쪽

- 브라우저 fingerprint
- 전체 `mouse_move_count`, `click_count`, `keystroke_count`
- seatmap stage raw telemetry
  - `seatmap_session_id`
  - `seatmap_user_id`
  - `seatmap_event_type`
  - `seatmap_page_enter_ts`
  - `seatmap_page_leave_ts`
  - `seatmap_duration_ms`
  - `seatmap_mousemove_events`
  - `seatmap_mousemove_count`
  - `seatmap_click_count`
  - `seatmap_viewport_width`
  - `seatmap_viewport_height`
  - `seatmap_mouse_activity_rate`
  - `seatmap_mouse_teleport_count`
  - `seatmap_mouse_teleport_rate`

## 출력 파일

실행이 끝나면 `--output` 디렉토리에 CSV/JSON 파일이 저장됩니다.

예시:

- `be_rawdata_YYYYMMDD_HHMMSS.csv`
- `fe_rawdata_YYYYMMDD_HHMMSS.csv`
- `request_log_YYYYMMDD_HHMMSS.json`

## 현재 버전에서 보는 포인트

- FE 모델:
  seatmap에서 실제 `mousemove`와 click이 발생하는지
- BE 모델:
  요청 간격이 너무 고정되지 않고, run마다 분산이 있는지
- bot / human 분리:
  `seatmap_duration_ms`, `seatmap_mouse_activity_rate`, `seatmap_mouse_teleport_rate` 차이가 충분한지

## 검증

문법 검증:

```bash
python3 -m py_compile browser_macro.py main.py config.py data_logger.py api_macro.py
```

## 커밋 예시

```bash
git status
git add README.md main.py browser_macro.py data_logger.py
git commit -m "Refresh README for behavior-type based macro flow"
git push origin main_daehyun
```
