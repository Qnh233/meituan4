"""策略模块：导入所有策略以触发全局注册。"""

from strategy.base import BaseStrategy, list_strategies, get_strategy

# 导入策略实现以触发 @register 装饰器
from strategy.greedy_variants import (
    GreedyScore,
    GreedyWillingness,
    GreedyRatio,
    GreedyCoverage,
    GreedySetPacking,
)
from strategy.local_search import SimulatedAnnealing, TabuSearch
from strategy.bipartite import HungarianPartial
from strategy.set_cover import MultiRound, IterativeMulti

__all__ = [
    "BaseStrategy",
    "list_strategies",
    "get_strategy",
]
