"""Microsoft MCP tools - aggregates all domain-specific tools"""

# Import all tools from domain modules
from .auth_tools import *
from .email_tools import *
from .calendar_tools import *
from .file_tools import *
from .search_tools import *

# Export the shared mcp instance
from .auth_tools import mcp

__all__ = ['mcp']