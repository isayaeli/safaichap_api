"""
Creates (or updates) the read-only Postgres role Grafana's business dashboard
uses. Grants are column-level, so Grafana can count and sum but never read
phone numbers, emails, webhook payloads, KYC documents or device tokens.
Safe to run on every deploy.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from psycopg2 import sql

# table → columns Grafana may SELECT. Add a column here before using it in a panel.
GRANTS = {
    'payments_payment': ['id', 'goal_id', 'amount', 'currency', 'method', 'provider', 'status', 'failure_reason',
                         'created_at', 'settled_at'],
    'payments_refund': ['id', 'goal_id', 'amount', 'currency', 'status', 'attempts', 'created_at', 'processed_at'],
    'goals_savingsgoal': ['id', 'itinerary_id', 'currency', 'total_amount', 'deposit_amount', 'amount_paid', 'status',
                          'frequency', 'travel_date', 'created_at', 'activated_at', 'completed_at'],
    'goals_installment': ['id', 'goal_id', 'due_date', 'amount', 'amount_paid', 'status'],
    'bookings_booking': ['id', 'goal_id', 'status', 'travel_date', 'created_at'],
    'notifications_notification': ['id', 'type', 'is_read', 'created_at'],
    'adminpanel_broadcast': ['id', 'title', 'recipients', 'sent', 'pushed', 'failed', 'created_at'],
    'userauth_useraccount': ['id', 'residency', 'preferred_currency', 'country', 'is_staff', 'is_active',
                             'created_at'],
    'catalogue_itinerary': ['id', 'title'],
    'core_appsetting': ['id', 'pending_payment_timeout_minutes'],
}


class Command(BaseCommand):
    help = "Creates/updates the read-only Postgres role for Grafana (GRAFANA_DB_USER / GRAFANA_DB_PASSWORD)."

    def handle(self, *args, **options):
        user, password = settings.GRAFANA_DB_USER, settings.GRAFANA_DB_PASSWORD
        if not password:
            self.stdout.write("GRAFANA_DB_PASSWORD is not set; skipping the Grafana database user.")
            return
        if connection.vendor != 'postgresql':
            self.stdout.write("Not a Postgres database; skipping the Grafana database user.")
            return

        role = sql.Identifier(user)
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [user])
            verb = 'ALTER' if cursor.fetchone() else 'CREATE'
            cursor.execute(sql.SQL(verb + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s")
                           .format(role), [password])
            # Start from nothing so columns removed from GRANTS lose access too.
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(connection.settings_dict['NAME']), role))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            for table, columns in GRANTS.items():
                cursor.execute(sql.SQL("GRANT SELECT ({}) ON {} TO {}").format(
                    sql.SQL(', ').join(map(sql.Identifier, columns)), sql.Identifier(table), role))
            # Long-running dashboard queries must never hold up the app.
            cursor.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '30s'").format(role))
            cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))

        self.stdout.write(self.style.SUCCESS(
            f"Grafana database user '{user}' {'created' if verb == 'CREATE' else 'updated'} "
            f"with read access to {len(GRANTS)} tables."))
