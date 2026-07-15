"""SQLAlchemy 2.0 async database setup with asyncpg.

Defines all 4 tables from tech-spec Section 2 with proper indexes,
JSONB columns, and Alembic-compatible metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import AsyncGenerator
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from opsmate.core.constants import ExecutionMode, ExecutionStatus

logger: logging.Logger = logging.getLogger(__name__)


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    pass


# ---------------------------------------------------------------------------
# Table: executions
# ---------------------------------------------------------------------------


class Execution(Base):
    """Persisted execution state. One row per user command."""

    __tablename__ = "executions"

    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Unique execution identifier",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        default=ExecutionStatus.PENDING.value,
        comment="Current execution status",
    )
    command_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Original natural language command",
    )
    plan: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialized ExecutionPlan as JSONB",
    )
    results: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Dict of step_id -> serialized StepResult",
    )
    context: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Serialized ExecutionContext",
    )
    execution_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ExecutionMode.MOCK.value,
        comment="mock | live | mixed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
        comment="Execution creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Last state update timestamp (UTC)",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Execution completion timestamp (UTC)",
    )
    planning_duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Intent classification + plan generation duration",
    )
    total_duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Total wall-clock execution duration",
    )

    # Relationships
    step_results: Mapped[list[StepResult]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="StepResult.started_at",
        lazy="selectin",
        comment="Individual step results",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="AuditLog.timestamp",
        lazy="selectin",
        comment="Audit trail entries for this execution",
    )

    __table_args__ = (
        Index("ix_executions_status_created", "status", "created_at"),
        Index("ix_executions_mode_created", "execution_mode", "created_at"),
        Index(
            "ix_executions_command_gin",
            "command_text",
            postgresql_using="gin",
            postgresql_ops={"command_text": "gin_trgm_ops"},
        ),
        Index("ix_executions_plan_gin", "plan", postgresql_using="gin"),
        Index("ix_executions_results_gin", "results", postgresql_using="gin"),
    )


# ---------------------------------------------------------------------------
# Table: step_results
# ---------------------------------------------------------------------------


class StepResult(Base):
    """Individual step execution result. One row per step per execution."""

    __tablename__ = "step_results"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.execution_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Step identifier from the execution plan DAG",
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="MCP tool name that was called",
    )
    server_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MCP server that handled the call",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="Step status (from StepStatus enum)",
    )
    output: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Tool call output (JSON-serialized)",
    )
    error: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialized StepError if step failed",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Number of execution attempts",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Step start timestamp",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Step completion timestamp",
    )

    # Relationship
    execution: Mapped[Execution] = relationship(back_populates="step_results")

    __table_args__ = (
        UniqueConstraint("execution_id", "step_id", name="uq_step_per_execution"),
        Index("ix_step_results_execution_status", "execution_id", "status"),
        Index("ix_step_results_server_tool", "server_name", "tool_name"),
    )


# ---------------------------------------------------------------------------
# Table: audit_logs
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Structured audit log entry. Append-only, never updated or deleted."""

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.execution_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="NULL for system-level events without an execution",
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Action type",
    )
    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Action-specific details (sanitized, no secrets)",
    )
    user_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="User identifier if available",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
        comment="Event timestamp (UTC)",
    )

    # Relationship
    execution: Mapped[Execution | None] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_execution_action", "execution_id", "action"),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Table: mcp_server_states
# ---------------------------------------------------------------------------


class MCPServerState(Base):
    """MCP server connection and circuit breaker state."""

    __tablename__ = "mcp_server_states"

    server_name: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="MCP server identifier",
    )
    connected: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the server is currently connected",
    )
    transport: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="stdio | sse",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="mock",
        comment="mock | live | local",
    )
    circuit_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="closed",
        server_default="closed",
        comment="closed | half_open | open",
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failure count",
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last failure",
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last successful call",
    )
    tools_cached: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="Cached tool schemas from this server",
    )
    tools_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When tools were last discovered",
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# ---------------------------------------------------------------------------
# Engine and session factory
# ---------------------------------------------------------------------------

_engine = None
_session_maker = None


def get_engine(database_url: str | None = None, **kwargs: Any) -> Any:
    """Get or create the async SQLAlchemy engine.

    Args:
        database_url: Database URL. If None, uses environment variable.
        **kwargs: Additional engine arguments.

    Returns:
        The async SQLAlchemy engine.
    """
    global _engine
    if _engine is None:
        url: str = database_url or (
            "postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate"
        )
        _engine = create_async_engine(
            url,
            pool_size=kwargs.get("pool_size", 10),
            max_overflow=kwargs.get("max_overflow", 20),
            echo=kwargs.get("echo", False),
            future=True,
        )
    return _engine


def get_session_maker(**kwargs: Any) -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory.

    Returns:
        An async_sessionmaker configured for AsyncSession.
    """
    global _session_maker
    if _session_maker is None:
        engine = get_engine(**kwargs)
        _session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_maker


async def init_db(database_url: str | None = None, **kwargs: Any) -> None:
    """Initialize database tables.

    Creates all tables if they do not exist. Also ensures pg_trgm extension.
    """
    engine = get_engine(database_url, **kwargs)
    async with engine.begin() as conn:
        # Enable pg_trgm for text search
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")


async def get_db_session(
    database_url: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI: yield an async database session.

    Usage:
        @app.get("/items")
        async def read_items(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    session_maker = get_session_maker(database_url=database_url)
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close the database engine and reset singletons."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_maker = None
    logger.info("Database connections closed")
