
# registration/apps.py
from django.apps import AppConfig

class RegistrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'registration'
    verbose_name = 'SJIS Math Club Registration'

    def ready(self):
        """Import signals when the app is ready"""
        import registration.signals