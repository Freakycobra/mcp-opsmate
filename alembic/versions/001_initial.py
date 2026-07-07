"""
Initial migration — create core tables.

Creates all 4 tables for mcp-opsmate:
  - executions         : Track automation command executions
  - step_results       : Individual step results per execution
  - audit_logs         : Audit trail for all actions
  - mcp_server_states  : MCP server health and status tracking

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all core tables."""
    # --------------------------------------------------------------------------
    # executions — Track automation command executions
    # --------------------------------------------------------------------------
    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command", sa.Text(), nullable=False, comment="Natural language command"),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", "cancelled", name="execution_status"),
            nullable=False,
            default="pending",
            comment="Current execution status",
        ),
        sa.Column("plan", sa.Text(), nullable=True, comment="Generated execution plan"),
        sa.Column("result", sa.Text(), nullable=True, comment="Execution result summary"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When the execution was created",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the execution started running",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the execution completed/failed",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Error message if execution failed",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            default=dict,
            comment="Additional execution metadata",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="valid_execution_status",
        ),
        comment="Tracks automation command executions",
    )

    # Index on status for fast filtering
    op.create_index(
        "idx_executions_status",
        "executions",
        ["status"],
    )

    # Index on created_at for chronological ordering
    op.create_index(
        "idx_executions_created_at",
        "executions",
        ["created_at"],
    )

    # --------------------------------------------------------------------------
    # step_results — Individual step results per execution
    # --------------------------------------------------------------------------
    op.create_table(
        "step_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent execution reference",
        ),
        sa.Column(
            "step_number",
            sa.Integer(),
            nullable=False,
            comment="Step order within the execution",
        ),
        sa.Column(
            "step_description",
            sa.Text(),
            nullable=False,
            comment="Description of what this step does",
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", "skipped", name="step_status"),
            nullable=False,
            default="pending",
            comment="Step execution status",
        ),
        sa.Column(
            "output",
            sa.Text(),
            nullable=True,
            comment="Step output/result text",
        ),
        sa.Column(
            "error_details",
            sa.Text(),
            nullable=True,
            comment="Error details if step failed",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="valid_step_status",
        ),
        comment="Individual step results for each execution",
    )

    # Composite index for fast lookup of steps by execution
    op.create_index(
        "idx_step_results_execution",
        "step_results",
        ["execution_id", "step_number"],
    )

    # --------------------------------------------------------------------------
    # audit_logs — Audit trail for all actions
    # --------------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="SET NULL"),
            nullable=True,
            comment="Related execution (nullable for system events)",
        ),
        sa.Column(
            "action",
            sa.String(128),
            nullable=False,
            comment="Action type (e.g., execution_created, plan_generated)",
        ),
        sa.Column(
            "actor",
            sa.String(256),
            nullable=True,
            default="system",
            comment="Who/what performed the action",
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            default=dict,
            comment="Structured action details",
        ),
        sa.Column(
            "ip_address",
            sa.String(45),
            nullable=True,
            comment="Client IP address (IPv4 or IPv6)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        comment="Audit trail for all system actions",
    )

    # Index for querying audit logs by execution
    op.create_index(
        "idx_audit_logs_execution",
        "audit_logs",
        ["execution_id"],
    )

    # Index for querying by action type
    op.create_index(
        "idx_audit_logs_action",
        "audit_logs",
        ["action"],
    )

    # Index for chronological queries
    op.create_index(
        "idx_audit_logs_created_at",
        "audit_logs",
        ["created_at"],
    )

    # --------------------------------------------------------------------------
    # mcp_server_states — MCP server health and status tracking
    # --------------------------------------------------------------------------
    op.create_table(
        "mcp_server_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_name",
            sa.String(128),
            nullable=False,
            unique=True,
            comment="MCP server identifier (e.g., aws-mcp, github-mcp)",
        ),
        sa.Column(
            "status",
            sa.Enum("healthy", "unhealthy", "standby", "error", "offline", name="server_status"),
            nullable=False,
            default="standby",
            comment="Current server health status",
        ),
        sa.Column(
            "last_heartbeat",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last successful heartbeat timestamp",
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            default=0,
            comment="Consecutive failure count for circuit breaker",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            default=dict,
            comment="Server-specific metadata (version, config, etc.)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('healthy', 'unhealthy', 'standby', 'error', 'offline')",
            name="valid_server_status",
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name="non_negative_failure_count",
        ),
        comment="MCP server health and status tracking for circuit breaker",
    )

    # Index for fast status lookups
    op.create_index(
        "idx_mcp_server_states_status",
        "mcp_server_states",
        ["status"],
    )

    # Index for heartbeat monitoring
    op.create_index(
        "idx_mcp_server_states_heartbeat",
        "mcp_server_states",
        ["last_heartbeat"],
    )


def downgrade() -> None:
    """Drop all core tables."""
    op.drop_index("idx_mcp_server_states_heartbeat", table_name="mcp_server_states")
    op.drop_index("idx_mcp_server_states_status", table_name="mcp_server_states")
    op.drop_table("mcp_server_states")

    op.drop_index("idx_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("idx_audit_logs_action", table_name="audit_logs")
    op.drop_index("idx_audit_logs_execution", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("idx_step_results_execution", table_name="step_results")
    op.drop_table("step_results")

    op.drop_index("idx_executions_created_at", table_name="executions")
    op.drop_index("idx_executions_status", table_name="executions")
    op.drop_table("executions")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS server_status")
    op.execute("DROP TYPE IF EXISTS step_status")
    op.execute("DROP TYPE IF EXISTS execution_status")
