# -*- coding: utf-8 -*-
# @File: agent_registry.py
# @Author: yaccii
# @Time: 2025-11-20 14:35
# @Description: Agent 注册表（公共版，只含默认助手）
from __future__ import annotations

from typing import Dict, List, Optional

from domain.agent import AgentConfig, TaskShortcut

# 内部存一份 Agent 配置
_AGENTS: Dict[str, AgentConfig] = {}
_DEFAULT_KEY = "default_chat"


def _init_builtin_agents() -> None:
    """初始化内置 Agent（公共仓库只放通用的，不含业务定制）"""
    global _AGENTS

    if _AGENTS:
        return

    default_agent = AgentConfig(
        key=_DEFAULT_KEY,
        name="默认助手",
        description="通用对话助手，可结合 RAG 进行知识问答。",
        icon="🤖",
        bot_name="gpt-4o-mini",
        allowed_models=[],
        enable_rag=True,
        rag_top_k=5,
        supports_modalities=["text"],
        system_prompt=(
            "你是一个通用中文 AI 助手，需要尽量准确、清晰、有条理地回答用户问题。\n"
            "当信息不足时，要主动说明假设，不要编造具体数据或引用。\n"
            "如果问题与系统、项目配置相关，尽量给出可执行的排查步骤。"
        ),
        task_shortcuts=[
            TaskShortcut(
                id="qa_general",
                title="知识问答",
                subtitle="根据已有知识库回答问题",
                prompt_template="请根据知识库，帮我解答这个问题：",
            ),
            TaskShortcut(
                id="summarize",
                title="总结内容",
                subtitle="为长文本做摘要和要点提取",
                prompt_template="请帮我总结下面这段内容的要点：",
            ),
        ],
    )

    _AGENTS[default_agent.key] = default_agent


def list_agents() -> List[AgentConfig]:
    """返回全部已注册 Agent（当前只有默认一个）"""
    if not _AGENTS:
        _init_builtin_agents()
    return list(_AGENTS.values())


def get_agent(key: str) -> Optional[AgentConfig]:
    """按 key 获取 AgentConfig"""
    if not _AGENTS:
        _init_builtin_agents()
    return _AGENTS.get(key)


def get_default_agent() -> AgentConfig:
    """获取默认 Agent"""
    if not _AGENTS:
        _init_builtin_agents()
    return _AGENTS[_DEFAULT_KEY]
