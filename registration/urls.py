# registration/urls.py - COMPLETE FILE

from django.urls import path
from . import views
from . import admin_views

urlpatterns = [
    # ============= PUBLIC URLS =============
    path('', views.home, name='home'),
    
    # ============= PACKAGE SELECTION & REGISTRATION =============
    # NEW: Package selection (first step)
    path('register/', views.package_selection, name='package_selection'),
    
    # UPDATED: Registration with package type
    path('register/regular/', views.student_registration, {'package_type': 'regular'}, name='register_regular'),
    path('register/bundle/<int:bundle_id>/', views.student_registration, {'package_type': 'bundle'}, name='register_bundle'),
    
    # ============= HTMX ENDPOINTS =============
    path('get-events-for-grade/', views.get_events_for_grade, name='get_events_for_grade'),
    path('get-group-for-grade/', views.get_group_for_grade, name='get_group_for_grade'),
    path('calculate-total/', views.calculate_total, name='calculate_total'),
    path('get-team-section/', views.get_team_section, name='get_team_section'),
    path('validate-grade/', views.validate_grade, name='validate_grade'),
    path('check-event-availability/', views.check_event_availability, name='check_event_availability'),
    
    # ============= PUBLIC INFORMATION PAGES =============
    path('events/', views.events_page, name='events_page'),
    path('about-us/', views.about_us, name='about_us'),
    path('valorant/', views.valorant_page, name='valorant_page'),
    path('join-us/', views.join_us, name='join_us'),
    
    # ============= EVENTS API ENDPOINTS =============
    path('api/events/<int:event_id>/rules/', views.event_rules_api, name='event_rules_api'),
    path('api/events/<int:event_id>/details/', views.event_details_api, name='event_details_api'),
    
    # ============= PAYMENT FLOW =============
    # Payment instructions page (shown before gateway)
    path('payment/instructions/<int:payment_id>/', views.payment_instructions, name='payment_instructions'),
    
    # Payment gateway
    path('payment/gateway/<int:payment_id>/', views.payment_gateway, name='payment_gateway'),
    
    # Payment callbacks
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/fail/<int:payment_id>/', views.payment_fail, name='payment_fail'),
    path('payment/cancel/<int:payment_id>/', views.payment_cancel, name='payment_cancel'),
    path('payment/ipn/', views.payment_ipn, name='payment_ipn'),
    
    # Payment recovery and error handling
    path('payment/expired/<int:payment_id>/', views.payment_expired, name='payment_expired'),
    path('payment/failed-init/<int:payment_id>/', views.payment_failed_init, name='payment_failed_init'),
    path('payment/retry/<int:payment_id>/', views.retry_payment, name='retry_payment'),
    path('payment/timeout/', views.handle_payment_timeout, name='payment_timeout'),
    path('payment/check/<int:student_id>/<str:transaction_id>/', views.check_payment_status, name='check_payment_status'),
    
    # ============= RECEIPT AND VERIFICATION =============
    path('qr-code/<str:receipt_number>/', views.generate_qr_code, name='generate_qr_code'),
    path('verify/receipt/<str:receipt_number>/', views.verify_receipt, name='verify_receipt'),
    path('receipt/print/<str:receipt_number>/', views.receipt_print_view, name='receipt_print_view'),
    path('check-status/', views.check_registration_status, name='check_registration_status'),
    
    # ============= ADMIN DASHBOARD =============
    path('dashboard/', admin_views.dashboard, name='admin_dashboard'),
    path('dashboard/students/', admin_views.student_list, name='admin_students'),
    path('dashboard/student/<int:student_id>/', admin_views.student_detail, name='admin_student_detail'),
    path('dashboard/payments/', admin_views.payment_list, name='admin_payments'),
    path('dashboard/events/', admin_views.event_list, name='admin_events'),
    path('dashboard/logs/', admin_views.admin_logs, name='admin_logs'),
    path('dashboard/reports/', admin_views.reports, name='admin_reports'),
    path('dashboard/schools/bulk-add/', admin_views.bulk_add_schools, name='bulk_add_schools'),
    
    # ============= EXPORT URLS =============
    path('dashboard/reports/export-comprehensive/', admin_views.export_detailed_report, name='export_detailed_report'),
    path('dashboard/reports/export-paid-only/', admin_views.export_paid_students_only, name='export_paid_students_only'),
    path('dashboard/reports/print/', admin_views.print_detailed_report_pdf, name='print_detailed_report'),
    path('dashboard/reports/export-valorant/', admin_views.export_valorant_applications, name='export_valorant_applications'),
    
    # ============= ADMIN ACTIONS =============
    path('dashboard/verify-payment/<int:payment_id>/', admin_views.verify_payment, name='verify_payment'),
    path('dashboard/generate-receipt/<int:student_id>/', admin_views.generate_receipt, name='generate_receipt'),
    path('dashboard/send-email/<int:student_id>/', admin_views.send_email, name='send_email'),
    path('dashboard/bulk-action/', admin_views.bulk_action, name='bulk_action'),
    path('dashboard/delete-student/<int:student_id>/', admin_views.delete_student, name='delete_student'),
    path('dashboard/logout/', admin_views.logout_view, name='admin_logout'),
]