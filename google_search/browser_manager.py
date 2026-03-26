"""
浏览器管理模块（已重构以实现“Infosec-Grade”隐身层）
Browser manager module (refactored to provide an "Infosec-Grade" stealth layer)

主要改进：
- 使用 Chromium 的 `launch_persistent_context`（本地 `./user_data`）使会话可持久化
- 使用 headless="new" 更难被检测
- UA 与 `hardwareConcurrency` / `deviceMemory` 保持一致
- 注入 stealth 补丁（尝试使用 `playwright_stealth`，失败时回退到内置脚本）
- 人类化交互助手：Bezier 鼠标移动，Gaussian 打字延迟，视口轻微抖动
- 区域设置与时区对齐宿主系统

Major improvements:
- Use Chromium's `launch_persistent_context` (local `./user_data`) to persist sessions
- Use `headless="new"` which is harder to detect
- Ensure UA coherence with `hardwareConcurrency` / `deviceMemory`
- Inject stealth patches (attempt `playwright_stealth`, fallback to built-in scripts)
- Humanization helpers: Bezier mouse moves, Gaussian typing delays, slight viewport jitter
- Align locale and timezone with the host system

注意：尽量 graceful degrade（在缺少可选依赖时不抛出错误）
Note: Graceful degradation is applied (do not raise if optional deps missing)
"""
import asyncio
import json
import locale as pylocale
import math
import os
import platform
import random
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

try:
    # optional: psutil gives accurate memory, fall back if missing  # 可选: psutil 提供更精确的内存信息，缺失时回退
    import psutil
except Exception:
    psutil = None

from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
)

from common.types import SavedState, FingerprintConfig
from common import logger
from .fingerprint import get_host_machine_config, get_device_config, playwright_devices


def _detect_locale_timezone(user_locale: Optional[str] = None) -> Tuple[str, str]:
    """Detect host locale and timezone id (best-effort).

    Returns (locale_str, timezone_id)
    """
    # locale  # 区域设置
    try:
        loc = user_locale or pylocale.getdefaultlocale()[0] or os.getenv("LANG", "en-US")
    except Exception:
        loc = user_locale or os.getenv("LANG", "en-US")

    # timezone (best-effort): prefer IANA via tzinfo.key if available  # 时区（尽量使用 IANA 名称，如果可用）
    try:
        tz = datetime.now().astimezone().tzinfo
        tzname = getattr(tz, "key", None) or getattr(tz, "zone", None) or tz.tzname(None)
        if not tzname:
            tzname = "UTC"
        # Normalize common short timezone abbreviations to IANA names for Playwright
        short_map = {
            'MDT': 'America/Denver',
            'MST': 'America/Denver',
            'PDT': 'America/Los_Angeles',
            'PST': 'America/Los_Angeles',
            'EDT': 'America/New_York',
            'EST': 'America/New_York',
            'CET': 'Europe/Berlin',
            'CEST': 'Europe/Berlin',
            'BST': 'Europe/London',
            'GMT': 'Etc/GMT'
        }
        if isinstance(tzname, str) and len(tzname) <= 4 and tzname.upper() in short_map:
            tzname = short_map[tzname.upper()]
    except Exception:
        tzname = "UTC"

    return loc, tzname


def _hardware_profile() -> Dict[str, int]:
    """Return keys: hardwareConcurrency (cpus), deviceMemory (GB)

    Falls back to reasonable defaults when info is unavailable.
    """
    cpus = os.cpu_count() or 4
    # device memory in GB  # 设备内存（GB）
    if psutil:
        try:
            mem_gb = max(1, int(psutil.virtual_memory().total / (1024 ** 3)))
        except Exception:
            mem_gb = 8
    else:
        # guess based on platform  # 根据平台猜测
        if platform.system().lower() == "linux":
            mem_gb = 8
        elif platform.system().lower() == "darwin":
            mem_gb = 16
        else:
            mem_gb = 8

    return {"hardwareConcurrency": int(cpus), "deviceMemory": int(mem_gb)}


