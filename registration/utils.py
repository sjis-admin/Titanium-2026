# registration/utils.py
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.cache import cache
from django.conf import settings
from django.utils.html import escape
from django.http import HttpResponse
from django.core.mail import send_mail
import hashlib
import logging
import hmac
import json
import uuid
import re
from decimal import Decimal
from datetime import timedelta
from threading import Thread

# Create HttpResponseTooManyRequests class for older Django versions
class HttpResponseTooManyRequests(HttpResponse):
    status_code = 429
    
    def __init__(self, content='Too Many Requests', *args, **kwargs):
        super().__init__(content, *args, **kwargs)

# Set up logging
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('registration.security')

def log_admin_action(user, action, model_name='', object_id='', description='', ip_address=None, user_agent=''):
    """
    Log admin actions to the database with enhanced security tracking
    
    Args:
        user: Django User object
        action: Action type (CREATE, UPDATE, DELETE, etc.)
        model_name: Name of the model being affected
        object_id: ID of the object being affected
        description: Human readable description of the action
        ip_address: IP address of the user
        user_agent: User agent string
    """
    from .models import AdminLog
    
    try:
        AdminLog.objects.create(
            admin_user=user,
            action=action,
            model_name=model_name,
            object_id=str(object_id) if object_id else '',
            description=description,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else ''  # Truncate long user agents
        )
        logger.info(f'Admin action logged: {user.username} - {action} - {description}')
    except Exception as e:
        logger.error(f'Failed to log admin action: {e}')

def log_security_alert(alert_type, description, ip_address, user_agent='', student=None, payment=None, data=None):
    """
    Log security alerts for monitoring
    
    Args:
        alert_type: Type of security alert
        description: Description of the alert
        ip_address: IP address involved
        user_agent: User agent string
        student: Related student object
        payment: Related payment object
        data: Additional data as dict
    """
    from .models import SecurityAlert
    
    try:
        SecurityAlert.objects.create(
            alert_type=alert_type,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else '',
            related_student=student,
            related_payment=payment,
            data=data
        )
        security_logger.warning(f'Security alert: {alert_type} - {description} - IP: {ip_address}')
    except Exception as e:
        security_logger.error(f'Failed to log security alert: {e}')

def get_client_ip(request):
    """
    Get the real IP address of the client with enhanced detection
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: IP address
    """
    # Check for IP in various headers (for load balancers, proxies)
    ip_headers = [
        'HTTP_X_FORWARDED_FOR',
        'HTTP_X_REAL_IP',
        'HTTP_X_FORWARDED',
        'HTTP_X_CLUSTER_CLIENT_IP',
        'HTTP_FORWARDED_FOR',
        'HTTP_FORWARDED',
        'REMOTE_ADDR'
    ]
    
    for header in ip_headers:
        ip = request.META.get(header)
        if ip:
            # Handle comma-separated IPs (proxy chains)
            ip = ip.split(',')[0].strip()
            # Validate IP format
            if is_valid_ip(ip):
                # Convert IPv6 localhost to IPv4
                if ip == '::1':
                    return '127.0.0.1'
                return ip
    
    return '127.0.0.1'  # Default fallback

def is_valid_ip(ip):
    """Validate IP address format"""
    import ipaddress
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def rate_limit_check(request, key_suffix='', limit=5, period=3600):
    """
    Check and enforce rate limiting
    
    Args:
        request: Django request object
        key_suffix: Additional suffix for cache key
        limit: Maximum attempts allowed
        period: Time period in seconds
        
    Returns:
        tuple: (is_allowed, attempts_remaining)
    """
    ip = get_client_ip(request)
    cache_key = f"rate_limit_{ip}_{key_suffix}"
    
    current_attempts = cache.get(cache_key, 0)
    
    if current_attempts >= limit:
        log_security_alert(
            'RATE_LIMIT',
            f'Rate limit exceeded for {key_suffix}',
            ip,
            request.META.get('HTTP_USER_AGENT', ''),
            data={'attempts': current_attempts, 'limit': limit}
        )
        return False, 0
    
    # Increment attempt count
    cache.set(cache_key, current_attempts + 1, period)
    return True, limit - current_attempts - 1

