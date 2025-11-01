# core/settings.py
import os
from pathlib import Path
import sys
from environs import Env
from decouple import config
from celery.schedules import crontab
import dj_database_url




# ==============================================================================
# CORE PATHS & CONFIGURATION
# ==============================================================================

# Initialize Env for reading .env file
env = Env()
env.read_env() # Reads the .env file

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Get SECRET_KEY from environment variable
SECRET_KEY = env("SECRET_KEY", default='django-insecure-b*tuoe%^o+=^35$0fufrm=oamh^(o0tabn39(7ni12(i-oup+4') # Fallback for local, but ensure it's set in .env for production


# SECURITY WARNING: don't run with debug turned on in production!
# Get DEBUG from environment variable
DEBUG = env.bool("DEBUG", default=True) # Default to True for local, set to False in .env for production


# Site URL
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")

DJANGO_SECRET_ADMIN_URL=env("DJANGO_SECRET_ADMIN_URL", default="admin/")

# ALLOWED_HOSTS from environment variable, split by comma
# For production, specify your Render URL and any other hostnames.
# For local, '127.0.0.1' and 'localhost' are usually sufficient.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost", "localhost:8000", "localhost:3001"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=['http://localhost:3000', 'http://localhost:8000'])
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'

CORS_ALLOW_ALL_ORIGINS = True



# ==============================================================================
# APPLICATION DEFINITION
# ==============================================================================

INSTALLED_APPS = [
    # ASGI Server (must be first for Channels)
    'daphne',
    
    # Django Core Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',

    
    # =================================================================================
    # Whitenoise must be listed before 'django.contrib.staticfiles' 
    'whitenoise.runserver_nostatic',  # For serving static files in development
    'django.contrib.staticfiles',
    # =================================================================================


    # Third-Party Apps
    'corsheaders',
    'rest_framework',
    'django_celery_beat',
    'pgvector',           # Enables vector field support in PostgreSQL

    # Local Apps
    'a2a_protocol',
    'forex_agent',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # For efficient static file serving

    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application' # For Channels

# ==============================================================================
# DATABASE
# ==============================================================================
# Uses dj-database-url to parse the DATABASE_URL from .env.
# This single line handles connection pooling, SSL, and different database backends.
DATABASES = {
    'default': dj_database_url.config(
        # Use the DATABASE_URL from the environment, fall back to SQLite for local dev
        default='sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3'),
        conn_max_age=600 # Keep connections alive for 10 minutes
    )
}

# ==============================================================================
# CACHING (with Redis)
# ==============================================================================
# Used for Celery, caching API responses, and session management.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config('REDIS_URL', default="redis://127.0.0.1:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# ==============================================================================
# ASYNCHRONOUS TASKS & SCHEDULING (Celery & Celery Beat)
# ==============================================================================
CELERY_BROKER_URL = config('REDIS_URL', default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = config('REDIS_URL', default="redis://127.0.0.1:6379/0") # CELERY_RESULT_BACKEND = 'django-db' # Store task results in the Django database

# Core settings
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'          # Can be 'UTC' or 'Africa/Lagos'


# Production-ready settings Task routing & reliability
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_TRACK_STARTED = True
CELERY_ACKS_LATE = True  # ensures tasks aren’t lost if worker crashes
CELERYD_PREFETCH_MULTIPLIER = 1  # prevent task duplication
CELERY_TASK_REJECT_ON_WORKER_LOST = True



# # Retry and connection handling (production safe)
# CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# CELERY_BROKER_CONNECTION_TIMEOUT = 30
# CELERY_BROKER_TRANSPORT_OPTIONS = {
#     "visibility_timeout": 3600,         # 1hr task visibility
#     "socket_timeout": 30,               # network read timeout
#     "socket_connect_timeout": 30,       # initial connection timeout
#     "retry_on_timeout": True,
#     "max_connections": 20,              # limit connections
#     "ssl_cert_reqs": None, # Important for rediss schemes if not using full cert validation
# }




# Defines the schedule for our proactive knowledge-gathering tasks.
CELERY_BEAT_SCHEDULE = {
    'scheduled-knowledge-update-every-2-hours': {
        'task': 'forex_agent.tasks.scheduled_knowledge_update',
        'schedule': crontab(minute='0', hour='*/2'),  # Runs at 00:00, 02:00, 04:00, etc.
    },
}



# ==============================================================================
# TEMPLATES, INTERNATIONALIZATION, PASSWORDS
# ==============================================================================
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



# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Consider 'Africa/Lagos' if that's your primary timezone for consistency with Celery
# TIME_ZONE = "Africa/Lagos"   # Can be 'Africa/Lagos' or 'UTC'
TIME_ZONE = 'UTC'


USE_I18N = True

USE_TZ = True



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


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'



# ==============================================================================
# STATIC & MEDIA FILES CONFIGURATION
# ==============================================================================
STATIC_URL = 'static/'
# This is where `collectstatic` will gather all static files for production.
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# This storage engine handles compression and caching for you.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')





# ==============================================================================
# DJANGO REST FRAMEWORK & CUSTOM ERROR HANDLING
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # Register our custom exception handler to ensure all API errors
    # return a clean, consistent JSON response.
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}


# ==============================================================================
# ROBUST LOGGING CONFIGURATION
# ==============================================================================
# Define the logs directory and create it if it does not exist
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} [{process:d}:{thread:d}] - {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} [{name}] - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO', # More verbose in local dev
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': sys.stdout,
        },
        # Optional: Add a file handler for production logging
        'file': {
            'level': 'INFO',
            # THIS IS THE ONLY LINE THAT IS CHANGED
            'class': 'core.log_handlers.MakeDirRotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            'maxBytes': 1024*1024*5, # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
       
    },
    'loggers': {
        # Root logger
        '': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        # Django's own loggers
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING', # Reduce noise from database queries # Quieter database logs unless there's an issue.
            'propagate': False,
        },
        # Our application's loggers
        'forex_agent': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG', # Capture all our custom logs
            'propagate': False,
        },
        'a2a_protocol': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}












