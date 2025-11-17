# registration/admin_views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Count, Sum, Q, F
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.template.loader import render_to_string, get_template
from django.http import FileResponse
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from xhtml2pdf import pisa
from django.contrib.auth import logout
from io import BytesIO

from .forms import BulkSchoolForm
import csv

@staff_member_required
def export_valorant_applications(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="valorant_applications.csv"'
    
    # Add BOM for Excel compatibility
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['Team Name', 'Member Name', 'Discord IGN', 'Riot IGN', 'Contact Number'])

    applications = ValorantTeamMember.objects.select_related('team_member__team').all()
    for application in applications:
        writer.writerow([
            application.team_member.team.name,
            application.team_member.name,
            application.discord_ign,
            application.riot_ign,
            application.contact_number,
        ])

    return response

@staff_member_required
def print_detailed_report_pdf(request):
    """Generate a PDF report of all paid students."""
    students = Student.objects.filter(is_paid=True, is_deleted=False).prefetch_related('payments', 'events').order_by('-created_at')
    template_path = 'admin/pdf_report_template.html'
    context = {
        'students': students,
        'today': timezone.now()
    }
    # Create a Django response object, and specify content_type as pdf
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="TSC_Detailed_Registration_Report_{}.pdf"'.format(timezone.now().strftime('%Y-%m-%d'))
    # find the template and render it.
    template = get_template(template_path)
    html = template.render(context)

    # create a pdf
    pisa_status = pisa.CreatePDF(
       html, dest=response)
    # if error then show some funy view
    if pisa_status.err:
       return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

from .models import Student, Event, Payment, AdminLog, Receipt, StudentEventRegistration, School, Grade, ValorantTeamMember
from .utils import log_admin_action, get_client_ip, export_detailed_report_csv