def generate_sslcommerz_hash(data, store_password):
    """
    Generate SSL Commerz verification hash with enhanced security
    
    Args:
        data: Dictionary of data to hash
        store_password: Store password from SSL Commerz
        
    Returns:
        str: SHA256 hash (more secure than MD5)
    """
    try:
        # Remove verify_sign and verify_key from data if present
        filtered_data = {k: v for k, v in data.items() if k not in ['verify_sign', 'verify_key']}
        
        # Sort the data by keys for consistent hashing
        sorted_data = sorted(filtered_data.items())
        
        # Create hash string
        hash_string = store_password
        for key, value in sorted_data:
            if value is not None and value != '':
                hash_string += f"|{key}={value}"
        
        # Use SHA256 instead of MD5 for better security
        return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.error(f"Error generating SSL Commerz hash: {e}")
        return ""

def verify_sslcommerz_callback(data, store_password):
    """
    Verify SSL Commerz callback authenticity
    
    Args:
        data: Callback data from SSL Commerz
        store_password: Store password
        
    Returns:
        bool: True if verification succeeds
    """
    try:
        received_hash = data.get('verify_sign', '')
        if not received_hash:
            return False
        
        expected_hash = generate_sslcommerz_hash(data, store_password)
        
        # Use secure comparison to prevent timing attacks
        return hmac.compare_digest(expected_hash, received_hash)
    except Exception as e:
        logger.error(f"Error verifying SSL Commerz callback: {e}")
        return False

def sanitize_payment_data(data):
    """
    Sanitize data before sending to payment gateway
    
    Args:
        data: Dictionary containing payment data
        
    Returns:
        dict: Sanitized data
    """
    sanitized = {}
    
    for key, value in data.items():
        if isinstance(value, str):
            # Remove potentially dangerous characters
            sanitized_value = escape(value)
            # Limit length to prevent buffer overflow
            sanitized_value = sanitized_value[:255]
            # Remove special characters that might break payment gateway
            sanitized_value = re.sub(r'[<>"\\]', '', sanitized_value)
            sanitized[key] = sanitized_value
        elif isinstance(value, (int, float, Decimal)):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)[:255] if value is not None else ''
    
    return sanitized

def validate_student_data(data):
    """
    Validate student registration data with enhanced security
    
    Args:
        data: Dictionary containing student data
        
    Returns:
        dict: Dictionary with 'valid' boolean and 'errors' list
    """
    errors = []
    
    # Required fields validation
    required_fields = ['name', 'email', 'mobile_number', 'school_college', 'grade', 'roll']
    for field in required_fields:
        if not data.get(field) or not str(data.get(field)).strip():
            errors.append(f'{field.replace("_", " ").title()} is required')
    
    # Email validation with enhanced checks
    email = data.get('email', '').strip()
    if email:
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            errors.append('Invalid email format')
        elif len(email) > 254:  # RFC 5321 limit
            errors.append('Email address too long')
    
    # Mobile number validation with enhanced checks
    mobile = data.get('mobile_number', '').strip()
    if mobile:
        # Remove any non-digit characters for validation
        digits_only = re.sub(r'\D', '', mobile)
        if len(digits_only) < 10 or len(digits_only) > 15:
            errors.append('Mobile number must be between 10-15 digits')
        # Check for Bangladesh number format if starts with +880
        if mobile.startswith('+880') and len(digits_only) != 13:
            errors.append('Invalid Bangladesh mobile number format')
    
    # Grade validation
    grade = data.get('grade')
    if grade:
        try:
            grade_int = int(grade)
            if grade_int < 3 or grade_int > 12:
                errors.append('Grade must be between 3 and 12')
        except (ValueError, TypeError):
            errors.append('Invalid grade format')
    
    # Name validation - FIXED: Corrected the regex pattern
    name = data.get('name', '').strip()
    if name:
        if len(name) < 2:
            errors.append('Name must be at least 2 characters long')
        elif len(name) > 200:
            errors.append('Name is too long')
        elif not re.match(r'^[a-zA-Z\s\."-]+$', name):
            errors.append('Name contains invalid characters')
    
    # School/College validation
    school = data.get('school_college', '').strip()
    if school and len(school) > 300:
        errors.append('School/College name is too long')
    
    # Roll validation
    roll = data.get('roll', '').strip()
    if roll and len(roll) > 50:
        errors.append('Roll number is too long')
    
    return {
        'valid': len(errors) == 0,
        'errors': errors
    }

