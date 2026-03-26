"""
搜索执行模块
Search execution module
"""
import random
from typing import List, Dict, Any

from playwright.async_api import Page
from common.types import SearchResult
from common import logger
from .fingerprint import get_random_delay


class SearchExecutor:
    """搜索执行器
    Search executor
    """
    
    def __init__(self):
        # 人机验证页面模式  # CAPTCHA/anti-bot page patterns
        self.sorry_patterns = [
            "google.com/sorry/index",
            "google.com/sorry",
            "recaptcha",
            "captcha",
            "unusual traffic"
        ]
        
        # 搜索框选择器  # Search input selectors
        self.search_input_selectors = [
            "textarea[name='q']",
            "input[name='q']",
            "textarea[title='Search']",
            "input[title='Search']",
            "textarea[aria-label='Search']",
            "input[aria-label='Search']",
            "textarea"
        ]
        
        # 搜索结果选择器  # Search result selectors
        self.search_result_selectors = [
            "#search",
            "#rso",
            ".g",
            "[data-sokoban-container]",
            "div[role='main']"
        ]
    
    def is_blocked_page(self, url: str, response_url: str = None) -> bool:
        """检查是否被重定向到人机验证页面
        Check whether the URL indicates a CAPTCHA/verification page
        """
        return any(
            pattern in url or
            (response_url and pattern in response_url)
            for pattern in self.sorry_patterns
        )
    
    async def execute_search(self, page: Page, query: str) -> bool:
        """执行搜索
        Execute a search on the given page
        """
        logger.info(f"正在输入搜索关键词: {query}  (Typing search query: {query})")
        
        # 等待搜索框出现 - 尝试多个可能的选择器
        search_input = None
        for selector in self.search_input_selectors:
            try:
                search_input = await page.wait_for_selector(selector, timeout=5000)
                if search_input:
                    logger.info(f"找到搜索框: {selector}  (Found search input: {selector})")
                    break
            except:
                continue
        
        if not search_input:
            logger.error("无法找到搜索框 (Unable to find search input)")
            raise Exception("无法找到搜索框")
        
        # 直接点击搜索框，减少延迟
        await search_input.click()
        await page.wait_for_timeout(500)  # 等待搜索框获得焦点
        
        # 清空搜索框内容
        await search_input.fill('')
        await page.wait_for_timeout(300)
        
        # 输入查询字符串
        await page.keyboard.type(query, delay=get_random_delay(10, 30))
        logger.info(f"已输入搜索关键词: {query}")
        
        # 等待一下确保输入完成
        await page.wait_for_timeout(get_random_delay(300, 500))
        
        # 尝试多种搜索执行方式
        search_executed = False
        
        # 方式1：按回车键
        try:
            logger.info("尝试方式1：按回车键执行搜索  (Attempting method 1: press Enter)")
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            
            # 检查是否被重定向到人机验证页面
            current_url = page.url
            if self.is_blocked_page(current_url):
                logger.warn("方式1执行后检测到人机验证页面，尝试方式2  (Method 1 hit CAPTCHA, trying method 2)")
                search_executed = False
            else:
                logger.info("回车键搜索执行完成  (Enter-key search executed)")
                search_executed = True
        except Exception as e:
            logger.warn(f"回车键搜索失败，尝试其他方式: {e}  (Enter-key search failed, trying alternatives)")
            search_executed = False
        
        # 方式2：如果回车失败或被重定向，尝试点击搜索按钮
        if not search_executed:
            try:
                logger.info("尝试方式2：点击搜索按钮  (Attempting method 2: click search button)")
                search_button = await page.query_selector('input[type="submit"], button[type="submit"], .gNO89b, .Tg7LZd')
                if search_button:
                    await search_button.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    
                    # 再次检查是否被重定向
                    current_url = page.url
                    if self.is_blocked_page(current_url):
                        logger.warn("方式2执行后检测到人机验证页面，尝试方式3  (Method 2 hit CAPTCHA, trying method 3)")
                        search_executed = False
                    else:
                        logger.info("搜索按钮点击完成  (Search button click completed)")
                        search_executed = True
                else:
                    logger.warn("未找到搜索按钮  (Search button not found)")
                    search_executed = False
            except Exception as e:
                logger.warn(f"搜索按钮点击失败: {e}  (Search button click failed)")
                search_executed = False
        
        # 方式3：如果前两种方式都失败，尝试表单提交
        if not search_executed:
            try:
                logger.info("尝试方式3：表单提交  (Attempting method 3: submit form)")
                search_form = await page.query_selector('form[role="search"], form[action*="search"], form')
                if search_form:
                    await search_form.evaluate('form => form.submit()')
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    
                    # 最后检查是否被重定向
                    current_url = page.url
                    if self.is_blocked_page(current_url):
                        logger.warn("方式3执行后仍然检测到人机验证页面  (Method 3 still encountered CAPTCHA)")
                        search_executed = False
                    else:
                        logger.info("表单提交完成  (Form submission completed)")
                        search_executed = True
                else:
                    logger.warn("未找到搜索表单  (Search form not found)")
                    search_executed = False
            except Exception as e:
                logger.warn(f"表单提交失败: {e}  (Form submission failed)")
                search_executed = False
        
        if not search_executed:
            # 检查最终状态
            final_url = page.url
            if self.is_blocked_page(final_url):
                raise Exception("所有搜索执行方式都遇到了人机验证页面")
            else:
                raise Exception("所有搜索执行方式都失败了")

        logger.info("搜索执行完成，等待页面加载  (Search execution finished; waiting for page load)")
        return True

    async def wait_for_search_results(self, page: Page, timeout: int, basic_view: bool = False) -> bool:
        """等待搜索结果加载
        Wait for search results to appear using progressive timeouts

        Supports `basic_view` where the page is static and we look for simpler containers.
        """
        logger.info(f"正在等待搜索结果加载... URL: {page.url} (basic_view={basic_view})  (Waiting for search results to load)")
        """等待搜索结果加载
        Wait for search results to appear using progressive timeouts
        """
        # (continued) main logic below
        
        results_found = False
        last_error = None
        
        if not basic_view:
            for selector in self.search_result_selectors:
                try:
                    logger.info(f"尝试等待选择器: {selector}  (Waiting for selector: {selector})")
                    
                    # 使用渐进式超时策略
                    selector_timeout = 5000  # 初始等待5秒
                    attempts = 0
                    max_attempts = 3
                    
                    while attempts < max_attempts:
                        try:
                            await page.wait_for_selector(selector, timeout=selector_timeout, state="visible")
                            logger.info(f"找到搜索结果: {selector}, 尝试次数: {attempts + 1}  (Found results with selector: {selector})")
                            results_found = True
                            break
                        except Exception as e:
                            attempts += 1
                            if attempts >= max_attempts:
                                raise e  # 最后一次尝试失败，抛出错误
                            
                            logger.info(f"选择器等待超时，增加等待时间重试: selector={selector}, attempt={attempts}, timeout={selector_timeout}  (Selector timed out; increasing timeout and retrying)")
                            selector_timeout = min(selector_timeout * 2, 15000)  # 翻倍超时时间，但不超过15秒
                            
                            # 短暂等待后重试
                            await page.wait_for_timeout(1000)
                    
                    if results_found:
                        break
                    
                except Exception as e:
                    last_error = e
                    logger.warn(f"选择器等待失败，继续尝试下一个: selector={selector}, error={str(e)}  (Selector wait failed; trying next)")
        else:
            # Basic view: look for simple static containers
            try:
                await page.wait_for_selector('div.g, div.tF2Cxc, h3', timeout=min(8000, timeout))
                logger.info("找到搜索结果: Basic View selectors  (Found search results: Basic View selectors)")
                results_found = True
            except Exception as e:
                last_error = e
                logger.warn(f"Basic View: 等待结果选择器失败: {e}  (Basic View: waiting for result selectors failed)")
            
        
        if not results_found:
            logger.error(f"无法找到搜索结果，开始诊断... lastError={str(last_error) if last_error else None}, currentUrl={page.url}  (Unable to find search results; diagnosing)")
            
            # 检查是否被重定向到人机验证页面
            current_url = page.url
            is_blocked_during_results = self.is_blocked_page(current_url)
            
            if is_blocked_during_results:
                logger.warn("等待搜索结果时检测到人机验证页面  (Detected CAPTCHA while waiting for search results)")
                # 返回特殊状态，让调用者知道需要处理人机验证
                raise Exception("检测到人机验证页面")
            else:
                # 如果不是人机验证问题，则抛出错误
                logger.error("无法找到搜索结果元素  (Unable to find search result elements)")
                raise Exception("无法找到搜索结果元素")
        
        # 减少等待时间
        await page.wait_for_timeout(get_random_delay(200, 500))
        
        logger.info("正在提取搜索结果...  (Extracting search results)")
        return True
    
    async def extract_search_results(self, page: Page, limit: int, basic_view: bool = False) -> List[Dict[str, Any]]:
        """提取搜索结果
        Extract raw search results from the page (ported logic)
        """
        # 提取搜索结果 - 使用移植自 google-search-extractor.cjs 的逻辑
        if basic_view:
            # Simpler extraction for gbv=1 (no JS, legacy HTML)
            results = await page.evaluate("""
                (maxResults) => {
                    const results = [];
                    const seenUrls = new Set();
                    const containers = document.querySelectorAll('div.g, div.tF2Cxc');
                    for (const container of containers) {
                        if (results.length >= maxResults) break;
                        const titleEl = container.querySelector('h3');
                        if (!titleEl) continue;
                        const title = (titleEl.textContent || '').trim();
                        let link = '';
                        const a = container.querySelector('a[href]');
                        if (a) link = a.href;
                        if (!link || !link.startsWith('http') || seenUrls.has(link)) continue;
                        // snippet: try span.st then div.VwiC3b
                        let snippet = '';
                        const st = container.querySelector('span.st');
                        if (st) snippet = (st.textContent || '').trim();
                        else {
                            const v = container.querySelector('div.VwiC3b');
                            if (v) snippet = (v.textContent || '').trim();
                        }
                        results.push({ title, link, snippet });
                        seenUrls.add(link);
                    }
                    return results.slice(0, maxResults);
                }
            """, limit)
            logger.info(f"成功获取到搜索结果（Basic View）: {len(results)} 条  (Successfully extracted search results (Basic View): {len(results)})")
            return results

        results = await page.evaluate("""
            (maxResults) => {
                const results = [];
                const seenUrls = new Set(); // 用于去重

                // 定义多组选择器，按优先级排序
                const selectorSets = [
                    { container: '#search div[data-hveid]', title: 'h3', snippet: '.VwiC3b' },
                    { container: '#rso div[data-hveid]', title: 'h3', snippet: '[data-sncf="1"]' },
                    { container: '.g', title: 'h3', snippet: 'div[style*="webkit-line-clamp"]' },
                    { container: 'div[jscontroller][data-hveid]', title: 'h3', snippet: 'div[role="text"]' }
                ];

                // 备用摘要选择器
                const alternativeSnippetSelectors = [
                    '.VwiC3b',
                    '[data-sncf="1"]',
                    'div[style*="webkit-line-clamp"]',
                    'div[role="text"]'
                ];

                // 尝试每组选择器
                for (const selectors of selectorSets) {
                    if (results.length >= maxResults) break; // 如果已达到数量限制，停止

                    const containers = document.querySelectorAll(selectors.container);

                    for (const container of containers) {
                        if (results.length >= maxResults) break;

                        const titleElement = container.querySelector(selectors.title);
                        if (!titleElement) continue;

                        const title = (titleElement.textContent || "").trim();

                        // 查找链接
                        let link = '';
                        const linkInTitle = titleElement.querySelector('a');
                        if (linkInTitle) {
                            link = linkInTitle.href;
                        } else {
                            let current = titleElement;
                            while (current && current.tagName !== 'A') {
                                current = current.parentElement;
                            }
                            if (current && current instanceof HTMLAnchorElement) {
                                link = current.href;
                            } else {
                                const containerLink = container.querySelector('a');
                                if (containerLink) {
                                    link = containerLink.href;
                                }
                            }
                        }

                        // 过滤无效或重复链接
                        if (!link || !link.startsWith('http') || seenUrls.has(link)) continue;

                        // 查找摘要
                        let snippet = '';
                        const snippetElement = container.querySelector(selectors.snippet);
                        if (snippetElement) {
                            snippet = (snippetElement.textContent || "").trim();
                        } else {
                            // 尝试其他摘要选择器
                            for (const altSelector of alternativeSnippetSelectors) {
                                const element = container.querySelector(altSelector);
                                if (element) {
                                    snippet = (element.textContent || "").trim();
                                    break;
                                }
                            }

                            // 如果仍然没有找到摘要，尝试通用方法
                            if (!snippet) {
                                const textNodes = Array.from(container.querySelectorAll('div')).filter(el =>
                                    !el.querySelector('h3') &&
                                    (el.textContent || "").trim().length > 20
                                );
                                if (textNodes.length > 0) {
                                    snippet = (textNodes[0].textContent || "").trim();
                                }
                            }
                        }

                        // 只添加有标题和链接的结果
                        if (title && link) {
                            results.push({ title, link, snippet });
                            seenUrls.add(link); // 记录已处理的URL
                        }
                    }
                }

                // 如果主要选择器未找到足够结果，尝试更通用的方法
                if (results.length < maxResults) {
                    const anchorElements = Array.from(document.querySelectorAll("a[href^='http']"));
                    for (const el of anchorElements) {
                        if (results.length >= maxResults) break;

                        const link = el.href;
                        // 过滤掉导航链接、图片链接、已存在链接等
                        if (!link || seenUrls.has(link) || link.includes("google.com/") ||
                            link.includes("accounts.google") || link.includes("support.google")) {
                            continue;
                        }

                        const title = (el.textContent || "").trim();
                        if (!title) continue; // 跳过没有文本内容的链接

                        // 尝试获取周围的文本作为摘要
                        let snippet = "";
                        let parent = el.parentElement;
                        for (let i = 0; i < 3 && parent; i++) {
                            const text = (parent.textContent || "").trim();
                            // 确保摘要文本与标题不同且有一定长度
                            if (text.length > 20 && text !== title) {
                                snippet = text;
                                break; // 找到合适的摘要就停止向上查找
                            }
                            parent = parent.parentElement;
                        }

                        results.push({ title, link, snippet });
                        seenUrls.add(link);
                    }
                }

                return results.slice(0, maxResults); // 确保不超过限制
            }
        """, limit)
        
        logger.info(f"成功获取到搜索结果: {len(results)} 条  (Successfully extracted search results: {len(results)})")
        return results
    
    def convert_to_search_results(self, raw_results: List[Dict[str, Any]]) -> List[SearchResult]:
        """将原始结果转换为SearchResult对象
        Convert raw result dictionaries into a list of `SearchResult` dataclass instances
        """
        return [
            SearchResult(title=result['title'], link=result['link'], snippet=result['snippet'])
            for result in raw_results
        ] 