@staff_member_required
def export_detailed_report(request):
    """
    Export detailed CSV report with comprehensive carnival overview
    """
    try:
        from .utils import export_comprehensive_report_csv, log_admin_action, get_client_ip
        
        # Generate the CSV content
        csv_content = export_comprehensive_report_csv()
        
        # Add BOM for Excel compatibility
        csv_content_with_bom = '\ufeff' + csv_content

        # Create response
        response = HttpResponse(csv_content_with_bom, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="TSC2025_Comprehensive_Report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        # Log the export action
        log_admin_action(
            user=request.user,
            action='EXPORT',
            model_name='Report',
            description='Exported comprehensive carnival report',
            ip_address=get_client_ip(request)
        )
        
        logger.info(f'Comprehensive report exported by {request.user.username}')
        
        return response
        
    except Exception as e:
        logger.error(f'Error exporting comprehensive report: {e}', exc_info=True)
        messages.error(request, f'Error generating report: {str(e)}')
        return redirect('admin_reports')


@staff_member_required 
def export_paid_students_only(request):
    """
    Export CSV report with only paid students (original functionality)
    """
    try:
        from .utils import export_detailed_report_csv, log_admin_action, get_client_ip
        
        # Generate the CSV content (paid students only)
        csv_content = export_detailed_report_csv()
        
        # Add BOM for Excel compatibility
        csv_content_with_bom = '\ufeff' + csv_content

        # Create response
        response = HttpResponse(csv_content_with_bom, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="TSC2025_Paid_Students_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        # Log the export action
        log_admin_action(
            user=request.user,
            action='EXPORT',
            model_name='Report',
            description='Exported paid students report',
            ip_address=get_client_ip(request)
        )
        
        logger.info(f'Paid students report exported by {request.user.username}')
        
        return response
        
    except Exception as e:
        logger.error(f'Error exporting paid students report: {e}', exc_info=True)
        messages.error(request, f'Error generating report: {str(e)}')
        return redirect('admin_reports')

@staff_member_required
def bulk_add_schools(request):
    if request.method == 'POST':
        form = BulkSchoolForm(request.POST)
        if form.is_valid():
            school_names = form.cleaned_data['school_names'].splitlines()
            created_count = 0
            for name in school_names:
                name = name.strip()
                if name:
                    _, created = School.objects.get_or_create(name=name)
                    if created:
                        created_count += 1
            messages.success(request, f'{created_count} new schools added successfully.')
            return redirect('admin:registration_school_changelist')
    else:
        form = BulkSchoolForm()
    return render(request, 'admin/bulk_add_schools.html', {'form': form})

import logging

logger = logging.getLogger(__name__)

import json

@staff_member_required
def dashboard(request):
    """Admin Dashboard Home"""
    # Log admin login
    log_admin_action(
        user=request.user,
        action='LOGIN',
        description='Admin dashboard accessed',
        ip_address=get_client_ip(request)
    )
    
    # Statistics
    total_students = Student.objects.count()
    paid_students = Student.objects.filter(is_paid=True).count()
    pending_payments = Student.objects.filter(is_paid=False).count()
    total_revenue = Payment.objects.filter(status='SUCCESS').aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Calculate expected revenue (total if all students paid their full amount)
    expected_revenue = Payment.objects.filter(status='PENDING').aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Recent registrations
    recent_students = Student.objects.order_by('-created_at')[:10]
    
    # Payment status breakdown
    payment_stats = Payment.objects.values('status').annotate(count=Count('id')).order_by('status')
    
    # Event-wise registrations
    event_stats = StudentEventRegistration.objects.values(event_name=F('event_option__event__name')).annotate(
        count=Count('id')
    ).order_by('-count')[:5]  # Top 5 events
    
    # Group-wise registrations
    group_stats = Student.objects.values('group').annotate(count=Count('id')).order_by('group')
    
    # Daily registration trends (last 7 days)
    seven_days_ago = timezone.now().date() - timedelta(days=6)
    
    # Fetch data in a single query
    daily_data = Student.objects.filter(
        created_at__date__gte=seven_days_ago
    ).values('created_at__date').annotate(
        total_count=Count('id'),
        paid_count=Count('id', filter=Q(is_paid=True))
    ).order_by('created_at__date')
    
    # Create a dictionary for quick lookups
    data_map = {item['created_at__date']: item for item in daily_data}
    
    # Prepare the final list for the template
    daily_registrations = []
    for i in range(7):
        date = seven_days_ago + timedelta(days=i)
        data = data_map.get(date)
        daily_registrations.append({
            'date': date.strftime('%a, %b %d'),
            'total_count': data['total_count'] if data else 0,
            'paid_count': data['paid_count'] if data else 0,
        })

    context = {
        'total_students': total_students,
        'paid_students': paid_students,
        'pending_payments': pending_payments,
        'total_revenue': total_revenue,
        'expected_revenue': expected_revenue,
        'recent_students': recent_students,
        'payment_stats': payment_stats,
        'event_stats': event_stats,
        'group_stats': group_stats,
        'daily_registrations': json.dumps(daily_registrations),
    }
    
    return render(request, 'admin/dashboard.html', context)

@staff_member_required
def student_list(request):
    """List all students with filtering and search"""
    students = Student.objects.annotate(
        total_amount_paid=Sum('payments__amount', filter=Q(payments__status='SUCCESS'))
    ).select_related('grade', 'school_college').prefetch_related('events').order_by('-created_at')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        students = students.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(school_college__name__icontains=search_query) |
            Q(roll__icontains=search_query) |
            Q(registration_id__icontains=search_query)
        )
    
    # Filter by payment status
    payment_filter = request.GET.get('payment', '')
    if payment_filter == 'paid':
        students = students.filter(is_paid=True)
    elif payment_filter == 'unpaid':
        students = students.filter(is_paid=False)
    
    # Filter by group
    group_filter = request.GET.get('group', '')
    if group_filter:
        students = students.filter(group=group_filter)
    
    # Filter by grade
    grade_filter = request.GET.get('grade', '')
    if grade_filter:
        students = students.filter(grade=grade_filter)
    
    # Pagination
    paginator = Paginator(students, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'payment_filter': payment_filter,
        'group_filter': group_filter,
        'grade_filter': grade_filter,
        'groups': Student.GROUP_CHOICES,
        'grades': Grade.objects.all(),
    }
    
    return render(request, 'admin/student_list.html', context)

@staff_member_required
def student_detail(request, student_id):
    """Detailed view of a student"""
    student = get_object_or_404(Student, id=student_id)
    payments = student.payments.all().order_by('-created_at')
    receipts = student.receipts.all().order_by('-generated_at')
    total_amount_paid = payments.filter(status='SUCCESS').aggregate(Sum('amount'))['amount__sum'] or 0
    
    context = {
        'student': student,
        'payments': payments,
        'receipts': receipts,
        'events': StudentEventRegistration.objects.filter(student=student, payment__status='SUCCESS'),
        'total_amount_paid': total_amount_paid,
    }
    
    return render(request, 'admin/student_detail.html', context)

@staff_member_required
def payment_list(request):
    """List all payments"""
    payments = Payment.objects.select_related('student').order_by('-created_at')
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        payments = payments.filter(status=status_filter)
    
    # Search by transaction ID or student name
    search_query = request.GET.get('search', '')
    if search_query:
        payments = payments.filter(
            Q(transaction_id__icontains=search_query) |
            Q(student__name__icontains=search_query)
        )
    
    # Calculate statistics
    stats = payments.aggregate(
        successful_payments=Count('id', filter=Q(status='SUCCESS')),
        pending_payments=Count('id', filter=Q(status='PENDING')),
        failed_payments=Count('id', filter=Q(status='FAILED')),
        total_revenue=Sum('amount', filter=Q(status='SUCCESS'))
    )
    stats['total_revenue'] = stats['total_revenue'] or 0

    # Pagination
    paginator = Paginator(payments, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_choices': Payment.PAYMENT_STATUS_CHOICES,
        'stats': stats,
    }
    
    return render(request, 'admin/payment_list.html', context)


@staff_member_required
def verify_payment(request, payment_id):
    """
    View to verify and manage payment status
    """
    payment = get_object_or_404(Payment, id=payment_id)
    
    # Handle AJAX status check requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        return JsonResponse({
            'status': payment.payment_status,
            'updated_at': payment.updated_at.isoformat()
        })
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            if payment.payment_status == 'PENDING':
                # Approve the payment
                payment.payment_status = 'COMPLETED'
                payment.save()
                
                # Update registration status
                registration = payment.registration
                registration.payment_status = 'PAID'
                registration.save()
                
                messages.success(request, f'Payment for {registration.name} has been successfully approved.')
                logger.info(f'Payment {payment.id} approved by admin {request.user.username}')
            else:
                messages.warning(request, 'This payment cannot be approved as it is not pending.')
                
        elif action == 'reject':
            if payment.payment_status == 'PENDING':
                # Reject the payment
                payment.payment_status = 'FAILED'
                payment.save()
                
                # Update registration status
                registration = payment.registration
                registration.payment_status = 'PENDING'
                registration.save()
                
                messages.error(request, f'Payment for {registration.name} has been rejected.')
                logger.info(f'Payment {payment.id} rejected by admin {request.user.username}')
            else:
                messages.warning(request, 'This payment cannot be rejected as it is not pending.')
        
        return redirect('admin_verify_payment', payment_id=payment_id)
    
    context = {
        'payment': payment,
        'registration': payment.registration,
    }
    
    return render(request, 'admin/verify_payment.html', context)

