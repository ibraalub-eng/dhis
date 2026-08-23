"""add auth tables

Revision ID: c3a1d5e7f920
Revises: b7aa201451a1
Create Date: 2026-08-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a1d5e7f920'
down_revision: Union[str, Sequence[str], None] = 'b7aa201451a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Permissions table (no FK dependencies)
    op.create_table('permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codename', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('codename'),
    )
    op.create_index('ix_permissions_id', 'permissions', ['id'])

    # Roles table (no FK dependencies)
    op.create_table('roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_roles_id', 'roles', ['id'])

    # Users table (no FK dependencies)
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_superuser', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username'),
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_username', 'users', ['username'])

    # Refresh tokens table (FK to users)
    op.create_table('refresh_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('token_jti', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_jti'),
    )
    op.create_index('ix_refresh_tokens_id', 'refresh_tokens', ['id'])
    op.create_index('ix_refresh_tokens_token_jti', 'refresh_tokens', ['token_jti'])

    # Association tables (FK to users/roles/permissions)
    op.create_table('user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id'),
    )

    op.create_table('role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )

    # Seed permissions
    permissions_data = [
        ("dashboard.read", "Read dashboard"),
        ("analysis.read", "Read analysis"),
        ("quality.read", "Read quality"),
        ("outliers.read", "Read outliers"),
        ("clinical.read", "Read clinical"),
        ("alerts.read", "Read alerts"),
        ("hospitals.read", "Read hospitals"),
        ("smart_analytics.read", "Read smart analytics"),
        ("rules.read", "Read rules"),
        ("root_cause.read", "Read root cause"),
        ("audit.read", "Read audit"),
        ("settings.read", "Read settings"),
        ("data.upload", "Upload data"),
        ("data.export", "Export data"),
        ("smart_analytics.generate_report", "Generate smart analytics report"),
        ("system.manage_users", "Manage users and roles"),
    ]
    for codename, desc in permissions_data:
        op.execute(f"INSERT INTO permissions (codename, description) VALUES ('{codename}', '{desc}')")

    # Seed roles
    op.execute("INSERT INTO roles (name, description, is_system) VALUES ('superadmin', 'Super administrator', TRUE)")
    op.execute("INSERT INTO roles (name, description, is_system) VALUES ('admin', 'Administrator', TRUE)")
    op.execute("INSERT INTO roles (name, description, is_system) VALUES ('doctor', 'Doctor', TRUE)")
    op.execute("INSERT INTO roles (name, description, is_system) VALUES ('viewer', 'Viewer (read-only)', TRUE)")

    # Assign permissions to roles
    # admin: all except system.manage_users
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'admin' AND p.codename != 'system.manage_users'
    """)
    # doctor: specific read + generate_report
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'doctor' AND p.codename IN (
            'dashboard.read', 'analysis.read', 'quality.read', 'smart_analytics.read',
            'smart_analytics.generate_report', 'hospitals.read', 'clinical.read', 'alerts.read'
        )
    """)
    # viewer: all *.read
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'viewer' AND p.codename LIKE '%.read'
    """)

    # Create default superadmin user
    import os
    from app.core.security import hash_password
    admin_pw = os.getenv("ADMIN_PASSWORD", "admin123")
    hashed = hash_password(admin_pw)
    hashed_escaped = hashed.replace("'", "''")
    op.execute(f"""
        INSERT INTO users (username, email, full_name, password_hash, is_active, is_superuser)
        VALUES ('admin', 'admin@health.local', 'System Administrator', '{hashed_escaped}', TRUE, TRUE)
    """)


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE username = 'admin'")
    op.execute("DELETE FROM role_permissions")
    op.execute("DELETE FROM user_roles")
    op.execute("DELETE FROM permissions")
    op.execute("DELETE FROM roles")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("permissions")
