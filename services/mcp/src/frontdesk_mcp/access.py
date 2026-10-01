"""Server-side lifecycle access boundary.

Two bearers reach /mcp/: the gateway's (conversational principal) and the call-end finalizer's
(lifecycle principal). This middleware makes the split real on the server: the conversational
principal never lists or calls `record_call_summary`; the lifecycle principal may call only that tool.
Client-side tool filtering in LiveKit/ContextForge is convenience, not authorization.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool

from .context import principal_var

LIFECYCLE_TAG = "lifecycle"


def _allowed(tool_tags: set[str] | frozenset[str]) -> bool:
    principal = principal_var.get()
    if principal is None:
        return False
    lifecycle_tool = LIFECYCLE_TAG in tool_tags
    return lifecycle_tool if principal == "lifecycle" else not lifecycle_tool


class LifecycleGate(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext) -> Sequence[Tool]:
        tools = await call_next(context)
        return [tool for tool in tools if _allowed(set(tool.tags or ()))]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        name = context.message.name
        tool = await context.fastmcp_context.fastmcp.get_tool(name) if context.fastmcp_context else None
        tags = set(tool.tags or ()) if tool is not None else set()
        if not _allowed(tags):
            principal = principal_var.get() or "unauthenticated"
            raise ToolError(f"{name} is not available to the {principal} principal (lifecycle access boundary)")
        return await call_next(context)
