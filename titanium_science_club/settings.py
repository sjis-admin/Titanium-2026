"""
Django settings for sjis_math_club project.
PRODUCTION-READY with Security Enhancements
"""

from pathlib import Path
import os
from decouple import config, Csv
from decimal import Decimal
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Explicitly load .env file from the project root
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=dotenv_path)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-f9kn#^oe2jf13wgj74(zw0v3x=%j%%rz%(%p&l=)g6dql*i)4x')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

# TESTING FLAG - ADD THIS
import sys
TESTING = 'test' in sys.argv


ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_htmx',

    'registration.apps.RegistrationConfig',
    'anymail',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'registration.middleware.SecurityHeadersMiddleware',
    'registration.middleware.PaymentSecurityMiddleware',
    'registration.middleware.PaymentErrorMonitoringMiddleware',
    'registration.signals.AdminRequestMiddleware',
]

ROOT_URLCONF = 'titanium_science_club.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'registration.context_processors.site_logo',
            ],
        },
    },
]

WSGI_APPLICATION = 'titanium_science_club.wsgi.application'

# Database - Configured with dj-database-url
# For local development, set DATABASE_URL in .env to "sqlite:///db.sqlite3"
# For production, set DATABASE_URL to your PostgreSQL connection string, e.g., "postgres://user:password@host:port/dbname"
DATABASES = {
    'default': dj_database_url.config(default=config('DATABASE_URL'))
}
# Add SSL require for postgres
if 'postgres' in DATABASES['default']['ENGINE']:
    DATABASES['default']['OPTIONS'] = {'sslmode': 'require'}

# Password validation
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
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True
USE_L10N = True 

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# SSL Commerz Settings - SECURE
SSLCOMMERZ_STORE_ID = config('SSLCOMMERZ_STORE_ID')
SSLCOMMERZ_STORE_PASSWORD = config('SSLCOMMERZ_STORE_PASSWORD')
SSLCOMMERZ_IS_SANDBOX = config('SSLCOMMERZ_IS_SANDBOX', default=True, cast=bool)
SSLCOMMERZ_FEE_PERCENTAGE = config('SSLCOMMERZ_FEE_PERCENTAGE', default='0.015', cast=Decimal)

if SSLCOMMERZ_IS_SANDBOX:
    SSLCOMMERZ_API_URL = "https://sandbox.sslcommerz.com/gwprocess/v4/api.php"
    SSLCOMMERZ_VALIDATION_URL = "https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php"
else:
    SSLCOMMERZ_API_URL = "https://securepay.sslcommerz.com/gwprocess/v4/api.php"
    SSLCOMMERZ_VALIDATION_URL = "https://securepay.sslcommerz.com/validator/api/validationserverAPI.php"


# Email Settings
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    # Use SMTP backend for production
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = config('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
    DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# Security Settings for Production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'SAMEORIGIN'
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    
    # Cookie Security
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Strict'

# Session Configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_COOKIE_AGE = 600  # 10 minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# Cache Configuration
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'tsc',
        'TIMEOUT': 300,
    }
} if config('REDIS_URL', default=None) else {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
        'payment_formatter': {
            'format': '{levelname} {asctime} [PAYMENT] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'admin_logs.log',
            'maxBytes': 1024*1024*15,  # 15MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'security.log',
            'maxBytes': 1024*1024*15,  # 15MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'payment_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'payment.log',
            'maxBytes': 1024*1024*20,  # 20MB
            'backupCount': 15,
            'formatter': 'payment_formatter',
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'error.log',
            'maxBytes': 1024*1024*10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'registration.utils': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'registration.admin': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'registration.views': {
            'handlers': ['payment_file', 'error_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'registration.security': {
            'handlers': ['security_file', 'console'],
            'level': 'WARNING',
            'propagate': True,
        },
        'django.security': {
            'handlers': ['security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'payment': {
            'handlers': ['payment_file', 'error_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / 'logs', exist_ok=True)



# File Upload Security
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Password Reset Configuration
PASSWORD_RESET_TIMEOUT = 300  # 5 minutes

# Application-specific settings
SITE_URL = config('SITE_URL', default='http://127.0.0.1:8000')

# Payment Configuration - Enhanced
PAYMENT_TIMEOUT_MINUTES = 15
MAX_PAYMENT_ATTEMPTS_PER_HOUR = 5
MAX_PAYMENT_RETRIES = 3
PAYMENT_RETRY_DELAY_MINUTES = 5

# Error Monitoring Configuration
PAYMENT_ERROR_MONITORING = {
    'ENABLE_ALERTS': True,
    'ALERT_EMAIL': config('ADMIN_EMAIL', default='titaniumscienceclub@sjis.edu.bd'),
    'MAX_FAILED_ATTEMPTS_BEFORE_ALERT': 5,
    'SUSPICIOUS_IP_MONITORING': True,
    'AUTO_BLOCK_SUSPICIOUS_IPS': False,  # Set to True for auto-blocking
}

# Enhanced Email Configuration for Error Notifications
if not DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    # Add backup email configuration
    EMAIL_TIMEOUT = 30
    EMAIL_USE_SSL = False  # Keep TLS for Gmail
    EMAIL_USE_TLS = True


# SSL Commerz Enhanced Configuration
SSLCOMMERZ_TIMEOUT = 30  # seconds
SSLCOMMERZ_RETRY_COUNT = 3
SSLCOMMERZ_RETRY_DELAY = 2  # seconds

# Enhanced Security Settings
SECURE_PAYMENT_PROCESSING = {
    'ENABLE_HASH_VERIFICATION': True,
    'ENABLE_IP_WHITELISTING': config('SSLCZ_ENABLE_IP_WHITELISTING', default=False, cast=bool),
    'SSLCOMMERZ_IPS': config('SSLCZ_IP_WHITELIST', default='', cast=lambda v: [s.strip() for s in v.split(',') if s.strip()]),
    'MAX_CALLBACK_RETRIES': 3,
    'CALLBACK_TIMEOUT_SECONDS': 30,
}

# Custom Error Pages

