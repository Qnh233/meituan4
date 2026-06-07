"""策略基类与全局注册表。

所有策略（手工编写或 LLM 生成）必须继承 BaseStrategy 并注册。
线上 solve() 通过注册表发现可用策略。
"""

from abc import ABC, abstractmethod
from parser import ProblemData

# 全局策略注册表
_registry: dict[str, type["BaseStrategy"]] = {}


def register(cls=None, *, name: str = "", aliases: list[str] | None = None):
    """装饰器：将策略类注册到全局注册表。"""
    def _register(cls_):
        key = name or cls_.__name__
        _registry[key] = cls_
        for alias in (aliases or []):
            _registry[alias] = cls_
        return cls_
    if cls is not None:
        return _register(cls)
    return _register


def list_strategies() -> list[str]:
    return sorted(_registry.keys())


def get_strategy(name: str) -> type["BaseStrategy"]:
    if name not in _registry:
        raise KeyError(f"未注册的策略: {name}，可用: {list_strategies()}")
    return _registry[name]


class BaseStrategy(ABC):
    """求解策略基类。子类需提供 name 和 solve()。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        """对 ProblemData 求解，返回 [(task_id_list_str, [courier_id,...]), ...]"""
        ...

    def get_metadata(self) -> dict:
        return {"name": self.name, "description": self.description}