@staff_member_required
def event_list(request):
    """List all events with registration statistics"""
    events = Event.objects.annotate(
        registration_count=Count('options__studenteventregistration', distinct=True, filter=Q(options__studenteventregistration__student__is_paid=True)),
        total_revenue=Sum('options__studenteventregistration__student__payments__amount', 
                         filter=Q(options__studenteventregistration__student__payments__status='SUCCESS'))
    ).order_by('-created_at')
    
    active_events_count = events.filter(is_active=True).count()
    total_registrations = sum(event.registration_count for event in events if event.registration_count)
    total_revenue = sum(event.total_revenue for event in events if event.total_revenue)
    
    context = {
        'events': events,
        'active_events_count': active_events_count,
        'total_registrations': total_registrations,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'admin/event_list.html', context)

@staff_member_required
def admin_logs(request):
    """View admin activity logs with real data and statistics"""
    # Get all logs with proper relationships
    logs = AdminLog.objects.select_related('admin_user').order_by('-timestamp')
    
    # Filter by user
    user_filter = request.GET.get('user', '')
    if user_filter:
        logs = logs.filter(admin_user__username=user_filter)
    
    # Filter by action
    action_filter = request.GET.get('action', '')
    if action_filter:
        logs = logs.filter(action=action_filter)
    
    # Filter by date range
    date_range_filter = request.GET.get('date_range', '')
    if date_range_filter == 'today':
        today = timezone.now().date()
        logs = logs.filter(timestamp__date=today)
    elif date_range_filter == 'week':
        week_ago = timezone.now() - timedelta(days=7)
        logs = logs.filter(timestamp__gte=week_ago)
    elif date_range_filter == 'month':
        month_ago = timezone.now() - timedelta(days=30)
        logs = logs.filter(timestamp__gte=month_ago)
    
    # Calculate statistics efficiently
    stats_queryset = AdminLog.objects.values('action').annotate(count=Count('id'))
    stats_map = {item['action']: item['count'] for item in stats_queryset}

    stats_cards = []
    for action_code, action_name in AdminLog.ACTION_CHOICES:
        count = stats_map.get(action_code, 0)
        icon, color = get_action_style(action_code)
        stats_cards.append({
            'name': action_name,
            'count': count,
            'icon': icon,
            'color': color,
        })

    # Get most active user
    most_active_user_data = AdminLog.objects.values('admin_user__username', 'admin_user__first_name', 'admin_user__last_name').annotate(
        count=Count('id')
    ).order_by('-count').first()
    
    most_active_user = None
    if most_active_user_data:
        if most_active_user_data['admin_user__first_name']:
            most_active_user = f"{most_active_user_data['admin_user__first_name']} {most_active_user_data['admin_user__last_name'] or ''}".strip()
        else:
            most_active_user = most_active_user_data['admin_user__username']

    # Get latest activity
    latest_log = AdminLog.objects.order_by('-timestamp').first()
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get unique users and actions for filters
    users = User.objects.filter(adminlog__isnull=False).distinct().order_by('username')
    
    context = {
        'page_obj': page_obj,
        'user_filter': user_filter,
        'action_filter': action_filter,
        'date_range_filter': date_range_filter,
        'users': users,
        'actions': AdminLog.ACTION_CHOICES,
        'stats_cards': stats_cards,
        'most_active_user': most_active_user,
        'latest_activity': latest_log.timestamp if latest_log else None,
    }
    
    return render(request, 'admin/admin_logs.html', context)

