# registration/models.py
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from cryptography.fernet import Fernet
from django.conf import settings
import uuid
import base64
from django.core.exceptions import ValidationError
from decimal import Decimal
import hashlib

class School(models.Model):
    name = models.CharField(max_length=300, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class Grade(models.Model):
    name = models.CharField(max_length=50, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name

class Event(models.Model):
    RULES_TYPE_CHOICES = [
        ('TEXT', 'Text'),
        ('IMAGE', 'Image'),
        ('PDF', 'PDF'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField()
    event_image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    target_grades = models.ManyToManyField(Grade, related_name='events', blank=True)
    
    # New fields for rules
    rules_type = models.CharField(max_length=10, choices=RULES_TYPE_CHOICES, default='TEXT')
    rules_text = models.TextField(blank=True)
    rules_file = models.FileField(upload_to='event_rules/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_gradient_class(self):
        """
        Return CSS gradient class based on event name hash
        """
        gradient_classes = [
            'gradient-primary',
            'gradient-secondary', 
            'gradient-accent',
            'gradient-success',
            'gradient-warning',
            'gradient-info'
        ]
        # Use hash of event name to consistently assign gradient
        hash_value = hash(self.name) % len(gradient_classes)
        return gradient_classes[hash_value]

    def __str__(self):
        return self.name

class EventOption(models.Model):
    EVENT_TYPE_CHOICES = [
        ('INDIVIDUAL', 'Individual'),
        ('TEAM', 'Team'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=100, help_text="e.g., 'Individual', 'Team'")
    event_type = models.CharField(max_length=10, choices=EVENT_TYPE_CHOICES, default='INDIVIDUAL')
    fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    max_participants = models.PositiveIntegerField(null=True, blank=True, help_text="Keep blank for unlimited participants.")
    max_team_size = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(2)], help_text="Required if event type is 'Team'. Minimum 2 members.")

    def clean(self):
        if self.event_type == 'TEAM' and not self.max_team_size:
            raise ValidationError({'max_team_size': "Max team size is required for team events."})
        if self.event_type == 'INDIVIDUAL' and self.max_team_size:
            self.max_team_size = None

    def __str__(self):
        return f"{self.event.name} - {self.name}"

class Student(models.Model):
    GROUP_CHOICES = [
        ('A', 'Group A (Grade 3-4)'),
        ('B', 'Group B (Grade 5-6)'),
        ('C', 'Group C (Grade 7-8)'),
        ('D', 'Group D (Grade 9-12)'),
    ]

    selected_bundle = models.ForeignKey(
        'DiscountBundle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
        help_text="Discount bundle selected by student (if any)"
    )
    
    # Basic Information
    name = models.CharField(max_length=200)
    school_college = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True)
    other_school = models.CharField(max_length=300, blank=True, null=True)
    grade = models.ForeignKey(Grade, on_delete=models.SET_NULL, null=True)
    group = models.CharField(max_length=1, choices=GROUP_CHOICES, editable=False)
    section = models.CharField(max_length=50, blank=True, null=True, help_text="Only for SJIS students")
    roll = models.CharField(max_length=50, help_text="Unique identification from school")
    # NEW FIELD - Add this line
    reference = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        help_text="Campus Ambassador's name"
    )
    # Contact Information (Encrypted)
    email = models.EmailField()
    mobile_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$', 
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
    )
    mobile_number = models.CharField(validators=[mobile_regex], max_length=17)
    
    # Registration Details
    events = models.ManyToManyField(EventOption, through='StudentEventRegistration')
    registration_id = models.CharField(max_length=20, unique=True, editable=False)
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    is_paid = models.BooleanField(default=False)
    payment_verified = models.BooleanField(default=False)
    payment_verification_hash = models.CharField(max_length=64, blank=True)
    
    # Security and Audit
    registration_ip = models.GenericIPAddressField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)  # Soft delete
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['registration_id']),
            models.Index(fields=['is_paid']),
            models.Index(fields=['created_at']),
        ]
    
    def clean(self):
        super().clean()
        # Validate grade and group consistency
        if self.grade:
            expected_group = self.calculate_group_from_grade_id(self.grade.id)
            if self.group and self.group != expected_group:
                raise ValidationError(f"Grade {self.grade.name} should be in Group {expected_group}")
    
    def save(self, *args, **kwargs):
        # Auto-assign group based on grade ranges
        if self.grade:
            self.group = self.calculate_group_from_grade_id(self.grade.id)

        if not self.registration_id:
            current_year = timezone.now().strftime('%y')
            prefix = f'TSC{current_year}'
            last_student = Student.objects.filter(registration_id__startswith=prefix).order_by('registration_id').last()
            
            if last_student:
                last_id = int(last_student.registration_id[len(prefix):])
                new_id = last_id + 1
            else:
                new_id = 1
            
            self.registration_id = f'{prefix}{new_id:04d}'
        
        # Generate payment verification hash
        if not self.payment_verification_hash:
            self.payment_verification_hash = self.generate_verification_hash()
        
        super().save(*args, **kwargs)
    
    @staticmethod
    def calculate_group_from_grade_id(grade_id):
        """Calculate group based on grade ID using the Grade model's order field"""
        try:
            grade = Grade.objects.get(id=grade_id)
            grade_order = grade.order
            
            # Determine group based on the 'order' field
            if 3 <= grade_order <= 4:
                return 'A'
            elif 5 <= grade_order <= 6:
                return 'B'
            elif 7 <= grade_order <= 8:
                return 'C'
            elif 9 <= grade_order <= 12:
                return 'D'
            else:
                # This case handles grades outside the defined groups (e.g., 1, 2, 13)
                return None
                
        except Grade.DoesNotExist:
            return None
    
    @staticmethod
    def calculate_group_from_grade(grade_name):
        """Calculate group based on grade - improved version"""
        import re
        
        try:
            # Extract numeric value from grade name
            grade_number_match = re.search(r'\d+', str(grade_name))
            if grade_number_match:
                grade_number = int(grade_number_match.group())
            else:
                # Handle word numbers
                word_to_number = {
                    'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 
                    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12
                }
                grade_lower = str(grade_name).lower()
                grade_number = None
                for word, number in word_to_number.items():
                    if word in grade_lower:
                        grade_number = number
                        break
                
                if grade_number is None:
                    raise ValidationError(f"Could not extract grade number from: {grade_name}")
            
            # Calculate group
            if 3 <= grade_number <= 4:
                return 'A'
            elif 5 <= grade_number <= 6:
                return 'B'
            elif 7 <= grade_number <= 8:
                return 'C'
            elif 9 <= grade_number <= 12:
                return 'D'
            else:
                raise ValidationError(f"Grade {grade_number} is not in valid range (3-12)")
                
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid grade format: {grade_name} - {str(e)}")
    
    def get_grade_and_group_display(self):
        """Get a clean display of grade and group without duplication"""
        if self.grade and self.group:
            group_display = dict(self.GROUP_CHOICES).get(self.group, '')
            return f"{self.grade.name} ({group_display})"
        elif self.grade:
            return self.grade.name
        elif self.group:
            return dict(self.GROUP_CHOICES).get(self.group, '')
        return "Not specified"
    
    def generate_verification_hash(self):
        """Generate verification hash for payment security"""
        data = f"{self.registration_id}{self.email}{self.total_amount}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def calculate_total_amount(self):
        """Calculate and update total amount"""
        if self.events.count() > 0:
            total = Decimal('500.00')
        else:
            total = Decimal('0.00')
        self.total_amount = total
        # Regenerate hash when amount changes
        self.payment_verification_hash = self.generate_verification_hash()
        return total
    
    def verify_payment_integrity(self, received_amount):
        """Verify payment amount matches expected amount"""
        expected = float(self.total_amount)
        received = float(received_amount)
        return abs(expected - received) < 0.01
    
    def can_register_for_event(self, event_option):
        """Check if student can register for an event"""
        if not event_option.event.is_active:
            return False, "Event is not active"

        # Check if the student is already registered for another option of the same event
        if StudentEventRegistration.objects.filter(student=self, event_option__event=event_option.event).exists():
            return False, f"You are already registered for {event_option.event.name}."

        return True, "Can register"
    
    def __str__(self):
        school_name = self.school_college.name if self.school_college else self.other_school
        return f"{self.name} - {school_name}"

