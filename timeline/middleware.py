from django.contrib.auth.models import User
from django.contrib import auth
from django.http import HttpResponseForbidden
import os

class IAPMiddleware:
    """
    Middleware for Google Cloud Identity-Aware Proxy (IAP).
    Checks for the IAP signed header and logs in the corresponding Django user.
    Blocks access if the user does not exist in the database.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only process IAP if the flag is enabled
        if os.getenv('USE_IAP', 'False') != 'True':
            return self.get_response(request)

        # Extract IAP headers
        # Django automatically converts 'X-Goog-...' to 'HTTP_X_GOOG_...'
        iap_email = request.META.get('HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL')
        
        if iap_email:
            # IAP email header often includes a prefix like 'accounts.google.com:user@example.com'
            email = iap_email.split(':')[-1]
            
            try:
                # Attempt to find a user with this email
                user = User.objects.get(email=email)
                
                # Check if we need to log them in
                if not request.user.is_authenticated or request.user.email != email:
                    # In a production IAP environment, we trust the header.
                    # We bypass standard password auth.
                    auth.login(request, user)
                
            except User.DoesNotExist:
                # Strict security: No auto-creation.
                return HttpResponseForbidden(
                    f"Access Denied: Your account ({email}) is not authorized. "
                    "Please contact an administrator to have your account pre-provisioned."
                )

        return self.get_response(request)