def get_action_style(action_code):
    if action_code == 'CREATE':
        return 'fa-plus-circle', 'blue'
    elif action_code == 'UPDATE':
        return 'fa-edit', 'yellow'
    elif action_code == 'DELETE':
        return 'fa-trash', 'red'
    elif action_code == 'LOGIN':
        return 'fa-sign-in-alt', 'green'
    elif action_code == 'LOGOUT':
        return 'fa-sign-out-alt', 'gray'
    elif action_code == 'PAYMENT_VERIFY':
        return 'fa-check-circle', 'emerald'
    elif action_code == 'RECEIPT_GENERATE':
        return 'fa-receipt', 'purple'
    elif action_code == 'EMAIL_SENT':
        return 'fa-envelope', 'indigo'
    else:
        return 'fa-cog', 'gray'

@staff_member_required
def reports(request):
    """Generate various reports"""
    # Registration summary
    total_registrations = Student.objects.count()
    paid_registrations = Student.objects.filter(is_paid=True).count()
    
    # Revenue summary
    total_revenue = Payment.objects.filter(status='SUCCESS').aggregate(Sum('amount'))['amount__sum'] or 0
    pending_revenue = Payment.objects.filter(status='PENDING').aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Event-wise breakdown
    event_breakdown = Event.objects.annotate(
        registrations=Count('options__studenteventregistration', distinct=True),
        revenue=Sum('options__studenteventregistration__student__payments__amount', filter=Q(options__studenteventregistration__student__payments__status='SUCCESS'))
    ).order_by('-registrations')
    
    # School-wise breakdown
    school_breakdown = Student.objects.values('school_college__name').annotate(
        count=Count('id'),
        paid_count=Count('id', filter=Q(is_paid=True))
    ).order_by('-count')[:10]
    
    # Grade-wise breakdown
    grade_breakdown = Student.objects.values('grade', 'group').annotate(
        count=Count('id'),
        paid_count=Count('id', filter=Q(is_paid=True))
    ).order_by('grade')
    
    # Payment method breakdown
    payment_method_breakdown = Payment.objects.filter(status='SUCCESS').values('payment_method').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('-count')
    
    context = {
        'total_registrations': total_registrations,
        'paid_registrations': paid_registrations,
        'total_revenue': total_revenue,
        'pending_revenue': pending_revenue,
        'event_breakdown': event_breakdown,
        'school_breakdown': school_breakdown,
        'grade_breakdown': grade_breakdown,
        'payment_method_breakdown': payment_method_breakdown,
    }
    
    return render(request, 'admin/reports.html', context)

@staff_member_required
def verify_payment(request, payment_id):
    """Manually verify a payment"""
    payment = get_object_or_404(Payment, id=payment_id)
    
    if request.method == 'POST':
        payment.status = 'SUCCESS'
        payment.student.is_paid = True
        payment.student.payment_verified = True
        payment.student.save()
        payment.save()
        
        # Generate receipt if doesn't exist
        if not payment.receipts.exists():
            receipt = Receipt.objects.create(
                student=payment.student,
                payment=payment,
                generated_by=request.user
            )
        
        # Log the action
        log_admin_action(
            user=request.user,
            action='PAYMENT_VERIFY',
            model_name='Payment',
            object_id=str(payment.id),
            description=f'Payment verified for {payment.student.name}',
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, f'Payment verified for {payment.student.name}')
        return redirect('admin_payments')
    
    return render(request, 'admin/verify_payment.html', {'payment': payment})