class BrowserManager:
    """浏览器管理器（提供隐身补丁与人类化交互工具）
    Browser manager (provides stealth patches and humanization helpers)
    """

    def __init__(self, user_data_dir: str = "./user_data"):
        self.google_domains = [
            "https://www.google.com",
            "https://www.google.co.uk",
            "https://www.google.ca",
            "https://www.google.com.au",
        ]
        self.user_data_dir = user_data_dir

    async def launch_browser(self, headless: bool, timeout: int, locale: Optional[str] = None) -> Tuple[Playwright, BrowserContext]:
        """Start a persistent Chromium context (returns (playwright, context)).

        Uses headless="new" when headless is True.
        """
        # 启动持久化浏览器上下文 headless=... user_data=...
        # Starting persistent browser context headless=... user_data=...  # 启动持久化浏览器上下文 headless=... user_data=...
        logger.info(f"Starting persistent browser context headless={headless} user_data={self.user_data_dir}")

        p = await async_playwright().start()
        # Some Playwright versions expect a boolean for `headless` on persistent contexts.
        # Use the boolean value to maximize compatibility.
        headless_val = bool(headless)

        # Determine fingerprint / locale / timezone  # 确定指纹 / 区域 / 时区
        detected_locale, detected_tz = _detect_locale_timezone(locale)

        # Get device config (UA, viewport...) from fingerprint module  # 从指纹模块获取设备配置（UA、视口等）
        device_name, device_config = get_device_config(None)

        # Jitter the viewport slightly to simulate visual jitter  # 视口轻微抖动以模拟视觉抖动
        base_viewport = device_config.get("viewport", {"width": 1920, "height": 1080})
        jitter_x = random.randint(-50, 50)
        jitter_y = random.randint(-50, 50)
        viewport = {"width": max(800, base_viewport.get("width", 1920) + jitter_x),
                    "height": max(600, base_viewport.get("height", 1080) + jitter_y)}

        # coherent hardware profile  # 一致的硬件配置
        hw = _hardware_profile()

        # ensure UA coherence: start from device user agent and avoid generic "Headless"  # 确保 UA 一致性：使用设备 UA，避免出现通用的 "Headless"
        user_agent = device_config.get("user_agent") or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Context creation options: persistent context accepts many of the same options  # 上下文创建选项：持久化上下文支持许多相同选项
        ctx_kwargs: Dict[str, Any] = {
            "viewport": viewport,
            "user_agent": user_agent,
            "locale": detected_locale,
            "timezone_id": detected_tz,
            "accept_downloads": True,
            "bypass_csp": False,
            "java_script_enabled": True,
            "permissions": ["geolocation", "notifications"],
            # ensure desktop  # 确保桌面模式
            "is_mobile": False,
            "has_touch": False,
        }

        # Ensure user_data_dir exists  # 确保 user_data 目录存在
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        # Launch persistent context  # 启动持久化上下文
        context = await p.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=headless_val,
            timeout=timeout * 2,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-web-security",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--hide-scrollbars",
                "--mute-audio",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-breakpad",
                "--disable-component-extensions-with-background-pages",
                "--disable-extensions",
                "--disable-features=TranslateUI",
                "--disable-ipc-flooding-protection",
                "--disable-renderer-backgrounding",
                "--enable-features=NetworkService,NetworkServiceInProcess",
                "--force-color-profile=srgb",
                "--metrics-recording-only",
            ],
            **ctx_kwargs,
        )

        # Apply stealth/init scripts to context (overrides navigator, chrome, outerWidth/Height, etc.)  # 应用隐身/初始化脚本到上下文（覆盖 navigator、chrome、outerWidth/Height 等）
        await self._apply_stealth_context_scripts(context, user_agent, hw)

        # 持久化浏览器上下文已启动并注入隐身补丁
        # Persistent browser context started and stealth patches injected  # 持久化浏览器上下文已启动并注入隐身补丁
        logger.info("Persistent browser context started and stealth patches injected")
        return p, context

    async def _apply_stealth_context_scripts(self, context: BrowserContext, user_agent: str, hw: Dict[str, int]) -> None:
        """Inject a set of init scripts to reduce automation fingerprints.

        Tries to use `playwright_stealth` if available (graceful), otherwise injects fallback scripts.
        """
        # core init script: overrides that must run before any page script  # 核心 init 脚本：必须在页面脚本之前运行的覆盖项
        init_script = f"""
        // Navigator stealth
        Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
        Object.defineProperty(navigator, 'vendor', {{ get: () => 'Google Inc.' }});
        Object.defineProperty(navigator, 'platform', {{ get: () => navigator.platform || 'Win32' }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hw.get('hardwareConcurrency', 4)} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {hw.get('deviceMemory', 8)} }});

        // chrome.csi stub
        window.chrome = window.chrome || {{}};
        window.chrome.csi = window.chrome.csi || function() {{ return {{}} }};

        // prevent detection via outerWidth/outerHeight
        Object.defineProperty(window, 'outerWidth', {{ get: () => window.innerWidth + 16 }});
        Object.defineProperty(window, 'outerHeight', {{ get: () => window.innerHeight + 96 }});

        // expose userAgent
        Object.defineProperty(navigator, 'userAgent', {{ get: () => '{user_agent}' }});

        // make languages realistic
        Object.defineProperty(navigator, 'languages', {{ get: () => ['en-US', 'en'] }});

        // remove webdriver related attributes on elements
        (function() {{
            const origCreate = Document.prototype.createElement;
            Document.prototype.createElement = function(name) {{
                const el = origCreate.call(this, name);
                try {{
                    Object.defineProperty(el, 'webdriver', {{ get: () => undefined }});
                }} catch(e) {{}}
                return el;
            }};
        }})();
        """

        await context.add_init_script(init_script)

        # Inject additional WebGL randomization and other fallbacks  # 注入额外的 WebGL 随机化和回退补丁
        webgl_patch = """
        try {
            if (typeof WebGLRenderingContext !== 'undefined') {
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParameter.call(this, parameter);
                };
            }
        } catch(e) {}
        """
        await context.add_init_script(webgl_patch)

        # attempt to apply playwright_stealth if available (best-effort)  # 尝试在可用时应用 playwright_stealth（尽力而为）
        try:
            from playwright_stealth import stealth_async

            async def _apply_stealth_to_existing_pages():
                for pg in context.pages:
                    try:
                        await stealth_async(pg)
                    except Exception:
                        pass

            # run for already open pages and also whenever new page is created  # 对已打开页面运行，并在新页面创建时运行
            await _apply_stealth_to_existing_pages()

            async def _on_page(page):
                try:
                    await stealth_async(page)
                except Exception:
                    pass

            context.on("page", lambda page: asyncio.create_task(_on_page(page)))
            # playwright_stealth 已加载并应用到上下文（如果可用）
            # playwright_stealth loaded and applied to context (if available)
            logger.info("playwright_stealth loaded and applied to context (if available)")
        except Exception:
            # playwright_stealth 不可用，使用内置 init scripts 回退
            # playwright_stealth not available, falling back to built-in init scripts
            logger.debug("playwright_stealth not available, falling back to built-in init scripts")

    async def create_context(self, browser_or_context, saved_state: SavedState, state_file: str, locale: str) -> BrowserContext:
        """Return a usable BrowserContext.

        If `browser_or_context` is already a BrowserContext, return it (after ensuring fingerprint coherence).
        If it is a Browser, create a new context from it (legacy behavior).
        """
        # If the provided object has `new_page` and not `new_context`, assume it's a BrowserContext  # 如果提供的对象有 `new_page` 且没有 `new_context`，则假定它是一个 BrowserContext
        if hasattr(browser_or_context, "new_page") and not hasattr(browser_or_context, "new_context"):
            context: BrowserContext = browser_or_context  # type: ignore
            # 使用现有的 BrowserContext（持久化上下文）
            # Using existing BrowserContext (persistent context)  # 使用现有的 BrowserContext（持久化上下文）
            logger.info("Using existing BrowserContext (persistent context)")
            return context

        # Else create a fresh context from Browser (legacy path)  # 否则从 Browser 创建新的上下文（旧路径）
        browser: Browser = browser_or_context  # type: ignore
        device_name, device_config = get_device_config(saved_state.fingerprint)

        # base options from device  # 来自设备的基础选项
        context_options = {**device_config}

        if saved_state.fingerprint:
            context_options.update({
                "locale": saved_state.fingerprint.locale,
                "timezone_id": saved_state.fingerprint.timezone_id,
            })
            # 使用保存的浏览器指纹配置
            # Using saved browser fingerprint configuration  # 使用保存的浏览器指纹配置
            logger.info("Using saved browser fingerprint configuration")
        else:
            host_cfg = get_host_machine_config(locale)
            context_options.update({
                "locale": host_cfg.locale,
                "timezone_id": host_cfg.timezone_id,
            })
            saved_state.fingerprint = host_cfg
            # 已生成并保存新的宿主指纹配置
            # Generated and saved new host fingerprint configuration  # 已生成并保存新的宿主指纹配置
            logger.info("Generated and saved new host fingerprint configuration")

        # desktop defaults  # 桌面默认设置
        context_options.update({
            "permissions": ["geolocation", "notifications"],
            "accept_downloads": True,
            "is_mobile": False,
            "has_touch": False,
            "java_script_enabled": True,
        })

        if state_file and Path(state_file).exists():
            context_options["storage_state"] = state_file

        context = await browser.new_context(**context_options)
        await self._apply_stealth_context_scripts(context, context_options.get("user_agent", ""), _hardware_profile())
        return context

    async def create_page(self, context: BrowserContext) -> Page:
        """Create a new page and apply small per-page stealth patches and user-like screen properties."""
        page = await context.new_page()

        # small per-page init scripts for screen and color depth consistency  # 每个页面的小型初始化脚本，用于屏幕和颜色深度一致性
        await page.add_init_script(
            """
            Object.defineProperty(window.screen, 'width', { get: () => window.innerWidth });
            Object.defineProperty(window.screen, 'height', { get: () => window.innerHeight });
            Object.defineProperty(window.screen, 'colorDepth', { get: () => 24 });
            Object.defineProperty(window.screen, 'pixelDepth', { get: () => 24 });
            """
        )

        # try to apply stealth on the page using playwright_stealth  # 尝试使用 playwright_stealth 在页面上应用隐身补丁
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            # already applied context-level init scripts; nothing else to do  # 已经应用了上下文级的 init 脚本；无需额外操作
            pass

        return page

    def get_google_domain(self, saved_state: SavedState) -> str:
        import random
        if saved_state.google_domain:
            selected_domain = saved_state.google_domain
            # 使用保存的Google域名: {selected_domain}
            # Using saved Google domain: {selected_domain}  # 使用保存的 Google 域名: {selected_domain}
            logger.info(f"Using saved Google domain: {selected_domain}")
        else:
            selected_domain = random.choice(self.google_domains)
            saved_state.google_domain = selected_domain
            # 随机选择Google域名: {selected_domain}
            # Randomly selected Google domain: {selected_domain}  # 随机选择的 Google 域名: {selected_domain}
            logger.info(f"Randomly selected Google domain: {selected_domain}")
        return selected_domain

    async def save_browser_state(self, context: BrowserContext, state_file: str, fingerprint_file: str, saved_state: SavedState, no_save_state: bool) -> None:
        try:
            if no_save_state:
                # 根据用户设置，不保存浏览器状态
                # Not saving browser state per user setting  # 根据用户设置，不保存浏览器状态
                logger.info("Not saving browser state per user setting")
                return

            # 正在保存浏览器状态: {state_file}
            # Saving browser state: {state_file}  # 正在保存浏览器状态: {state_file}
            logger.info(f"Saving browser state: {state_file}")
            state_dir = Path(state_file).parent
            state_dir.mkdir(parents=True, exist_ok=True)

            await context.storage_state(path=state_file)
            # 浏览器状态保存成功!
            # Browser state saved successfully!  # 浏览器状态保存成功!
            logger.info("Browser state saved successfully!")

            # 保存指纹配置
            try:
                fingerprint_data = {
                    'fingerprint': asdict(saved_state.fingerprint) if saved_state.fingerprint else None,
                    'google_domain': saved_state.google_domain,
                }
                with open(fingerprint_file, 'w', encoding='utf-8') as f:
                    json.dump(fingerprint_data, f, indent=2, ensure_ascii=False)
                # 指纹配置已保存: {fingerprint_file}
                # Fingerprint configuration saved: {fingerprint_file}  # 指纹配置已保存: {fingerprint_file}
                logger.info(f"Fingerprint configuration saved: {fingerprint_file}")
            except Exception as fingerprint_error:
                # 保存指纹配置时发生错误
                # Error while saving fingerprint configuration  # 保存指纹配置时发生错误
                logger.error(f"Error while saving fingerprint configuration: {fingerprint_error}")
        except Exception as error:
            # 保存浏览器状态时发生错误
            # Error while saving browser state  # 保存浏览器状态时发生错误
            logger.error(f"Error while saving browser state: {error}")

    def load_saved_state(self, state_file: str) -> tuple[Optional[str], SavedState, str]:
        from common.types import SavedState, FingerprintConfig

        storage_state: Optional[str] = None
        saved_state = SavedState()
        fingerprint_file = state_file.replace(".json", "-fingerprint.json")

        if Path(state_file).exists():
            # 发现浏览器状态文件，将使用保存的浏览器状态以避免反机器人检测: {state_file}
            # Found browser state file; will use saved state to avoid anti-bot detection: {state_file}  # 发现浏览器状态文件；将使用已保存状态以避免反爬检测: {state_file}
            logger.info(f"Found browser state file; will use saved state to avoid anti-bot detection: {state_file}")
            storage_state = state_file
            if Path(fingerprint_file).exists():
                try:
                    with open(fingerprint_file, 'r', encoding='utf-8') as f:
                        fingerprint_data = json.load(f)
                        fp = fingerprint_data.get('fingerprint')
                        saved_state = SavedState(
                            fingerprint=FingerprintConfig(**fp) if fp else None,
                            google_domain=fingerprint_data.get('google_domain')
                        )
                    # 已加载保存的浏览器指纹配置
                    # Loaded saved browser fingerprint configuration  # 已加载保存的浏览器指纹配置
                    logger.info("Loaded saved browser fingerprint configuration")
                except Exception as e:
                    # 无法加载指纹配置文件，将创建新的指纹
                    # Unable to load fingerprint file; will create a new fingerprint  # 无法加载指纹文件；将创建新的指纹
                    logger.warn(f"Unable to load fingerprint file; will create a new fingerprint: {e}")
        else:
            # 未找到浏览器状态文件，将创建新的浏览器会话和指纹: {state_file}
            # No browser state file found; will create a new browser session and fingerprint: {state_file}  # 未找到浏览器状态文件；将创建新的浏览器会话和指纹: {state_file}
            logger.info(f"No browser state file found; will create a new browser session and fingerprint: {state_file}")

        return storage_state, saved_state, fingerprint_file

    # ---------------------- Humanization helpers ----------------------
    async def bezier_mouse_move(self, page: Page, start: Tuple[int, int], end: Tuple[int, int], steps: int = 30, duration_ms: int = 700) -> None:
        """Move the mouse along a randomized Bezier curve between start and end.

        - `start` and `end` are (x, y)
        - `steps` controls sampling density
        - `duration_ms` total duration (approx)
        """
        sx, sy = start
        ex, ey = end

        # Create control points  # 创建控制点
        def _rand_ctrl(a, b):
            return a + (b - a) * random.random() + random.uniform(-100, 100)

        cx1 = _rand_ctrl(sx, ex)
        cy1 = _rand_ctrl(sy, ey)
        cx2 = _rand_ctrl(sx, ex)
        cy2 = _rand_ctrl(sy, ey)

        async def _point(t):
            # cubic bezier  # 三次贝塞尔曲线
            x = (
                (1 - t) ** 3 * sx
                + 3 * (1 - t) ** 2 * t * cx1
                + 3 * (1 - t) * t ** 2 * cx2
                + t ** 3 * ex
            )
            y = (
                (1 - t) ** 3 * sy
                + 3 * (1 - t) ** 2 * t * cy1
                + 3 * (1 - t) * t ** 2 * cy2
                + t ** 3 * ey
            )
            return x, y

        interval = max(0.01, duration_ms / 1000.0 / steps)
        for i in range(steps + 1):
            t = i / steps
            x, y = await _point(t)
            try:
                await page.mouse.move(float(x), float(y))
            except Exception:
                # some pages may not permit immediate mouse events; ignore  # 有些页面可能不允许立即的鼠标事件；忽略之
                pass
            await asyncio.sleep(interval * (0.8 + random.random() * 0.4))

    async def human_type(self, page: Page, selector: str, text: str, mean_ms: int = 100, sigma_ms: int = 50) -> None:
        """Type text into `selector` with per-character Gaussian delays (ms).

        Ensures each delay is >= 15ms.
        """
        await page.focus(selector)
        for ch in text:
            raw_delay = random.gauss(mean_ms, sigma_ms)
            delay = max(15, int(raw_delay))
            try:
                # type single char with the computed delay  # 使用计算出的延迟输入单个字符
                await page.keyboard.type(ch, delay=delay)
            except Exception:
                # fallback: insert via evaluate  # 回退：通过 evaluate 插入字符
                await page.evaluate("(sel, c) => { document.querySelector(sel).value += c }", selector, ch)
            # small random pause after character to emulate micro-pauses  # 字符后的小随机暂停以模拟微暂停
            await asyncio.sleep(max(0.01, delay / 1000.0) * random.uniform(0.1, 0.3))

    def get_system_locale_timezone(self) -> Tuple[str, str]:
        return _detect_locale_timezone(None)


# end of file
