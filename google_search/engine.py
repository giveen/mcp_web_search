"""
基于 Playwright 的 Google 搜索功能
Google search functionality based on Playwright
"""
import asyncio
import json
import os
import platform
import random
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Any, Dict

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from common.types import (
    SearchResponse, SearchResult, CommandOptions, HtmlResponse,
    FingerprintConfig, SavedState
)
from common import logger

# 导入新创建的模块
# Import newly created modules
from .fingerprint import get_host_machine_config, get_device_config, get_random_delay
from .browser_manager import BrowserManager
from .search_executor import SearchExecutor
from .html_extractor import HtmlExtractor
from .utils import safe_close_browser, safe_stop_playwright, suppress_platform_resource_warnings

# 抑制平台特定的资源清理警告
# Suppress platform-specific resource cleanup warnings
suppress_platform_resource_warnings()


class CaptchaDetected(Exception):
    """Raised when a CAPTCHA / verification page is encountered.
    Contains an optional `url` attribute with the blocked URL.
    """

    def __init__(self, message: str, url: Optional[str] = None):
        super().__init__(message)
        self.url = url


async def google_search(
    query: str,
    options: Optional[CommandOptions] = None,
    existing_browser: Optional[Browser] = None
) -> SearchResponse:
    """
    执行Google搜索并返回结果
    Execute a Google search and return results
    """
    if options is None:
        options = CommandOptions()

    # 设置默认选项
    limit = options.limit or 10
    timeout = options.timeout or 60000
    state_file = options.state_file or "./browser-state.json"
    no_save_state = options.no_save_state or False
    locale = options.locale or "zh-CN"

    # 忽略传入的headless参数，总是以无头模式启动（首次尝试）
    use_headless = True

    logger.info(f"Initializing browser... options: limit={limit}, timeout={timeout}, stateFile={state_file}, noSaveState={no_save_state}, locale={locale}")

    browser_manager = BrowserManager()
    search_executor = SearchExecutor()

    # 检查是否存在状态文件
    storage_state, saved_state, fingerprint_file = browser_manager.load_saved_state(state_file)

    return await _perform_search_internal(
        query=query,
        limit=limit,
        timeout=timeout,
        state_file=state_file,
        no_save_state=no_save_state,
        locale=locale,
        saved_state=saved_state,
        fingerprint_file=fingerprint_file,
        headless=use_headless,
        existing_browser=existing_browser,
        browser_manager=browser_manager,
        search_executor=search_executor,
        attempts_remaining=3,
    )


async def _perform_search_internal(
    query: str,
    limit: int,
    timeout: int,
    state_file: str,
    no_save_state: bool,
    locale: str,
    saved_state: SavedState,
    fingerprint_file: str,
    headless: bool,
    existing_browser: Optional[Browser] = None,
    browser_manager: BrowserManager = None,
    search_executor: SearchExecutor = None,
    attempts_remaining: int = 3,
) -> SearchResponse:
    """内部搜索函数，处理浏览器启动和 CAPTCHA 重试逻辑
    Internal helper that handles browser startup and CAPTCHA/verification retry logic
    """
    if browser_manager is None:
        browser_manager = BrowserManager()
    if search_executor is None:
        search_executor = SearchExecutor()

    # If an external browser was provided, try once using it and do not attempt to relaunch it automatically
    if existing_browser:
        try:
            return await _perform_search_with_browser(
                browser=existing_browser,
                query=query,
                limit=limit,
                timeout=timeout,
                state_file=state_file,
                no_save_state=no_save_state,
                locale=locale,
                saved_state=saved_state,
                fingerprint_file=fingerprint_file,
                headless=headless,
                browser_was_provided=True,
                browser_manager=browser_manager,
                search_executor=search_executor,
                attempts_remaining=attempts_remaining,
            )
        except CaptchaDetected as cpe:
            logger.warn(f"CAPTCHA detected when using provided browser: {cpe}, url={cpe.url}")
            return SearchResponse(
                query=query,
                results=[
                    SearchResult(
                        title="Search failed (CAPTCHA)",
                        link="",
                        snippet=f"CAPTCHA detected and cannot automatically recover. URL: {cpe.url}"
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Error while searching with provided browser: {e}")
            return SearchResponse(
                query=query,
                results=[SearchResult(title="Search failed", link="", snippet=str(e))]
            )

    # No external browser provided; we can launch and retry as needed
    attempt = 0
    last_error: Optional[Exception] = None
    current_headless = headless

    while attempts_remaining > 0:
        attempt += 1
        p = None
        context = None
        try:
            logger.info(f"Attempt {attempt}: launching browser in {'headless' if current_headless else 'headful'} mode")
            p, context = await browser_manager.launch_browser(current_headless, timeout, locale)

            try:
                return await _perform_search_with_browser(
                    browser=context,
                    query=query,
                    limit=limit,
                    timeout=timeout,
                    state_file=state_file,
                    no_save_state=no_save_state,
                    locale=locale,
                    saved_state=saved_state,
                    fingerprint_file=fingerprint_file,
                    headless=current_headless,
                    browser_was_provided=False,
                    browser_manager=browser_manager,
                    search_executor=search_executor,
                    attempts_remaining=attempts_remaining,
                )
            finally:
                # ensure context closed by browser_manager or caller; safe to ignore failures here
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass
        except CaptchaDetected as cpe:
            last_error = cpe
            logger.warn(f"CAPTCHA detected on attempt {attempt}: {cpe}, url={cpe.url}")
            # Stop playwright/browser process for a clean restart
            if p is not None:
                try:
                    await safe_stop_playwright(p)
                except Exception:
                    pass

            attempts_remaining -= 1
            if attempts_remaining <= 0:
                return SearchResponse(
                    query=query,
                    results=[
                        SearchResult(
                            title="Search failed (CAPTCHA)",
                            link="",
                            snippet=f"CAPTCHA detected and retries exhausted. Last URL: {cpe.url}"
                        )
                    ]
                )

            # Backoff delay (exponential + jitter)
            backoff = min(30, (2 ** (attempt)) + random.uniform(0.5, 2.0))
            logger.info(f"Backing off for {backoff:.1f}s before retrying (will try headful mode next)")
            await asyncio.sleep(backoff)
            # Try headful on retries to allow manual verification if needed
            current_headless = False
            continue
        except Exception as e:
            logger.error(f"Non-recoverable error during attempt {attempt}: {e}")
            last_error = e
            if p is not None:
                try:
                    await safe_stop_playwright(p)
                except Exception:
                    pass
            break

    err_msg = str(last_error) if last_error else "Unknown error"
    return SearchResponse(
        query=query,
        results=[SearchResult(title="Search failed", link="", snippet=f"Could not complete search: {err_msg}")]
    )


async def _perform_search_with_browser(
    browser: Browser,
    query: str,
    limit: int,
    timeout: int,
    state_file: str,
    no_save_state: bool,
    locale: str,
    saved_state: SavedState,
    fingerprint_file: str,
    headless: bool,
    browser_was_provided: bool,
    browser_manager: BrowserManager,
    search_executor: SearchExecutor,
    attempts_remaining: int = 3,
) -> SearchResponse:
    """使用给定浏览器/上下文执行搜索的内部函数
    Internal function that runs a search using the provided browser/context
    """
    context = None
    page = None
    try:
        # Create or reuse context/page via the browser manager helpers
        context = await browser_manager.create_context(browser, saved_state, state_file, locale)
        page = await browser_manager.create_page(context)

        # Navigate to Google and check for blocking
        selected_domain = browser_manager.get_google_domain(saved_state)
        logger.info("Navigating to Google search page...")
        response = await page.goto(selected_domain, timeout=timeout, wait_until="networkidle")

        current_url = page.url
        response_url = response.url if response else None
        if search_executor.is_blocked_page(current_url, response_url):
            raise CaptchaDetected("Blocked by CAPTCHA/verification on initial navigation", current_url)

        # Execute the search
        await search_executor.execute_search(page, query)
        await page.wait_for_load_state("networkidle", timeout=timeout)
        await page.wait_for_timeout(3000)

        final_url = page.url
        logger.info(f"Final URL after page load: {final_url}")

        if search_executor.is_blocked_page(final_url):
            raise CaptchaDetected("Blocked by CAPTCHA/verification after search execution", final_url)

        # Extract results
        await search_executor.wait_for_search_results(page, timeout)
        raw_results = await search_executor.extract_search_results(page, limit)
        search_results = search_executor.convert_to_search_results(raw_results)

        # Save browser state
        try:
            await browser_manager.save_browser_state(context, state_file, fingerprint_file, saved_state, no_save_state)
        except Exception as save_err:
            logger.error(f"Error saving browser state: {save_err}")

        if not browser_was_provided:
            await safe_close_browser(browser)
        else:
            logger.info("Keeping the browser instance open")

        return SearchResponse(query=query, results=search_results)

    except CaptchaDetected:
        # Bubble up CAPTCHA for caller to handle retry/backoff
        raise
    except Exception as error:
        logger.error(f"An error occurred during search: {error}")
        try:
            if context is not None and not no_save_state:
                state_dir = Path(state_file).parent
                state_dir.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=state_file)
        except Exception as state_err:
            logger.error(f"Error while saving browser state after failure: {state_err}")

        if not browser_was_provided:
            await safe_close_browser(browser)
        else:
            logger.info("Keeping the browser instance open")

        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="Search failed",
                    link="",
                    snippet=f"Could not complete search, error: {str(error)}"
                )
            ]
        )


async def get_google_search_page_html(
    query: str,
    options: Optional[CommandOptions] = None,
    save_to_file: bool = False,
    output_path: Optional[str] = None
) -> HtmlResponse:
    """
    获取Google搜索结果页面的原始HTML
    Get the raw HTML of a Google search results page
    """
    if options is None:
        options = CommandOptions()

    timeout = options.timeout or 60000
    state_file = options.state_file or "./browser-state.json"
    no_save_state = options.no_save_state or False
    locale = options.locale or "zh-CN"

    logger.info(f"Initializing browser to fetch search page HTML... options: {options}")

    browser_manager = BrowserManager()
    html_extractor = HtmlExtractor()

    storage_state, saved_state, fingerprint_file = browser_manager.load_saved_state(state_file)

    return await html_extractor.extract_html(
        query, timeout, state_file, no_save_state, locale,
        saved_state, fingerprint_file, save_to_file, output_path
    )
