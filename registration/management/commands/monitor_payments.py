# registration/management/commands/monitor_payments.py - NEW COMMAND
from django.core.management.base import BaseCommand
from django.core.mail import mail_admins
from registration.payment_monitoring import PaymentMonitor

class Command(BaseCommand):
    help = 'Monitor payment system and send alerts'

    def handle(self, *args, **options):
        monitor = PaymentMonitor()
        
        # Check for stuck payments
        stuck = monitor.check_stuck_payments()
        if stuck:
            self.stdout.write(self.style.WARNING(
                f'⚠️ Found {len(stuck)} stuck payments: {", ".join(stuck)}'
            ))
            mail_admins(
                'TSC 2026 - Stuck Payments Alert',
                f'Found {len(stuck)} stuck payments:\n' + '\n'.join(stuck)
            )
        
        # Check for duplicates
        duplicates = monitor.detect_duplicate_payments()
        if duplicates:
            self.stdout.write(self.style.WARNING(
                f'⚠️ Found {len(duplicates)} potential duplicate payments'
            ))
        
        # Check amount mismatches
        mismatches = monitor.check_amount_mismatches()
        if mismatches:
            self.stdout.write(self.style.ERROR(
                f'❌ Found {len(mismatches)} amount mismatches'
            ))
            mail_admins(
                'TSC 2026 - Payment Amount Mismatches',
                f'Critical: Found {len(mismatches)} amount mismatches:\n' +
                '\n'.join([str(m) for m in mismatches])
            )
        
        # Get statistics
        stats = monitor.get_payment_statistics()
        self.stdout.write(self.style.SUCCESS(
            f'\n📊 Payment Statistics (Last 7 days):\n' +
            f'  Total Attempts: {stats["total_attempts"]}\n' +
            f'  Successful: {stats["successful"]}\n' +
            f'  Failed: {stats["failed"]}\n' +
            f'  Pending: {stats["pending"]}\n' +
            f'  Success Rate: {stats["success_rate"]:.2f}%'
        ))
