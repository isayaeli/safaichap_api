from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '10.0.2.2', 'app', 'jace-sledlike-constrainingly.ngrok-free.dev'] + config(
    'EXTRA_ALLOWED_HOSTS', default='', cast=Csv()
)

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
