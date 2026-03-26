"""
数据类型定义模块
Data types definitions module
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchResult:
    """搜索结果
    Search result
    """
    title: str
    link: str
    snippet: str


@dataclass
class SearchResponse:
    """搜索响应
    Search response
    """
    query: str
    results: List[SearchResult]


@dataclass
class CommandOptions:
    """命令行选项
    Command line options
    """
    limit: Optional[int] = None
    timeout: Optional[int] = None
    state_file: Optional[str] = None
    no_save_state: Optional[bool] = None
    locale: Optional[str] = None
    headless: Optional[bool] = None
    basic_view: Optional[bool] = None


@dataclass
class HtmlResponse:
    """HTML响应
    HTML response
    """
    query: str
    html: str
    url: str
    saved_path: Optional[str] = None
    screenshot_path: Optional[str] = None
    original_html_length: Optional[int] = None


@dataclass
class FingerprintConfig:
    """浏览器指纹配置
    Browser fingerprint configuration
    """
    device_name: str
    locale: str
    timezone_id: str
    color_scheme: str
    reduced_motion: str
    forced_colors: str


@dataclass
class SavedState:
    """保存的浏览器状态
    Saved browser state
    """
    fingerprint: Optional[FingerprintConfig] = None
    google_domain: Optional[str] = None
