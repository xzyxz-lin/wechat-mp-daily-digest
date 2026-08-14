#!/usr/bin/env python3
"""
文章标题中文翻译模块。

使用 deep_translator（Google Translate）将英文标题翻译为中文，
带本地 JSON 缓存避免重复请求。翻译失败时返回原文，不阻断主流程。

用法：
    from translator import translate_title, translate_batch

    zh = translate_title("Local molecular motions encode time-resolved infrared spectra of proteins")
    # → "局部分子运动编码蛋白质的时间分辨红外光谱"

    results = translate_batch(["title1", "title2", ...])
    # → {"title1": "翻译1", "title2": "翻译2"}
"""

from __future__ import annotations

import json
import logging
import time
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 缓存文件路径（放 data 目录下，不入 git）
CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_FILE = CACHE_DIR / ".translation_cache.json"

# 翻译缓存：内存字典 + 文件持久化
_cache: dict[str, str] = {}
_cache_loaded = False
_cache_lock = threading.Lock()

# 请求间隔（秒），避免被 Google 限流
_MIN_INTERVAL = 0.5
_last_request_time = 0.0
_time_lock = threading.Lock()


def _load_cache() -> None:
    """从磁盘加载翻译缓存。"""
    global _cache_loaded, _cache
    with _cache_lock:
        if _cache_loaded:
            return
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _cache = json.load(f)
                logger.debug(f"已加载翻译缓存：{len(_cache)} 条")
            except Exception as e:
                logger.warning(f"读取翻译缓存失败：{e}，将新建")
                _cache = {}
        else:
            _cache = {}
        _cache_loaded = True


def _save_cache() -> None:
    """将翻译缓存写回磁盘。"""
    with _cache_lock:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存翻译缓存失败：{e}")


def translate_title(title: str) -> str:
    """翻译单条标题。

    Args:
        title: 英文标题

    Returns:
        中文翻译；失败时返回原文
    """
    if not title or not title.strip():
        return title

    title = title.strip()

    # 检查缓存
    _load_cache()
    with _cache_lock:
        cached = _cache.get(title)
        if cached:
            return cached

    # 已经包含中文的标题（公众号文章可能本来就是中文），跳过
    # 简单启发：如果中文字符占比 > 20%，认为不需要翻译
    chinese_chars = sum(1 for ch in title if "\u4e00" <= ch <= "\u9fff")
    if len(title) > 0 and chinese_chars / len(title) > 0.2:
        with _cache_lock:
            _cache[title] = title
        _save_cache()
        return title

    # 调用 Google 翻译
    try:
        from deep_translator import GoogleTranslator

        # 限流
        global _last_request_time
        with _time_lock:
            elapsed = time.time() - _last_request_time
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)
            _last_request_time = time.time()

        translator = GoogleTranslator(source="en", target="zh-CN")
        result = translator.translate(title)

        if result and result.strip() and result != title:
            translated = result.strip()
        else:
            translated = title  # 翻译结果与原文相同，视为失败

    except Exception as e:
        logger.debug(f"翻译失败 [{title[:40]}...]: {e}")
        translated = title

    # 写入缓存
    with _cache_lock:
        _cache[title] = translated
    _save_cache()

    return translated


def translate_batch(titles: list[str]) -> dict[str, str]:
    """批量翻译（自动去重）。

    Args:
        titles: 英文标题列表

    Returns:
        {原文: 译文} 字典
    """
    unique = list(dict.fromkeys(titles))  # 去重保序
    results: dict[str, str] = {}

    for title in unique:
        results[title] = translate_title(title)

    return results


# CLI 测试入口
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_titles = [
        "Local molecular motions encode time-resolved infrared spectra of proteins",
        "Blinking membrane patterns induced by protein binding/unbinding",
        "Substrate-Directed Wetting Layers in Bicontinuous Particle-Stabilised Emulsions",
        "Nature Communications: Targeting cancer-specific mutations",
    ]
    print("=== 翻译测试 ===")
    for t in test_titles:
        zh = translate_title(t)
        print(f"EN: {t}")
        print(f"ZH: {zh}")
        print()
