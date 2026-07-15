"""API route modules for opsmate.

Re-exports all route modules for convenient imports from opsmate.api.routes.
"""
from opsmate.api.routes import admin
from opsmate.api.routes import commands
from opsmate.api.routes import executions
from opsmate.api.routes import health
from opsmate.api.routes import stream

__all__ = ["admin", "commands", "executions", "health", "stream"]
