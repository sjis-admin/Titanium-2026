# registration/management/commands/send_payment_report.py - NEW COMMAND
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from registration.payment_monitoring import PaymentMonitor
from datetime import timedelta

class Command(BaseCommand):
    help = 'Send daily payment report to admins'

    def handle(self, *args, **options):
        monitor = PaymentMonitor()
        stats = monitor.get_payment_statistics(days=1)
        
        report = f"""
TSC 2026 - Daily Payment Report
Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}

=== Today's Statistics ===
Total Payment Attempts: {stats['total_attempts']}
Successful Payments: {stats['successful']}
Failed Payments: {stats['failed']}
Pending Payments: {stats['pending']}
Cancelled Payments: {stats['cancelled']}
Success Rate: {stats['success_rate']:.2f}%

=== System Health ===
"""
        
        # Add stuck payments info
        stuck = monitor.check_stuck_payments()
        if stuck:
            report += f"⚠️ WARNING: {len(stuck)} stuck payments found\n"
        else:
            report += "✓ No stuck payments\n"
        
        # Add duplicate check
        duplicates = monitor.detect_duplicate_payments()
        if duplicates:
            report += f"⚠️ WARNING: {len(duplicates)} potential duplicates\n"
        else:
            report += "✓ No duplicate payments detected\n"
        
        # Add mismatch check
        mismatches = monitor.check_amount_mismatches()
        if mismatches:
            report += f"❌ CRITICAL: {len(mismatches)} amount mismatches\n"
        else:
            report += "✓ No amount mismatches\n"
        
        report += "\n--- End of Report ---"
        
        # Send email
        try:
            send_mail(
                subject=f'TSC 2026 - Daily Payment Report - {timezone.now().strftime("%Y-%m-%d")}',
                message=report,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[settings.EMAIL_HOST_USER],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS('✅ Payment report sent'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Failed to send report: {e}'))