"""
Truve 매크로 데이터 수집기 - 메인 실행

보안 기준:
  - Rule 1: 모든 CLI 입력값 서버단 검증 (레벨, URL, 횟수 등)
  - Rule 2: 크리덴셜 CLI 평문 전달 최소화, 환경변수 우선
  - Rule 4: 콘솔 로그에 이메일/비밀번호 마스킹, traceback 내부경로 비노출
  - Rule 0: 예외 시 안전한 fallback

사용법:
  # 봇형 데이터 5회 실행
  python main.py --behavior-type bot --behavior-runs 5

  # 사람형 데이터 2회 실행
  python main.py --behavior-type human --behavior-runs 2

  # 레벨 비교표만 출력
  python main.py --info

  # 크리덴셜은 .env 파일 또는 환경변수 권장
  # (CLI --email/--password 는 프로세스 목록 노출 위험)
"""

import argparse
import asyncio
import logging
import random
import sys
import time

from config import (
    BOT_LEVELS, BASE_URL, TEST_ACCOUNTS,
    validate_url, validate_runs, validate_show_id,
    mask_email, build_booking_options,
)
from data_logger import DataLogger
from browser_macro import TruveMacro, PLAYWRIGHT_AVAILABLE

# [Rule 4] 로깅 설정: 민감정보 노출 방지
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("truve-macro")


def print_banner():
    print("""
 ╔══════════════════════════════════════════════════════════╗
 ║  TRUVE 매크로 데이터 수집기                              ║
 ║  목적: BE/FE 매크로 탐지 모델 학습용 봇 데이터 생성      ║
 ║  실행: 실제 브라우저가 열리고 화면에서 동작이 보임        ║
 ╚══════════════════════════════════════════════════════════╝
    """)


def print_behavior_info():
    """bot/human 행동 타입 비교표 출력"""
    print("\n  [행동 타입 비교]")
    print("  " + "-" * 72)
    print("  bot")
    print("    - 목표: 짧은 seatmap 체류, 적은 탐색, 높은 teleport 성향")
    print("    - seatmap 체류시간: 1매 0.18~0.32초 / 2매 0.25~0.42초")
    print("    - queue polling / retry / 입력 속도도 전반적으로 더 공격적")
    print()
    print("  human")
    print("    - 목표: 긴 seatmap 체류, 많은 탐색, 낮은 teleport 성향")
    print("    - seatmap 체류시간: 1매 1.05~1.85초 / 2매 1.55~2.7초")
    print("    - hover / pause / 곡선 이동 비중을 높여 사람형 분포를 만듦")
    print("  " + "-" * 72)


def resolve_behavior_profile(behavior_type: str) -> tuple[int, dict]:
    """behavior_type 하나로 내부 프로필(속도/행동)을 결정한다."""
    if behavior_type == "human":
        return 8, {
            "typing_use_paste": False,
            "mouse_move_to_target": True,
            "scroll_enabled": True,
            "action_delay_ms": (62, 165),
            "typing_delay_ms": (7, 19),
            "seat_select_delay_ms": (95, 400),
            "hover_before_click_ms": (7, 34),
            "queue_poll_ms": (620, 1150),
            "queue_ignore_server_interval": False,
            "retry_count": 1,
            "retry_delay_ms": (0, 0),
            "random_hesitation": False,
            "idle_pause_chance": 0.0,
            "idle_pause_ms": (0, 0),
            "mouse_move_steps": 14,
            "mouse_move_speed_ms": 3,
            "mouse_curve": "human_like",
            "mouse_jitter_px": 1.0,
            "scroll_delay_ms": 70,
            "seat_retry_limit": 3,
        }

    # 봇형: 기존보다 20~30% 더 빠르게
    return 1, {
        "typing_use_paste": True,
        "mouse_move_to_target": False,
        "scroll_enabled": False,
        "action_delay_ms": (6, 55),
        "seat_select_delay_ms": (0, 60),
        "hover_before_click_ms": (0, 4),
        "queue_poll_ms": (20, 45),
        "queue_ignore_server_interval": True,
        "retry_count": 28,
        "retry_delay_ms": (2, 6),
    }


async def run_macro(base_url: str, profile_level: int, runs: int,
                    accounts: list, show_id: int, schedule_id: int,
                    applicant: dict, booking_options: dict,
                    data_logger: DataLogger, level_overrides: dict = None,
                    tag_name: str = "", behavior_type: str = "bot",
                    seat_count_mode: str = "random"):
    """단일 행동 타입으로 매크로 실행"""
    cfg = BOT_LEVELS[profile_level]

    print(f"\n{'#'*60}")
    print(f"  행동 타입: {behavior_type}")
    print(f"  내부 프로필: {cfg['name']}")
    print(f"  {cfg['description']}")
    print(f"  반복: {runs}회")
    print(f"{'#'*60}")

    for run_idx in range(runs):
        account = accounts[run_idx % len(accounts)]
        print(f"\n  --- Run {run_idx + 1}/{runs} (계정: {mask_email(account['email'])}) ---")

        run_booking_options = dict(booking_options)
        if seat_count_mode == "random":
            run_booking_options["seat_count"] = random.randint(1, 2)
        print(f"      이번 시도 좌석 수: {run_booking_options['seat_count']}매")
        applicant_for_run = dict(applicant)

        # 매 run마다 새 매크로 인스턴스 (깨끗한 상태)
        macro = TruveMacro(base_url, profile_level, data_logger,
                           booking_options=run_booking_options,
                           level_overrides=level_overrides,
                           scenario=f"manual_{behavior_type}",
                           tag=tag_name,
                           behavior_type=behavior_type)

        try:
            be_record, fe_record = await macro.run(
                account=account,
                show_id=show_id,
                schedule_id=schedule_id,
                applicant=applicant_for_run,
            )

            data_logger.add_be_record(be_record)
            data_logger.add_fe_record(fe_record)

            print(f"\n  Run {run_idx + 1} 결과:")
            print(f"    소요: {be_record.total_flow_duration_ms:.0f}ms")
            print(f"    요청간격 평균: {be_record.req_interval_mean_ms:.0f}ms")
            print(f"    요청간격 CV: {be_record.req_interval_cv:.3f}")
            print(f"    마우스 이동: {fe_record.mouse_move_count}회")
            print(f"    클릭: {fe_record.click_count}회")
            print(f"    키입력: {fe_record.keystroke_count}회")
            print(
                f"    seatmap: {fe_record.seatmap_duration_ms}ms / "
                f"mousemove {fe_record.seatmap_mousemove_count}회 / "
                f"click {fe_record.seatmap_click_count}회 / "
                f"activity {fe_record.seatmap_mouse_activity_rate:.2f}/s / "
                f"teleport {fe_record.seatmap_mouse_teleport_rate:.2f}"
            )
            print(f"    webdriver: {fe_record.webdriver_detected}")

        except Exception as exc:
            # [Rule 4] 내부 경로/스택 미노출, 에러 유형만 출력
            logger.error("Run %d 실패: %s", run_idx + 1, type(exc).__name__)
            print(f"  [ERROR] Run {run_idx + 1} 실패: {type(exc).__name__}")

        # 연속 실행 간 대기
        if run_idx < runs - 1:
            if behavior_type == "bot":
                await asyncio.sleep(random.uniform(0.7, 1.4))
            else:
                await asyncio.sleep(random.uniform(1.0, 2.0))