def verify_payment_amount(expected_amount, received_amount, tolerance=0.01):
    """
    Verify payment amount with tolerance for floating point precision
    
    Args:
        expected_amount: Expected payment amount
        received_amount: Amount received from gateway
        tolerance: Tolerance for floating point comparison
        
    Returns:
        bool: True if amounts match within tolerance
    """
    try:
        expected = float(expected_amount)
        received = float(received_amount)
        return abs(expected - received) <= tolerance
    except (ValueError, TypeError):
        return False

def generate_secure_transaction_id():
    """
    Generate a secure, unique transaction ID
    
    Returns:
        str: Secure transaction ID
    """
    # Use UUID4 for randomness and current timestamp for uniqueness
    timestamp = str(int(timezone.now().timestamp()))
    random_part = str(uuid.uuid4()).replace('-', '')[:8].upper()
    return f"TSC2025-{timestamp[-6:]}{random_part}"

class EmailThread(Thread):
    def __init__(self, subject, message, from_email, recipient_list, html_message):
        self.subject = subject
        self.message = message
        self.from_email = from_email
        self.recipient_list = recipient_list
        self.html_message = html_message
        super().__init__()

    def run(self):
        try:
            send_mail(
                self.subject,
                self.message,
                self.from_email,
                self.recipient_list,
                html_message=self.html_message,
                fail_silently=False
            )
            logger.info(f'Email sent successfully to {self.recipient_list}')
        except Exception as e:
            logger.error(f'Failed to send email to {self.recipient_list}: {e}')

def send_email_async(subject, message, from_email, recipient_list, html_message=None):
    """
    Send email asynchronously using a thread.
    """
    EmailThread(subject, message, from_email, recipient_list, html_message).start()

def send_notification_email(to_email, subject, message, html_message=None):
    """
    Send notification email with enhanced error handling
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        message: Plain text message
        html_message: HTML message (optional)
        
    Returns:
        bool: True if email was queued successfully
    """
    try:
        # Validate email address - FIXED: Corrected the regex pattern
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', to_email):
            logger.error(f'Invalid email address: {to_email}')
            return False
        
        send_email_async(
            subject=subject[:255],  # Limit subject length
            message=message,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[to_email],
            html_message=html_message
        )
        return True
    except Exception as e:
        logger.error(f'Failed to queue email to {to_email}: {e}')
        return False

def get_payment_status_display(status):
    """
    Get human-readable payment status
    
    Args:
        status: Payment status code
        
    Returns:
        str: Human-readable status
    """
    status_map = {
        'PENDING': 'Pending',
        'SUCCESS': 'Successful',
        'FAILED': 'Failed',
        'CANCELLED': 'Cancelled',
        'EXPIRED': 'Expired'
    }
    return status_map.get(status, status)

def calculate_group_from_grade(grade):
    """
    Calculate group based on grade with validation
    
    Args:
        grade: Grade as string or int
        
    Returns:
        str: Group code (A, B, C, or D) or None if invalid
    """
    try:
        grade_int = int(grade)
        if 3 <= grade_int <= 4:
            return 'A'
        elif 5 <= grade_int <= 6:
            return 'B'
        elif 7 <= grade_int <= 8:
            return 'C'
        elif 9 <= grade_int <= 12:
            return 'D'
        else:
            return None
    except (ValueError, TypeError):
        return None

