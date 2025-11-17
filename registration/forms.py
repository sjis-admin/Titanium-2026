# registration/forms.py - FIXED VERSION
from django import forms
from django.core.exceptions import ValidationError
from .models import Student, School, Grade, EventOption
import logging

logger = logging.getLogger(__name__)

class StudentRegistrationForm(forms.ModelForm):
    other_school = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Enter your school/college name'
        })
    )
    selected_events = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,  # We'll do custom validation in clean_selected_events
    )

    class Meta:
        model = Student
        fields = ['name', 'email', 'mobile_number', 'school_college', 'other_school', 
                 'grade', 'section', 'roll', 'reference']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter your full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter your email address'
            }),
            'mobile_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '01XXXXXXXXX'
            }),
            'school_college': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'
            }),
            'grade': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'id': 'id_grade'
            }),
            'section': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'e.g., A, B, C'
            }),
            'roll': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter your roll number/ID'
            }),
            'reference': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': "Your Campus Ambassador's name"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        schools = School.objects.all().order_by('name')
        school_choices = [('', 'Other (specify below)')]
        school_choices.extend([(school.id, school.name) for school in schools])
        self.fields['school_college'].choices = school_choices
        
        grades = Grade.objects.all().order_by('order')
        grade_choices = [('', 'Select your grade')]
        grade_choices.extend([(grade.id, grade.name) for grade in grades])
        self.fields['grade'].choices = grade_choices

    def clean_selected_events(self):
        selected_events_str = self.cleaned_data.get('selected_events', '').strip()
        
        logger.info(f"clean_selected_events() - raw data: '{selected_events_str}'")
        
        if not selected_events_str:
            raise ValidationError("Please select at least one event.")
        
        try:
            event_option_ids = []
            cleaned_string = selected_events_str.replace('"', '').replace("'", '').strip()
            
            if cleaned_string.startswith('[') and cleaned_string.endswith(']'):
                cleaned_string = cleaned_string.strip('[]')
            
            id_strings = [id_str.strip() for id_str in cleaned_string.split(',') if id_str.strip()]
            
            for id_str in id_strings:
                if id_str.isdigit():
                    event_option_ids.append(int(id_str))
                else:
                    logger.warning(f"Non-digit value in selected_events: {id_str}")
            
            if not event_option_ids:
                raise ValidationError("Please select at least one event.")
            
            event_options = EventOption.objects.filter(
                id__in=event_option_ids, 
                event__is_active=True
            )
            
            if len(event_options) != len(event_option_ids):
                found_ids = list(event_options.values_list('id', flat=True))
                missing_ids = set(event_option_ids) - set(found_ids)
                logger.error(f"Some events not found. Missing IDs: {missing_ids}")
                raise ValidationError("One or more selected events are invalid.")
            
            logger.info(f"✓ clean_selected_events passed - {len(event_options)} events found")
            return event_options

        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing selected_events: {e}")
            raise ValidationError("Invalid event selection format.")

    def clean(self):
        cleaned_data = super().clean()
        
        # Cross-field validation for grade and events
        grade = cleaned_data.get('grade')
        event_options = cleaned_data.get('selected_events')
        
        # Check if this is a bundle registration by looking for 'bundle_id' in the submitted data
        is_bundle_registration = 'bundle_id' in self.data
        
        if grade and event_options:
            invalid_events = []
            valid_event_options = []
            
            for event_option in event_options:
                if event_option.event.target_grades.filter(id=grade.id).exists():
                    valid_event_options.append(event_option)
                else:
                    invalid_events.append(event_option.event.name)
            
            if invalid_events:
                if is_bundle_registration:
                    # For bundles, silently filter out invalid events
                    cleaned_data['selected_events'] = valid_event_options
                    logger.info(f"Bundle registration for grade {grade.name}: "
                                f"Filtered out invalid events: {', '.join(invalid_events)}")
                else:
                    # For regular registration, raise a validation error
                    self.add_error(
                        'selected_events',
                        f"These events are not available for {grade.name}: {', '.join(invalid_events)}"
                    )
        
        # Validate school
        school_college = cleaned_data.get('school_college')
        other_school = cleaned_data.get('other_school', '').strip()
        
        if not school_college and not other_school:
            self.add_error("other_school", "Please select or specify your school/college.")
        
        # Validate grade
        if not cleaned_data.get('grade'):
            self.add_error("grade", "Please select your grade.")
        
        return cleaned_data

class BulkSchoolForm(forms.Form):
    """Form for bulk adding schools"""
    schools = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 10,
            'cols': 50,
            'placeholder': 'Enter school names, one per line:\n\nABC School\nXYZ College\nPQR Institute'
        }),
        help_text='Enter one school name per line. Duplicate schools will be ignored.'
    )

    def clean_schools(self):
        """Clean and validate school names"""
        schools_text = self.cleaned_data['schools']
        school_names = []
        
        if not schools_text.strip():
            raise ValidationError('Please enter at least one school name.')
        
        # Split by lines and clean each name
        lines = schools_text.split('\n')
        for line in lines:
            school_name = line.strip()
            if school_name and len(school_name) <= 300:  # Respect model max_length
                school_names.append(school_name)
            elif school_name and len(school_name) > 300:
                raise ValidationError(f'School name "{school_name[:50]}..." is too long (max 300 characters).')
        
        if not school_names:
            raise ValidationError('No valid school names found. Please check your input.')
        
        # Remove duplicates while preserving order
        unique_schools = []
        seen = set()
        for name in school_names:
            if name.lower() not in seen:
                unique_schools.append(name)
                seen.add(name.lower())
        
        return unique_schools

class AdminStudentUpdateForm(forms.ModelForm):
    """Form for admin to update student information"""
    class Meta:
        model = Student
        fields = ['name', 'email', 'mobile_number', 'school_college', 'grade', 'section', 'roll', 'reference', 'is_paid', 'payment_verified']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'mobile_number': forms.TextInput(attrs={'class': 'form-control'}),
            'school_college': forms.Select(attrs={'class': 'form-control'}),
            'grade': forms.Select(attrs={'class': 'form-control'}),
            'section': forms.TextInput(attrs={'class': 'form-control'}),
            'roll': forms.TextInput(attrs={'class': 'form-control'}),
        }

class PaymentVerificationForm(forms.Form):
    """Form for manual payment verification"""
    verify = forms.BooleanField(
        required=False,
        label='Mark as Verified',
        help_text='Check this box to verify the payment manually.'
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        required=False,
        label='Verification Notes',
        help_text='Optional notes about the verification.'
    )

class BulkActionForm(forms.Form):
    """Form for bulk actions on students"""
    ACTION_CHOICES = [
        ('', 'Select Action'),
        ('verify_payment', 'Verify Payment'),
        ('mark_paid', 'Mark as Paid'),
        ('send_email', 'Send Confirmation Email'),
        ('export_csv', 'Export to CSV'),
        ('delete', 'Delete (Soft)'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    student_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

class EmailForm(forms.Form):
    """Form for sending emails to students"""
    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Email subject line'
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 10, 'class': 'form-control'}),
        help_text='Email message content'
    )
    include_receipt = forms.BooleanField(
        required=False,
        label='Include Receipt',
        help_text='Attach the registration receipt to the email'
    )
