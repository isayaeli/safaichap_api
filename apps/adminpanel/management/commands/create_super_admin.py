from django.core.management.base import BaseCommand, CommandError

from apps.adminpanel.models import Role, StaffProfile
from apps.adminpanel.permissions import SUPER_ADMIN
from apps.adminpanel.services import sync_rbac
from apps.userauth.models import UserAccount
from utils.firebase import initialize_firebase


class Command(BaseCommand):
    help = "Gives a Firebase email user the Super Admin dashboard role (creating the Firebase user if needed)."

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', default='')

    def handle(self, *args, email, name, **options):
        from apps.adminpanel.utils_firebase import get_or_create_firebase_user, password_setup_link

        if initialize_firebase() is None:
            raise CommandError("Firebase credentials aren't configured (FIREBASE_CREDENTIALS_PATH/JSON).")
        sync_rbac()
        email = email.lower()
        uid = get_or_create_firebase_user(email, name)
        user, _ = UserAccount.objects.get_or_create(username=uid, defaults={'email': email})
        user.email = user.email or email
        user.full_name = user.full_name or name or None
        user.is_staff = True
        user.save()
        profile, _ = StaffProfile.objects.get_or_create(user=user)
        profile.is_active = True
        profile.save()
        profile.roles.add(Role.objects.get(name=SUPER_ADMIN))
        self.stdout.write(self.style.SUCCESS(f"{email} is now a Super Admin."))
        link = password_setup_link(email)
        if link:
            self.stdout.write(f"Set the password here if you haven't yet:\n{link}")