def export_students_csv():
    """
    Export all students to CSV format with security considerations
    
    Returns:
        str: CSV content as string
    """
    from .models import Student
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Registration ID', 'Name', 'Email', 'Mobile', 'School/College',
        'Grade', 'Group', 'Section', 'Roll', 'Total Amount', 'Paid',
        'Payment Verified', 'Created At'
    ])
    
    # Data - only include non-deleted students
    students = Student.objects.filter(is_deleted=False).order_by('-created_at')
    for student in students:
        writer.writerow([
            str(student.registration_id),
            student.name,
            student.email,
            student.mobile_number,
            student.school_college,
            student.grade.name if student.grade else '',
            student.get_group_display(),
            student.section or '',
            student.roll,
            student.total_amount,
            'Yes' if student.is_paid else 'No',
            'Yes' if student.payment_verified else 'No',
            student.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    return output.getvalue()

def export_payments_csv():
    """
    Export all payments to CSV format
    
    Returns:
        str: CSV content as string
    """
    from .models import Payment
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Transaction ID', 'Student Name', 'Student Email', 'Amount',
        'Payment Method', 'Status', 'Gateway TXN ID', 'Created At', 'Completed At'
    ])
    
    # Data
    payments = Payment.objects.select_related('student').order_by('-created_at')
    for payment in payments:
        writer.writerow([
            payment.transaction_id,
            payment.student.name,
            payment.student.email,
            payment.amount,
            payment.get_payment_method_display() if payment.payment_method else '',
            payment.get_status_display(),
            payment.gateway_txnid or '',
            payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            payment.completed_at.strftime('%Y-%m-%d %H:%M:%S') if payment.completed_at else ''
        ])
    
    return output.getvalue()

def get_dashboard_metrics():
    """
    Get comprehensive dashboard metrics with caching
    
    Returns:
        dict: Dashboard metrics
    """
    from .models import Student, Payment, Event, AdminLog
    from django.db.models import Count, Sum, Avg
    
    # Try to get from cache first
    cache_key = 'dashboard_metrics'
    metrics = cache.get(cache_key)
    
    if metrics is None:
        now = timezone.now()
        today = now.date()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        
        try:
            # Basic counts (exclude soft-deleted)
            total_students = Student.objects.filter(is_deleted=False).count()
            paid_students = Student.objects.filter(is_deleted=False, is_paid=True).count()
            pending_students = Student.objects.filter(is_deleted=False, is_paid=False).count()
            
            # Revenue metrics
            successful_payments = Payment.objects.filter(status='SUCCESS')
            total_revenue = successful_payments.aggregate(Sum('amount'))['amount__sum'] or 0
            average_payment = successful_payments.aggregate(Avg('amount'))['amount__avg'] or 0
            
            # Time-based metrics
            registrations_today = Student.objects.filter(
                is_deleted=False, created_at__date=today
            ).count()
            
            registrations_week = Student.objects.filter(
                is_deleted=False, created_at__gte=week_ago
            ).count()
            
            registrations_month = Student.objects.filter(
                is_deleted=False, created_at__gte=month_ago
            ).count()
            
            # Event metrics
            active_events = Event.objects.filter(is_active=True).count()
            
            # Payment method breakdown
            payment_methods = Payment.objects.filter(
                status='SUCCESS'
            ).values('payment_method').annotate(
                count=Count('id'),
                total=Sum('amount')
            ).order_by('-count')
            
            # Recent activity count
            recent_admin_actions = AdminLog.objects.filter(
                timestamp__gte=week_ago
            ).count()
            
            metrics = {
                'total_students': total_students,
                'paid_students': paid_students,
                'pending_students': pending_students,
                'total_revenue': float(total_revenue),
                'average_payment': float(average_payment),
                'registrations_today': registrations_today,
                'registrations_week': registrations_week,
                'registrations_month': registrations_month,
                'active_events': active_events,
                'payment_methods': list(payment_methods),
                'recent_admin_actions': recent_admin_actions,
                'last_updated': now.isoformat()
            }
            
            # Cache for 5 minutes
            cache.set(cache_key, metrics, 300)
            
        except Exception as e:
            logger.error(f'Error getting dashboard metrics: {e}')
            # Return default metrics on error
            metrics = {
                'total_students': 0,
                'paid_students': 0,
                'pending_students': 0,
                'total_revenue': 0,
                'average_payment': 0,
                'registrations_today': 0,
                'registrations_week': 0,
                'registrations_month': 0,
                'active_events': 0,
                'payment_methods': [],
                'recent_admin_actions': 0,
                'last_updated': now.isoformat()
            }
    
    return metrics

