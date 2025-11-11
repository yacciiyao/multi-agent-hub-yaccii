# -*- coding: utf-8 -*-
# @File: base.py
# @Author: yaccii
# @Time: 2025-11-08 16:42
# @Description:
from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """模型基类, 禁止额外字段, 允许复杂类型"""
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
