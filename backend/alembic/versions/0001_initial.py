"""Create governance trust engine tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "systems",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signals_json", sa.JSON(), nullable=False),
        sa.Column("policy_results_json", sa.JSON(), nullable=False),
        sa.Column("risk_tier", sa.String(length=16), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_system_id", "evaluations", ["system_id"])
    op.create_index("ix_evaluations_timestamp", "evaluations", ["timestamp"])
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("sutra", sa.String(length=100), nullable=False),
        sa.Column("rule_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("nist_ref", sa.String(length=32), nullable=False),
        sa.Column("nist_characteristic", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    if bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER evaluations_no_update BEFORE UPDATE ON evaluations "
            "BEGIN SELECT RAISE(ABORT, 'evaluations are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER evaluations_no_delete BEFORE DELETE ON evaluations "
            "BEGIN SELECT RAISE(ABORT, 'evaluations are append-only'); END"
        )
    elif bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION reject_evaluation_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'evaluations are append-only'; END; $$"
        )
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER evaluations_no_{operation.lower()} BEFORE {operation} "
                "ON evaluations FOR EACH ROW EXECUTE FUNCTION reject_evaluation_mutation()"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"DROP TRIGGER IF EXISTS evaluations_no_{operation.lower()} ON evaluations")
        op.execute("DROP FUNCTION IF EXISTS reject_evaluation_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS evaluations_no_update")
        op.execute("DROP TRIGGER IF EXISTS evaluations_no_delete")
    op.drop_table("policy_rules")
    op.drop_index("ix_evaluations_timestamp", table_name="evaluations")
    op.drop_index("ix_evaluations_system_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_table("systems")
