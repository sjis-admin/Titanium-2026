# registration/payment_monitoring.py - NEW FILE
"""
Payment monitoring and security enhancements
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
from registration.models import Payment, SecurityAlert, PaymentAttempt
import logging

logger = logging.getLogger(__name__)


class PaymentMonitor:
    """Monitor payment system for issues and anomalies"""
    
    @staticmethod
    def check_stuck_payments():
        """Find payments stuck in PENDING state"""
        threshold = timezone.now() - timedelta(hours=1)
        stuck_payments = Payment.objects.filter(
            status='PENDING',
            created_at__lt=threshold,
            expires_at__gt=timezone.now()  # Not expired but old
        )
        
        if stuck_payments.exists():
            logger.warning(f"⚠️ Found {stuck_payments.count()} stuck pending payments")
            return list(stuck_payments.values_list('transaction_id', flat=True))
        return []
    
    @staticmethod
    def detect_duplicate_payments():
        """Detect potential duplicate payments"""
        duplicates = Payment.objects.filter(
            status='SUCCESS'
        ).values('student', 'amount').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        if duplicates:
            logger.warning(f"⚠️ Found {len(duplicates)} potential duplicate payments")
        return duplicates
    
    @staticmethod
    def check_amount_mismatches():
        """Check for payment amount discrepancies"""
        mismatches = []
        payments = Payment.objects.filter(
            status='SUCCESS'
        ).select_related('student')
        
        for payment in payments:
            expected = payment.student.total_amount
            if abs(float(payment.amount) - float(expected)) > 0.01:
                mismatches.append({
                    'transaction_id': payment.transaction_id,
                    'expected': expected,
                    'received': payment.amount
                })
        
        if mismatches:
            logger.error(f"❌ Found {len(mismatches)} amount mismatches")
        return mismatches
    
    @staticmethod
    def get_payment_statistics(days=7):
        """Get payment statistics for monitoring"""
        since = timezone.now() - timedelta(days=days)
        
        stats = {
            'total_attempts': Payment.objects.filter(created_at__gte=since).count(),
            'successful': Payment.objects.filter(
                created_at__gte=since, 
                status='SUCCESS'
            ).count(),
            'failed': Payment.objects.filter(
                created_at__gte=since,
                status='FAILED'
            ).count(),
            'pending': Payment.objects.filter(
                created_at__gte=since,
                status='PENDING'
            ).count(),
            'cancelled': Payment.objects.filter(
                created_at__gte=since,
                status='CANCELLED'
            ).count(),
        }
        
        stats['success_rate'] = (
            (stats['successful'] / stats['total_attempts'] * 100)
            if stats['total_attempts'] > 0 else 0
        )
        
        return stats