def format_currency(amount):
    """
    Format currency for display with validation
    
    Args:
        amount: Decimal, float, or string amount
        
    Returns:
        str: Formatted currency string
    """
    try:
        amount_float = float(amount) if amount is not None else 0
        return f"৳{amount_float:,.2f}"
    except (ValueError, TypeError):
        return "৳0.00"

def cleanup_old_logs(days=90):
    """
    Clean up old admin logs and security alerts
    
    Args:
        days: Number of days to keep logs (default: 90)
        
    Returns:
        dict: Number of records cleaned up
    """
    from .models import AdminLog, SecurityAlert, PaymentAttempt
    
    try:
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Clean up admin logs
        old_admin_logs = AdminLog.objects.filter(timestamp__lt=cutoff_date)
        admin_count = old_admin_logs.count()
        old_admin_logs.delete()
        
        # Clean up security alerts (keep only unresolved ones)
        old_alerts = SecurityAlert.objects.filter(
            created_at__lt=cutoff_date,
            resolved=True
        )
        alert_count = old_alerts.count()
        old_alerts.delete()
        
        # Clean up old payment attempts
        old_attempts = PaymentAttempt.objects.filter(attempt_time__lt=cutoff_date)
        attempt_count = old_attempts.count()
        old_attempts.delete()
        
        logger.info(f'Cleaned up {admin_count} admin logs, {alert_count} security alerts, {attempt_count} payment attempts')
        
        return {
            'admin_logs': admin_count,
            'security_alerts': alert_count,
            'payment_attempts': attempt_count
        }
        
    except Exception as e:
        logger.error(f'Error cleaning up logs: {e}')
        return {'admin_logs': 0, 'security_alerts': 0, 'payment_attempts': 0}

