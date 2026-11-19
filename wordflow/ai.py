"""可选的在线模型。只有用户打开开关并确认后才会发送文本。

生成内容只作为学习参考，不写入词典释义，也不作为测验的正确答案。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

from wordflow.settings import Settings


class AIError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str


PROVIDERS = {
    "deepseek": Provider("DeepSeek", "https://api.deepseek.com", "deepseek-flash"),
    "openai": Provider("OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
    "qwen": Provider("阿里云千问（北京）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "custom": Provider("自定义", "", ""),
}


@dataclass
class AIClient:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: int = 60
    before_request: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def complete(self, system: str, user: str, *, timeout: int | None = None) -> str:
        if self.before_request is not None:
            self.before_request()
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        if self.api_key:
            request.add_unredirected_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout if timeout is None else timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = self._safe(exc.read().decode("utf-8", errors="replace"))[:500]
            raise AIError(f"模型服务返回 {exc.code}：{detail}") from None
        except Exception as exc:
            raise AIError(self._safe(f"无法连接模型服务：{exc}")) from None
        try:
            body = json.loads(raw)
            message = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIError("模型返回的内容无法读取。") from exc
        if isinstance(message, list):
            parts = [part.get("text") if isinstance(part, dict) else part for part in message]
            message = "\n".join(part for part in parts if isinstance(part, str) and part.strip())
        text = str(message or "").strip()
        if not text:
            raise AIError("模型没有返回文字。")
        return self._safe(text)

    def _safe(self, message: str) -> str:
        if self.api_key:
            return message.replace(self.api_key, "***")
        return message


def active_provider(settings) -> str:
    provider = settings.get("ai_provider", "")
    if provider in PROVIDERS:
        return provider
    if any(settings.get(key, "") for key in ("ai_base_url", "ai_model", "ai_api_key")):
        return "custom"
    return "deepseek"


def provider_connection(settings, provider: str) -> AIClient:
    preset = PROVIDERS[provider]
    prefix = "ai_" if provider == "custom" else f"ai_{provider}_"
    return AIClient(
        base_url=preset.base_url or settings.get("ai_base_url", "").strip(),
        api_key=settings.get(prefix + "api_key", "").strip(),
        model=settings.get(prefix + "model", preset.model).strip() or preset.model,
    )


def _origin(url: str) -> tuple:
    try:
        parts = urlsplit(url)
        return parts.scheme, parts.hostname, parts.port or {"https": 443, "http": 80}.get(parts.scheme)
    except ValueError:
        return "", "", None


def save_provider_connection(settings, provider: str, base_url: str, model: str, api_key: str) -> AIClient:
    previous = provider_connection(settings, provider)
    if provider == "custom":
        base_url = base_url.strip()
        if _origin(base_url) != _origin(previous.base_url):
            settings.set("ai_material_consent", 0)
            # Clear the old token before writing the new destination, including if a save is interrupted.
            settings.set("ai_api_key", "")
            if api_key.strip() == previous.api_key:
                api_key = ""
        settings.set("ai_base_url", base_url)
    if active_provider(settings) != provider:
        settings.set("ai_material_consent", 0)
    prefix = "ai_" if provider == "custom" else f"ai_{provider}_"
    settings.set(prefix + "model", model.strip() or PROVIDERS[provider].model)
    settings.set(prefix + "api_key", api_key.strip())
    settings.set("ai_provider", provider)
    return provider_connection(settings, provider)


def configured_client(settings) -> AIClient:
    provider = active_provider(settings)
    client = provider_connection(settings, provider)
    scheme, host, _port = _origin(client.base_url)
    if scheme not in ("https", "http") or not host:
        raise AIError("请输入有效的服务地址。本地 Ollama 一般是 http://127.0.0.1:11434/v1。")
    if not client.model:
        raise AIError("请填写模型名称。")
    if provider != "custom" and not client.api_key:
        raise AIError(f"请填写{PROVIDERS[provider].name}的 API Key。")
    return client


def client_from_settings(settings) -> AIClient:
    if not settings.flag("ai_enabled") or not settings.flag("ai_consent"):
        raise AIError("请先启用在线助手，并勾选允许向所选模型服务发送内容。")
    return configured_client(settings)


def material_client_from_settings(settings: Settings) -> AIClient | None:
    flags = ("ai_enabled", "ai_consent", "ai_material_consent")
    if not all(settings.flag(flag) for flag in flags):
        return None
    client = configured_client(settings)

    def check_current_permission() -> None:
        current = Settings(settings.store)
        if not all(current.flag(flag) for flag in flags) or configured_client(current) != client:
            raise AIError("素材在线处理设置已更改。请核对在线助手设置，再补齐剩余内容。")

    client.before_request = check_current_permission
    return client


def explain_prompt(lemma: str, sentence: str, gloss: str) -> tuple[str, str]:
    if not lemma.strip() or not sentence.strip():
        raise AIError("请同时提供单词和它所在的英文句子。")
    system = (
        "你是英语学习助手。只根据用户给出的句子，解释这个词在句中的意思。"
        "句子不足以判断时，直接说无法确定，不要猜测一个确定词义。"
        "不要编造音标，也不要把你的说明说成词典原文。用中文回答。"
    )
    user = f"单词：{lemma.strip()}\n本地词典释义（可能为空，仅供对照）：{gloss.strip() or '无'}\n句子：{sentence.strip()}"
    return system, user


def mnemonic_prompt(lemma: str, gloss: str) -> tuple[str, str]:
    if not lemma.strip():
        raise AIError("请先填写单词。")
    system = (
        "你是英语学习助手。根据给出的单词和已有中文释义，写一条简短的记忆提示。"
        "如果没有提供释义，不要自己编造词义，只说明缺少释义、无法可靠记忆。"
        "把内容标明为记忆提示，不要说它是词典释义。"
    )
    user = f"单词：{lemma.strip()}\n已有释义：{gloss.strip() or '无'}"
    return system, user


def example_prompt(lemma: str, gloss: str) -> tuple[str, str]:
    if not lemma.strip() or not gloss.strip():
        raise AIError("生成例句需要单词和本地词典里的中文释义。没有可靠释义时不会让模型编造词义。")
    system = (
        "你是英语学习助手。用给定词义写一个不超过 18 个词的英文例句，句子要能看出这个意思。"
        "不要更换词义。不要附加音标。可以在例句后用一行中文说明句子在说什么，并标明这是参考译文。"
    )
    user = f"单词：{lemma.strip()}\n采用的词义：{gloss.strip()}"
    return system, user


def confusion_prompt(rows: list[dict]) -> tuple[str, str]:
    if len(rows) < 2:
        raise AIError("错题还不够，至少需要两个答错过的单词才能做对照。")
    lines = [f"{row['lemma']}｜{row.get('gloss') or '无本地释义'}｜答错 {row.get('wrong_count', 0)} 次" for row in rows[:12]]
    system = (
        "你是英语学习助手。用户给出一组自己答错过的单词和本地释义。"
        "只在这些单词之间找出真正容易混淆的组合，用中文说明差别。"
        "如果某两个词并不容易混淆，不要硬配成一组。不要引入列表之外的单词。"
    )
    return system, "单词列表：\n" + "\n".join(lines)


def reading_prompt(learning: list[dict], known: list[dict]) -> tuple[str, str]:
    if not learning:
        raise AIError("生词本里还没有带释义的单词，暂时不能生成短文。")
    learn_lines = [f"{row['lemma']}：{row['gloss']}" for row in learning[:12]]
    known_lines = [row["lemma"] for row in known[:16]]
    system = (
        "你是英语学习助手。用下面的生词写一篇 80 到 120 词的英文短文，生词都要自然出现。"
        "短文后只为列表里的生词附上用户提供的中文释义，不要为其他词编造中文释义。"
        "不要把短文说成用户的原始文档。"
    )
    user = "生词：\n" + "\n".join(learn_lines) + "\n可以当作已知词使用：" + (", ".join(known_lines) or "无")
    return system, user


def plan_prompt(summary: dict) -> tuple[str, str]:
    system = (
        "你是英语学习助手。根据用户自己的学习数量，用中文写一个未来 7 天的复习和学习安排。"
        "到期复习优先于新词。不要假设文档内容，也不要编造用户没提供的分数。"
    )
    user = (
        f"今日到期复习：{summary.get('due_total', 0)}\n"
        f"生词数量：{summary.get('learning', 0)}\n"
        f"熟词数量：{summary.get('mastered', 0)}\n"
        f"未测试：{summary.get('untested', 0)}\n"
        f"每天计划新词：{summary.get('daily_goal', 0)}\n"
        f"今日已学习：{summary.get('studied_today', 0)}"
    )
    return system, user
