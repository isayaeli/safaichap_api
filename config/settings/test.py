import os

os.environ.setdefault('DJANGO_SECRET_KEY', 'test-secret-key')

from .base import *  # noqa: E402

DEBUG = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

FIREBASE_CREDENTIALS_PATH = ''
FIREBASE_CREDENTIALS_JSON = ''
FIELD_ENCRYPTION_KEY = 'r8_2Lg5LmCOHpjcrJbzYWMYo5CkkDcXxgzh4ICEdS2M='
CLICKPESA_WEBHOOK_SECRET = 'test-clickpesa-secret'
FLUTTERWAVE_WEBHOOK_HASH = 'test-flutterwave-hash'

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_CLASSES': [],
}
