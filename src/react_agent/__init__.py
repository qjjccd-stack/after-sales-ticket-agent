"""React Agent.

This module defines a custom reasoning and action agent graph.
It invokes tools in a simple loop.
"""

# 包入口没有手写函数：导入 graph.py 中已编译的图，并通过 __all__ 声明公开名称。
# 导入只装配图；只有后续调用 graph.ainvoke()/astream() 才会实际执行节点。
from react_agent.graph import graph

__all__ = ["graph"]