class Team(models.Model):
    registration = models.OneToOneField('StudentEventRegistration', on_delete=models.CASCADE, related_name='team')
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='members')
    name = models.CharField(max_length=200, default="")
    is_leader = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.name} - {self.team.name}'

class ValorantTeamMember(models.Model):
    team_member = models.OneToOneField(TeamMember, on_delete=models.CASCADE, related_name='valorant_info')
    discord_ign = models.CharField(max_length=100, help_text="Discord IGN (e.g., username#1234)")
    riot_ign = models.CharField(max_length=100, help_text="Riot IGN (e.g., username#NA1)")
    contact_number = models.CharField(max_length=20, help_text="Contact number for the team member")

    def __str__(self):
        return f"Valorant Info for {self.team_member.name}"

class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('EXPIRED', 'Expired'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('BKASH', 'bKash'),
        ('ROCKET', 'Rocket'),
        ('NAGAD', 'Nagad'),
        ('CARD', 'Credit/Debit Card'),
        ('UPAY', 'Upay'),
        ('OTHER', 'Other'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='payments')
    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    amount = models.DecimalField(
    max_digits=10,
    decimal_places=2,
    validators=[MinValueValidator(Decimal('0.01'))]   # ✅ fixed
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    
    # SSL Commerz specific fields
    sessionkey = models.CharField(max_length=200, blank=True)
    gateway_txnid = models.CharField(max_length=200, blank=True)
    gateway_response = models.JSONField(blank=True, null=True)
    
    # Security fields
    payment_hash = models.CharField(max_length=64, blank=True)
    verification_signature = models.CharField(max_length=128, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
    
    def save(self, *args, **kwargs):
        # Set expiration time if not set
        if not self.expires_at and self.status == 'PENDING':
            self.expires_at = timezone.now() + timezone.timedelta(
                minutes=getattr(settings, 'PAYMENT_TIMEOUT_MINUTES', 15)
            )
        
        # Set completion time when marked as success
        if self.status == 'SUCCESS' and not self.completed_at:
            self.completed_at = timezone.now()
        
        super().save(*args, **kwargs)
    
    def generate_payment_hash(self):
        """Generate secure hash for payment verification"""
        data = f"{self.transaction_id}{self.student.registration_id}{self.amount}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def verify_ssl_commerz_signature(self, received_data):
        """Verify SSL Commerz callback signature"""
        from .utils import generate_sslcommerz_hash
        expected_hash = generate_sslcommerz_hash(received_data, settings.SSLCOMMERZ_STORE_PASSWORD)
        received_hash = received_data.get('verify_sign', '')
        return expected_hash == received_hash
    
    def is_expired(self):
        """Check if payment has expired"""
        if self.expires_at and self.status == 'PENDING':
            return timezone.now() > self.expires_at
        return False
    
    def mark_expired(self):
        """Mark payment as expired"""
        if self.is_expired() and self.status == 'PENDING':
            self.status = 'EXPIRED'
            self.save()
    
    def __str__(self):
        return f"Payment {self.transaction_id} - {self.student.name}"

class StudentEventRegistration(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    event_option = models.ForeignKey(EventOption, on_delete=models.CASCADE)
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    registration_ip = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        unique_together = ['student', 'event_option']
        indexes = [
            models.Index(fields=['registered_at']),
        ]

class PaymentAttempt(models.Model):
    """Track payment attempts for security monitoring"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    attempt_time = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-attempt_time']
        indexes = [
            models.Index(fields=['ip_address', 'attempt_time']),
        ]

class AdminLog(models.Model):
    ACTION_CHOICES = [
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
        ('LOGIN', 'Logged In'),
        ('LOGOUT', 'Logged Out'),
        ('PAYMENT_VERIFY', 'Payment Verified'),
        ('PAYMENT_REJECT', 'Payment Rejected'),
        ('RECEIPT_GENERATE', 'Receipt Generated'),
        ('EMAIL_SENT', 'Email Sent'),
        ('BULK_UPDATE', 'Bulk Update'),
        ('SECURITY_ALERT', 'Security Alert'),
    ]
    
    admin_user = models.ForeignKey(User, on_delete=models.CASCADE)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    model_name = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['admin_user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.admin_user.username} - {self.action} - {self.timestamp}"

from django.db import transaction

class Receipt(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='receipts')
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='receipts')
    receipt_number = models.CharField(max_length=20, unique=True, db_index=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(blank=True, null=True)
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['receipt_number']),
            models.Index(fields=['generated_at']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.receipt_number:
            with transaction.atomic():
                current_year = timezone.now().year
                prefix = f"TSC{current_year}"  # Changed to TSC with full year
                
                # Lock the table to prevent race conditions
                last_receipt = Receipt.objects.select_for_update().filter(
                    receipt_number__startswith=prefix
                ).order_by('receipt_number').last()
                
                if last_receipt:
                    try:
                        # Extract the numeric part (e.g., "TSC2025-0001" → 1)
                        parts = last_receipt.receipt_number.split('-')
                        if len(parts) == 2:
                            last_number = int(parts[1])
                            new_number = last_number + 1
                        else:
                            new_number = 1
                    except (ValueError, IndexError):
                        new_number = 1
                else:
                    new_number = 1
                
                self.receipt_number = f"{prefix}-{new_number:04d}"
        
        super().save(*args, **kwargs)
    
    def record_download(self):
        """Record receipt download"""
        self.download_count += 1
        self.last_downloaded_at = timezone.now()
        self.save(update_fields=['download_count', 'last_downloaded_at'])
    
    def __str__(self):
        return f"Receipt {self.receipt_number} - {self.student.name}"

class SecurityAlert(models.Model):
    """Track security-related events"""
    ALERT_TYPES = [
        ('PAYMENT_FRAUD', 'Payment Fraud Attempt'),
        ('RATE_LIMIT', 'Rate Limit Exceeded'),
        ('INVALID_HASH', 'Invalid Hash Verification'),
        ('SUSPICIOUS_IP', 'Suspicious IP Activity'),
        ('MULTIPLE_REGISTRATIONS', 'Multiple Registrations'),
    ]
    
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    description = models.TextField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    related_student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True)
    related_payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    data = models.JSONField(blank=True, null=True)
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_type', 'created_at']),
            models.Index(fields=['ip_address']),
        ]
    
    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.created_at}"

class Countdown(models.Model):
    title = models.CharField(max_length=200)
    target_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

class HomePageAsset(models.Model):
    ASSET_TYPE_CHOICES = [
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
    ]
    
    title = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    file = models.FileField(upload_to='homepage_assets/')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class SocialMediaProfile(models.Model):
    PLATFORM_CHOICES = [
        ('FACEBOOK', 'Facebook'),
        ('INSTAGRAM', 'Instagram'),
        ('TWITTER', 'Twitter'),
        ('LINKEDIN', 'LinkedIn'),
        ('YOUTUBE', 'YouTube'),
        ('DISCORD', 'Discord'),
    ]

    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, unique=True)
    url = models.URLField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.platform

class TeamMemberProfile(models.Model):
    MEMBER_TYPE_CHOICES = [
        ('MODERATOR', 'Moderator'),
        ('BOARD_MEMBER', 'Board Member'),
    ]

    name = models.CharField(max_length=200)
    designation = models.CharField(max_length=200)
    image = models.ImageField(upload_to='team_members/')
    member_type = models.CharField(max_length=20, choices=MEMBER_TYPE_CHOICES)

    def __str__(self):
        return self.name

class PastEventImage(models.Model):
    image = models.ImageField(upload_to='past_events/')
    caption = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.caption or 'Past Event Image'

class ValorantBackgroundVideo(models.Model):
    title = models.CharField(max_length=200)
    video = models.FileField(upload_to='valorant_backgrounds/')
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class SiteLogo(models.Model):
    name = models.CharField(max_length=200)
    logo = models.FileField(upload_to='site_logos/')
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name



class ValorantApplicationSettings(models.Model):
    is_enabled = models.BooleanField(default=False, help_text="Enable or disable Valorant applications")

    def __str__(self):
        return "Valorant Application Settings"



class DiscountBundle(models.Model):
    """Discount bundle packages for different grade groups"""
    BUNDLE_TYPE_CHOICES = [
        ('JUNIOR', 'Titanium Junior Innovators Pack (Grade 3-6)'),
        ('SENIOR', 'Titanium Senior Visionaries Pack (Grade 7-12)'),
    ]
    
    name = models.CharField(max_length=200)
    bundle_type = models.CharField(max_length=10, choices=BUNDLE_TYPE_CHOICES)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Grade range for this bundle
    min_grade = models.ForeignKey(
        Grade, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='bundles_min',
        help_text="Minimum grade for this bundle"
    )
    max_grade = models.ForeignKey(
        Grade, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='bundles_max',
        help_text="Maximum grade for this bundle"
    )
    
    # Visual elements
    badge_color = models.CharField(
        max_length=50,
        default='blue',
        help_text="Tailwind color class (e.g., 'blue', 'purple', 'green')"
    )
    icon = models.CharField(
        max_length=50,
        default='fa-star',
        help_text="FontAwesome icon class (e.g., 'fa-star', 'fa-rocket')"
    )
    
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['display_order', 'bundle_type']
        verbose_name = 'Discount Bundle'
        verbose_name_plural = 'Discount Bundles'
    
    def __str__(self):
        return f"{self.name} - ৳{self.price}"
    
    def get_events(self):
        """Get all events in this bundle"""
        return self.bundle_events.select_related('event_option__event').all()
    
    def is_available_for_grade(self, grade):
        """Check if bundle is available for given grade"""
        if not self.min_grade or not self.max_grade:
            return False
        return self.min_grade.order <= grade.order <= self.max_grade.order


class BundleEvent(models.Model):
    """Events included in a discount bundle"""
    bundle = models.ForeignKey(
        DiscountBundle, 
        on_delete=models.CASCADE,
        related_name='bundle_events'
    )
    event_option = models.ForeignKey(
        EventOption, 
        on_delete=models.CASCADE,
        related_name='bundle_inclusions'
    )
    display_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['display_order']
        unique_together = ['bundle', 'event_option']
        verbose_name = 'Bundle Event'
        verbose_name_plural = 'Bundle Events'
    
    def __str__(self):
        return f"{self.bundle.name} - {self.event_option.event.name}"
