# registration/middleware.py
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages
import logging
from django.utils import timezone
from django.conf import settings
from .models import SecurityAlert
from .utils import get_client_ip
from registration.models import PaymentAttempt, SecurityAlert

logger = logging.getLogger(__name__)

class PaymentErrorMonitoringMiddleware:
    """
    Middleware to monitor and log payment-related errors
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Monitor payment-related 404 errors
        if (response.status_code == 404 and 
            'payment' in request.path.lower()):
            
            self.log_payment_404_error(request)
        
        return response

    def process_exception(self, request, exception):
        """
        Log exceptions that occur during payment processing
        """
        if 'payment' in request.path.lower():
            self.log_payment_exception(request, exception)
        
        return None  # Allow normal exception handling to continue

    def log_payment_404_error(self, request):
        """
        Log 404 errors on payment URLs - might indicate URL manipulation
        """
        try:
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            SecurityAlert.objects.create(
                alert_type='PAYMENT_URL_404',
                description=f'404 error on payment URL: {request.path}',
                ip_address=ip_address,
                user_agent=user_agent[:500],
                data={
                    'url': request.path,
                    'method': request.method,
                    'get_params': dict(request.GET.items()),
                    'post_params': dict(request.POST.items()) if request.method == 'POST' else {}
                }
            )
            
            logger.warning(f'Payment URL 404: {request.path} from IP {ip_address}')
            
        except Exception as e:
            logger.error(f'Error logging payment 404: {e}')

    def log_payment_exception(self, request, exception):
        """
        Log exceptions during payment processing
        """
        try:
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            SecurityAlert.objects.create(
                alert_type='PAYMENT_EXCEPTION',
                description=f'Exception during payment processing: {str(exception)}',
                ip_address=ip_address,
                user_agent=user_agent[:500],
                data={
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception),
                    'url': request.path,
                    'method': request.method,
                    'get_params': dict(request.GET.items()),
                    'post_params': dict(request.POST.items()) if request.method == 'POST' else {}
                }
            )
            
            logger.error(f'Payment exception: {exception} on {request.path} from IP {ip_address}')
            
        except Exception as e:
            logger.error(f'Error logging payment exception: {e}')

class SecurityHeadersMiddleware:
    """Add security headers to all responses"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # Content Security Policy
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.tailwindcss.com unpkg.com cdnjs.cloudflare.com cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com fonts.googleapis.com",
            "font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com",
            "img-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
        ]
        response['Content-Security-Policy'] = '; '.join(csp_directives)
        
        return response
    
class PaymentSecurityMiddleware:
    """Enhanced security middleware for payment routes"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Log payment-related requests
        if '/payment/' in request.path:
            logger.info(f"Payment request: {request.path} from {self.get_client_ip(request)}")
            
            # Track payment attempts
            if request.method == 'POST':
                self.track_payment_attempt(request)
        
        response = self.get_response(request)
        return response
    
    def track_payment_attempt(self, request):
        """Track payment attempts for fraud detection"""
        ip = self.get_client_ip(request)
        
        # Check for suspicious activity
        recent_attempts = PaymentAttempt.objects.filter(
            ip_address=ip,
            attempt_time__gte=timezone.now() - timezone.timedelta(hours=1)
        ).count()
        
        if recent_attempts >= 10:
            logger.warning(f"⚠️ Suspicious activity: {recent_attempts} payment attempts from {ip}")
            SecurityAlert.objects.create(
                alert_type='RATE_LIMIT',
                description=f'Excessive payment attempts from IP: {ip}',
                ip_address=ip,
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                data={'attempts': recent_attempts}
            )
    
    @staticmethod
    def get_client_ip(request):
        """Get real client IP"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip