"""
Truve 예매 매크로 - Playwright headed 모드
실제 브라우저 화면에서 마우스가 움직이고, 클릭되고, 키보드 입력되는 것이 보임.

프론트엔드 구조 (Next.js App Router):
  /signin                     → 로그인
  /shows/now                  → 공연 목록
  /shows/{showId}             → 공연 상세 (예매하기 버튼 → 캡차 → 대기열)
  /shows/{showId}/seat        → 좌석 선택 (PixiJS Canvas)
  /payments                   → 결제 (예약자 정보 입력 + Toss 결제)

주의: 좌석 선택 페이지는 PixiJS Canvas로 렌더링됨 → Canvas 좌표 클릭 필요
"""

import asyncio
import math
import random
import time
import uuid

from config import BOT_LEVELS, BASE_URL, mask_email
from data_logger import DataLogger, BEDataRecord, FEDataRecord

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARN] playwright 미설치.")
    print("  pip install playwright && playwright install chromium")


class MouseController:
    """레벨별 마우스 움직임 제어 - 화면에서 실제로 보임"""

    def __init__(self, page: Page, level_config: dict):
        self.page = page
        self.cfg = level_config
        self.current_x = 400.0
        self.current_y = 300.0
        self.move_log: list[dict] = []

    async def move_to(self, target_x: float, target_y: float):
        """레벨에 맞는 마우스 이동 - 화면에서 커서가 움직이는 것이 보임"""
        if not self.cfg["mouse_move_to_target"]:
            self.current_x = target_x
            self.current_y = target_y
            return

        steps = self.cfg["mouse_move_steps"]
        speed_ms = self.cfg["mouse_move_speed_ms"]
        curve = self.cfg["mouse_curve"]
        jitter = self.cfg["mouse_jitter_px"]

        sx, sy = self.current_x, self.current_y

        # 베지어 곡선용 제어점 (한 번만 생성)
        ctrl_x = (sx + target_x) / 2 + random.uniform(-80, 80)
        ctrl_y = (sy + target_y) / 2 + random.uniform(-50, 50)

        for i in range(1, steps + 1):
            t = i / steps

            if curve == "none":
                x, y = target_x, target_y
            elif curve == "linear":
                x = sx + (target_x - sx) * t
                y = sy + (target_y - sy) * t
            elif curve == "ease_in_out":
                ease = t * t * (3 - 2 * t)  # smoothstep
                x = sx + (target_x - sx) * ease
                y = sy + (target_y - sy) * ease
            elif curve == "bezier":
                inv = 1 - t
                x = inv*inv*sx + 2*inv*t*ctrl_x + t*t*target_x
                y = inv*inv*sy + 2*inv*t*ctrl_y + t*t*target_y
            elif curve == "human_like":
                ease = t * t * (3 - 2 * t)
                # 끝부분 미세 오버슈트
                if t > 0.85:
                    ease += random.uniform(-0.015, 0.02)
                x = sx + (target_x - sx) * ease
                y = sy + (target_y - sy) * ease
                # 인간형 미세 떨림
                x += random.gauss(0, jitter * 0.3)
                y += random.gauss(0, jitter * 0.3)
            else:
                x = sx + (target_x - sx) * t
                y = sy + (target_y - sy) * t

            # 떨림 추가
            if jitter > 0 and curve != "human_like":
                x += random.uniform(-jitter, jitter)
                y += random.uniform(-jitter, jitter)

            await self.page.mouse.move(x, y)
            self.move_log.append({"x": x, "y": y, "t": time.time()})
            self.current_x, self.current_y = x, y

            if speed_ms > 0:
                # 인간형: 속도 변화 (시작/끝은 느리게)
                if curve == "human_like":
                    factor = 1.0 + 0.5 * math.sin(t * math.pi)
                    await asyncio.sleep(speed_ms * factor / 1000.0)
                else:
                    await asyncio.sleep(speed_ms / 1000.0)

    async def click_at(self, target_x: float, target_y: float):
        """마우스 이동 → 호버 → 클릭 (화면에서 보임)"""
        offset = self.cfg["click_offset_px"]
        hover_min, hover_max = self.cfg["hover_before_click_ms"]

        click_x = target_x + random.uniform(-offset, offset)
        click_y = target_y + random.uniform(-offset, offset)

        await self.move_to(click_x, click_y)

        if hover_max > 0:
            hover = random.uniform(hover_min, hover_max)
            await asyncio.sleep(hover / 1000.0)

        await self.page.mouse.click(click_x, click_y)


class KeyboardController:
    """레벨별 키보드 입력 - 화면에서 글자가 하나씩 입력되는 것이 보임"""

    def __init__(self, page: Page, level_config: dict):
        self.page = page
        self.cfg = level_config
        self.keystroke_log: list[dict] = []

    async def type_text(self, selector: str, text: str):
        """레벨에 맞는 텍스트 입력"""
        if self.cfg["typing_use_paste"]:
            await self.page.fill(selector, text)
            self.keystroke_log.append({"type": "paste", "len": len(text), "t": time.time()})
            return

        await self.page.click(selector)
        await asyncio.sleep(0.05)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.05)

        d_min, d_max = self.cfg["typing_delay_ms"]

        for char in text:
            delay = random.uniform(d_min, d_max)

            # Level 10: 오타 시뮬레이션
            if self.cfg.get("misclick_chance", 0) > 0 and random.random() < 0.02:
                wrong = chr(ord(char) + random.choice([-1, 1]))
                await self.page.keyboard.type(wrong, delay=delay)
                await asyncio.sleep(delay / 1000.0)
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(delay * 2 / 1000.0)

            await self.page.keyboard.type(char, delay=delay)
            self.keystroke_log.append({"char": char, "delay": delay, "t": time.time()})


class TruveMacro:
    """
    Truve 예매 매크로 - headed 모드 (화면에서 실행됨)

    실행하면 실제 브라우저 창이 열리고,
    마우스가 움직이고, 클릭하고, 키보드 입력하는 것이 모두 보임.
    """

    def __init__(self, base_url: str, level: int, logger: DataLogger,
                 booking_options: dict = None, level_overrides: dict = None,
                 scenario: str = "", tag: str = ""):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("pip install playwright && playwright install chromium")

        self.base_url = base_url.rstrip("/")
        self.level = level
        self.scenario = scenario
        self.tag = tag
        # 레벨 설정 복사 후 오버라이드 적용 (stealth 시나리오용)
        self.cfg = dict(BOT_LEVELS[level])
        if level_overrides:
            self.cfg.update(level_overrides)
        self.logger = logger
        self.run_id = str(uuid.uuid4())[:8]
        # 예매 부가 설정 (좌석 등급/구역/매수, 결제 방식, 회차 날짜/시간)
        self.booking = booking_options or {
            "seat_grade": "any",
            "seat_section": "any",
            "seat_count": 2,
            "pay_method": "CARD",
            "schedule_date": None,
            "schedule_time": None,
        }

        self._pw = None
        self.browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.mouse: MouseController = None
        self.keyboard: KeyboardController = None

        self._be = BEDataRecord(
            run_id=self.run_id, bot_profile=f"level_{level}",
            level=level, scenario=scenario, tag=tag,
        )
        self._fe = FEDataRecord(
            run_id=self.run_id, bot_profile=f"level_{level}",
            level=level, scenario=scenario, tag=tag,
        )
        self._last_action = 0.0

    # ================================================================
    # Setup / Teardown
    # ================================================================

    async def setup(self):
        """브라우저 시작 - 화면에 브라우저 창이 열림"""
        print(f"\n  [Setup] Level {self.level}: {self.cfg['name']}")

        self._pw = await async_playwright().start()

        args = ["--start-maximized", "--disable-infobars"]
        if self.cfg["hide_webdriver"]:
            args.append("--disable-blink-features=AutomationControlled")

        vw, vh = self.cfg["viewport"]
        self.browser = await self._pw.chromium.launch(
            headless=False,  # 항상 화면에 보임
            slow_mo=self.cfg["slow_mo"],
            args=args,
        )

        # no_viewport=True → 브라우저 창 전체 크기 사용 (--start-maximized와 연동)
        # viewport 설정이 있으면 창 크기와 무관하게 고정되므로, 전체화면 보장을 위해 no_viewport 사용
        ctx_opts = {
            "no_viewport": True,
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }
        if self.cfg["user_agent"]:
            ctx_opts["user_agent"] = self.cfg["user_agent"]

        self.context = await self.browser.new_context(**ctx_opts)
        self.page = await self.context.new_page()

        self.mouse = MouseController(self.page, self.cfg)
        self.keyboard = KeyboardController(self.page, self.cfg)

        # webdriver 숨기기 (Level 4+)
        if self.cfg["hide_webdriver"]:
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1,2,3,4,5]
                });
                window.chrome = { runtime: {} };
            """)

        # 텔레메트리 수집기 주입
        await self.page.add_init_script("""
            window.__tel = {
                mouse:[], clicks:[], keys:[], scrolls:[],
                vis:0, focus:0
            };
            document.addEventListener('mousemove', e =>
                window.__tel.mouse.push({x:e.clientX,y:e.clientY,t:Date.now()}));
            document.addEventListener('click', e =>
                window.__tel.clicks.push({x:e.clientX,y:e.clientY,t:Date.now()}));
            document.addEventListener('keydown', e =>
                window.__tel.keys.push({k:e.key,t:Date.now(),d:'dn'}));
            document.addEventListener('keyup', e =>
                window.__tel.keys.push({k:e.key,t:Date.now(),d:'up'}));
            document.addEventListener('scroll', () =>
                window.__tel.scrolls.push({y:window.scrollY,t:Date.now()}));
            document.addEventListener('visibilitychange', () => window.__tel.vis++);
            window.addEventListener('focus', () => window.__tel.focus++);
            window.addEventListener('blur', () => window.__tel.focus++);
        """)

    async def teardown(self):
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    # ================================================================
    # 공통
    # ================================================================

    async def _delay(self):
        """레벨별 동작 간 딜레이"""
        d_min, d_max = self.cfg["action_delay_ms"]
        delay = random.uniform(d_min, d_max)

        # Level 10: 망설임/멍때리기
        if self.cfg.get("random_hesitation") and random.random() < 0.15:
            delay += random.uniform(1000, 5000)
        if self.cfg.get("idle_pause_chance", 0) > 0:
            if random.random() < self.cfg["idle_pause_chance"]:
                p_min, p_max = self.cfg["idle_pause_ms"]
                extra = random.uniform(p_min, p_max)
                delay += extra
                print(f"      (Lv10 시뮬: {extra/1000:.1f}초 멍때림)")

        now = time.time() * 1000
        if self._last_action > 0:
            self._be.req_intervals_ms.append(round(now - self._last_action, 2))
        self._last_action = now

        await asyncio.sleep(delay / 1000.0)

    async def _dismiss_popups(self):
        """
        화면 위에 떠있는 팝업/모달/공연안내 등을 자동으로 닫는다.
        매 스텝 전에 호출하여 클릭 차단 요소를 제거.
        여러 팝업이 겹쳐있을 수 있으므로 반복 시도.
        """
        dismissed = False

        # ── 공연안내 팝업 닫기 (shadcn Dialog) ──
        # 정확한 셀렉터: button[data-slot="dialog-close"]
        # 단, 캡차/VQA/대기열 모달은 절대 닫지 않음

        try:
            result = await self.page.evaluate("""() => {
                // data-slot="dialog-close" 버튼이 있는 모달 찾기
                const closeBtns = document.querySelectorAll('button[data-slot="dialog-close"]');
                if (closeBtns.length === 0) return 'none';

                for (const btn of closeBtns) {
                    // 이 버튼이 속한 모달의 텍스트 확인
                    const modal = btn.closest('[data-slot="dialog-content"], [role="dialog"]');
                    if (!modal) continue;

                    const text = modal.textContent || '';

                    // 캡차/VQA/대기열/결제 모달이면 → 절대 닫지 않음
                    const protect = ['시작하기', '캡차', 'captcha', '대기열',
                                     '대기 중', '접속 중', 'WAITING', '결제하기',
                                     '타일', 'tile', '좌석'];
                    if (protect.some(kw => text.includes(kw))) continue;

                    // 공연안내 등 일반 팝업 → 닫기
                    btn.click();
                    return 'closed';
                }

                // data-slot이 없는 경우 aria-label="Close" 시도
                const ariaClose = document.querySelectorAll('button[aria-label="Close"]');
                for (const btn of ariaClose) {
                    const modal = btn.closest('[role="dialog"]');
                    if (!modal) continue;
                    const text = modal.textContent || '';
                    const protect = ['시작하기', '캡차', 'captcha', '대기열',
                                     '대기 중', '접속 중', 'WAITING', '결제하기',
                                     '타일', 'tile', '좌석'];
                    if (protect.some(kw => text.includes(kw))) continue;
                    btn.click();
                    return 'closed';
                }

                return 'skip';
            }""")

            if result == "closed":
                await asyncio.sleep(0.5)
                print(f"      [팝업] 공연안내 닫기 완료")
                return True

        except Exception:
            pass

        return False

    async def _click_selector(self, selector: str, desc: str = ""):
        """
        CSS 셀렉터로 요소 찾아 클릭.
        팝업 닫기는 여기서 자동 호출하지 않음 (캡차/VQA 모달 오닫기 방지).
        필요한 스텝에서 명시적으로 _dismiss_popups() 호출할 것.
        """
        await self._delay()

        try:
            el = await self.page.wait_for_selector(selector, timeout=10000)

            # 요소가 뷰포트에 보이도록 스크롤
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)

            box = await el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                if desc:
                    print(f"      클릭: {desc}")
                await self.mouse.click_at(cx, cy)
            else:
                if desc:
                    print(f"      클릭(직접): {desc}")
                await el.click(force=True)

        except Exception:
            # force 클릭 재시도
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if desc:
                    print(f"      클릭(force): {desc}")
                await el.click(force=True)
            except Exception as e:
                print(f"      [!] 클릭 실패: {selector} ({type(e).__name__})")
                raise

    async def _scroll(self):
        """레벨별 스크롤"""
        if not self.cfg["scroll_enabled"]:
            return
        await asyncio.sleep(self.cfg["scroll_delay_ms"] / 1000.0)
        amount = random.randint(200, 500)
        await self.page.evaluate(f"window.scrollBy(0, {amount})")
        if self.level >= 8 and random.random() < 0.3:
            await asyncio.sleep(0.5)
            await self.page.evaluate(f"window.scrollBy(0, -{amount // 2})")

    # ================================================================
    # Step 1: 로그인 (/signin)
    # ================================================================

    async def step1_login(self, email: str, password: str):
        """
        로그인 - 이미 로그인 상태면 스킵
        상단 네비에 "로그인" 버튼이 보이면 → 미로그인 → 로그인 수행
        "로그인" 버튼이 없으면 → 이미 로그인됨 → 스킵
        """
        print(f"\n  [Step 1/8] 로그인 확인")
        self._be.api_call_sequence.append("signin")

        # 먼저 메인 페이지로 이동해서 로그인 상태 확인
        await self.page.goto(f"{self.base_url}/", wait_until="networkidle")
        await asyncio.sleep(1)

        # 상단에 "로그인" 텍스트/버튼이 있는지 확인
        login_btn = await self.page.query_selector(
            'a:has-text("로그인"), button:has-text("로그인")'
        )

        if not login_btn:
            # 로그인 버튼이 없음 = 이미 로그인 상태
            print(f"      -> 이미 로그인 상태, 스킵")
            self._be.login_method = "already_logged_in"
            return

        # 미로그인 → 로그인 수행
        print(f"      미로그인 상태, 로그인 진행")
        await self.page.goto(f"{self.base_url}/signin", wait_until="networkidle")
        await self._delay()

        # [Rule 4] 이메일 마스킹 출력
        print(f"      이메일: {mask_email(email)}")
        await self.keyboard.type_text('input[name="email"]', email)
        await self._delay()

        print(f"      비밀번호 입력 중...")
        await self.keyboard.type_text('input[name="password"]', password)
        await self._delay()

        await self._click_selector(
            'button[type="submit"]',
            "로그인 버튼"
        )

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        print(f"      -> 로그인 완료")
        self._be.login_method = "email"

    # ================================================================
    # Step 2: 공연 상세 → 날짜/회차 선택
    # ================================================================

    async def step2_select_show(self, show_id: int):
        """
        공연 상세 페이지로 이동 + 회차(날짜/시간) 선택
        - /shows/{showId}
        - 캘린더에서 날짜 선택 → 회차 시간 선택
        - schedule_date/schedule_time = None → any (랜덤/첫 번째 가용)
        """
        print(f"\n  [Step 2/8] 공연 페이지 이동 (showId={show_id})")
        self._be.api_call_sequence.append("show_detail")

        await self.page.goto(
            f"{self.base_url}/shows/{show_id}",
            wait_until="networkidle",
        )
        await self._delay()

        # 사람 시뮬: 공연 정보 둘러보기
        if self.level >= 7:
            await self._scroll()
            await asyncio.sleep(random.uniform(1, 3))
            await self._scroll()

        # ── 회차 날짜 선택 ──
        target_date = self.booking.get("schedule_date")
        if target_date and target_date.lower() != "any":
            # 특정 날짜 클릭 (YYYY-MM-DD → DD)
            day = str(int(target_date.split("-")[2]))
            print(f"      날짜 선택: {target_date}")
            try:
                date_btn = await self.page.query_selector(
                    f'button[name="day"]:has-text("{day}")'
                )
                if date_btn:
                    box = await date_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] 날짜 {day}일 못찾음, 기본 유지")
            except Exception:
                print(f"      [!] 날짜 선택 실패, 기본 유지")
        else:
            # any: 공연이 있는 날짜를 찾아서 선택
            print(f"      날짜: any (공연 있는 날짜 탐색)")
            await self._select_available_date()

        await self._delay()

        # ── 회차 시간 선택 ──
        target_time = self.booking.get("schedule_time")
        if target_time and target_time.lower() != "any":
            print(f"      회차 시간 선택: {target_time}")
            try:
                time_btn = await self.page.query_selector(
                    f'button:has-text("{target_time}"), '
                    f'[class*="schedule"]:has-text("{target_time}")'
                )
                if time_btn:
                    box = await time_btn.bounding_box()
                    if box:
                        await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        await asyncio.sleep(0.5)
                else:
                    print(f"      [!] {target_time} 회차 못찾음, 가용 회차 탐색")
                    await self._select_available_schedule()
            except Exception:
                await self._select_available_schedule()
        else:
            # any: 가용 회차 탐색
            print(f"      회차: any (가용 회차 탐색)")
            await self._select_available_schedule()

        print(f"      -> 공연/회차 선택 완료")

    async def _select_available_date(self):
        """
        공연이 있는 날짜를 찾아서 클릭.
        캘린더에서 disabled 아닌 날짜를 하나씩 클릭해보고,
        "선택하신 날짜에 공연이 없습니다" 메시지가 안 뜨는 날짜를 찾는다.
        """
        max_attempts = 15  # 최대 15개 날짜 시도

        # 활성화된(disabled 아닌) 날짜 버튼 수집
        avail_days = await self.page.query_selector_all(
            'button[name="day"]:not([disabled])'
        )
        if not avail_days:
            print(f"      [!] 클릭 가능한 날짜 없음")
            return

        # 랜덤 셔플 (봇 패턴 다양화)
        indices = list(range(len(avail_days)))
        random.shuffle(indices)

        for attempt, idx in enumerate(indices[:max_attempts]):
            day_btn = avail_days[idx]
            box = await day_btn.bounding_box()
            if not box:
                continue

            day_text = await day_btn.text_content()
            await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            await asyncio.sleep(0.8)

            # "공연이 없습니다" 메시지 확인
            no_show = await self.page.query_selector('text=공연이 없습니다')
            if not no_show:
                # 공연 있는 날짜 찾음
                print(f"      -> {day_text}일 선택 (공연 있음, {attempt+1}번째 시도)")
                return

        print(f"      [!] {max_attempts}개 날짜 시도했으나 가용 날짜 없음")

    async def _select_available_schedule(self):
        """
        가용 회차(시간) 찾아서 클릭.
        회차 버튼/리스트에서 클릭 가능한 것을 찾는다.
        """
        # 회차 버튼 후보 셀렉터 (다양한 구조 대응)
        selectors = [
            '[class*="schedule"] button:not([disabled])',
            'button[class*="schedule"]:not([disabled])',
            '[class*="time"] button:not([disabled])',
            'button[class*="round"]:not([disabled])',
            # 일반적인 회차 리스트 아이템
            '[role="radio"]:not([disabled])',
            '[role="option"]:not([disabled])',
        ]

        for sel in selectors:
            btns = await self.page.query_selector_all(sel)
            if btns:
                pick = random.choice(btns)
                box = await pick.bounding_box()
                if box:
                    await self.mouse.click_at(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    await asyncio.sleep(0.5)
                picked_text = await pick.text_content()
                print(f"      -> '{picked_text.strip()}' 회차 선택")
                return

        print(f"      [!] 가용 회차를 찾을 수 없음")

    # ================================================================
    # Step 3: 예매하기 버튼 → 캡차
    # ================================================================

    async def step3_captcha(self):
        """
        공연안내 팝업 닫기 → 예매하기 버튼 → 캡차(VQA) 처리
        주의: 캡차 모달은 role="dialog"이므로 _dismiss_popups로 닫으면 안 됨!
              공연안내 팝업만 예매하기 전에 닫는다.
        """
        print(f"\n  [Step 3/8] 예매하기 + 캡차")
        self._be.api_call_sequence.append("captcha")

        # ── 공연안내 팝업 닫기 (예매하기 전에) ──
        # 캡차 모달이 아직 안 떴으므로 여기서만 dismiss 허용
        # 공연안내가 확실히 닫힐 때까지 최대 3회 시도
        for _try in range(3):
            closed = await self._dismiss_popups()
            if not closed:
                break
            await asyncio.sleep(0.5)
        await self._delay()

        # ── 예매하기 버튼 클릭 ──
        await self._click_selector(
            'button:has-text("예매하기")',
            "예매하기 버튼"
        )

        # ── 캡차(VQA) 모달 대기 ──
        # 여기서부터는 _dismiss_popups 절대 호출 금지!
        await asyncio.sleep(2)

        # ── 캡차 타일 선택 (3x2 = 6개 중 1개) ──
        await self._delay()
        tile_index = random.randint(0, 5)
        try:
            tiles = await self.page.query_selector_all(
                '[class*="aspect-square"][class*="rounded-xl"]'
            )
            if tiles and len(tiles) > tile_index:
                box = await tiles[tile_index].bounding_box()
                if box:
                    print(f"      캡차 타일 {tile_index + 1}/6 선택")
                    await self.mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
            else:
                print(f"      [!] 캡차 타일 {len(tiles) if tiles else 0}개 발견, 클릭 시도")
                # 폴백: 모달 내부에서 클릭 가능한 div 찾기
                await self.page.evaluate("""() => {
                    const modal = document.querySelector('[role="dialog"]');
                    if (!modal) return;
                    const tiles = modal.querySelectorAll('[class*="aspect-square"], [class*="rounded-xl"]');
                    if (tiles.length > 0) tiles[Math.floor(Math.random() * tiles.length)].click();
                }""")
        except Exception:
            print(f"      [!] 캡차 타일 클릭 실패")

        await self._delay()

        # ── "시작하기" 버튼 클릭 (캡차 모달 내부) ──
        # _click_selector 사용하되 dismiss 안 함 (이미 위에서 제거)
        try:
            await self._click_selector(
                'button:has-text("시작하기")',
                "시작하기 버튼"
            )
        except Exception:
            # 폴백: 모달 내부에서 시작하기 버튼 JS 클릭
            try:
                await self.page.evaluate("""() => {
                    const modal = document.querySelector('[role="dialog"]');
                    if (!modal) return;
                    const btns = modal.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.includes('시작하기') || btn.textContent.includes('접속')) {
                            btn.click(); return;
                        }
                    }
                }""")
                print(f"      -> 시작하기 (JS 클릭)")
            except Exception:
                print(f"      [!] 시작하기 버튼 실패")

        await asyncio.sleep(1)
        print(f"      -> 캡차 통과")

    # ================================================================
    # Step 4: 대기열
    # ================================================================

    async def step4_queue(self, show_id: int):
        """
        대기열 대기 (QueueStep 모달)
        - 순위 표시: text-5xl font-extrabold text-red-500
        - 자동으로 /shows/{showId}/seat 으로 리다이렉트됨
        """
        print(f"\n  [Step 4/8] 대기열 대기")
        self._be.api_call_sequence.append("queue")

        max_wait = 300  # 최대 5분
        start = time.time()
        poll_count = 0

        while time.time() - start < max_wait:
            poll_start = time.time()
            poll_count += 1

            # 짧게라도 URL 변화를 먼저 기다려 좌석 페이지 전환을 바로 잡는다.
            try:
                await self.page.wait_for_url("**/seat", timeout=250)
            except Exception:
                pass

            # 현재 URL 확인 → 좌석 페이지로 이동했으면 통과
            current_url = self.page.url
            if "/seat" in current_url:
                print(f"      -> 대기열 통과! (폴링 {poll_count}회)")
                self._be.queue_poll_count = poll_count
                return True

            # URL 변경 전이라도 좌석 화면 요소가 먼저 보이면 통과 처리
            try:
                seat_ready = await self.page.evaluate("""() => {
                    return Boolean(
                        document.querySelector("canvas")
                        || [...document.querySelectorAll("button, div, span")]
                            .some(el => (el.textContent || "").includes("결제하기"))
                    );
                }""")
                if seat_ready:
                    print(f"      -> 대기열 통과! (좌석 화면 선감지, 폴링 {poll_count}회)")
                    self._be.queue_poll_count = poll_count
                    return True
            except Exception:
                pass

            # 순위 읽기
            try:
                rank_text = await self.page.evaluate("""() => {
                    const el = document.querySelector('.text-5xl, .text-red-500');
                    return el ? el.textContent.trim() : '?';
                }""")
                if poll_count % 5 == 0:
                    print(f"      대기 중... (순위: {rank_text}, 폴링: {poll_count}회)")
            except Exception:
                pass

            poll_elapsed = (time.time() - poll_start) * 1000
            self._be.queue_poll_intervals_ms.append(round(poll_elapsed, 2))

            # 폴링 간격
            if self.cfg["queue_ignore_server_interval"]:
                p_min, p_max = self.cfg["queue_poll_ms"]
                wait = random.uniform(p_min, p_max)
            else:
                wait = 3000  # 서버 기본값 사용

            await asyncio.sleep(wait / 1000.0)

        self._be.queue_poll_count = poll_count
        print(f"      -> 대기열 타임아웃")
        return False

    # ================================================================
    # Step 5: 좌석 선택 (/shows/{showId}/seat)
    # ================================================================

    async def step5_select_seats(self, show_id: int):
        """
        좌석 선택 - DOM 기반 (PixiJS Canvas도 폴백 지원)
        스크린샷 확인: 좌석은 일반 DOM 요소 (원형 div/button)
        색상: VIP=보라, R=녹, S=파랑, A=노랑 / 선택시=빨강 / 예매됨=회색
        """
        print(f"\n  [Step 5/8] 좌석 선점")
        self._be.api_call_sequence.append("seat_select")
        await self._dismiss_popups()

        # 좌석 페이지가 아니면 이동
        if "/seat" not in self.page.url:
            await self.page.goto(
                f"{self.base_url}/shows/{show_id}/seat",
                wait_until="networkidle",
            )

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        seat_view_start = time.time()

        d_min, d_max = self.cfg["seat_select_delay_ms"]
        think_time = random.uniform(d_min, d_max)
        print(f"      좌석 고르는 중... ({think_time/1000:.1f}초)")
        await asyncio.sleep(think_time / 1000.0)

        max_seats = self.booking.get("seat_count", 2)
        target_grade = self.booking.get("seat_grade", "any").lower()

        # ── DOM에서 좌석 요소 찾기 (JS로 available 좌석 수집) ──
        available_count = await self.page.evaluate("""(targetGrade) => {
            // PixiJS Canvas 존재 여부 확인
            if (document.querySelector('canvas')) return -1;  // Canvas면 -1

            // DOM 좌석: 클릭 가능한 원형 요소 찾기
            // available 좌석 = 회색(reserved)이 아닌 색상이 있는 좌석
            const allEls = document.querySelectorAll(
                'circle, [class*="seat"], [data-seat], [data-status]'
            );
            return allEls.length;
        }""", target_grade)

        if available_count == -1:
            # Canvas 기반 → Canvas 좌표 클릭
            print(f"      PixiJS Canvas 감지 → Canvas 좌표 클릭")
            return await self._select_seats_canvas(max_seats)

        # ── DOM 기반 좌석 선택 (최대 3회 재시도) ──
        max_attempts = self.cfg.get("max_seat_attempts", 5)
        for attempt in range(max_attempts):
            selected = await self.page.evaluate(f"""(maxSeats) => {{
                // 좌석 후보 셀렉터
                const seatSelectors = [
                    'circle[fill]:not([fill="#aaaaaa"]):not([fill="#f1f1f4"]):not([fill="rgb(170,170,170)"])',
                    '[data-status="available"]',
                    '[class*="seat"]:not([class*="reserved"]):not([class*="unavailable"]):not([class*="sold"])',
                    'g[cursor="pointer"] circle',
                    'circle[cursor="pointer"]',
                    'g[style*="cursor: pointer"] circle',
                ];

                let seats = [];
                for (const sel of seatSelectors) {{
                    const found = document.querySelectorAll(sel);
                    if (found.length > 0) {{
                        seats = [...found];
                        break;
                    }}
                }}

                if (seats.length === 0) {{
                    // 폴백: circle 중 회색 아닌 것
                    const all = document.querySelectorAll('circle, rect');
                    seats = [...all].filter(el => {{
                        const fill = (el.getAttribute('fill') || '').toLowerCase();
                        return fill && fill !== 'none' && fill !== '#ffffff'
                               && !fill.includes('aaa') && !fill.includes('f1f1');
                    }});
                }}

                if (seats.length === 0) return {{found: 0, clicked: 0}};

                // 클릭
                let clicked = 0;
                const toClick = Math.min(maxSeats, seats.length);
                for (let i = 0; i < toClick; i++) {{
                    const seat = seats[i];
                    // 마우스 이벤트 순서대로 발생 (pointerdown → click)
                    seat.dispatchEvent(new PointerEvent('pointerdown', {{bubbles:true}}));
                    seat.dispatchEvent(new PointerEvent('pointerup', {{bubbles:true}}));
                    seat.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
                    clicked++;
                }}
                return {{found: seats.length, clicked: clicked}};
            }}""", max_seats)

            found = selected.get("found", 0) if isinstance(selected, dict) else 0
            clicked = selected.get("clicked", 0) if isinstance(selected, dict) else selected

            if clicked > 0:
                self._be.seat_hold_attempts = clicked
                self._be.seat_view_to_hold_ms = (time.time() - seat_view_start) * 1000
                self._be.selected_seat_ids = list(range(clicked))
                print(f"      -> 좌석 {clicked}석 선택 완료 (DOM, 가용 {found}석, 시도 {attempt+1}회)")
                # 선택 패널에 좌석 수 표시되는지 확인
                await asyncio.sleep(0.5)
                return True

            print(f"      [!] 좌석 선택 실패 (시도 {attempt+1}/{max_attempts}, 가용 {found}석)")
            await asyncio.sleep(1)

        # 최종 폴백: 좌표 클릭
        print(f"      DOM 선택 전부 실패, 좌표 클릭 시도")
        return await self._select_seats_canvas(max_seats)

    async def _select_seats_canvas(self, max_seats: int):
        """Canvas 또는 DOM 폴백: 좌석 영역에서 좌표 클릭"""
        # 페이지에서 좌석 영역 찾기
        canvas = await self.page.query_selector('canvas')
        if canvas:
            box = await canvas.bounding_box()
        else:
            # 전체 페이지 콘텐츠 영역
            box = await self.page.evaluate("""() => {
                const main = document.querySelector('main') || document.body;
                const r = main.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }""")

        if not box:
            print(f"      [!] 좌석 영역을 찾을 수 없음")
            return False

        cx, cy = box["x"], box["y"]
        cw, ch = box["width"], box["height"]

        selected = 0
        for i in range(max_seats):
            # 좌석 영역 (상단 30~60% 범위에 1층 좌석 분포)
            sx = cx + cw * random.uniform(0.2, 0.8)
            sy = cy + ch * random.uniform(0.15, 0.55)

            await self.mouse.click_at(sx, sy)
            selected += 1
            self._be.seat_hold_attempts += 1
            print(f"      좌석 {selected}/{max_seats} 클릭 (x={sx:.0f}, y={sy:.0f})")
            # 좌석 반영은 너무 빠르게 넘기면 누락되는 경우가 있어 별도 안정화 대기
            await asyncio.sleep(random.uniform(0.35, 0.7))

        print(f"      -> 좌석 {selected}석 클릭 (좌표)")
        return selected > 0

    async def _read_booking_state(self) -> dict:
        """현재 페이지에서 선택 좌석 수와 결제 금액을 추정한다."""
        try:
            return await self.page.evaluate("""() => {
                const text = (document.body.innerText || "").replace(/\\s+/g, " ");

                const parseAmount = (source) => {
                    const patterns = [
                        /총\\s*(\\d[\\d,]*)원\\s*결제하기/,
                        /(\\d[\\d,]*)원\\s*결제하기/,
                        /(\\d[\\d,]*)원\\s*결제/,
                        /총\\s*(\\d[\\d,]*)원/,
                        /합계\\s*(\\d[\\d,]*)원/,
                        /결제\\s*금액\\s*(\\d[\\d,]*)원/,
                        /상품\\s*금액\\s*(\\d[\\d,]*)원/,
                        /최종\\s*금액\\s*(\\d[\\d,]*)원/,
                    ];
                    for (const pattern of patterns) {
                        const match = source.match(pattern);
                        if (match) {
                            const value = parseInt(match[1].replace(/,/g, ""), 10);
                            if (!Number.isNaN(value)) return value;
                        }
                    }
                    return 0;
                };

                const countPatterns = [
                    /선택\\s*좌석\\s*(\\d+)/,
                    /총\\s*(\\d+)\\s*매/,
                    /선택\\s*매수\\s*(\\d+)/,
                ];
                let selectedCount = 0;
                for (const pattern of countPatterns) {
                    const match = text.match(pattern);
                    if (match) {
                        selectedCount = parseInt(match[1], 10);
                        if (!Number.isNaN(selectedCount)) break;
                    }
                }

                const buttonTexts = [...document.querySelectorAll("button, [role='button'], div, span, p, strong")]
                    .map(el => (el.textContent || "").replace(/\\s+/g, " ").trim())
                    .filter(Boolean)
                    .filter(value =>
                        value.includes("결제")
                        || value.includes("좌석")
                        || value.includes("총")
                        || value.includes("금액")
                        || value.includes("합계")
                    )
                    .slice(0, 25);

                let amount = parseAmount(text);
                if (amount === 0) {
                    for (const value of buttonTexts) {
                        amount = parseAmount(value);
                        if (amount > 0) break;
                    }
                }

                return {
                    selectedCount,
                    amount,
                    buttonTexts,
                };
            }""")
        except Exception:
            return {
                "selectedCount": 0,
                "amount": 0,
                "buttonTexts": [],
            }

    async def _wait_for_booking_state(self, *,
                                      min_selected: int = 0,
                                      require_amount: bool = False,
                                      timeout_ms: int = 8000,
                                      label: str = "") -> bool:
        """선택 좌석 수/결제 금액이 반영될 때까지 대기한다."""
        deadline = time.time() + timeout_ms / 1000.0
        last_state = None

        while time.time() < deadline:
            state = await self._read_booking_state()
            last_state = state

            selected_ok = min_selected <= 0 or state.get("selectedCount", 0) >= min_selected
            amount_ok = (state.get("amount", 0) > 0) if require_amount else True
            if selected_ok and amount_ok:
                if label:
                    print(
                        f"      -> {label} 확인 "
                        f"(선택 {state.get('selectedCount', 0)}석, 금액 {state.get('amount', 0)}원)"
                    )
                return True

            await asyncio.sleep(0.6)

        if label and last_state:
            print(
                f"      [!] {label} 대기 실패 "
                f"(선택 {last_state.get('selectedCount', 0)}석, 금액 {last_state.get('amount', 0)}원)"
            )
            print(f"      [DEBUG] UI 텍스트 후보: {last_state.get('buttonTexts', [])}")
        return False

    # ================================================================
    # Step 6: 결제하기 클릭 → 결제 페이지
    # ================================================================

    async def step6_to_payment(self):
        """
        결제하기 버튼 클릭 → /payments 페이지 이동
        - 버튼 텍스트: "N원 결제하기"
        """
        print(f"\n  [Step 6/8] Booking 생성 + 결제 페이지 이동")
        self._be.api_call_sequence.append("to_payment")
        await self._dismiss_popups()

        await self._delay()

        ready = await self._wait_for_booking_state(
            min_selected=0,
            require_amount=True,
            timeout_ms=12000,
            label="좌석/금액 반영",
        )
        if not ready:
            raise RuntimeError("좌석 선택 후 결제 금액이 0원 상태로 유지됨")

        try:
            await self._click_selector(
                'button:has-text("결제하기")',
                "결제하기 버튼"
            )
        except Exception:
            # 직접 이동
            await self.page.goto(f"{self.base_url}/payments", wait_until="networkidle")

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # 실제 결제 페이지로 이동했는지 확인
        if "/payments" not in self.page.url:
            print(f"      [!] 결제 페이지 이동 실패 (현재: {self.page.url})")
            print(f"      [!] 좌석 선점이 안 됐을 수 있음, 직접 이동 시도")
            await self.page.goto(f"{self.base_url}/payments", wait_until="networkidle")
            await asyncio.sleep(1)

        payment_ready = await self._wait_for_booking_state(
            min_selected=0,
            require_amount=True,
            timeout_ms=10000,
            label="결제 페이지 금액 반영",
        )
        if not payment_ready:
            raise RuntimeError("결제 페이지 금액이 0원 상태로 유지됨")

        print(f"      -> 결제 페이지 로딩 완료 ({self.page.url})")

    async def _wait_for_payment_form_ready(self, timeout_ms: int = 12000) -> bool:
        """예약자 정보 입력 폼이 실제로 보일 때까지 기다린다."""
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                ready = await self.page.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.width > 0
                            && rect.height > 0;
                    };

                    const inputs = [...document.querySelectorAll("input, textarea")]
                        .filter(isVisible);
                    const buttons = [...document.querySelectorAll("button, [role='button']")]
                        .filter(isVisible)
                        .map(el => (el.textContent || "").replace(/\\s+/g, " ").trim())
                        .filter(Boolean);
                    const text = (document.body.innerText || "").replace(/\\s+/g, " ");

                    const hasFormText = text.includes("예약자 정보")
                        || text.includes("티켓 수령 방법")
                        || text.includes("결제수단");
                    const hasPaymentButton = buttons.some(value => value.includes("결제하기"));
                    return hasFormText && inputs.length >= 3 && hasPaymentButton;
                }""")
                if ready:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def _debug_payment_page(self):
        """결제 페이지에서 보이는 입력칸/버튼 정보를 출력한다."""
        try:
            inputs = await self.page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none"
                        && style.visibility !== "hidden"
                        && rect.width > 0
                        && rect.height > 0;
                };
                return [...document.querySelectorAll("input, textarea, select")]
                    .filter(isVisible)
                    .slice(0, 20)
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        name: el.getAttribute("name") || "",
                        id: el.id || "",
                        type: el.getAttribute("type") || "",
                        placeholder: el.getAttribute("placeholder") || "",
                        value: el.value || "",
                    }));
            }""")
            buttons = await self.page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none"
                        && style.visibility !== "hidden"
                        && rect.width > 0
                        && rect.height > 0;
                };
                return [...document.querySelectorAll("button, [role='button'], label, div, span")]
                    .filter(isVisible)
                    .map(el => (el.textContent || "").replace(/\\s+/g, " ").trim())
                    .filter(Boolean)
                    .filter(value =>
                        value.includes("결제")
                        || value.includes("동의")
                        || value.includes("현장수령")
                        || value.includes("무통장")
                        || value.includes("간편")
                    )
                    .slice(0, 30);
            }""")
            print(f"      [DEBUG] 결제 페이지 input: {inputs}")
            print(f"      [DEBUG] 결제 페이지 버튼/텍스트: {buttons}")
        except Exception as exc:
            print(f"      [DEBUG] 결제 페이지 디버그 실패: {type(exc).__name__}")

    async def _click_text_candidates(self, texts: list[str], desc: str) -> bool:
        """페이지 내에서 후보 텍스트를 포함하는 클릭 가능한 요소를 찾는다."""
        for text in texts:
            selectors = [
                f'button:has-text("{text}")',
                f'label:has-text("{text}")',
                f'[role="button"]:has-text("{text}")',
                f'text={text}',
            ]

            for selector in selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if not el or not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(0.1)
                    box = await el.bounding_box()
                    if box:
                        print(f"      클릭: {desc}")
                        await self.mouse.click_at(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    else:
                        print(f"      클릭(force): {desc}")
                        await el.click(force=True)
                    return True
                except Exception:
                    continue

            try:
                clicked = await self.page.evaluate("""(targetText) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.width > 0
                            && rect.height > 0;
                    };

                    const candidates = [...document.querySelectorAll("button, label, [role='button'], div, span")];
                    const match = candidates.find(el =>
                        isVisible(el) && (el.textContent || "").includes(targetText)
                    );
                    if (!match) return false;

                    const clickable = match.closest("button, label, [role='button']") || match;
                    clickable.click();
                    return true;
                }""", text)
                if clicked:
                    print(f"      클릭(JS): {desc}")
                    return True
            except Exception:
                pass

        return False

    # ================================================================
    # Step 7: 예약자 정보 입력 + 결제
    # ================================================================

    async def step7_payment(self, applicant: dict):
        """
        결제 페이지 (/payments) 전체 폼 처리

        폼 구조:
          [예약자 정보]
            - name (이름): placeholder "홍길동"
            - birth (생년월일): placeholder "19990129" (8자리)
            - email (이메일): placeholder "XXXX@naver.com"
            - phone (전화번호): placeholder "01012345678" (11자리, - 제외)

          [티켓 수령 방법]
            - "현장수령" (value="NONE") — 현재 유일한 옵션

          [결제수단]
            - "간편 결제 · 카드 결제" (value="CARD")
            - "무통장 입금" (value="VIRTUAL_ACCOUNT")
            ※ 무통장 선택 시 → Toss SDK 내부에서 은행선택/입금자명 처리
            ※ 소득공제 = Toss SDK 내부 하드코딩 ("소득공제" 자동 적용)

          [약관 동의] — 커스텀 체크마크 (✓)
            - "이용약관 전체 동의" → 전체 토글
            - "(필수) 취소 규정 안내" — agrees[0], 필수
            - "(필수) 티켓 이용정책 동의" — agrees[1], 필수
            - "개인정보 제 3자 제공 안내" — agrees[2], 선택

          [결제 버튼]
            - "총 N원 결제하기" (bg-[#F93E4B])
            - 제한시간: 7분 카운트다운
        """
        print(f"\n  [Step 7/8] Payment-ready + 예약자 정보 입력")
        self._be.api_call_sequence.append("payment")
        # 결제 페이지에서는 dismiss 안 함 (결제 모달 오닫기 방지)

        ready = await self._wait_for_payment_form_ready()
        if not ready:
            await self._debug_payment_page()
            raise RuntimeError("결제 페이지 폼이 준비되지 않음")

        # ── 1. 예약자 정보 입력 ──
        print(f"      [예약자 정보]")

        fields = [
            (
                ['input[name="name"]', 'input[id="name"]', 'input[placeholder*="홍길동"]',
                 'input[autocomplete="name"]', 'input[type="text"]'],
                ["name", "이름", "홍길동"],
                applicant["name"],
                "이름",
            ),
            (
                ['input[name="birth"]', 'input[id="birth"]', 'input[placeholder*="1999"]',
                 'input[maxlength="8"]', 'input[inputmode="numeric"]'],
                ["birth", "생년월일", "1999"],
                applicant["birth"],
                "생년월일",
            ),
            (
                ['input[name="email"]', 'input[id="email"]', 'input[type="email"]',
                 'input[placeholder*="@"]'],
                ["email", "이메일", "mail", "@"],
                applicant["email"],
                "이메일",
            ),
            (
                ['input[name="phone"]', 'input[id="phone"]', 'input[type="tel"]',
                 'input[inputmode="tel"]', 'input[placeholder*="010"]'],
                ["phone", "전화", "휴대폰", "010"],
                applicant["phone"],
                "전화번호",
            ),
        ]

        for selectors, keywords, value, label in fields:
            display = mask_email(value) if label == "이메일" else value
            print(f"      {label}: {display}")
            ok = await self._fill_form_field(selectors, value, label, keywords)
            if not ok:
                await self._debug_payment_page()
                raise RuntimeError(f"{label} 입력 실패")
            await self._delay()

        # 사람 시뮬: 입력 후 스크롤
        if self.level >= 7:
            await self._scroll()

        # ── 2. 티켓 수령 방법 ──
        print(f"      [수령방법] 현장수령")
        receipt_ok = await self._click_text_candidates(["현장수령", "현장 수령"], "현장수령 선택")
        if not receipt_ok:
            await self._debug_payment_page()
            raise RuntimeError("현장수령 선택 실패")
        await self._delay()

        # ── 3. 결제수단 선택 ──
        pay_method = self.booking.get("pay_method", "CARD")
        if pay_method == "CARD":
            pay_label = "간편 결제"
            pay_desc = "카드/간편결제"
        else:
            pay_label = "무통장 입금"
            pay_desc = "무통장 입금 (은행선택/소득공제는 Toss에서 처리)"

        print(f"      [결제수단] {pay_desc}")
        method_candidates = (
            ["간편 결제", "간편결제", "카드 결제"]
            if pay_method == "CARD"
            else ["무통장 입금", "무통장입금"]
        )
        method_ok = await self._click_text_candidates(method_candidates, f"{pay_label} 선택")
        if not method_ok:
            await self._debug_payment_page()
            raise RuntimeError(f"{pay_label} 선택 실패")
        await self._delay()

        # 사람 시뮬: 결제수단 선택 후 스크롤
        if self.level >= 6:
            await self._scroll()

        # ── 4. 약관 동의 ──
        # 무조건 "전체 동의"만 누름 (개별 먼저 누르면 토글 꼬임)
        print(f"      [약관 동의]")
        agreed = await self._click_text_candidates(
            ["전체 동의", "이용약관 전체 동의", "전체동의"], "전체 동의"
        )
        if agreed:
            print(f"      -> 전체 동의 체크 완료")
        else:
            await self._check_agreements_individually()

        await self._delay()

        # ── 5. 결제 전 최종 확인 ──

        # Level 10: 결제 전 망설임
        if self.cfg.get("random_hesitation") and random.random() < 0.2:
            hesitate = random.uniform(1.5, 4.0)
            print(f"      (Lv10: 결제 전 {hesitate:.1f}초 망설임)")
            await asyncio.sleep(hesitate)

        # Level 8+: 금액 확인하듯 스크롤
        if self.level >= 8:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(0.5, 1.5))

        # ── 6. 최종 결제 버튼 클릭 ──
        print(f"      [결제] 최종 결제 버튼 클릭")
        try:
            # "총 N원 결제하기" 버튼 (bg-[#F93E4B])
            clicked = await self._click_text_candidates(
                ["결제하기", "총", "결제"], "최종 결제 버튼"
            )
            if not clicked:
                await self._click_selector(
                    'button:has-text("결제하기")',
                    "최종 결제 버튼"
                )
        except Exception as e:
            await self._debug_payment_page()
            print(f"      [!] 결제 버튼 클릭 실패: {type(e).__name__}")

        # Toss Payments 모달/iframe 로딩 대기
        await asyncio.sleep(3)

        # ── 7. Toss SDK 내부 조작 ──
        await self._handle_toss_sdk(pay_method, applicant)

    # ================================================================
    # Toss Payments SDK 내부 조작
    # ================================================================

    async def _get_toss_frame(self):
        """
        Toss SDK는 iframe 또는 새 창(팝업)으로 열림.
        두 가지 모두 시도하여 Toss 결제 화면에 접근한다.
        """
        # 방법 1: iframe으로 열린 경우
        for frame in self.page.frames:
            url = frame.url
            if "tosspayments" in url or "toss" in url or "brandpay" in url:
                print(f"      [Toss] iframe 감지: {url[:60]}...")
                return frame

        # 방법 2: 새 팝업 창으로 열린 경우
        pages = self.context.pages
        for p in pages:
            if p != self.page and ("toss" in p.url or "tosspayments" in p.url):
                print(f"      [Toss] 팝업 창 감지: {p.url[:60]}...")
                return p

        # 방법 3: 새 창이 열릴 때까지 잠시 대기
        try:
            new_page = await self.context.wait_for_event("page", timeout=5000)
            if "toss" in new_page.url:
                print(f"      [Toss] 새 창 감지: {new_page.url[:60]}...")
                return new_page
        except Exception:
            pass

        # 방법 4: 현재 페이지에서 Toss UI가 직접 렌더링된 경우
        toss_el = await self.page.query_selector(
            '[class*="toss"], [id*="toss"], [data-testid*="toss"]'
        )
        if toss_el:
            print(f"      [Toss] 현재 페이지 내 Toss 엘리먼트 감지")
            return self.page

        return None

    async def _handle_toss_sdk(self, pay_method: str, applicant: dict):
        """
        Toss Payments SDK 모달/iframe 내부 요소 조작

        [카드 결제 (CARD)]
          - 카드사 선택 또는 간편결제(토스페이/카카오페이 등) 선택
          - 카드 정보 입력 (카드번호, 유효기간, CVC 등)

        [무통장 입금 (VIRTUAL_ACCOUNT)]
          - 입금할 은행 선택 (국민, 신한, 우리, 하나 등)
          - 입금자명 입력
          - 현금영수증: 소득공제 / 지출증빙 / 발급안함 선택
          - 소득공제 선택 시: 휴대폰번호 입력
          - 결제하기 버튼 클릭
        """
        print(f"\n  [Step 8/8] Toss Payments 결제 처리")
        self._be.api_call_sequence.append("toss_sdk")

        toss = await self._get_toss_frame()
        if not toss:
            print(f"      [!] Toss SDK 화면을 찾을 수 없음 (iframe/팝업/직접 렌더링 없음)")
            print(f"      [!] 결제 화면이 열리지 않았거나 리다이렉트 방식일 수 있음")
            return

        await asyncio.sleep(1)

        if pay_method == "VIRTUAL_ACCOUNT":
            await self._toss_virtual_account(toss, applicant)
        else:
            await self._toss_card(toss)

    async def _toss_fill_input(self, toss, selectors: list, value: str, label: str):
        """
        Toss SDK iframe/팝업 안에서 input에 값 입력.
        iframe은 keyboard가 frame 레벨이라 page.keyboard 대신 toss에서 직접 처리.
        """
        for sel in selectors:
            try:
                field = await toss.query_selector(sel)
                if not field:
                    continue
                if not await field.is_visible():
                    continue

                # 방법 1: focus → 전체삭제 → 한 글자씩 입력
                await field.focus()
                await asyncio.sleep(0.1)
                await field.press("Control+A")
                await field.press("Backspace")
                await asyncio.sleep(0.1)

                # 한 글자씩 press (type보다 확실)
                for char in value:
                    await field.press(char)
                    await asyncio.sleep(0.02)

                try:
                    current = await field.input_value()
                    if current and len(current) >= len(value) - 1:
                        print(f"      -> {label} 입력 완료 (press)")
                        return True
                except Exception:
                    pass

                # 방법 2: field.type
                try:
                    await field.click(force=True)
                    await field.press("Control+A")
                    await field.press("Backspace")
                    await field.type(value, delay=30)
                    print(f"      -> {label} 입력 완료 (type)")
                    return True
                except Exception:
                    pass

                # 방법 3: fill
                try:
                    await field.fill(value)
                    print(f"      -> {label} 입력 완료 (fill)")
                    return True
                except Exception:
                    pass

                # 방법 4: JS 직접
                try:
                    await field.evaluate(f"""(el) => {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(el, '{value}');
                        el.dispatchEvent(new Event('input', {{bubbles:true}}));
                        el.dispatchEvent(new Event('change', {{bubbles:true}}));
                    }}""")
                    print(f"      -> {label} 입력 완료 (JS)")
                    return True
                except Exception:
                    pass

            except Exception:
                continue

        print(f"      [!] {label} 입력 실패")
        return False

    async def _toss_click_text(self, toss, text: str, label: str):
        """
        Toss SDK 안에서 텍스트로 요소 클릭.
        사람처럼 마우스로 이동 → 클릭 (가능하면).
        """
        # 방법 1: 텍스트로 찾아서 마우스 클릭 (사람처럼)
        try:
            btn = await toss.query_selector(f'text={text}')
            if btn and await btn.is_visible():
                box = await btn.bounding_box()
                if box:
                    # 마우스로 이동 후 클릭 (사람처럼)
                    await self.mouse.click_at(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    await asyncio.sleep(0.3)
                    print(f"      -> {label} 완료 (마우스)")
                    return True
                else:
                    await btn.click(force=True)
                    print(f"      -> {label} 완료")
                    return True
        except Exception:
            pass

        # 방법 2: force 클릭
        try:
            btn = await toss.query_selector(f'text={text}')
            if btn:
                await btn.click(force=True)
                print(f"      -> {label} 완료 (force)")
                return True
        except Exception:
            pass

        # 방법 3: JS 텍스트 매칭
        try:
            clicked = await toss.evaluate(f"""() => {{
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                while (walker.nextNode()) {{
                    if (walker.currentNode.textContent.includes('{text}')) {{
                        const el = walker.currentNode.parentElement;
                        if (el) {{ el.click(); return true; }}
                    }}
                }}
                return false;
            }}""")
            if clicked:
                print(f"      -> {label} 완료 (JS)")
                return True
        except Exception:
            pass

        return False

    async def _toss_click_any_text(self, toss, texts: list[str], label: str) -> bool:
        """여러 후보 텍스트 중 하나를 찾아 클릭."""
        for text in texts:
            if await self._toss_click_text(toss, text, f"{label} ({text})"):
                return True
        return False

    async def _toss_select_receipt_option(self, toss) -> bool:
        """현금영수증을 발급안함으로 선택한다."""
        aliases = ["발급안함", "미발행", "신청안함", "발행안함", "안 함", "안함", "미신청"]
        trigger_texts = ["소득공제용(휴대폰)", "현금영수증", "발급안함", "미발행"]
        selected_by_select = False

        await self._toss_click_any_text(toss, trigger_texts, "현금영수증 선택창 열기")
        await asyncio.sleep(0.5)

        try:
            select = await toss.query_selector('select[name="cashReceiptCode"], select[id*="cashReceipt"], select')
            if select and await select.is_visible():
                options = await select.evaluate("""(el) => {
                    return [...el.options].map(opt => ({
                        value: opt.value || "",
                        label: (opt.textContent || "").trim(),
                    }));
                }""")
                for option in options:
                    option_text = f"{option.get('label', '')} {option.get('value', '')}"
                    if any(alias in option_text for alias in aliases):
                        await select.select_option(value=option["value"])
                        print(f"      -> 현금영수증 선택 완료 (select: {option['label'] or option['value']})")
                        selected_by_select = True
                        break
        except Exception:
            pass

        clicked = await self._toss_click_any_text(toss, aliases, "현금영수증 선택")
        await asyncio.sleep(0.5)
        # 최종 "확인" 버튼은 필수 라디오/체크 이후에만 누른다.
        # 여기서는 현금영수증 값만 선택하고 종료한다.
        return selected_by_select or clicked

    async def _toss_accept_required_agreements(self, toss) -> bool:
        """
        Toss iframe 하단의 필수 체크박스/라디오를 클릭한다.
        """
        try:
            result = await toss.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none"
                        && style.visibility !== "hidden"
                        && rect.width > 0
                        && rect.height > 0;
                };
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const requiredHints = [
                    "필수", "약관", "동의", "개인정보",
                    "전자금융거래", "서비스 이용", "개인(신용)정보",
                ];

                const controls = [...document.querySelectorAll('input[type="checkbox"], input[type="radio"]')];
                let clicked = 0;

                for (const control of controls) {
                    if (control.checked) continue;
                    const label = control.closest("label");
                    const scope = label || control.parentElement || control;
                    if (!isVisible(scope) && !isVisible(control)) continue;

                    const text = normalize(scope?.textContent || label?.textContent || "");
                    if (!requiredHints.some(hint => text.includes(hint))) continue;

                    if (label && isVisible(label)) {
                        label.click();
                    } else {
                        control.click();
                    }
                    clicked += 1;
                }

                const remaining = [...document.querySelectorAll('input[type="checkbox"], input[type="radio"]')]
                    .filter(control => {
                        if (control.checked) return false;
                        const label = control.closest("label");
                        const scope = label || control.parentElement || control;
                        if (!isVisible(scope) && !isVisible(control)) return false;
                        const text = normalize(scope?.textContent || "");
                        return requiredHints.some(hint => text.includes(hint));
                    }).length;

                return {clicked, remaining};
            }""")
        except Exception as exc:
            print(f"      [!] Toss 필수 체크 처리 실패: {type(exc).__name__}")
            return False

        if result.get("clicked"):
            print(f"      -> Toss 필수 체크 클릭: {result['clicked']}개")
        return result.get("remaining", 0) == 0

    async def _toss_click_final_confirm(self, toss) -> bool:
        """
        Toss 마지막 단계의 확인/결제 버튼은 필수 항목 체크가 끝난 뒤에만 누른다.
        """
        await asyncio.sleep(0.5)
        btn_texts = ["확인", "결제하기", "입금하기", "동의하고 결제하기"]
        for txt in btn_texts:
            result = await self._toss_click_text(toss, txt, "Toss 최종 확인")
            if result:
                return True
        return False

    async def _toss_virtual_account(self, toss, applicant: dict):
        """
        Toss SDK - 무통장 입금 처리
        1) 은행 선택
        2) 입금자명 입력
        3) 현금영수증 (소득공제/지출증빙/발급안함)
        4) iframe 하단 필수 체크
        5) 결제하기 클릭
        """
        bank = self.booking.get("bank", "국민")
        depositor = applicant.get("name", "테스트봇")
        cash_receipt = self.booking.get("cash_receipt", "발급안함")

        print(f"      [무통장 입금]")

        # ── 1. 은행 선택 ──
        print(f"      은행 선택: {bank}")
        await self._delay()

        # select 드롭다운 형태
        try:
            bank_select = await toss.query_selector('select')
            if bank_select:
                await bank_select.select_option(label=bank)
                print(f"      -> 은행 선택 완료 (select)")
            else:
                # 버튼/텍스트 형태
                await self._toss_click_text(toss, bank, f"은행 {bank}")
        except Exception as e:
            # 폴백: 텍스트 매칭
            await self._toss_click_text(toss, bank, f"은행 {bank}")
        await self._delay()

        # ── 2. 입금자명 입력 ──
        print(f"      입금자명: {depositor}")
        await self._toss_fill_input(toss, [
            'input[name*="depositor"]',
            'input[name*="name"]',
            'input[placeholder*="입금자"]',
            'input[placeholder*="이름"]',
            'input[placeholder*="성명"]',
            'input:not([type="tel"]):not([type="email"]):not([inputmode="numeric"])',
        ], depositor, "입금자명")
        await self._delay()

        # ── 3. 현금영수증: 발급안함 선택 ──
        print(f"      현금영수증: {cash_receipt}")
        receipt_ok = await self._toss_select_receipt_option(toss)
        if not receipt_ok:
            raise RuntimeError("현금영수증 '발급안함' 선택 실패")

        await self._delay()

        # ── 4. iframe 하단 필수 체크 ──
        print(f"      [Toss] 하단 필수 체크")
        checked = await self._toss_accept_required_agreements(toss)
        if not checked:
            raise RuntimeError("Toss 필수 체크 미완료")
        await self._delay()

        # ── 5. 결제하기 / 확인 버튼 ──
        print(f"      [Toss] 필수 체크 후 최종 확인 버튼 클릭")
        final_clicked = await self._toss_click_final_confirm(toss)
        if not final_clicked:
            raise RuntimeError("Toss 최종 확인 버튼 클릭 실패")

        await asyncio.sleep(3)
        print(f"      -> 무통장 입금 처리 완료")

    async def _toss_card(self, toss):
        """
        Toss SDK - 카드/간편결제 처리
        카드사 선택 → 카드 정보는 테스트 환경에서 Toss가 처리
        """
        card_company = self.booking.get("card_company", "삼성")

        print(f"      [카드 결제]")
        print(f"      카드사: {card_company}")
        await self._delay()

        # 카드사 선택
        result = await self._toss_click_text(toss, card_company, f"{card_company} 선택")
        if not result:
            # 폴백: 아무 카드사나 클릭
            try:
                first = await toss.query_selector('button, [class*="card"], [role="radio"]')
                if first:
                    await first.click(force=True)
                    print(f"      -> 첫 번째 결제수단 선택")
            except Exception:
                pass

        await self._delay()

        # 결제하기 버튼
        btn_texts = ["결제하기", "다음", "확인", "동의하고 결제하기"]
        for txt in btn_texts:
            result = await self._toss_click_text(toss, txt, "Toss 결제")
            if result:
                break

        await asyncio.sleep(3)
        print(f"      -> 카드 결제 처리 완료")

    async def _fill_form_field(self, selectors: list[str], value: str,
                               label: str, keywords: list[str] = None) -> bool:
        """
        결제 폼 필드에 값 입력. inputMode="tel" 등 특수 필드 대응.
        1차: 클릭 → type
        2차: fill
        3차: JS nativeInputValueSetter + React 이벤트
        """
        element = None

        for selector in selectors:
            try:
                candidate = await self.page.query_selector(selector)
                if candidate and await candidate.is_visible():
                    element = candidate
                    break
            except Exception:
                continue

        if not element and keywords:
            try:
                for candidate in await self.page.query_selector_all("input, textarea"):
                    try:
                        if not await candidate.is_visible():
                            continue
                        info = await candidate.evaluate("""(el) => ({
                            name: el.getAttribute("name") || "",
                            id: el.id || "",
                            placeholder: el.getAttribute("placeholder") || "",
                            type: el.getAttribute("type") || "",
                            autocomplete: el.getAttribute("autocomplete") || "",
                            label: [...(el.labels || [])].map(label => label.textContent || "").join(" "),
                        })""")
                        haystack = " ".join(str(info.get(key, "")).lower() for key in info)
                        if any(keyword.lower() in haystack for keyword in keywords):
                            element = candidate
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not element:
            print(f"      [!] {label} 입력 필드 탐색 실패")
            return False

        methods = [
            ("type", self._fill_form_field_by_type),
            ("fill", self._fill_form_field_by_fill),
            ("js", self._fill_form_field_by_js),
        ]

        for method_name, method in methods:
            try:
                ok = await method(element, value)
                if not ok:
                    continue
                current = await element.input_value()
                if current == value:
                    print(f"      -> {label} 입력 완료 ({method_name})")
                    return True
            except Exception:
                continue

        print(f"      [!] {label} 입력 실패")
        return False

    async def _fill_form_field_by_type(self, element, value: str) -> bool:
        await element.click(force=True)
        await asyncio.sleep(0.1)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        await element.type(value, delay=30)
        return True

    async def _fill_form_field_by_fill(self, element, value: str) -> bool:
        await element.click(force=True)
        await element.fill(value)
        return True

    async def _fill_form_field_by_js(self, element, value: str) -> bool:
        await element.evaluate("""(el, nextValue) => {
            const proto = el.tagName === "TEXTAREA"
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
            if (descriptor && descriptor.set) {
                descriptor.set.call(el, nextValue);
            } else {
                el.value = nextValue;
            }
            el.dispatchEvent(new Event("input", {bubbles: true}));
            el.dispatchEvent(new Event("change", {bubbles: true}));
            el.dispatchEvent(new Event("blur", {bubbles: true}));
        }""", value)
        return True

    async def _check_agreements_individually(self):
        """
        약관 3개 개별 체크 (사람처럼 하나씩).
        커스텀 체크마크(✓) 컴포넌트이므로 여러 방법으로 시도.
        """
        agreement_keywords = ["취소 규정", "이용정책", "개인정보"]
        checked = 0

        for keyword in agreement_keywords:
            try:
                # 방법 1: 텍스트 포함 요소의 부모/형제 클릭
                el = await self.page.query_selector(f'text={keyword}')
                if el:
                    # 체크마크는 텍스트 옆에 있으므로 텍스트 자체를 클릭
                    await el.click(force=True)
                    checked += 1
                    await asyncio.sleep(0.3)
                    continue
            except Exception:
                pass

            try:
                # 방법 2: 부모 div 전체를 클릭 (체크마크+텍스트 포함 영역)
                parent = await self.page.evaluate(f"""() => {{
                    const els = [...document.querySelectorAll('*')];
                    const match = els.find(el => el.textContent.includes('{keyword}'));
                    if (match) {{ match.click(); return true; }}
                    return false;
                }}""")
                if parent:
                    checked += 1
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        if checked == 0:
            # 최종 폴백: "전체 동의"를 JS로 강제 클릭
            try:
                await self.page.evaluate("""() => {
                    const els = [...document.querySelectorAll('*')];
                    const agreeAll = els.find(el => el.textContent.includes('전체 동의'));
                    if (agreeAll) agreeAll.click();
                }""")
                print(f"      -> 전체 동의 (JS 강제 클릭)")
                return
            except Exception:
                pass

        print(f"      -> 약관 동의 {checked}/{len(agreement_keywords)}개 체크")

    # ================================================================
    # 데이터 수집
    # ================================================================

    async def _collect_fingerprint(self):
        """브라우저 핑거프린트 수집"""
        try:
            fp = await self.page.evaluate("""() => ({
                wd: navigator.webdriver,
                pl: navigator.plugins.length,
                lang: navigator.languages?.join(',') || '',
                pf: navigator.platform,
                sw: screen.width, sh: screen.height,
                vw: window.innerWidth, vh: window.innerHeight,
                cd: screen.colorDepth,
                tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
            })""")
            self._fe.webdriver_detected = fp.get("wd", True)
            self._fe.plugins_count = fp.get("pl", 0)
            self._fe.languages = fp.get("lang", "")
            self._fe.platform = fp.get("pf", "")
            self._fe.screen_resolution = f"{fp.get('sw')}x{fp.get('sh')}"
            self._fe.viewport_size = f"{fp.get('vw')}x{fp.get('vh')}"
            self._fe.color_depth = fp.get("cd", 0)
            self._fe.timezone = fp.get("tz", "")
        except Exception:
            pass

    async def _collect_telemetry(self):
        """텔레메트리 수집"""
        try:
            tel = await self.page.evaluate("() => window.__tel || {}")

            mouse = tel.get("mouse", [])
            self._fe.mouse_move_count = len(mouse)
            if len(mouse) > 1:
                speeds = []
                for i in range(1, len(mouse)):
                    dx = mouse[i]["x"] - mouse[i-1]["x"]
                    dy = mouse[i]["y"] - mouse[i-1]["y"]
                    dt = max(1, mouse[i]["t"] - mouse[i-1]["t"])
                    speeds.append(math.sqrt(dx*dx + dy*dy) / dt)
                if speeds:
                    self._fe.mouse_move_speed_avg = sum(speeds) / len(speeds)
                    m = self._fe.mouse_move_speed_avg
                    self._fe.mouse_move_speed_var = sum((s-m)**2 for s in speeds) / len(speeds)

                if len(mouse) >= 2:
                    s, e = mouse[0], mouse[-1]
                    straight = math.sqrt((e["x"]-s["x"])**2 + (e["y"]-s["y"])**2)
                    total = sum(
                        math.sqrt((mouse[i]["x"]-mouse[i-1]["x"])**2 +
                                  (mouse[i]["y"]-mouse[i-1]["y"])**2)
                        for i in range(1, len(mouse))
                    )
                    self._fe.mouse_path_linearity = straight / total if total > 0 else 0

            clicks = tel.get("clicks", [])
            self._fe.click_count = len(clicks)
            if len(clicks) > 1:
                self._fe.click_intervals_ms = [
                    clicks[i]["t"] - clicks[i-1]["t"] for i in range(1, len(clicks))
                ]

            keys = [k for k in tel.get("keys", []) if k.get("d") == "dn"]
            self._fe.keystroke_count = len(keys)
            if len(keys) > 1:
                self._fe.keystroke_intervals_ms = [
                    keys[i]["t"] - keys[i-1]["t"] for i in range(1, len(keys))
                ]

            scrolls = tel.get("scrolls", [])
            self._fe.scroll_count = len(scrolls)

            self._fe.page_visibility_changes = tel.get("vis", 0)
            self._fe.focus_blur_count = tel.get("focus", 0)
        except Exception:
            pass

    # ================================================================
    # 전체 플로우 실행
    # ================================================================

    async def run(self, account: dict, show_id: int,
                  schedule_id: int = None, applicant: dict = None) -> tuple:
        """
        전체 예매 플로우 실행.
        매 run마다 새 브라우저를 열고 닫아서 깨끗한 상태 보장.
        """
        flow_start = time.time()

        if not applicant:
            applicant = {
                "name": "테스트봇",
                "birth": "20000101",
                "email": account["email"],
                "phone": "01012345678",
            }

        print(f"\n{'='*60}")
        print(f"  Truve 매크로 실행")
        print(f"  Level {self.level}: {self.cfg['name']}")
        print(f"  {self.cfg['description']}")
        print(f"  계정: {mask_email(account['email'])}")
        print(f"  대상: {self.base_url}/shows/{show_id}")
        bk = self.booking
        print(f"  좌석: {bk['seat_grade'].upper()} / {bk['seat_section']} / {bk['seat_count']}매")
        print(f"  결제: {bk['pay_method']}")
        if bk.get("schedule_date"):
            print(f"  날짜: {bk['schedule_date']} {bk.get('schedule_time', '(첫 회차)')}")
        print(f"{'='*60}")

        try:
            # 매번 새 브라우저 (이전 run의 상태/쿠키 영향 제거)
            await self.setup()

            # ── 실제 API 흐름 순서 ──
            # login → show/schedule → captcha → queue → session/seat → booking → payment → toss

            await self.step1_login(account["email"], account["password"])
            await self._collect_fingerprint()
            await self.step2_select_show(show_id)
            await self.step3_captcha()

            queue_ok = await self.step4_queue(show_id)

            if queue_ok:
                seats_ok = await self.step5_select_seats(show_id)

                if not seats_ok:
                    print(f"\n  [!] 좌석 선택 실패 — 결제 진행 불가, 플로우 중단")
                else:
                    has_selected = await self._wait_for_booking_state(
                        min_selected=0,
                        require_amount=True,
                        timeout_ms=12000,
                        label="좌석 선점 반영",
                    )

                    if not has_selected:
                        print(f"\n  [!] 좌석 선점 확인 실패 (선택 좌석/금액 미반영) — 재시도")
                        # 한번 더 좌석 선택 시도
                        seats_ok = await self.step5_select_seats(show_id)
                        if seats_ok:
                            seats_ok = await self._wait_for_booking_state(
                                min_selected=0,
                                require_amount=True,
                                timeout_ms=12000,
                                label="좌석 선점 재시도 반영",
                            )

                    if seats_ok:
                        await self.step6_to_payment()
                        await self.step7_payment(applicant)

            await self._collect_telemetry()
            print(f"\n  [완료] 매크로 플로우 종료")

        except Exception as e:
            print(f"\n  [에러] {type(e).__name__}: {e}")

        finally:
            elapsed = (time.time() - flow_start) * 1000
            self._be.total_flow_duration_ms = elapsed
            self._be.session_duration_ms = elapsed
            self._fe.time_on_page_ms = elapsed
            self._be.user_agent = self.cfg.get("user_agent", "Chromium")

            if self.keyboard:
                paste_count = sum(1 for k in self.keyboard.keystroke_log if k.get("type") == "paste")
                self._fe.paste_event_count = paste_count

            await self.teardown()

        return self._be, self._fe
