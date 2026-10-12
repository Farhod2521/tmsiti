# config/settings/development.py
from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.0.102']

# Lokal ishlab chiqishda admin panel kompyuterning o'zidan ham ochilsin
SHNQ_ADMIN_ALLOWED_IPS = SHNQ_ADMIN_ALLOWED_IPS + ',127.0.0.1,::1'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
