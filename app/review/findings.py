"""审查发现（Finding）的结构化模型与解析。

模型最终回复是一段文本，里面应该是一个 JSON 数组。真实世界的输出经常
不那么干净：外面包了 ```json 代码块、前后夹着解释文字、个别字段值不合法。
parse_findings 负责"宽容地拆包、严格地验收"：
- 包得不好可以修（剥代码块、找数组边界）；
- 字段不合法不迁就（Pydantic 校验失败的那条直接丢弃并记录原因）。
"""

from __future__ import annotations

import json  # 把 JSON 字符串解析成 Python 对象
import re  # 用正则从模型文本里抠出 JSON 数组
from enum import Enum  # 枚举基类

from pydantic import BaseModel, Field, ValidationError  # 数据校验三件套


class Severity(str, Enum):
    """严重度枚举：blocker（必坏/安全漏洞）> major（大概率出问题）> minor（建议改进）。"""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class Category(str, Enum):
    """问题类别：对应任务书app/agent/context.py里要求的四类审查维度。"""

    CORRECTNESS = "correctness"  # 正确性缺陷
    REGRESSION = "regression"  # 与历史 bug 相似的模式
    SECURITY = "security"  # 安全问题
    MAINTAINABILITY = "maintainability"  # 可维护性


class Finding(BaseModel):
    """一条审查发现：Pydantic 会在创建对象时逐字段校验，不合格直接抛错。"""

    file: str = Field(min_length=1)  # 文件相对路径，不能为空
    line: int = Field(ge=1)  # 行号必须是 >=1 的整数
    severity: Severity  # 只能是三个枚举值之一
    category: Category  # 只能是四个类别之一
    message: str = Field(min_length=1)  # 问题描述，不能为空
    evidence: str = ""  # 证据（可选）：代码引用 / 历史提交 / 规范条款
    suggestion: str = ""  # 修复建议（可选）


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)  # 匹配 ```json ... ``` 代码块（非贪婪、跨行）


def _extract_json_array(text: str) -> str | None:
    """从模型输出里抠出 JSON 数组部分。"""
    fence = _FENCE_RE.search(text)  # 先看文本里有没有代码块
    candidate = fence.group(1).strip() if fence else text.strip()  # 有就取块内内容，没有就用全文
    if candidate.startswith("["):  # 已经是干净的数组，直接用
        return candidate
    start, end = candidate.find("["), candidate.rfind("]")  # 否则找第一个 "[" 和最后一个 "]"
    if start != -1 and end > start:  # 两个边界都存在且顺序正确
        return candidate[start : end + 1]  # 截取中间这一段当作候选 JSON
    return None  # 什么数组都没找到


def parse_findings(text: str) -> tuple[list[Finding], list[str]]:
    """解析模型最终回复 → (合法 Finding 列表, 错误说明列表)。"""
    payload = _extract_json_array(text)  # 第一步：从自由文本里抠出 JSON 数组
    if payload is None:  # 没找到数组，直接报错
        return [], ["输出中没有找到 JSON 数组"]

    try:  # 第二步：解析 JSON 字符串——格式坏了就捕获异常
        items = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [], [f"JSON 解析失败: {exc}"]

    if not isinstance(items, list):  # 顶层必须是数组，否则没法逐条处理
        return [], ["JSON 顶层不是数组"]

    findings: list[Finding] = []  # 合格品收集箱
    errors: list[str] = []  # 被丢弃条目的原因记录
    for index, item in enumerate(items):  # 第三步：逐条验收
        try:  # 用 Pydantic 校验这一条的形状
            findings.append(Finding.model_validate(item))
        except ValidationError as exc:  # 字段缺失/类型错误/违反约束都会被这里接住
            first = exc.errors()[0]  # 只取第一条错误，信息量够且不啰嗦
            errors.append(f"第 {index} 条被丢弃: {first['loc']} {first['msg']}")
    return findings, errors  # 合格列表 + 错误列表（错误不阻塞流程，供日志和评测分析）
