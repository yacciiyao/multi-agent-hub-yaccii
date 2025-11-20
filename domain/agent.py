# -*- coding: utf-8 -*-
# @File: agent.py
# @Author: yaccii
# @Time: 2025-11-20 14:36
# @Description:
from typing import Optional, List

from pydantic import BaseModel, Field


class TaskShortcut(BaseModel):
    """
    输入框上方的 Prompt 快捷按钮定义。
    """
    id: str = Field(..., description="在该 Agent 内唯一的快捷任务 ID")
    title: str = Field(..., description="按钮主标题")
    subtitle: Optional[str] = Field(None, description="按钮副标题，小字提示")
    prompt_template: Optional[str] = Field(
        None,
        description="可选的 Prompt 模板，前端或后端可用来生成默认输入内容",
    )


class AgentConfig(BaseModel):
    """
    单个 Agent 的完整配置：
    - 角色名称 / 描述 / 图标
    - 默认模型 / 允许模型
    - RAG 策略
    - 支持的模态
    - 系统提示词
    - 快捷任务
    """
    key: str = Field(..., description="唯一标识，如 brand_insight / default_chat")
    name: str = Field(..., description="展示名称，如 品牌洞察助手")
    description: str = Field(..., description="一句话描述该 Agent 的能力与定位")
    icon: Optional[str] = Field(None, description="前端展示用的图标名称或 Emoji")

    bot_name: str = Field(..., description="默认使用的模型标识，如 gpt-3.5-turbo")
    allowed_models: List[str] = Field(
        default_factory=list,
        description="允许切换的模型列表，为空则表示不限制（由前端控制）",
    )

    enable_rag: bool = Field(
        default=False,
        description="是否默认启用 RAG 检索",
    )
    rag_top_k: int = Field(
        default=5,
        ge=0,
        le=50,
        description="RAG 默认检索的文档条数（为0时不检索）",
    )

    supports_modalities: List[str] = Field(
        default_factory=lambda: ["text"],
        description='支持的模态类型，如 ["text"], ["text", "image"]',
    )

    system_prompt: str = Field(
        ...,
        description="该 Agent 的系统提示词，用于约束角色与输出风格",
    )

    task_shortcuts: List[TaskShortcut] = Field(
        default_factory=list,
        description="该 Agent 在输入框上方展示的快捷任务列表",
    )
