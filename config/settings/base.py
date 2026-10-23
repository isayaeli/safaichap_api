from pathlib import Path
from decouple import config, Csv
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('DJANGO_SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

AUTH_USER_MODEL = 'userauth.UserAccount'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'django_filters',
    'django_prometheus',
    'drf_yasg',
    'django_celery_beat',
    'apps.core.apps.CoreConfig',
    'apps.userauth.apps.UserAuthConfig',
    'apps.catalogue',
    'apps.goals',
    'apps.payments',
    'apps.bookings',
    'apps.notifications',
    'apps.wishlist',
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

ASGI_APPLICATION = 'config.asgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django_prometheus.db.backends.postgresql',
        'NAME': config('DB_NAME', default='safarichap'),
        'USER': config('DB_USER', default='safarichap'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

# "Today" for every business rule is computed in this zone; timestamps are stored in UTC.
TIME_ZONE = 'Africa/Dar_es_Salaam'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
MEDIA_URL = '/media/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Firebase configuration
# Never commit the service account. Mount it as a file (FIREBASE_CREDENTIALS_PATH)
# or pass the JSON itself (FIREBASE_CREDENTIALS_JSON). Initialised in CoreConfig.ready().
FIREBASE_CREDENTIALS_PATH = config('FIREBASE_CREDENTIALS_PATH', default='')
FIREBASE_CREDENTIALS_JSON = config('FIREBASE_CREDENTIALS_JSON', default='')


# Rest Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.userauth.authentication.FirebaseAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'payments': config('THROTTLE_PAYMENTS', default='20/min'),
        'kyc': config('THROTTLE_KYC', default='5/min'),
        'webhooks': config('THROTTLE_WEBHOOKS', default='600/min'),
    },
    'DATE_FORMAT': '%Y-%m-%d',
}


# Celery configuration
REDIS_URL = config('REDIS_URL', default='redis://redis:6379/0')
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default=REDIS_URL)
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    'process-missed-and-expired-daily': {
        'task': 'apps.goals.tasks.process_missed_and_expired',
        'schedule': crontab(hour=0, minute=15),  # 00:15 EAT
    },
    'send-due-reminders-daily': {
        'task': 'apps.goals.tasks.send_due_reminders',
        'schedule': crontab(hour=9, minute=0),  # 09:00 EAT
    },
    'reconcile-pending-payments': {
        'task': 'apps.payments.tasks.reconcile_pending_payments',
        'schedule': crontab(minute='*/2'),  # every 2 minutes
    },
    'refresh-fx-rates-daily': {
        'task': 'apps.core.tasks.refresh_fx_rates',
        'schedule': crontab(hour=6, minute=0),  # 06:00 EAT
    },
    'process-refunds': {
        'task': 'apps.payments.tasks.process_refunds',
        'schedule': crontab(minute='*/10'),  # every 10 minutes
    },
}


# Email configuration (operator booking emails).
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='SafariChap <no-reply@safarichap.co.tz>')
EMAIL_OPERATOR_ON_BOOKING = config('EMAIL_OPERATOR_ON_BOOKING', default=False, cast=bool)


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config('REDIS_CACHE_URL', default='redis://redis:6379/1'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"


# CORS (the mobile app doesn't need it; only for browser clients you list here).
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())


# KYC document numbers are encrypted at rest with this Fernet key
# (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
FIELD_ENCRYPTION_KEY = config('FIELD_ENCRYPTION_KEY', default='')


# ClickPesa configuration (mobile money: USSD push + payouts)
CLICKPESA_CLIENT_ID = config('CLICK_PESA_CLIENT_ID', default='')
CLICKPESA_API_KEY = config('CLICK_PESA_API_KEY', default='')
CLICKPESA_BASE_URL = config('CLICK_PESA_BASE_URL', default='https://api.clickpesa.com/third-parties')
CLICKPESA_TOKEN_URL = f"{CLICKPESA_BASE_URL}/generate-token"
# Shared secret appended to the webhook URL registered with ClickPesa:
#   https://<host>/api/payments/webhooks/clickpesa/?secret=<CLICK_PESA_WEBHOOK_SECRET>
CLICKPESA_WEBHOOK_SECRET = config('CLICK_PESA_WEBHOOK_SECRET', default='')

# Card gateway (Flutterwave Standard hosted checkout)
FLUTTERWAVE_SECRET_KEY = config('FLUTTERWAVE_SECRET_KEY', default='')
FLUTTERWAVE_BASE_URL = config('FLUTTERWAVE_BASE_URL', default='https://api.flutterwave.com/v3')
# The "secret hash" set in the Flutterwave dashboard; sent back in the `verif-hash` header.
FLUTTERWAVE_WEBHOOK_HASH = config('FLUTTERWAVE_WEBHOOK_HASH', default='')
CARD_CHECKOUT_REDIRECT_URL = config('CARD_CHECKOUT_REDIRECT_URL', default='https://safarichap.co.tz/payments/done')


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": config('LOG_LEVEL', default='INFO'),
    },
}
