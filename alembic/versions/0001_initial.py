"""Create governance trust engine tables."""
from alembic import op

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from trust_engine.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
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
        op.execute("DROP FUNCTION IF EXISTS reject_evaluation_mutation()")
    Base.metadata.drop_all(bind=bind)