async def async_main(args):
    """비동기 메인"""
    data_logger = DataLogger(output_dir=args.output)

    # [Rule 2] 계정 설정: 환경변수 우선, CLI 보조
    if args.email and args.password:
        accounts = [{"email": args.email, "password": args.password}]
    elif TEST_ACCOUNTS:
        accounts = TEST_ACCOUNTS
    else:
        print("  [ERROR] 테스트 계정이 설정되지 않았습니다.")
        print("  방법 1: .env 파일에 TRUVE_TEST_ACCOUNTS 설정")
        print("  방법 2: --email / --password 옵션 사용")
        sys.exit(1)

    # 예약자 정보
    applicant = {
        "name": args.applicant_name,
        "birth": args.applicant_birth,
        "email": accounts[0]["email"],
        "phone": args.applicant_phone,
    }

    # [Rule 1] 예매 부가 옵션 검증
    default_seat_count = 2 if args.seat_count_mode == "random" else args.seat_count
    try:
        booking_options = build_booking_options(
            seat_grade=args.seat_grade,
            seat_section=args.seat_section,
            seat_count=default_seat_count,
            pay_method=args.pay_method,
            bank=args.bank,
            card_company=args.card_company,
            cash_receipt=args.cash_receipt,
            schedule_date=args.schedule_date,
            schedule_time=args.schedule_time,
        )
    except ValueError as e:
        print(f"  [INPUT ERROR] {e}")
        sys.exit(1)

    profile_level, level_overrides = resolve_behavior_profile(args.behavior_type)
    runs = args.runs

    if args.behavior_runs is not None:
        runs = args.behavior_runs

    # CLI --retry 오버라이드
    if args.retry is not None:
        level_overrides["retry_count"] = args.retry

    total_start = time.time()
    tag_name = args.tag or ""

    await run_macro(
        base_url=args.url,
        profile_level=profile_level,
        runs=runs,
        accounts=accounts,
        show_id=args.show_id,
        schedule_id=args.schedule_id,
        applicant=applicant,
        booking_options=booking_options,
        data_logger=data_logger,
        level_overrides=level_overrides,
        tag_name=tag_name,
        behavior_type=args.behavior_type,
        seat_count_mode=args.seat_count_mode,
    )

    total_elapsed = time.time() - total_start

    # 결과 저장
    files = data_logger.save_all()
    data_logger.print_summary()

    print(f"\n  총 소요 시간: {total_elapsed:.1f}초")
    print(f"\n  [출력 파일]")
    for name, path in files.items():
        print(f"    {name}: {path}")

    print(f"\n  데이터 라벨:")
    print(f"    behavior_type={args.behavior_type}, is_bot={'1' if args.behavior_type == 'bot' else '0'}")
    print("    내부 프로필 메타(bot_profile)는 함께 저장")


