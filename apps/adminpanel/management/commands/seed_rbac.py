from django.core.management.base import BaseCommand

from apps.adminpanel.services import sync_rbac


class Command(BaseCommand):
    help = "Syncs dashboard permission codes and built-in roles (safe to run on every deploy)."

    def handle(self, *args, **options):
        sync_rbac()
        self.stdout.write(self.style.SUCCESS("Dashboard permissions and roles are up to date."))
