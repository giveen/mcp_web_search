#!/usr/bin/env python3
"""
Google搜索MCP服务器
Google Search MCP server
将搜索功能封装为工具，通过MCP协议提供服务
Wraps search functionality as tools exposed over the MCP protocol
"""
import asyncio
import json
import os
import signal
import sys
import time

from pathlib import Path
from typing import Any, Dict, List
from dataclasses import asdict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from google_search.engine import google_search, get_google_search_page_html
from google_search.browser_manager import BrowserManager, MAX_CONCURRENT_CRAWLS
from urllib.parse import urlparse

# Concurrency control for crawls
_crawl_semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS if MAX_CONCURRENT_CRAWLS and isinstance(MAX_CONCURRENT_CRAWLS, int) else 2)

# Per-domain last crawl times to enforce politeness delays
_last_crawl_times: Dict[str, float] = {}
# Politeness delay (seconds) between requests to the same domain
_POLITENESS_DELAY_SECONDS: float = 2.0
# Per-domain locks to serialize requests to the same host
_domain_locks: Dict[str, asyncio.Lock] = {}
from google_search.distiller import ContentDistiller
from google_search.search_executor import SearchExecutor
from google_search.utils import safe_stop_playwright, safe_close_context, safe_close_page
from common.types import CommandOptions, SavedState
from common import logger

# Ensure a sane default locale inside the process so logs and Playwright
# default locale don't unexpectedly pick up container/system locale.
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")


# 创建MCP服务器实例
# Create MCP server instance
server = Server("google-search-server")

# Cooldown tracking to avoid rapid repeated searches after CAPTCHA
# Timestamp (epoch seconds) of last detected CAPTCHA
_last_captcha_time: float = 0.0
# Cooldown window in seconds (configurable)
_captcha_cooldown_seconds: int = int(os.getenv("MCP_CAPTCHA_COOLDOWN", "90"))


