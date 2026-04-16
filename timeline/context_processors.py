from django.conf import settings

def auth_settings(request):
    """
    Exposes architecture-level auth flags to all templates.
    """
    return {
        'USE_IAP': getattr(settings, 'USE_IAP', False),
        'USE_GOOGLE_OAUTH': getattr(settings, 'USE_GOOGLE_OAUTH', False),
    }
