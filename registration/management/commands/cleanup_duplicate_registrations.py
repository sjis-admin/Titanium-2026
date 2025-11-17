# registration/management/commands/cleanup_duplicate_registrations.py
# Create this file to clean up existing database issues

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from registration.models import StudentEventRegistration, Payment
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up duplicate and incomplete event registrations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.WARNING('Starting registration cleanup...'))
        
        # Find duplicate registrations
        duplicates = StudentEventRegistration.objects.values(
            'student', 'event_option'
        ).annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        total_cleaned = 0
        
        if duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f'Found {len(duplicates)} sets of duplicate registrations'
                )
            )
            
            for dup in duplicates:
                # Get all duplicate registrations for this student/event combination
                regs = StudentEventRegistration.objects.filter(
                    student_id=dup['student'],
                    event_option_id=dup['event_option']
                ).order_by('registered_at')
                
                # Keep the first one if it has a successful payment, otherwise keep the last one
                successful_reg = regs.filter(payment__status='SUCCESS').first()
                
                if successful_reg:
                    # Keep the successful one, delete others
                    to_delete = regs.exclude(id=successful_reg.id)
                    count = to_delete.count()
                    
                    if not dry_run:
                        to_delete.delete()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Kept successful registration, removed {count} duplicates'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f'[DRY RUN] Would keep successful registration, remove {count} duplicates'
                            )
                        )
                    total_cleaned += count
                else:
                    # No successful payment - keep the most recent, delete older ones
                    to_keep = regs.last()
                    to_delete = regs.exclude(id=to_keep.id)
                    count = to_delete.count()
                    
                    if not dry_run:
                        to_delete.delete()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Kept most recent registration, removed {count} older duplicates'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f'[DRY RUN] Would keep most recent, remove {count} older duplicates'
                            )
                        )
                    total_cleaned += count
        
        # Clean up orphaned registrations (no payment or expired payment)
        orphaned = StudentEventRegistration.objects.filter(
            payment__isnull=True
        ) | StudentEventRegistration.objects.filter(
            payment__status__in=['FAILED', 'CANCELLED', 'EXPIRED']
        )
        
        orphaned_count = orphaned.count()
        if orphaned_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Found {orphaned_count} orphaned registrations'
                )
            )
            
            if not dry_run:
                orphaned.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Removed {orphaned_count} orphaned registrations'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'[DRY RUN] Would remove {orphaned_count} orphaned registrations'
                    )
                )
            total_cleaned += orphaned_count
        
        # Summary
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\n[DRY RUN] Would clean up {total_cleaned} problematic registrations'
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    'Run without --dry-run to actually clean up the database'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Successfully cleaned up {total_cleaned} problematic registrations'
                )
            )