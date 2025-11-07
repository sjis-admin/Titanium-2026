# registration/admin.py
from django.contrib import admin
from django.shortcuts import redirect
from django.utils.html import format_html
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.db.models import Count
from .models import (Student, Event, EventOption, Payment, AdminLog, Receipt, 
                    StudentEventRegistration, School, Countdown, 
                    HomePageAsset, SocialMediaProfile, TeamMemberProfile, PastEventImage,
                    ValorantBackgroundVideo, SiteLogo, Grade, ValorantApplicationSettings)

@admin.register(TeamMemberProfile)
class TeamMemberProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'designation', 'member_type')

@admin.register(PastEventImage)
class PastEventImageAdmin(admin.ModelAdmin):
    list_display = ('caption',)

@admin.register(ValorantBackgroundVideo)
class ValorantBackgroundVideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'created_at')
    list_filter = ('is_active',)
    actions = ['activate', 'deactivate']

    def activate(self, request, queryset):
        queryset.update(is_active=True)
    activate.short_description = "Mark selected videos as active"

    def deactivate(self, request, queryset):
        queryset.update(is_active=False)
    deactivate.short_description = "Mark selected videos as inactive"

@admin.register(SiteLogo)
class SiteLogoAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    actions = ['activate']

    def activate(self, request, queryset):
        SiteLogo.objects.all().update(is_active=False)
        queryset.update(is_active=True)
    activate.short_description = "Mark selected logo as active"

@admin.register(HomePageAsset)
class HomePageAssetAdmin(admin.ModelAdmin):
    list_display = ('title', 'asset_type', 'is_active', 'created_at')

@admin.register(SocialMediaProfile)
class SocialMediaProfileAdmin(admin.ModelAdmin):
    list_display = ('platform', 'url', 'is_active')

@admin.register(Countdown)
class CountdownAdmin(admin.ModelAdmin):
    list_display = ('title', 'target_date', 'is_active')

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name']
    ordering = ['name']
    change_list_template = "admin/registration/school/change_list.html"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['bulk_add_url'] = reverse('bulk_add_schools')
        return super().changelist_view(request, extra_context=extra_context)
from .utils import log_admin_action, get_client_ip

class StudentEventRegistrationInline(admin.TabularInline):
    model = StudentEventRegistration
    extra = 0
    readonly_fields = ['registered_at']

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = [
        'registration_id', 'name', 'school_college', 'grade', 'group', 'email', 
        'mobile_number', 'reference', 'total_amount', 'payment_status', 'created_at'  # Added 'reference'
    ]
    list_filter = [
        'grade', 'group', 'is_paid', 'payment_verified', 'created_at', 'school_college'
    ]
    search_fields = ['registration_id', 'name', 'email', 'mobile_number', 'roll', 'school_college', 'reference']  # Added 'reference'
    readonly_fields = ['registration_id', 'group', 'total_amount', 'created_at', 'updated_at']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    inlines = [StudentEventRegistrationInline]
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('name', 'email', 'mobile_number')
        }),
        ('Academic Information', {
            'fields': ('school_college', 'grade', 'group', 'section', 'roll', 'reference')  # Added 'reference'
        }),
        ('Registration Details', {
            'fields': ('registration_id', 'total_amount', 'is_paid', 'payment_verified')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_paid', 'mark_as_unpaid', 'send_confirmation_email']
    
    def payment_status(self, obj):
        if obj.is_paid:
            color = 'green'
            status = 'Paid'
            if obj.payment_verified:
                status += ' ✓'
        else:
            color = 'red'
            status = 'Unpaid'
        return format_html('<span style="color: {};">{}</span>', color, status)
    payment_status.short_description = 'Payment Status'
    
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(is_paid=True, payment_verified=True)
        
        # Log the action
        log_admin_action(
            user=request.user,
            action='UPDATE',
            model_name='Student',
            object_id=','.join([str(obj.id) for obj in queryset]),
            description=f'Marked {updated} students as paid',
            ip_address=get_client_ip(request)
        )
        
        self.message_user(request, f'{updated} students marked as paid.')
    mark_as_paid.short_description = 'Mark selected students as paid'
    
    def mark_as_unpaid(self, request, queryset):
        updated = queryset.update(is_paid=False, payment_verified=False)
        
        log_admin_action(
            user=request.user,
            action='UPDATE',
            model_name='Student',
            object_id=','.join([str(obj.id) for obj in queryset]),
            description=f'Marked {updated} students as unpaid',
            ip_address=get_client_ip(request)
        )
        
        self.message_user(request, f'{updated} students marked as unpaid.')
    mark_as_unpaid.short_description = 'Mark selected students as unpaid'
    
    def send_confirmation_email(self, request, queryset):
        from .views import send_registration_email
        import threading
        import logging

        logger = logging.getLogger(__name__)

        def send_emails_in_background(students):
            count = 0
            for student in students:
                if student.is_paid:
                    receipt = student.receipts.first()
                    if receipt:
                        try:
                            send_registration_email(student, receipt)
                            count += 1
                        except Exception as e:
                            logger.error(f"Failed to send email to {student.email}: {e}")
            
            log_admin_action(
                user=request.user,
                action='EMAIL_SENT',
                model_name='Student',
                description=f'Attempted to send confirmation emails to {count} students in the background.',
                ip_address=get_client_ip(request)
            )

        students_to_email = list(queryset)
        thread = threading.Thread(target=send_emails_in_background, args=(students_to_email,))
        thread.start()

        self.message_user(request, f'Started sending confirmation emails to {len(students_to_email)} students in the background.')
    send_confirmation_email.short_description = 'Send confirmation email'
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        action = 'UPDATE' if change else 'CREATE'
        log_admin_action(
            user=request.user,
            action=action,
            model_name='Student',
            object_id=str(obj.id),
            description=f'{action.lower()}d student: {obj.name}',
            ip_address=get_client_ip(request)
        )

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')

class EventOptionInline(admin.TabularInline):
    model = EventOption
    extra = 1

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at', 'target_grades']
    search_fields = ['name', 'description']
    ordering = ['-created_at']
    filter_horizontal = ('target_grades',)
    inlines = [EventOptionInline]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_active', 'target_grades')
        }),
        ('Event Media', {
            'fields': ('event_image',)
        }),
        ('Event Rules', {
            'fields': ('rules_type', 'rules_text', 'rules_file'),
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        action = 'UPDATE' if change else 'CREATE'
        log_admin_action(
            user=request.user,
            action=action,
            model_name='Event',
            object_id=str(obj.id),
            description=f'{action.lower()}d event: {obj.name}',
            ip_address=get_client_ip(request)
        )

    class Media:
        js = ('admin/js/event_admin.js',)



@admin.register(ValorantApplicationSettings)
class ValorantApplicationSettingsAdmin(admin.ModelAdmin):
    list_display = ('is_enabled',)
