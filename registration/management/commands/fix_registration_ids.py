# registration/management/commands/fix_registration_ids.py
# Create this file to fix existing wrong registration IDs

from django.core.management.base import BaseCommand
from django.utils import timezone
from registration.models import Student, Receipt
from django.db import transaction


class Command(BaseCommand):
    help = 'Fix registration IDs that have wrong prefix (JMC instead of TSC)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually changing',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.WARNING('Checking for incorrect registration IDs...'))
        
        # Find students with wrong prefix
        current_year = timezone.now().strftime('%y')
        wrong_prefix = f'JMC{current_year}'
        correct_prefix = f'TSC{current_year}'
        
        wrong_students = Student.objects.filter(
            registration_id__startswith=wrong_prefix
        )
        
        count = wrong_students.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('✅ No incorrect registration IDs found!'))
            return
        
        self.stdout.write(
            self.style.WARNING(f'Found {count} students with incorrect registration IDs')
        )
        
        if dry_run:
            for student in wrong_students:
                old_id = student.registration_id
                new_id = old_id.replace(wrong_prefix, correct_prefix)
                self.stdout.write(
                    self.style.WARNING(f'[DRY RUN] Would change: {old_id} → {new_id}')
                )
        else:
            with transaction.atomic():
                fixed_count = 0
                conflict_count = 0
                for student in wrong_students:
                    old_id = student.registration_id
                    proposed_new_id = old_id.replace(wrong_prefix, correct_prefix)
                    
                    try:
                        # Check if the proposed_new_id already exists
                        if Student.objects.filter(registration_id=proposed_new_id).exclude(pk=student.pk).exists():
                            # Conflict: proposed_new_id is already taken by another student
                            # Append a suffix to the old_id to make it unique and mark as conflict
                            conflict_new_id = f"{old_id}_CONFLICT"
                            if len(conflict_new_id) > 20: # Ensure it doesn't exceed max_length
                                conflict_new_id = f"{old_id[:13]}_CFLCT" # Truncate and append
                            
                            student.registration_id = conflict_new_id
                            student.save(update_fields=['registration_id'])
                            self.stdout.write(
                                self.style.ERROR(f'❌ Conflict: {old_id} could not be changed to {proposed_new_id}. Changed to {conflict_new_id} instead.')
                            )
                            conflict_count += 1
                        else:
                            # No conflict, proceed with the intended change
                            student.registration_id = proposed_new_id
                            student.save(update_fields=['registration_id'])
                            self.stdout.write(
                                self.style.SUCCESS(f'✅ Changed: {old_id} → {proposed_new_id}')
                            )
                            fixed_count += 1
                    except Exception as e: # Catch any other unexpected errors during save
                        self.stdout.write(
                            self.style.ERROR(f'❌ Error processing {old_id}: {e}')
                        )
                        conflict_count += 1 # Treat as a conflict/unfixed
                
                self.stdout.write(
                    self.style.SUCCESS(f'\n✅ Successfully fixed {fixed_count} registration IDs')
                )
                if conflict_count > 0:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️ {conflict_count} registration IDs had conflicts and were modified to ensure uniqueness (e.g., JMC..._CONFLICT). Please review these manually.')
                    )
            
        # Also check receipts
        self.stdout.write(self.style.WARNING('\nChecking receipt numbers...'))
        
        wrong_receipts = Receipt.objects.filter(
            receipt_number__startswith='JMC'
        )
        
        receipt_count = wrong_receipts.count()
        
        if receipt_count == 0:
            self.stdout.write(self.style.SUCCESS('✅ No incorrect receipt numbers found!'))
            return
        
        self.stdout.write(
            self.style.WARNING(f'Found {receipt_count} receipts with incorrect numbers')
        )
        
        if dry_run:
            for receipt in wrong_receipts:
                old_num = receipt.receipt_number
                new_num = old_num.replace('JMC', 'TSC')
                self.stdout.write(
                    self.style.WARNING(f'[DRY RUN] Would change receipt: {old_num} → {new_num}')
                )
        else:
            with transaction.atomic():
                fixed_receipt_count = 0
                conflict_receipt_count = 0
                for receipt in wrong_receipts:
                    old_num = receipt.receipt_number
                    proposed_new_num = old_num.replace('JMC', 'TSC')
                    
                    try:
                        if Receipt.objects.filter(receipt_number=proposed_new_num).exclude(pk=receipt.pk).exists():
                            conflict_new_num = f"{old_num}_CONFLICT"
                            if len(conflict_new_num) > 20:
                                conflict_new_num = f"{old_num[:13]}_CFLCT"
                            
                            receipt.receipt_number = conflict_new_num
                            receipt.save(update_fields=['receipt_number'])
                            self.stdout.write(
                                self.style.ERROR(f'❌ Conflict: Receipt {old_num} could not be changed to {proposed_new_num}. Changed to {conflict_new_num} instead.')
                            )
                            conflict_receipt_count += 1
                        else:
                            receipt.receipt_number = proposed_new_num
                            receipt.save(update_fields=['receipt_number'])
                            self.stdout.write(
                                self.style.SUCCESS(f'✅ Changed receipt: {old_num} → {proposed_new_num}')
                            )
                            fixed_receipt_count += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'❌ Error processing receipt {old_num}: {e}')
                        )
                        conflict_receipt_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(f'\n✅ Successfully fixed {fixed_receipt_count} receipt numbers')
            )
            if conflict_receipt_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ {conflict_receipt_count} receipt numbers had conflicts and were modified to ensure uniqueness (e.g., JMC..._CONFLICT). Please review these manually.')
                )