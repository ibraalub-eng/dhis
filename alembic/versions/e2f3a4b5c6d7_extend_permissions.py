"""extend permissions

Revision ID: e2f3a4b5c6d7
Revises: d1a2b3c4e5f6
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'd1a2b3c4e5f6'
branch_labels = None
depends_on = None

# New granular permissions for write/manage operations
NEW_PERMISSIONS = [
    # Hospital management
    ("hospitals.write", "Create and edit hospitals"),
    ("hospitals.manage", "Delete hospitals and clear data"),
    # Governorate management
    ("governorates.read", "Read governorates"),
    ("governorates.write", "Create and edit governorates"),
    ("governorates.manage", "Delete governorates"),
    # Hospital types
    ("hospital_types.read", "Read hospital types"),
    ("hospital_types.write", "Create and edit hospital types"),
    ("hospital_types.manage", "Delete hospital types"),
    # Facility ownerships
    ("facility_ownerships.read", "Read facility ownerships"),
    ("facility_ownerships.write", "Create and edit facility ownerships"),
    ("facility_ownerships.manage", "Delete facility ownerships"),
    # Facility types
    ("facility_types.read", "Read facility types"),
    ("facility_types.write", "Create and edit facility types"),
    ("facility_types.manage", "Delete facility types"),
    # Data management
    ("data.read", "Read uploaded data"),
    ("data.manage", "Clear and delete uploaded data"),
    # Reports
    ("reports.read", "Read quality reports"),
    ("reports.export", "Export reports as Excel/PDF"),
    # Comparative analysis
    ("comparative.read", "Read comparative analysis"),
    # Regional analysis
    ("regional.read", "Read regional analysis"),
    # Dashboard
    ("dashboard.write", "Edit dashboard settings"),
    # Rules management
    ("rules.write", "Create and edit validation rules"),
    ("rules.manage", "Delete validation rules"),
    # Settings
    ("settings.write", "Edit application settings"),
    # AI
    ("ai.read", "Read AI configuration"),
    ("ai.write", "Edit AI provider settings"),
    # System
    ("system.read_audit", "Read system audit logs"),
    ("system.manage_data", "Clear all data (nuclear option)"),
    ("system.export_data", "Export all system data"),
]


def upgrade():
    # Insert new permissions (skip duplicates)
    for codename, desc in NEW_PERMISSIONS:
        op.execute(
            f"INSERT INTO permissions (codename, description) "
            f"VALUES ('{codename}', '{desc}') "
            f"ON CONFLICT DO NOTHING"
        )

    # Assign new permissions to admin and superadmin roles
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name IN ('superadmin', 'admin')
        AND p.codename IN (
            'hospitals.write', 'hospitals.manage',
            'governorates.read', 'governorates.write', 'governorates.manage',
            'hospital_types.read', 'hospital_types.write', 'hospital_types.manage',
            'facility_ownerships.read', 'facility_ownerships.write', 'facility_ownerships.manage',
            'facility_types.read', 'facility_types.write', 'facility_types.manage',
            'data.read', 'data.manage',
            'reports.read', 'reports.export',
            'comparative.read', 'regional.read',
            'dashboard.write',
            'rules.write', 'rules.manage',
            'settings.write',
            'ai.read', 'ai.write',
            'system.read_audit', 'system.manage_data', 'system.export_data'
        )
        ON CONFLICT DO NOTHING
    """)

    # Assign read-only permissions to doctor role
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'doctor'
        AND p.codename IN (
            'governorates.read', 'hospital_types.read',
            'facility_ownerships.read', 'facility_types.read',
            'data.read', 'reports.read', 'comparative.read', 'regional.read',
            'ai.read'
        )
        ON CONFLICT DO NOTHING
    """)

    # Assign read permissions to viewer role
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'viewer'
        AND p.codename IN (
            'governorates.read', 'hospital_types.read',
            'facility_ownerships.read', 'facility_types.read',
            'data.read', 'reports.read', 'reports.export',
            'comparative.read', 'regional.read',
            'ai.read'
        )
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    codenames = [c for c, _ in NEW_PERMISSIONS]
    placeholders = ", ".join(f"'{c}'" for c in codenames)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE codename IN ({placeholders}))")
    op.execute(f"DELETE FROM permissions WHERE codename IN ({placeholders})")
