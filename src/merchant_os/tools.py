from dataclasses import dataclass
from typing import Any, Callable, Dict

@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[Dict[str, Any]], Any]

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    def register(self, tool: Tool):
        self._tools[tool.name] = tool
    def call(self, name: str, payload: Dict[str, Any]):
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name].handler(payload)
    def list(self):
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]
