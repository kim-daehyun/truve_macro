# Truve 매크로 데이터 수집기

Truve 티켓팅 플로우를 자동으로 실행하면서, **봇 탐지 모델 학습용 BE / FE raw data**를 수집하는 Playwright 기반 매크로입니다.

브라우저는 headed 모드로 실행되며, 실제로 브라우저 창이 열리고 로그인부터 공연 선택, 캡차, 대기열, 좌석 선택, 결제, Toss 처리까지 화면에서 동작이 보입니다.

## 프로젝트 목적

이 프로젝트의 목적은 단순 자동 예매가 아니라, 다음 두 가지 유형의 학습 데이터를 만드는 것입니다.

- BE 데이터: 요청 간격, queue polling, 좌석 선점 시점, 결제 단계 이동 속도 등
- FE 데이터: seatmap 단계의 mousemove, click, 체류시간, teleport 성향 등

즉, `bot`과 `human` 두 행동 타입을 의도적으로 다르게 생성해 **탐지 모델이 구분할 수 있는 분포 차이**를 만드는 것이 핵심입니다.

## 현재 버전 핵심 요약

- `--behavior-type bot|human`으로 전체 행동 성향을 제어합니다.
- 현재 버전은 **매 run마다 항상 1매만 예매**합니다.
- `seatmap` 단계에서는 실제 `mousemove`와 클릭이 발생하도록 구현되어 있습니다.
- `human`은 좌석 선점 전까지 비교적 규칙적으로 움직이고, 좌석 선점 후 결제 단계에서 더 불규칙하게 동작합니다.
- `bot`은 좌석 선점 전/후 모두 비교적 규칙적인 리듬을 유지합니다.

## 실행 환경

- Python 3.10+
- Playwright
- Chromium

설치:

```bash
git clone https://github.com/HOHK0923/truve-5team-test-macro.git
cd truve-5team-test-macro
pip install -r requirements.txt
playwright install chromium
```

## 환경 설정

`.env.example`을 복사해 `.env`로 사용하시면 됩니다.

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

주의:

- `--password`는 프로세스 목록에 노출될 수 있으므로 가능하면 `.env` 사용을 권장합니다.
- 현재 코드 기본 URL은 [config.py](/Users/daehyun/truve-5team-test-macro/config.py) 기준 `https://front-nu-tawny.vercel.app` 입니다.

## 실행 예시

봇형 데이터 20회:

```bash
python main.py --behavior-type bot --behavior-runs 20 --email 'your_email' --password 'your_pw'
```

사람형 데이터 10회:

```bash
python main.py --behavior-type human --behavior-runs 10 --email 'your_email' --password 'your_pw'
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

행동 타입 비교표만 출력:

```bash
python main.py --info
```

## 행동 타입 설계

### `bot`

- 목적: 명확한 봇형 패턴 생성
- 특징: 빠른 요청, 짧은 seatmap 체류, 적은 탐색, 높은 teleport 성향
- seatmap에서 실제 mousemove는 발생하지만, 사람보다 경로가 짧고 목적성이 강합니다.

### `human`

- 목적: 실제 사용자에 가까운 패턴 생성
- 특징: 더 자연스러운 마우스 이동, 더 긴 seatmap 체류, 좌석 선점 후 결제 단계의 불규칙성 확대
- seatmap에서 mousemove 수와 탐색량이 더 많고, 결제 단계에서는 확인 pause가 더 들어갑니다.

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
9. Toss 처리
10. 결과 저장
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
| `--info` | 행동 타입 비교표 출력 후 종료 | off |

### 예약자 정보 옵션

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
| `--seat-count` | 현재 버전은 1매 고정 | `1` |
| `--seat-count-mode` | 현재 버전은 항상 1매로 동작 | `random` |

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

## 저장되는 데이터

실행이 끝나면 `--output` 디렉토리에 아래 파일이 저장됩니다.

- `be_rawdata_YYYYMMDD_HHMMSS.csv`
- `fe_rawdata_YYYYMMDD_HHMMSS.csv`
- `combined_rawdata_YYYYMMDD_HHMMSS.json`

### BE 레코드 예시 항목

- `run_id`
- `behavior_type`
- `is_bot`
- `req_intervals_ms`
- `req_interval_mean_ms`
- `req_interval_std_ms`
- `req_interval_cv`
- `queue_poll_intervals_ms`
- `queue_poll_count`
- `total_flow_duration_ms`
- `seat_view_to_hold_ms`
- `seat_hold_attempts`
- `selected_seat_ids`
- `api_call_sequence`

### FE 레코드 예시 항목

- `run_id`
- `behavior_type`
- `is_bot`
- `webdriver_detected`
- `mouse_move_count`
- `click_count`
- `keystroke_count`
- `seatmap_session_id`
- `seatmap_user_id`
- `seatmap_event_type`
- `seatmap_page_enter_ts`
- `seatmap_page_leave_ts`
- `seatmap_duration_ms`
- `seatmap_mousemove_events`
- `seatmap_mousemove_count`
- `seatmap_click_count`
- `seatmap_mouse_activity_rate`
- `seatmap_mouse_teleport_count`
- `seatmap_mouse_teleport_rate`

## 핵심 포인트

- 이 매크로는 단순 예매 자동화가 아니라 **탐지 모델 학습용 데이터 생성기**입니다.
- 핵심 차별점은 `bot/human` 행동 분포를 의도적으로 다르게 설계했다는 점입니다.
- FE 측면에서는 seatmap의 실제 `mousemove`와 클릭이 쌓이도록 구현되어 있습니다.
- BE 측면에서는 요청 간격, queue polling, 좌석 선점/결제 시점 차이를 기록할 수 있습니다.
- 현재 버전은 데이터 품질과 반복 실행 안정성을 위해 **1매 고정**으로 운용합니다.
