"""add menu tables and permission

Revision ID: c7d8e9f0a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a2b3'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade():
    # Tables — guarded create (safe if _ensure_all_tables already created them)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "menu_groups" not in inspector.get_table_names():
        op.create_table(
            "menu_groups",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("icon", sa.String(20), server_default=""),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("1")),
        )
    if "menu_items" not in inspector.get_table_names():
        op.create_table(
            "menu_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("group_id", sa.Integer, sa.ForeignKey("menu_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("tab_key", sa.String(50), nullable=False),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.UniqueConstraint("group_id", "tab_key"),
        )

    # Permission
    op.execute("""
        INSERT INTO permissions (codename, description)
        SELECT 'menu.manage', 'Manage menu layout and groups'
        WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE codename = 'menu.manage')
    """)

    # Assign to superadmin + admin roles
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE p.codename = 'menu.manage'
          AND r.name IN ('superadmin', 'admin')
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
    """)


def downgrade():
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE codename = 'menu.manage')")
    op.execute("DELETE FROM permissions WHERE codename = 'menu.manage'")
    op.drop_table("menu_items", if_exists=True)
    op.drop_table("menu_groups", if_exists=True)