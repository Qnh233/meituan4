"""离线 Agent CLI。

当前推荐入口是 agent.simple_loop：一个顺序 agent loop，无 LangGraph 编排。
保留 agent.cli 只是为了兼容 `python -m agent` 和旧入口。
"""

from agent.simple_loop import main


if __name__ == "__main__":
    raise SystemExit(main())