def main():
    parser = argparse.ArgumentParser(
        description="Truve 매크로 데이터 수집기 (headed 브라우저)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py --behavior-type bot --behavior-runs 5
  python main.py --behavior-type human --behavior-runs 2
  python main.py --info
        """,
    )
    parser.add_argument("--behavior-type", default="bot", choices=["bot", "human"],
                        help="행동 라벨 (bot=봇형 데이터, human=사람형 데이터)")
    parser.add_argument("--behavior-runs", type=int, default=None,
                        help="행동 타입 기준 반복 횟수 (--runs보다 우선)")
    parser.add_argument("--runs", type=int, default=1, help="반복 횟수 (1~100)")
    parser.add_argument("--url", default=BASE_URL, help="대상 URL")
    parser.add_argument("--show-id", type=int, default=1, help="대상 공연 ID")
    parser.add_argument("--schedule-id", type=int, default=1, help="대상 회차 ID")
    parser.add_argument("--email", default=None, help="로그인 이메일 (.env 권장)")
    parser.add_argument("--password", default=None, help="로그인 비밀번호 (.env 권장)")
    parser.add_argument("--applicant-name", default="테스트봇", help="예약자 이름")
    parser.add_argument("--applicant-birth", default="20000101", help="예약자 생년월일")
    parser.add_argument("--applicant-phone", default="01062971082", help="예약자 전화번호")
    parser.add_argument("--output", default="./output", help="출력 디렉토리")
    parser.add_argument("--info", action="store_true", help="행동 타입 비교표 출력 후 종료")
    parser.add_argument("--retry", type=int, default=None, help="실패 시 재시도 횟수 (미지정시 behavior-type 기본값)")
    parser.add_argument("--tag", default=None, help="데이터에 붙일 커스텀 태그 (예: test-01, batch-a)")

    # ── 예매 부가 설정 ──
    booking_group = parser.add_argument_group("예매 부가 설정")
    booking_group.add_argument(
        "--seat-grade", default="any",
        choices=["VIP", "R", "S", "A", "any"],
        help="좌석 등급 (기본: any=아무거나)",
    )
    booking_group.add_argument(
        "--seat-section", default="any",
        help="좌석 구역 (OP, 1F-A, 1F-B, 1F-C, 2F-A, 2F-B, 2F-C, any)",
    )
    booking_group.add_argument(
        "--seat-count", type=int, default=2,
        help="예매 매수 1~2 (기본: 2)",
    )
    booking_group.add_argument(
        "--seat-count-mode", default="random",
        choices=["random", "fixed"],
        help="좌석 매수 선택 방식 (random=매 run마다 1~2 랜덤, fixed=--seat-count 고정)",
    )
    booking_group.add_argument(
        "--pay-method", default="VIRTUAL_ACCOUNT",
        choices=["CARD", "VIRTUAL_ACCOUNT"],
        help="결제 방식 (CARD=카드, VIRTUAL_ACCOUNT=무통장)",
    )
    booking_group.add_argument(
        "--bank", default="신한",
        help="무통장 입금 은행 (국민,신한,우리,하나,농협,카카오뱅크 등)",
    )
    booking_group.add_argument(
        "--card-company", default="삼성",
        help="카드 결제 카드사 (삼성,현대,KB국민,신한 등)",
    )
    booking_group.add_argument(
        "--cash-receipt", default="발급안함",
        choices=["소득공제", "지출증빙", "발급안함"],
        help="현금영수증 유형 (무통장 입금 시)",
    )
    booking_group.add_argument(
        "--schedule-date", default="any",
        help="회차 날짜 (YYYY-MM-DD 또는 any=랜덤)",
    )
    booking_group.add_argument(
        "--schedule-time", default="any",
        help="회차 시간 (HH:MM 또는 any=랜덤)",
    )

    args = parser.parse_args()

    print_banner()

    if args.info:
        print_behavior_info()
        return

    if not PLAYWRIGHT_AVAILABLE:
        print("  [ERROR] playwright가 설치되지 않았습니다.")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    # [Rule 1] 모든 외부 입력값 검증
    try:
        validate_url(args.url)
        validate_runs(args.runs)
        if args.behavior_runs is not None:
            validate_runs(args.behavior_runs)
        validate_show_id(args.show_id)
        validate_show_id(args.schedule_id)
    except ValueError as e:
        print(f"  [INPUT ERROR] {e}")
        sys.exit(1)

    print(f"  대상: {args.url}")
    print(f"  행동 타입: {args.behavior_type}")
    effective_runs = args.behavior_runs if args.behavior_runs is not None else args.runs
    print(f"  반복: {effective_runs}회")
    print(f"  공연: showId={args.show_id}")
    seat_count_label = "1~2 랜덤" if args.seat_count_mode == "random" else f"{args.seat_count}매"
    print(f"  좌석: {args.seat_grade.upper()} / {args.seat_section.upper()} / {seat_count_label}")
    if args.pay_method == "CARD":
        print(f"  결제: 카드 ({args.card_company})")
    else:
        print(f"  결제: 무통장 ({args.bank}) / 현금영수증: {args.cash_receipt}")
    if args.schedule_date.lower() == "any":
        print(f"  회차: any (랜덤 날짜/시간)")
    else:
        print(f"  날짜: {args.schedule_date} {args.schedule_time}")
    if args.retry is not None:
        print(f"  재시도: {args.retry}회")
    if args.tag:
        print(f"  태그: {args.tag}")

    # [Rule 2] 비밀번호 CLI 전달 시 경고
    if args.password:
        print("  [WARN] --password CLI 전달은 프로세스 목록 노출 위험.")
        print("         .env 파일 사용을 권장합니다.")

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
