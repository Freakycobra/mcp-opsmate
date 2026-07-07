#!/usr/bin/env python3
"""
mcp-opsmate — Demo Data Seeder

Seeds the database with 5 sample executions in various states
(completed, failed, pending) for demonstration purposes.

Usage:
    python scripts/seed_demo_data.py
    # Or via Docker:
    docker compose exec api python scripts/seed_demo_data.py
    # Or via Make:
    make db-seed
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

# ------------------------------------------------------------------------------
# Ensure opsmate package is importable when running inside container
# ------------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ------------------------------------------------------------------------------
# Configuration — reads from environment or uses sensible defaults
# ------------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://opsmate:opsmate@postgres:5432/opsmate",
)

# ------------------------------------------------------------------------------
# Sample execution data
# ------------------------------------------------------------------------------
EXECUTIONS: list[dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "command": "Deploy nginx ingress controller to production cluster",
        "status": "completed",
        "plan": (
            "1. Verify cluster connectivity to prod-k8s\n"
            "2. Add ingress-nginx Helm repository\n"
            "3. Install ingress-nginx chart with custom values\n"
            "4. Verify LoadBalancer service is provisioned\n"
            "5. Validate ingress rules are functional"
        ),
        "result": (
            "Successfully deployed nginx ingress controller. "
            "LoadBalancer IP: 203.0.113.45. All health checks passed. "
            "Ingress rules active across 3 namespaces."
        ),
        "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
        "completed_at": datetime.now(timezone.utc) - timedelta(hours=1, minutes=45),
    },
    {
        "id": str(uuid4()),
        "command": "Scale ECS service 'api-worker' to 5 tasks in us-east-1",
        "status": "completed",
        "plan": (
            "1. Authenticate with AWS (mock)\n"
            "2. Describe current ECS service configuration\n"
            "3. Update desired count to 5\n"
            "4. Wait for service stability\n"
            "5. Verify all tasks are running healthy"
        ),
        "result": (
            "ECS service 'api-worker' scaled from 2 to 5 tasks. "
            "All 5 tasks running and passing health checks. "
            "Service stable in us-east-1."
        ),
        "created_at": datetime.now(timezone.utc) - timedelta(hours=5),
        "completed_at": datetime.now(timezone.utc) - timedelta(hours=4, minutes=50),
    },
    {
        "id": str(uuid4()),
        "command": "Create S3 bucket 'opsmate-terraform-state' with versioning",
        "status": "failed",
        "plan": (
            "1. Check if bucket already exists\n"
            "2. Create bucket with private ACL\n"
            "3. Enable versioning\n"
            "4. Configure server-side encryption (AES-256)\n"
            "5. Apply bucket policy for access control"
        ),
        "result": (
            "Failed: Bucket name 'opsmate-terraform-state' already exists "
            "in another AWS account. Please choose a unique bucket name "
            "following the global S3 namespace rules."
        ),
        "created_at": datetime.now(timezone.utc) - timedelta(hours=8),
        "completed_at": datetime.now(timezone.utc) - timedelta(hours=7, minutes=55),
    },
    {
        "id": str(uuid4()),
        "command": "Rotate RDS PostgreSQL credentials for 'analytics-db'",
        "status": "pending",
        "plan": (
            "1. Connect to AWS Secrets Manager\n"
            "2. Generate new strong password\n"
            "3. Update secret value\n"
            "4. Trigger RDS password rotation\n"
            "5. Verify application connectivity"
        ),
        "result": None,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        "completed_at": None,
    },
    {
        "id": str(uuid4()),
        "command": "Run terraform plan for infrastructure/vpc module",
        "status": "completed",
        "plan": (
            "1. Initialize Terraform backend\n"
            "2. Validate Terraform configuration\n"
            "3. Refresh state from remote\n"
            "4. Run terraform plan with -out=tfplan\n"
            "5. Parse and summarize plan output"
        ),
        "result": (
            "Terraform plan completed with 4 changes: "
            "+2 to add (2 new subnets), ~1 to change (route table), "
            "-1 to destroy (unused NAT gateway). "
            "Estimated cost impact: +$45.20/month."
        ),
        "created_at": datetime.now(timezone.utc) - timedelta(days=1),
        "completed_at": datetime.now(timezone.utc) - timedelta(days=1) + timedelta(minutes=15),
    },
]

STEP_RESULTS: list[dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "step_number": 1,
        "step_description": "Verify cluster connectivity to prod-k8s",
        "status": "completed",
        "output": "Cluster 'prod-k8s' is reachable. Version: v1.29.0. Nodes: 5/5 ready.",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "step_number": 2,
        "step_description": "Add ingress-nginx Helm repository",
        "status": "completed",
        "output": "Helm repo 'ingress-nginx' added successfully. URL: https://kubernetes.github.io/ingress-nginx",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1, minutes=55),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "step_number": 3,
        "step_description": "Install ingress-nginx chart",
        "status": "completed",
        "output": "Release 'ingress-nginx' installed. Namespace: ingress-nginx. Chart version: 4.9.0.",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1, minutes=50),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[2]["id"],
        "step_number": 1,
        "step_description": "Check if bucket already exists",
        "status": "failed",
        "output": "Error: BucketAlreadyExists — The requested bucket name is not available.",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=8),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[3]["id"],
        "step_number": 1,
        "step_description": "Connect to AWS Secrets Manager",
        "status": "pending",
        "output": None,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=10),
    },
]

AUDIT_LOGS: list[dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "action": "execution_created",
        "details": {"command": EXECUTIONS[0]["command"], "mode": "mock"},
        "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "action": "plan_generated",
        "details": {"plan_steps": 5, "estimated_duration": "15m"},
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1, minutes=58),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[0]["id"],
        "action": "execution_completed",
        "details": {"result_summary": "Ingress controller deployed successfully"},
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1, minutes=45),
    },
    {
        "id": str(uuid4()),
        "execution_id": EXECUTIONS[2]["id"],
        "action": "execution_failed",
        "details": {"error": "BucketAlreadyExists", "bucket": "opsmate-terraform-state"},
        "created_at": datetime.now(timezone.utc) - timedelta(hours=7, minutes=55),
    },
]

MCP_SERVER_STATES: list[dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "server_name": "aws-mcp",
        "status": "healthy",
        "last_heartbeat": datetime.now(timezone.utc) - timedelta(minutes=2),
        "metadata": {"region": "us-east-1", "mode": "mock", "endpoint": "http://localstack:4566"},
    },
    {
        "id": str(uuid4()),
        "server_name": "kubernetes-mcp",
        "status": "healthy",
        "last_heartbeat": datetime.now(timezone.utc) - timedelta(minutes=5),
        "metadata": {"cluster": "prod-k8s", "version": "v1.29.0", "nodes": 5},
    },
    {
        "id": str(uuid4()),
        "server_name": "github-mcp",
        "status": "standby",
        "last_heartbeat": datetime.now(timezone.utc) - timedelta(hours=1),
        "metadata": {"mode": "mock", "rate_limit_remaining": 4999},
    },
    {
        "id": str(uuid4()),
        "server_name": "slack-mcp",
        "status": "standby",
        "last_heartbeat": datetime.now(timezone.utc) - timedelta(hours=2),
        "metadata": {"mode": "mock", "connected_channels": 0},
    },
    {
        "id": str(uuid4()),
        "server_name": "tavily-mcp",
        "status": "healthy",
        "last_heartbeat": datetime.now(timezone.utc) - timedelta(minutes=10),
        "metadata": {"mode": "mock", "searches_today": 12, "quota_remaining": 988},
    },
]


# ------------------------------------------------------------------------------
# Database seeding logic
# ------------------------------------------------------------------------------
async def seed_database() -> None:
    """Seed the database with demo data."""
    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg is required. Install with: pip install asyncpg")
        sys.exit(1)

    # Parse database URL for asyncpg connection
    # Convert SQLAlchemy asyncpg URL to asyncpg DSN
    db_url = DATABASE_URL
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        print("Seeding demo data...")

        # Clear existing data (respect foreign keys)
        print("  Clearing existing data...")
        await conn.execute("TRUNCATE TABLE audit_logs CASCADE")
        await conn.execute("TRUNCATE TABLE step_results CASCADE")
        await conn.execute("TRUNCATE TABLE mcp_server_states CASCADE")
        await conn.execute("TRUNCATE TABLE executions CASCADE")

        # Insert executions
        print(f"  Inserting {len(EXECUTIONS)} executions...")
        for ex in EXECUTIONS:
            await conn.execute(
                """
                INSERT INTO executions (
                    id, command, status, plan, result,
                    created_at, completed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                ex["id"],
                ex["command"],
                ex["status"],
                ex["plan"],
                ex["result"],
                ex["created_at"],
                ex["completed_at"],
            )

        # Insert step_results
        print(f"  Inserting {len(STEP_RESULTS)} step results...")
        for sr in STEP_RESULTS:
            await conn.execute(
                """
                INSERT INTO step_results (
                    id, execution_id, step_number, step_description,
                    status, output, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                sr["id"],
                sr["execution_id"],
                sr["step_number"],
                sr["step_description"],
                sr["status"],
                sr["output"],
                sr["created_at"],
            )

        # Insert audit_logs
        print(f"  Inserting {len(AUDIT_LOGS)} audit logs...")
        for al in AUDIT_LOGS:
            await conn.execute(
                """
                INSERT INTO audit_logs (
                    id, execution_id, action, details, created_at
                ) VALUES ($1, $2, $3, $4, $5)
                """,
                al["id"],
                al["execution_id"],
                al["action"],
                str(al["details"]).replace("'", '"'),  # Simple JSON-like string
                al["created_at"],
            )

        # Insert mcp_server_states
        print(f"  Inserting {len(MCP_SERVER_STATES)} MCP server states...")
        for mss in MCP_SERVER_STATES:
            await conn.execute(
                """
                INSERT INTO mcp_server_states (
                    id, server_name, status, last_heartbeat, metadata
                ) VALUES ($1, $2, $3, $4, $5)
                """,
                mss["id"],
                mss["server_name"],
                mss["status"],
                mss["last_heartbeat"],
                str(mss["metadata"]).replace("'", '"'),
            )

        print("Demo data seeded successfully!")
        print(f"  - {len(EXECUTIONS)} executions")
        print(f"  - {len(STEP_RESULTS)} step results")
        print(f"  - {len(AUDIT_LOGS)} audit logs")
        print(f"  - {len(MCP_SERVER_STATES)} MCP server states")

    finally:
        await conn.close()


# ------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("mcp-opsmate — Demo Data Seeder")
    print("=" * 60)
    print()

    try:
        asyncio.run(seed_database())
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    print()
    print("Done! View the data at: http://localhost:8080")
