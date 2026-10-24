"""
Single source of truth for dashboard permission codes and the system roles.
`seed_rbac` syncs both into the database; views reference the codes by string.
"""

# (code, label, group)
PERMISSIONS = [
    ('reports.view', 'View overview and reports', 'Overview'),

    ('users.view', 'View customers', 'Users'),
    ('users.manage', 'Edit and disable customers', 'Users'),
    ('users.export', 'Export customers to CSV', 'Users'),

    ('kyc.view', 'View KYC submissions', 'KYC'),
    ('kyc.review', 'Approve or reject KYC', 'KYC'),

    ('catalogue.view', 'View operators, destinations and trips', 'Catalogue'),
    ('catalogue.manage', 'Create and edit operators, destinations and trips', 'Catalogue'),

    ('goals.view', 'View savings goals', 'Goals'),
    ('goals.manage', 'Pause, resume, reschedule and cancel goals', 'Goals'),

    ('payments.view', 'View payments', 'Payments'),
    ('payments.view_raw', 'View raw provider webhooks', 'Payments'),
    ('payments.reconcile', 'Reconcile payments with the provider', 'Payments'),

    ('refunds.view', 'View refunds', 'Refunds'),
    ('refunds.manage', 'Process and close refunds', 'Refunds'),

    ('bookings.view', 'View bookings', 'Bookings'),
    ('bookings.manage', 'Edit bookings and trip documents', 'Bookings'),

    ('fx.view', 'View FX rates', 'FX rates'),
    ('fx.manage', 'Override and refresh FX rates', 'FX rates'),

    ('settings.view', 'View app settings', 'Settings'),
    ('settings.manage', 'Change app settings', 'Settings'),

    ('notifications.view', 'View sent notifications', 'Notifications'),
    ('notifications.send', 'Send notifications to customers', 'Notifications'),

    ('staff.view', 'View staff', 'Staff & roles'),
    ('staff.manage', 'Invite, edit and deactivate staff', 'Staff & roles'),
    ('roles.view', 'View roles', 'Staff & roles'),
    ('roles.manage', 'Create and edit roles', 'Staff & roles'),

    ('audit.view', 'View the audit log', 'Audit log'),
]

ALL_CODES = [code for code, _, _ in PERMISSIONS]
VIEW_CODES = [code for code in ALL_CODES if code.endswith('.view')]

SUPER_ADMIN = 'Super Admin'

# name → (description, permission codes)
SYSTEM_ROLES = {
    SUPER_ADMIN: ("Full access, including staff and roles.", ALL_CODES),
    'Operations': ("Runs trips day to day: catalogue, goals and bookings.", [
        'reports.view', 'users.view', 'catalogue.view', 'catalogue.manage', 'goals.view', 'goals.manage',
        'bookings.view', 'bookings.manage', 'payments.view', 'notifications.view',
    ]),
    'Finance': ("Money in and out: payments, refunds and FX.", [
        'reports.view', 'users.view', 'goals.view', 'payments.view', 'payments.view_raw', 'payments.reconcile',
        'refunds.view', 'refunds.manage', 'fx.view', 'fx.manage', 'settings.view',
    ]),
    'Support': ("Helps customers: profiles, KYC, goals and messages.", [
        'reports.view', 'users.view', 'users.manage', 'kyc.view', 'kyc.review', 'goals.view', 'goals.manage',
        'payments.view', 'refunds.view', 'bookings.view', 'notifications.view', 'notifications.send',
    ]),
    'Content': ("Keeps the catalogue up to date.", ['catalogue.view', 'catalogue.manage']),
    'Viewer': ("Read-only access to everything except staff.", [
        c for c in VIEW_CODES if c not in ('staff.view', 'roles.view', 'audit.view')
    ]),
}
