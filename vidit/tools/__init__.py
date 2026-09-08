"""The Feature Panel (Constitution section 5): Vidit's tools."""
from .base import Tool, ToolContext, ToolResult, ToolRegistry
from .files import FileAnalyzer, LocalSearch
from .web import DeepResearch, WebSearch
from .code import CodeTools
from .system import SystemControl
from .canvas import Canvas

__all__ = [
    "Tool", "ToolContext", "ToolResult", "ToolRegistry",
    "FileAnalyzer", "LocalSearch", "DeepResearch", "WebSearch", "CodeTools", "SystemControl", "Canvas",
]
