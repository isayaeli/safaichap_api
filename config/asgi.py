"""
ASGI config for safarichap project.

https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from decouple import config
from django.core.asgi import get_asgi_application

DJANGO_ENV = config('DJANGO_ENV', default='development')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', f'config.settings.{DJANGO_ENV}')

application = get_asgi_application()