@staff_member_required
def generate_receipt(request, student_id):
    """Generate receipt for a student"""
    student = get_object_or_404(Student, id=student_id)
    
    if not student.is_paid:
        messages.error(request, 'Cannot generate receipt for unpaid registration.')
        return redirect('admin_student_detail', student_id=student.id)
    
    payment = student.payments.filter(status='SUCCESS').first()
    if not payment:
        messages.error(request, 'No successful payment found.')
        return redirect('admin_student_detail', student_id=student.id)
    
    # Create or get existing receipt
    receipt, created = Receipt.objects.get_or_create(
        student=student,
        payment=payment,
        defaults={'generated_by': request.user}
    )
    
    if created:
        log_admin_action(
            user=request.user,
            action='RECEIPT_GENERATE',
            model_name='Receipt',
            object_id=str(receipt.id),
            description=f'Receipt generated for {student.name}',
            ip_address=get_client_ip(request)
        )
    
    # Return receipt as HTML (you can implement PDF generation later)
    context = {
        'student': student,
        'receipt': receipt,
        'payment': payment,
        'events': receipt.payment.studenteventregistration_set.all(),
    }
    
    return render(request, 'admin/receipt_template.html', context)

@staff_member_required
def send_email(request, student_id):
    """Send registration email to student"""
    student = get_object_or_404(Student, id=student_id)
    
    if not student.is_paid:
        messages.error(request, 'Cannot send email for unpaid registration.')
        return redirect('admin_student_detail', student_id=student.id)
    
    # Get receipt
    receipt = student.receipts.first()
    if not receipt:
        messages.error(request, 'No receipt found. Please generate receipt first.')
        return redirect('admin_student_detail', student_id=student.id)
    
    try:
        from .views import send_registration_email
        send_registration_email(student, receipt)
        
        log_admin_action(
            user=request.user,
            action='EMAIL_SENT',
            model_name='Student',
            object_id=str(student.id),
            description=f'Registration email sent to {student.email}',
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, f'Email sent successfully to {student.email}')
    except Exception as e:
        messages.error(request, f'Failed to send email: {str(e)}')
    
    return redirect('admin_student_detail', student_id=student.id)

@staff_member_required
def bulk_action(request):
    """Handle bulk actions on students"""
    if request.method == 'POST':
        action = request.POST.get('action')
        student_ids = request.POST.getlist('student_ids')
        
        if not student_ids:
            messages.error(request, 'No students selected.')
            return redirect('admin_students')
        
        students = Student.objects.filter(id__in=student_ids)
        count = students.count()
        
        if action == 'mark-paid':
            students.update(is_paid=True, payment_verified=True)
            log_admin_action(
                user=request.user,
                action='UPDATE',
                model_name='Student',
                description=f'Bulk marked {count} students as paid',
                ip_address=get_client_ip(request)
            )
            messages.success(request, f'{count} students marked as paid.')
            
        elif action == 'mark-unpaid':
            students.update(is_paid=False, payment_verified=False)
            log_admin_action(
                user=request.user,
                action='UPDATE',
                model_name='Student',
                description=f'Bulk marked {count} students as unpaid',
                ip_address=get_client_ip(request)
            )
            messages.success(request, f'{count} students marked as unpaid.')
            
        elif action == 'send-email':
            sent_count = 0
            from .views import send_registration_email
            for student in students:
                if student.is_paid:
                    receipt = student.receipts.first()
                    if receipt:
                        try:
                            send_registration_email(student, receipt)
                            sent_count += 1
                        except Exception:
                            pass
            
            log_admin_action(
                user=request.user,
                action='EMAIL_SENT',
                model_name='Student',
                description=f'Bulk sent emails to {sent_count} students',
                ip_address=get_client_ip(request)
            )
            messages.success(request, f'Emails sent to {sent_count} students.')
            
    return redirect('admin_students')

@staff_member_required
def delete_student(request, student_id):
    """Delete a student"""
    student = get_object_or_404(Student, id=student_id)
    
    if request.method == 'POST':
        student_name = student.name
        student.delete()
        
        log_admin_action(
            user=request.user,
            action='DELETE',
            model_name='Student',
            object_id=str(student_id),
            description=f'Deleted student: {student_name}',
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, f'Student {student_name} has been deleted.')
    
    return redirect('admin_students')

@staff_member_required
def logout_view(request):
    """Log out the admin user."""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('admin:login')