def detect_suspicious_activity(ip_address, user_agent, student_data=None):
    """
    Detect suspicious registration or payment activity
    
    Args:
        ip_address: Client IP address
        user_agent: User agent string
        student_data: Student data if available
        
    Returns:
        list: List of detected issues
    """
    issues = []
    
    try:
        from .models import Student, PaymentAttempt, SecurityAlert
        
        # Check for too many registrations from same IP
        recent_registrations = Student.objects.filter(
            registration_ip=ip_address,
            created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        if recent_registrations >= 5:
            issues.append('Multiple registrations from same IP')
        
        # Check for suspicious payment attempts
        recent_attempts = PaymentAttempt.objects.filter(
            ip_address=ip_address,
            attempt_time__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        if recent_attempts >= 10:
            issues.append('Excessive payment attempts')
        
        # Check for suspicious user agent
        if not user_agent or len(user_agent) < 10:
            issues.append('Suspicious or missing user agent')
        
        # Check for duplicate student data
        if student_data:
            email = student_data.get('email')
            mobile = student_data.get('mobile_number')
            
            if email and Student.objects.filter(email=email, is_deleted=False).exists():
                issues.append('Email already registered')
            
            if mobile and Student.objects.filter(mobile_number=mobile, is_deleted=False).exists():
                issues.append('Mobile number already registered')
        
        # Log if any issues found
        if issues:
            log_security_alert(
                'SUSPICIOUS_IP',
                f'Suspicious activity detected: {", ".join(issues)}',
                ip_address,
                user_agent,
                data={'issues': issues}
            )
    
    except Exception as e:
        logger.error(f'Error detecting suspicious activity: {e}')
    
    return issues

def export_detailed_report_csv():
    """
    Export a detailed CSV report of all paid students with complete event information.
    """
    from .models import Student, StudentEventRegistration
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Enhanced Header with more comprehensive information
    writer.writerow([
        'Student Name', 'Registration ID', 'Email', 'Mobile Number', 'School/College',
        'Grade', 'Group', 'Section', 'Roll', 'Amount Paid', 'Payment Method',
        'Transaction ID', 'Payment Date', 'Registered Events', 'Event Details',
        'Number of Events', 'Individual Events', 'Team Events', 'Team Details', 'Reference'
    ])

    # Data - Get all paid students with proper relationships
    students = Student.objects.filter(
        is_paid=True, 
        is_deleted=False
    ).prefetch_related(
        'payments', 
        'studenteventregistration_set__event_option__event',
        'studenteventregistration_set__team__members'
    ).order_by('-created_at')

    for student in students:
        # Get payment information
        payment = student.payments.filter(status='SUCCESS').first()
        
        # Get all event registrations for this student
        all_registrations = student.studenteventregistration_set.all()
        
        # Separate individual and team events
        individual_events = []
        team_events = []
        event_details_list = []
        team_details_list = []
        
        for registration in all_registrations:
            event_option = registration.event_option
            event_name = event_option.event.name
            option_name = event_option.name
            fee = event_option.fee
            
            # Create detailed event info
            event_detail = f"{event_name} ({option_name}) - ৳{fee}"
            event_details_list.append(event_detail)
            
            if event_option.event_type == 'INDIVIDUAL':
                individual_events.append(f"{event_name} ({option_name})")
            elif event_option.event_type == 'TEAM':
                team_events.append(f"{event_name} ({option_name})")
                
                # Get team details if exists
                if hasattr(registration, 'team') and registration.team:
                    team = registration.team
                    team_name = team.name
                    
                    member_details = []
                    for member in team.members.order_by('-is_leader', 'id'):
                        detail = member.name
                        if member.is_leader:
                            detail += " (Leader)"
                        member_details.append(detail)
                    
                    if member_details:
                        team_details_list.append(
                            f"{event_name} - Team: {team_name} | Members: [{', '.join(member_details)}]"
                        )

        # Prepare final strings
        all_event_names = ", ".join([reg.event_option.event.name for reg in all_registrations])
        event_details_str = " | ".join(event_details_list)
        individual_events_str = ", ".join(individual_events) if individual_events else "None"
        team_events_str = ", ".join(team_events) if team_events else "None"
        team_details_str = " | ".join(team_details_list) if team_details_list else "N/A"
        num_events = all_registrations.count()

        # Write the row
        writer.writerow([
            student.name,
            student.registration_id,
            student.email,
            student.mobile_number,
            student.school_college.name if student.school_college else student.other_school or 'N/A',
            student.grade.name if student.grade else 'N/A',
            student.get_group_display(),
            student.section or 'N/A',
            student.roll,
            payment.amount if payment else 'N/A',
            payment.get_payment_method_display() if payment and payment.payment_method else 'N/A',
            payment.transaction_id if payment else 'N/A',
            payment.completed_at.strftime('%Y-%m-%d %H:%M:%S') if payment and payment.completed_at else 'N/A',
            all_event_names,  # All registered events
            event_details_str,  # Detailed event info with fees
            num_events,
            individual_events_str,  # Only individual events
            team_events_str,  # Only team events
            team_details_str,  # Complete team details
            student.reference or 'N/A'
        ])

    return output.getvalue()


def export_comprehensive_report_csv():
    """
    Export a comprehensive CSV report including unpaid students for complete carnival overview.
    """
    from .models import Student, Payment, Event, EventOption, StudentEventRegistration
    import csv
    from io import StringIO
    from django.db.models import Count, Sum

    output = StringIO()
    writer = csv.writer(output)

    # Write summary statistics first
    writer.writerow(['=== CARNIVAL OVERVIEW REPORT ==='])
    writer.writerow([])
    
    # Overall statistics
    total_students = Student.objects.filter(is_deleted=False).count()
    paid_students = Student.objects.filter(is_deleted=False, is_paid=True).count()
    pending_students = total_students - paid_students
    
    total_revenue = Payment.objects.filter(status='SUCCESS').aggregate(
        Sum('amount')
    )['amount__sum'] or 0
    
    writer.writerow(['OVERALL STATISTICS'])
    writer.writerow(['Total Registrations', total_students])
    writer.writerow(['Paid Registrations', paid_students])
    writer.writerow(['Pending Payments', pending_students])
    writer.writerow(['Total Revenue', f'৳{total_revenue}'])
    writer.writerow(['Collection Rate', f'{(paid_students/total_students*100):.1f}%' if total_students > 0 else '0%'])
    writer.writerow([])
    
    # Event-wise statistics - FIXED
    writer.writerow(['EVENT-WISE BREAKDOWN'])
    writer.writerow(['Event Name', 'Total Registrations', 'Paid Registrations', 'Revenue'])
    
    events = Event.objects.filter(is_active=True)
    for event in events:
        # Count registrations through the correct relationship
        total_regs = StudentEventRegistration.objects.filter(
            event_option__event=event
        ).count()
        
        paid_regs = StudentEventRegistration.objects.filter(
            event_option__event=event,
            student__is_paid=True, 
            student__is_deleted=False
        ).count()
        
        # Calculate revenue for this event - FIXED
        event_revenue = 0
        for option in event.options.all():
            paid_registrations = StudentEventRegistration.objects.filter(
                event_option=option,
                student__is_paid=True,
                student__is_deleted=False
            )
            event_revenue += sum([option.fee for _ in paid_registrations])
        
        writer.writerow([
            event.name,
            total_regs,
            paid_regs,
            f'৳{event_revenue}'
        ])
    
    writer.writerow([])
    writer.writerow(['=== DETAILED STUDENT RECORDS ==='])
    writer.writerow([])
    
    # Detailed student records header
    writer.writerow([
        'Status', 'Student Name', 'Registration ID', 'Email', 'Mobile Number', 
        'School/College', 'Grade', 'Group', 'Section', 'Roll', 
        'Amount Paid', 'Payment Status', 'Payment Method', 'Transaction ID', 
        'Payment Date', 'All Events', 'Event Details', 'Individual Events', 
        'Team Events', 'Team Details', 'Registration Date', 'Reference'
    ])

    # Get all students (both paid and unpaid)
    students = Student.objects.filter(is_deleted=False).prefetch_related(
        'payments', 
        'studenteventregistration_set__event_option__event',
        'studenteventregistration_set__team__members'
    ).order_by('-created_at')

    for student in students:
        # Determine status
        status = "PAID" if student.is_paid else "PENDING"
        
        # Get payment information
        payment = student.payments.filter(status='SUCCESS').first()
        
        # Get all event registrations
        all_registrations = student.studenteventregistration_set.all()
        
        # Process events (same logic as before)
        individual_events = []
        team_events = []
        event_details_list = []
        team_details_list = []
        
        for registration in all_registrations:
            event_option = registration.event_option
            event_name = event_option.event.name
            option_name = event_option.name
            fee = event_option.fee
            
            event_detail = f"{event_name} ({option_name}) - ৳{fee}"
            event_details_list.append(event_detail)
            
            if event_option.event_type == 'INDIVIDUAL':
                individual_events.append(f"{event_name} ({option_name})")
            elif event_option.event_type == 'TEAM':
                team_events.append(f"{event_name} ({option_name})")
                
                if hasattr(registration, 'team') and registration.team:
                    team = registration.team
                    team_name = team.name
                    
                    member_details = []
                    for member in team.members.order_by('-is_leader', 'id'):
                        detail = member.name
                        if member.is_leader:
                            detail += " (Leader)"
                        member_details.append(detail)
                    
                    if member_details:
                        team_details_list.append(
                            f"{event_name} - Team: {team_name} | Members: [{', '.join(member_details)}]"
                        )

        # Prepare strings
        all_event_names = ", ".join([reg.event_option.event.name for reg in all_registrations])
        event_details_str = " | ".join(event_details_list)
        individual_events_str = ", ".join(individual_events) if individual_events else "None"
        team_events_str = ", ".join(team_events) if team_events else "None"
        team_details_str = " | ".join(team_details_list) if team_details_list else "N/A"

        writer.writerow([
            status,
            student.name,
            student.registration_id,
            student.email,
            student.mobile_number,
            student.school_college.name if student.school_college else student.other_school or 'N/A',
            student.grade.name if student.grade else 'N/A',
            student.get_group_display(),
            student.section or 'N/A',
            student.roll,
            payment.amount if payment else student.total_amount,
            "Completed" if student.is_paid else "Pending",
            payment.get_payment_method_display() if payment and payment.payment_method else 'N/A',
            payment.transaction_id if payment else 'N/A',
            payment.completed_at.strftime('%Y-%m-%d %H:%M:%S') if payment and payment.completed_at else 'N/A',
            all_event_names,
            event_details_str,
            individual_events_str,
            team_events_str,
            team_details_str,
            student.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            student.reference or 'N/A'
        ])

    return output.getvalue()