@server.list_tools()
async def list_tools() -> List[Tool]:
    """注册可用的工具
    Register available tools
    """
    return [
        Tool(
            name="google-search",
            description="使用Google搜索引擎查询实时网络信息，返回包含标题、链接和摘要的搜索结果。适用于需要获取最新信息、查找特定主题资料、研究当前事件或验证事实的场景。结果以JSON格式返回，包含查询内容和匹配结果列表。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询字符串。为获得最佳结果：1)优先使用英语关键词搜索，因为英语内容通常更丰富、更新更及时，特别是技术和学术领域；2)使用具体关键词而非模糊短语；3)可使用引号\"精确短语\"强制匹配；4)使用site:域名限定特定网站；5)使用-排除词过滤结果；6)使用OR连接备选词；7)优先使用专业术语；8)控制在2-5个关键词以获得平衡结果；9)根据目标内容选择合适的语言（如需要查找特定中文资源时再使用中文）。例如:'climate change report 2024 site:gov -opinion' 或 '\"machine learning algorithms\" tutorial (Python OR Julia)'",
                    },
                    "limit": {
                        "type": "number",
                        "description": "返回的搜索结果数量 (默认: 10，建议范围: 1-20)",
                        "default": 10,
                    },
                    "timeout": {
                        "type": "number",
                        "description": "搜索操作的超时时间(毫秒) (默认: 30000，可根据网络状况调整)",
                        "default": 30000,
                    },
                    "basic_view": {
                        "type": "boolean",
                        "description": "是否请求 Google 基本视图 (gbv=1)。在某些验证码/阻断情况下，Basic View 会作为回退选项使用。",
                        "default": False,
                    },
                    "basicView": {
                        "type": "boolean",
                        "description": "Alias for basic_view (camelCase). Whether to request Google Basic View (gbv=1).",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get-webpage-html",
            description="获取Google搜索后网页的HTML内容，适用于需要分析网页结构、提取特定信息或保存网页内容的场景。返回清理后的HTML内容、页面URL和可选的截图。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询字符串，用于获取目标网页"},
                    "saveToFile": {"type": "boolean", "description": "是否将HTML保存到文件", "default": False},
                    "outputPath": {"type": "string", "description": "HTML输出文件路径（可选）"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get-webpage-markdown",
            description="深度阅读并将网页提炼为Markdown，适用于LLM消费（优先使用Crawl4AI，失败时回退）。Returns JSON with markdown, metadata and screenshot_path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标网页的完整URL"},
                    "query": {"type": "string", "description": "可选的搜索/意图字符串，用于内容优先级排序（Crawl4AI）"},
                    "use_basic_view": {"type": "boolean", "description": "是否使用 basic view (gbv=1) 以绕过反爬虫强阻断", "default": False},
                    "useBasicView": {"type": "boolean", "description": "Alias for use_basic_view (camelCase)", "default": False},
                    "timeout": {"type": "number", "description": "导航/提取超时时间(毫秒)", "default": 60000},
                    "saveScreenshot": {"type": "boolean", "description": "是否保存页面截图", "default": True},
                    "outputPath": {"type": "string", "description": "可选的截图输出路径（文件或目录）"},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="google-search-and-browse",
            description=(
                "Perform a Google search then visit each of the top N result pages, "
                "extracting distilled Markdown content and metadata from every page. "
                "Returns a JSON bundle with an array of per-page results containing "
                "rank, title, url, snippet (from Google), markdown, metadata "
                "(title/url/extraction_method) and any per-page error. "
                "Optionally saves the bundle to a JSON file. "
                "Ideal for deep research: search → read → aggregate in one call."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Number of top search results to browse (default: 5, max: 10).",
                        "default": 5,
                    },
                    "search_timeout": {
                        "type": "number",
                        "description": "Timeout for the initial Google search (ms, default: 30000).",
                        "default": 30000,
                    },
                    "page_timeout": {
                        "type": "number",
                        "description": "Per-page navigation/extraction timeout (ms, default: 60000).",
                        "default": 60000,
                    },
                    "basic_view": {
                        "type": "boolean",
                        "description": "Request Google Basic View (gbv=1) to reduce blocking.",
                        "default": False,
                    },
                    "saveToFile": {
                        "type": "boolean",
                        "description": "Save the aggregated JSON bundle to disk.",
                        "default": False,
                    },
                    "outputPath": {
                        "type": "string",
                        "description": "Directory (or file path) for the saved JSON bundle.",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    try:
        if name == "google-search":
            query = arguments.get("query", "")
            limit = int(arguments.get("limit", 10))
            timeout = int(arguments.get("timeout", 30000))
            basic_view = bool(arguments.get("basic_view", arguments.get("basicView", False)))

            if time.time() - _last_captcha_time < _captcha_cooldown_seconds:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": {"reason": "cooldown", "message": "Cooldown after recent CAPTCHA"}}, ensure_ascii=False),
                    )
                ]

            browser_manager = BrowserManager()
            # Use auto-cleanup context manager to avoid orphaned browsers
            try:
                async with browser_manager.get_page_context() as (context, page):
                    result = await asyncio.wait_for(
                        google_search(
                            query,
                            CommandOptions(limit=limit, timeout=timeout, basic_view=basic_view),
                            existing_browser=context,  # type: ignore[arg-type]
                        ),
                        timeout=(timeout / 1000) + 10,
                    )
                    try:
                        result_obj = asdict(result)
                    except Exception:
                        # Fallback: convert result to a JSON-serializable form
                        if isinstance(result, dict):
                            result_obj = result
                        else:
                            to_dict_fn = getattr(result, "to_dict", None)
                            if callable(to_dict_fn):
                                try:
                                    result_obj = to_dict_fn()
                                except Exception:
                                    result_obj = getattr(result, "__dict__", str(result))
                            else:
                                result_obj = getattr(result, "__dict__", str(result))
                        
                    text = json.dumps(result_obj, ensure_ascii=False)
                    return [TextContent(type="text", text=text)]
            except Exception as e:
                logger.error(f"google-search failed: {e}")
                return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

        elif name == "get-webpage-html":
            query = arguments.get("query", "")
            save_to_file = bool(arguments.get("saveToFile", False))
            output_path = arguments.get("outputPath")

            if not query:
                return [TextContent(type="text", text=json.dumps({"error": "搜索查询不能为空"}, ensure_ascii=False))]

            browser_manager = BrowserManager()
            try:
                async with browser_manager.get_page_context() as (context, page):
                    # Use the existing context/page to perform a search and capture HTML
                    selected_domain = browser_manager.get_google_domain(SavedState())
                    await page.goto(selected_domain, timeout=60000, wait_until="networkidle")
                    # perform search
                    try:
                        search_input = await page.wait_for_selector("textarea[name='q'], input[name='q']", timeout=5000)
                        if search_input is not None:
                            await search_input.click()
                            await page.keyboard.type(query, delay=10)
                            await page.keyboard.press("Enter")
                    except Exception:
                        pass
                    await page.wait_for_load_state("networkidle", timeout=60000)
                    await page.wait_for_timeout(1000)
                    full_html = await page.content()
                    cleaned = full_html
                    # Simplified cleaning: remove scripts and styles
                    import re

                    cleaned = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", cleaned, flags=re.IGNORECASE)
                    cleaned = re.sub(r"<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>", "", cleaned, flags=re.IGNORECASE)

                    saved_path = None
                    screenshot_path = None
                    if save_to_file:
                        out_dir = Path(output_path) if output_path else Path("mcp_html_output")
                        if out_dir.is_file():
                            out_dir = out_dir.parent
                        out_dir.mkdir(parents=True, exist_ok=True)
                        ts = int(time.time())
                        file_path = out_dir / f"{query.replace(' ','_')}-{ts}.html"
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(cleaned)
                        saved_path = str(file_path)
                        try:
                            screenshot_path = str(out_dir / f"{query.replace(' ','_')}-{ts}.png")
                            await page.screenshot(path=screenshot_path, full_page=True)
                        except Exception:
                            screenshot_path = None

                    resp = {
                        "query": query,
                        "url": page.url,
                        "original_html_length": len(full_html),
                        "html": cleaned[:200000],
                        "saved_path": saved_path,
                        "screenshot_path": screenshot_path,
                    }
                    return [TextContent(type="text", text=json.dumps(resp, ensure_ascii=False))]
            except asyncio.TimeoutError:
                return [TextContent(type="text", text=json.dumps({"error": "HTML获取超时"}, ensure_ascii=False))]
            except Exception as e:
                logger.error(f"HTML获取失败: {e}")
                return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

        elif name == "get-webpage-markdown":
            url = arguments.get("url", "")
            query = arguments.get("query")
            timeout = int(arguments.get("timeout", 60000))
            save_screenshot = bool(arguments.get("saveScreenshot", True))
            output_path = arguments.get("outputPath")

            if not url:
                return [TextContent(type="text", text=json.dumps({"error": "url 不能为空"}, ensure_ascii=False))]

            logger.info(f"收到网页提炼请求: url={url}, query={query}, timeout={timeout}")

            # parse use_basic_view flag (support camelCase alias)
            use_basic_view = bool(arguments.get("use_basic_view", arguments.get("useBasicView", False)))

            browser_manager = BrowserManager()
            search_executor = SearchExecutor()

            # Concurrency: queue and wait for available crawl slot
            logger.info(f"[INFO] Queueing crawl for {url}...")
            await _crawl_semaphore.acquire()

            screenshot_path = None
            try:
                # Enforce per-domain politeness delay using a per-domain lock
                domain = urlparse(url).netloc.lower()
                lock = _domain_locks.get(domain)
                if lock is None:
                    lock = asyncio.Lock()
                    _domain_locks[domain] = lock

                async with lock:
                    last = _last_crawl_times.get(domain)
                    now = time.time()
                    if last and now - last < _POLITENESS_DELAY_SECONDS:
                        to_wait = _POLITENESS_DELAY_SECONDS - (now - last)
                        logger.info(f"[INFO] Politeness delay for {domain}: sleeping {to_wait:.2f}s")
                        await asyncio.sleep(to_wait)
                    _last_crawl_times[domain] = time.time()

                async with browser_manager.get_page_context() as (context, page):
                    try:
                        response = await page.goto(url, timeout=timeout, wait_until="networkidle")
                    except Exception as nav_e:
                        logger.error(f"Navigation to {url} failed: {nav_e}")
                        return [TextContent(type="text", text=json.dumps({"error": {"reason": "navigation_failed", "message": str(nav_e)}}, ensure_ascii=False))]

                    status = None
                    try:
                        status = response.status if response else None
                    except Exception:
                        status = None

                    if status and status >= 400:
                        err_obj = {"error": {"reason": "http_error", "status": status, "url": url}}
                        return [TextContent(type="text", text=json.dumps(err_obj, ensure_ascii=False))]

                    if search_executor.is_blocked_page(page.url, response.url if response and getattr(response, "url", None) else ""):
                        err_obj = {"error": {"reason": "blocked", "message": "Blocked by CAPTCHA or verification page", "url": page.url}}
                        return [TextContent(type="text", text=json.dumps(err_obj, ensure_ascii=False))]

                    if save_screenshot:
                        out_dir = Path(output_path) if output_path else Path("mcp_html_output")
                        if out_dir.is_file():
                            out_dir = out_dir.parent
                        out_dir.mkdir(parents=True, exist_ok=True)
                        ts = int(time.time())
                        screenshot_path = str(out_dir / f"screenshot_{ts}.png")
                        try:
                            await page.screenshot(path=screenshot_path, full_page=True)
                        except Exception as ss_e:
                            logger.warning(f"Screenshot failed: {ss_e}")
                            screenshot_path = None

                    # Export a minimal, filtered storage_state for Crawl4AI to carry reputation
                    exported_path = None
                    cleanup_func = None
                    try:
                        try:
                            exported_path, cleanup_func = await browser_manager.export_for_crawl4ai(context, [url], ttl_seconds=30)
                            logger.info(f"[INFO] export_for_crawl4ai created: {exported_path}")
                        except Exception as e:
                            logger.warning(f"[WARN] export_for_crawl4ai failed: {e}")

                        if exported_path:
                            # Create an ephemeral Playwright context that uses the exported storage_state
                            from playwright.async_api import async_playwright

                            p2 = await async_playwright().start()
                            ctx2 = None
                            browser2 = None
                            try:
                                browser2 = await p2.chromium.launch(headless=True)
                                ctx2 = await browser2.new_context(storage_state=exported_path)
                                distiller = ContentDistiller(context=ctx2, page=None)
                                distill_result = await distiller.distill(url, query=query, basic_view=use_basic_view)
                            finally:
                                try:
                                    if ctx2 is not None:
                                        await ctx2.close()
                                except Exception:
                                    pass
                                try:
                                    if browser2 is not None:
                                        await browser2.close()
                                except Exception:
                                    pass
                                try:
                                    await p2.stop()
                                except Exception:
                                    pass
                        else:
                            distiller = ContentDistiller(context=context, page=page)
                            distill_result = await distiller.distill(url, query=query, basic_view=use_basic_view)
                    finally:
                        try:
                            if cleanup_func:
                                await cleanup_func()
                                logger.info("[INFO] export_for_crawl4ai cleanup completed")
                        except Exception as e:
                            logger.warning(f"[WARN] export_for_crawl4ai cleanup failed: {e}")

                    out = {
                        "markdown": distill_result.get("markdown", ""),
                        "metadata": {
                            "title": distill_result.get("title", ""),
                            "url": distill_result.get("url", url),
                            "extraction_method": distill_result.get("method", "fallback"),
                        },
                        "screenshot_path": screenshot_path,
                    }

                    strategy = distill_result.get("method", "fallback") if isinstance(distill_result, dict) else "fallback"
                    logger.info(f"[INFO] Crawl completed for {url} using {strategy}")

                    return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False))]
            except Exception as e:
                logger.error(f"网页提炼失败: {e}")
                return [TextContent(type="text", text=json.dumps({"error": {"reason": "exception", "message": str(e)}}, ensure_ascii=False))]
            finally:
                try:
                    _crawl_semaphore.release()
                except Exception:
                    pass

        elif name == "google-search-and-browse":
            query = arguments.get("query", "")
            limit = min(int(arguments.get("limit", 5)), 10)
            search_timeout = int(arguments.get("search_timeout", 30000))
            page_timeout = int(arguments.get("page_timeout", 60000))
            basic_view = bool(arguments.get("basic_view", False))
            save_to_file = bool(arguments.get("saveToFile", False))
            output_path = arguments.get("outputPath")

            if not query:
                return [TextContent(type="text", text=json.dumps({"error": "query cannot be empty"}, ensure_ascii=False))]

            if time.time() - _last_captcha_time < _captcha_cooldown_seconds:
                return [TextContent(type="text", text=json.dumps({"error": {"reason": "cooldown", "message": "Cooldown after recent CAPTCHA"}}, ensure_ascii=False))]

            logger.info(f"[google-search-and-browse] query={query!r}, limit={limit}")

            # ── Step 1: run Google search ────────────────────────────────────
            browser_manager = BrowserManager()
            search_executor = SearchExecutor()
            try:
                async with browser_manager.get_page_context() as (context, page):
                    search_result = await asyncio.wait_for(
                        google_search(
                            query,
                            CommandOptions(limit=limit, timeout=search_timeout, basic_view=basic_view),
                            existing_browser=context,  # type: ignore[arg-type]
                        ),
                        timeout=(search_timeout / 1000) + 10,
                    )
            except Exception as e:
                logger.error(f"[google-search-and-browse] search failed: {e}")
                return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

            try:
                result_obj = asdict(search_result)
            except Exception:
                result_obj = search_result if isinstance(search_result, dict) else getattr(search_result, "__dict__", {})

            raw_results = result_obj.get("results", [])
            logger.info(f"[google-search-and-browse] got {len(raw_results)} search results, browsing up to {limit}")

            # ── Step 2: visit each result page and distill ───────────────────
            async def _distill_one(rank: int, item: dict) -> dict:
                url = item.get("link", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")

                if not url:
                    return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                            "markdown": "", "metadata": {}, "error": "empty url"}

                logger.info(f"[google-search-and-browse] [{rank}] distilling {url}")
                await _crawl_semaphore.acquire()
                try:
                    domain = urlparse(url).netloc.lower()
                    lock = _domain_locks.get(domain)
                    if lock is None:
                        lock = asyncio.Lock()
                        _domain_locks[domain] = lock

                    async with lock:
                        last = _last_crawl_times.get(domain)
                        now = time.time()
                        if last and now - last < _POLITENESS_DELAY_SECONDS:
                            to_wait = _POLITENESS_DELAY_SECONDS - (now - last)
                            await asyncio.sleep(to_wait)
                        _last_crawl_times[domain] = time.time()

                    bm = BrowserManager()
                    async with bm.get_page_context() as (ctx, pg):
                        try:
                            response = await pg.goto(url, timeout=page_timeout, wait_until="networkidle")
                        except Exception as nav_e:
                            logger.warning(f"[google-search-and-browse] [{rank}] navigation failed: {nav_e}")
                            return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                                    "markdown": "", "metadata": {}, "error": f"navigation_failed: {nav_e}"}

                        status = None
                        try:
                            status = response.status if response else None
                        except Exception:
                            pass
                        if status and status >= 400:
                            return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                                    "markdown": "", "metadata": {}, "error": f"http_{status}"}

                        if search_executor.is_blocked_page(pg.url, response.url if response and getattr(response, "url", None) else ""):
                            return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                                    "markdown": "", "metadata": {}, "error": "blocked_by_captcha"}

                        try:
                            distiller = ContentDistiller(context=ctx, page=pg)
                            distill_result = await distiller.distill(url, query=query, basic_view=basic_view)
                        except Exception as de:
                            logger.warning(f"[google-search-and-browse] [{rank}] distill failed: {de}")
                            return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                                    "markdown": "", "metadata": {}, "error": str(de)}

                    return {
                        "rank": rank,
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "markdown": distill_result.get("markdown", ""),
                        "metadata": {
                            "title": distill_result.get("title", title),
                            "url": distill_result.get("url", url),
                            "extraction_method": distill_result.get("method", "fallback"),
                        },
                        "error": None,
                    }
                except Exception as e:
                    logger.error(f"[google-search-and-browse] [{rank}] unexpected error: {e}")
                    return {"rank": rank, "title": title, "url": url, "snippet": snippet,
                            "markdown": "", "metadata": {}, "error": str(e)}
                finally:
                    _crawl_semaphore.release()

            # Run page distillations sequentially to respect semaphore & politeness
            page_results = []
            for i, item in enumerate(raw_results[:limit], start=1):
                page_results.append(await _distill_one(i, item))

            # ── Step 3: assemble and optionally save ─────────────────────────
            bundle = {
                "query": query,
                "total_browsed": len(page_results),
                "results": page_results,
            }

            saved_path = None
            if save_to_file:
                out_dir = Path(output_path) if output_path else Path("mcp_html_output")
                if out_dir.is_file():
                    out_dir = out_dir.parent
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time())
                safe_q = query[:40].replace(" ", "_").replace("/", "-")
                file_path = out_dir / f"browse_{safe_q}-{ts}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(bundle, f, ensure_ascii=False, indent=2)
                saved_path = str(file_path)
                logger.info(f"[google-search-and-browse] saved bundle to {saved_path}")

            bundle["saved_path"] = saved_path
            return [TextContent(type="text", text=json.dumps(bundle, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        logger.error(f"工具调用失败: {e}")
        return [TextContent(type="text", text=f"工具调用失败: {str(e)}")]


async def main():
    """主函数
    Main entrypoint for the MCP server
    """

    # 设置信号处理
    def signal_handler(signum, frame):
        logger.info("收到退出信号，正在关闭服务器...  (Shutdown signal received; closing server)")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(
        "启动Google搜索MCP服务器...  (Starting Google Search MCP server)"
    )  # Starting Google Search MCP server...

    # Default: stdio transport (MCP over stdin/stdout)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

def serve_sse():
    """Synchronous entrypoint to run the Starlette/uvicorn server for SSE.

    This must be synchronous because `uvicorn.run()` manages the event loop
    itself and cannot be called from within `asyncio.run()`.
    """
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    from mcp.server.sse import SseServerTransport
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
        return Response()

    async def health(request):
        return Response("ok", status_code=200)

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/health", endpoint=health, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]

    starlette_app = Starlette(routes=routes)

    host = os.getenv("MCP_SSE_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SSE_PORT", "8000"))

    logger.info(f"Starting SSE/HTTP MCP server on {host}:{port}")
    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    # If requested, run as an SSE/HTTP server. This path must be synchronous
    # because `uvicorn.run()` starts its own event loop.
    if os.getenv("MCP_SSE", "0") == "1":
        serve_sse()
    else:
        asyncio.run(main())
