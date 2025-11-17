# registration/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction, models
from django.db.models import Min, Exists, OuterRef, Subquery
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required 
import requests
import json
import logging
import hashlib
import hmac
from decimal import Decimal
import qrcode
import io

import logging

logger = logging.getLogger(__name__)

from .models import (
    Student, Event, EventOption, Payment, Receipt, 
    StudentEventRegistration, PaymentAttempt, School, Grade,
    Team, TeamMember, Countdown, HomePageAsset, SocialMediaProfile,
    TeamMemberProfile, PastEventImage, ValorantBackgroundVideo, 
    ValorantApplicationSettings,
    DiscountBundle, BundleEvent, ValorantTeamMember  # ADD THESE TWO
)
from .forms import StudentRegistrationForm
from .sslcommerz import SSLCOMMERZ


def home(request):
    """
    Home page with event listing and security monitoring
    """
    # Check for suspicious activity
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    try:
        individual_options = EventOption.objects.filter(event=OuterRef('pk'), event_type='INDIVIDUAL')
        team_options = EventOption.objects.filter(event=OuterRef('pk'), event_type='TEAM')

        # Subqueries to get individual and team fees
        individual_fee_subquery = EventOption.objects.filter(
            event=OuterRef('pk'),
            event_type='INDIVIDUAL'
        ).values('fee')[:1]

        team_fee_subquery = EventOption.objects.filter(
            event=OuterRef('pk'),
            event_type='TEAM'
        ).values('fee')[:1]

        active_events = Event.objects.filter(is_active=True).annotate(
            min_fee=Min('options__fee'),
            has_individual=Exists(individual_options),
            has_team=Exists(team_options),
            individual_fee=Subquery(individual_fee_subquery, output_field=models.DecimalField()),
            team_fee=Subquery(team_fee_subquery, output_field=models.DecimalField())
        ).order_by('created_at')
        active_events_list = list(active_events)
        
        # Get registration statistics for display
        stats = {
            'total_registrations': Student.objects.filter(is_deleted=False).count(),
            'active_events': len(active_events_list),
        }

        # Get active countdown timer
        countdown = Countdown.objects.filter(is_active=True).first()

        # Get home page assets
        home_page_assets = HomePageAsset.objects.filter(is_active=True)
        slideshow_images = home_page_assets.filter(asset_type='IMAGE')
        background_video = home_page_assets.filter(asset_type='VIDEO').first()

        # Get social media profiles
        social_media_profiles = SocialMediaProfile.objects.filter(is_active=True)
        
        context = {
            'events': active_events_list,
            'stats': stats,
            'countdown': countdown,
            'slideshow_images': slideshow_images,
            'background_video': background_video,
            'social_media_profiles': social_media_profiles,
        }
        
        return render(request, 'registration/home.html', context)
        
    except Exception as e:
        logger.error(f'Error in home view: {e}')
        messages.error(request, 'An error occurred while loading the page.')
        return render(request, 'registration/home.html', {'events': [], 'stats': {}, 'countdown': None})

def student_registration(request):
    """Enhanced registration with proper duplicate and edge case handling"""
    ip_address = get_client_ip(request)
    
    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        
        logger.info(f"Registration attempt from IP: {ip_address}")
        
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Get or create student
                    student, created = Student.objects.select_for_update().get_or_create(
                        email=form.cleaned_data['email'],
                        defaults={
                            'name': form.cleaned_data['name'],
                            'school_college': form.cleaned_data.get('school_college'),
                            'other_school': form.cleaned_data.get('other_school'),
                            'grade': form.cleaned_data['grade'],
                            'section': form.cleaned_data.get('section'),
                            'roll': form.cleaned_data['roll'],
                            'reference': form.cleaned_data.get('reference'),
                            'mobile_number': form.cleaned_data['mobile_number'],
                            'registration_ip': ip_address,
                        }
                    )

                    # Check for existing SUCCESSFUL payment
                    if student.is_paid and student.payment_verified:
                        logger.warning(f"Student {student.email} already has completed registration")
                        messages.warning(
                            request,
                            f'You have already completed registration with ID: {student.registration_id}. '
                            'Please check your email for the receipt. If you need to register for additional events, '
                            'contact us at sjismathclub@gmail.com'
                        )
                        return redirect('home')

                    # Check for existing pending payment (valid session)
                    existing_pending = Payment.objects.filter(
                        student=student,
                        status='PENDING',
                        expires_at__gt=timezone.now()
                    ).first()
                    
                    if existing_pending:
                        # Resume existing payment session
                        logger.info(f"Resuming payment session {existing_pending.transaction_id}")
                        messages.info(
                            request, 
                            'You have a pending payment session. Redirecting you to complete it...'
                        )
                        return redirect('payment_instructions', payment_id=existing_pending.id)

                    event_options = form.cleaned_data['selected_events']
                    
                    if not event_options or len(event_options) == 0:
                        raise ValueError("Please select at least one event to continue.")
                    
                    logger.info(f"Processing registration for {student.name} with {len(event_options)} events")
                    
                    # ENHANCED: Check which events are already registered
                    already_registered_events = []
                    new_events = []
                    
                    for option in event_options:
                        existing_reg = StudentEventRegistration.objects.filter(
                            student=student,
                            event_option__event=option.event
                        ).first()
                        
                        if existing_reg:
                            # Check if previous registration was successful
                            if existing_reg.payment and existing_reg.payment.status == 'SUCCESS':
                                already_registered_events.append(option.event.name)
                            else:
                                # Previous registration was incomplete, allow re-registration
                                logger.info(f"Replacing incomplete registration for {option.event.name}")
                                existing_reg.delete()  # Remove incomplete registration
                                new_events.append(option)
                        else:
                            new_events.append(option)
                    
                    # If all events are already registered
                    if already_registered_events and not new_events:
                        event_list = ', '.join(already_registered_events)
                        logger.warning(f"All selected events already registered for {student.email}")
                        messages.warning(
                            request,
                            f'You are already registered for: {event_list}. '
                            f'Please check your email for confirmation or contact support.'
                        )
                        return redirect('home')
                    
                    # If some events are already registered, warn user
                    if already_registered_events:
                        event_list = ', '.join(already_registered_events)
                        messages.warning(
                            request,
                            f'Note: You are already registered for {event_list}. '
                            f'Proceeding with new event registration only.'
                        )
                    
                    # Use only new events for payment
                    events_to_register = new_events if new_events else event_options
                    
                    if not events_to_register:
                        raise ValueError("No valid events to register for.")
                    
                    # Calculate amounts
                    if events_to_register:
                        subtotal = Decimal('500.00')
                    else:
                        subtotal = Decimal('0.00')
                    fee_percentage = Decimal(getattr(settings, 'SSLCOMMERZ_FEE_PERCENTAGE', '0.015'))
                    fee = (subtotal * fee_percentage).quantize(Decimal('0.01'))
                    total_amount = subtotal + fee

                    if total_amount <= 0:
                        raise ValueError("Total amount must be greater than zero.")

                    # Create payment with extended expiration
                    payment = Payment.objects.create(
                        student=student,
                        amount=total_amount,
                        client_ip=ip_address,
                        transaction_id=generate_secure_transaction_id(),
                        expires_at=timezone.now() + timezone.timedelta(minutes=30)
                    )
                    
                    logger.info(f"Payment created: {payment.transaction_id} for ৳{total_amount}")

                    # Create event registrations
                    registration_count = 0
                    for option in events_to_register:
                        reg = StudentEventRegistration.objects.create(
                            student=student,
                            event_option=option,
                            payment=payment,
                            registration_ip=ip_address
                        )
                        registration_count += 1
                        
                        logger.info(f"Event registration: {option.event.name} - {option.name}")
                        
                        # Handle team creation
                        if option.event_type == 'TEAM':
                            team_name = request.POST.get(f'team_name_{option.id}', '').strip()
                            if not team_name:
                                raise ValueError(f"Team name required for {option.event.name}")
                            
                            team = Team.objects.create(name=team_name, registration=reg)
                            leader_index = request.POST.get(f'team_leader_{option.id}', '0')
                            
                            # Add team members
                            team_member = TeamMember.objects.create(
                                team=team, 
                                name=student.name, 
                                is_leader=(leader_index == '0')
                            )
                            if option.event.name == 'Valorant':
                                ValorantTeamMember.objects.create(
                                    team_member=team_member,
                                    discord_ign=request.POST.get(f'team_member_{option.id}_0_discord_ign', '').strip(),
                                    riot_ign=request.POST.get(f'team_member_{option.id}_0_riot_ign', '').strip(),
                                    contact_number=request.POST.get(f'team_member_{option.id}_0_contact_number', '').strip(),
                                )
                            
                            for i in range(1, option.max_team_size or 2):
                                member_name = request.POST.get(f'team_member_{option.id}_{i}_name', '').strip()
                                if member_name:
                                    team_member = TeamMember.objects.create(
                                        team=team, 
                                        name=member_name, 
                                        is_leader=(leader_index == str(i))
                                    )
                                    if option.event.name == 'Valorant':
                                        ValorantTeamMember.objects.create(
                                            team_member=team_member,
                                            discord_ign=request.POST.get(f'team_member_{option.id}_{i}_discord_ign', '').strip(),
                                            riot_ign=request.POST.get(f'team_member_{option.id}_{i}_riot_ign', '').strip(),
                                            contact_number=request.POST.get(f'team_member_{option.id}_{i}_contact_number', '').strip(),
                                        )
                            
                            logger.info(f"Team {team_name} created")
                    
                    if registration_count == 0:
                        raise ValueError("No new event registrations created.")
                    
                    logger.info(f"Successfully created {registration_count} registrations")

                # Store payment ID in session
                request.session['pending_payment_id'] = payment.id
                request.session['payment_initiated_at'] = timezone.now().isoformat()
                
                # Success message
                messages.success(
                    request,
                    f'Registration details saved! Registration ID: {student.registration_id}. '
                    f'Please complete payment within 30 minutes.'
                )
                
                # Redirect to payment instructions
                return redirect('payment_instructions', payment_id=payment.id)

            except ValueError as ve:
                logger.error(f'Validation error: {ve}')
                messages.error(request, str(ve))
                return render(request, 'registration/register.html', {'form': form})
            
            except Exception as e:
                logger.error(f'Registration error: {e}', exc_info=True)
                messages.error(
                    request, 
                    'An unexpected error occurred. Please try again or contact support at sjismathclub@gmail.com'
                )
                return render(request, 'registration/register.html', {'form': form})
        else:
            logger.error(f"Form validation failed: {form.errors}")
            
            if 'selected_events' in form.errors:
                messages.error(request, 'Please select at least one event.')
            else:
                messages.error(request, 'Please correct the errors in the form.')
            
            # Log all errors for debugging
            for field, errors in form.errors.items():
                logger.error(f"Field '{field}' errors: {errors}")
            
            return render(request, 'registration/register.html', {'form': form})
    else:
        # GET request - show form
        form = StudentRegistrationForm()

    return render(request, 'registration/register.html', {'form': form})


def check_registration_status(request):
    """
    Allow users to check their registration status
    """
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        registration_id = request.POST.get('registration_id', '').strip()
        
        if not email and not registration_id:
            messages.error(request, 'Please provide either email or registration ID.')
            return render(request, 'registration/check_status.html')
        
        try:
            # Find student
            if registration_id:
                student = Student.objects.get(registration_id=registration_id, is_deleted=False)
            else:
                student = Student.objects.get(email=email, is_deleted=False)
            
            # Get payments
            payments = student.payments.all().order_by('-created_at')
            successful_payment = payments.filter(status='SUCCESS').first()
            pending_payments = payments.filter(
                status='PENDING',
                expires_at__gt=timezone.now()
            )
            
            # FIXED: Use prefetch_related for reverse relationships
            event_registrations = StudentEventRegistration.objects.filter(
                student=student
            ).select_related(
                'event_option__event', 
                'payment'
            ).prefetch_related(
                'team__members__valorant_info'  # FIXED
            )
            
            context = {
                'student': student,
                'successful_payment': successful_payment,
                'pending_payments': pending_payments,
                'event_registrations': event_registrations,
                'found': True,
            }
            
            return render(request, 'registration/check_status.html', context)
            
        except Student.DoesNotExist:
            messages.error(request, 'No registration found with the provided details.')
            return render(request, 'registration/check_status.html')
        except Exception as e:
            logger.error(f'Error checking status: {e}')
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'registration/check_status.html')
    
    return render(request, 'registration/check_status.html')

def payment_instructions(request, payment_id):
    """Show payment instructions before redirecting to gateway"""
    try:
        payment = get_object_or_404(Payment, id=payment_id, status='PENDING')
        student = payment.student
        
        # Check if payment has expired
        if payment.is_expired():
            payment.status = 'EXPIRED'
            payment.save()
            messages.warning(request, 'This payment session has expired. Please register again.')
            return redirect('package_selection')
        
        # FIXED: Use prefetch_related for reverse relationships
        event_registrations = StudentEventRegistration.objects.filter(
            student=student,
            payment=payment
        ).select_related(
            'event_option__event'
        ).prefetch_related(
            'team__members__valorant_info'  # FIXED
        )
        
        context = {
            'payment': payment,
            'student': student,
            'event_registrations': event_registrations,
            'expires_at': payment.expires_at,
        }
        
        return render(request, 'registration/payment_instructions.html', context)
        
    except Payment.DoesNotExist:
        messages.error(request, "Invalid payment session.")
        return redirect('package_selection')


# Updated get_events_for_grade view in views.py
@require_GET
def get_events_for_grade(request):
    grade_id = request.GET.get('grade')
    
    if not grade_id:
        # Return empty state when no grade is selected
        context = {
            'events': [],
            'show_no_grade_message': True,
        }
        return render(request, 'registration/_event_list.html', context)
    
    try:
        grade = Grade.objects.get(id=grade_id)
        # Get events that include this grade in their target_grades
        events = Event.objects.filter(
            target_grades__id=grade_id, 
            is_active=True
        ).distinct().prefetch_related('options', 'target_grades')
        
        logger.info(f"Grade {grade.name} selected - Found {events.count()} events")
        
        context = {
            'events': events,
            'selected_grade': grade,
            'show_no_events_message': events.count() == 0,
        }
        
        return render(request, 'registration/_event_list.html', context)
        
    except Grade.DoesNotExist:
        logger.warning(f"Invalid grade ID requested: {grade_id}")
        context = {
            'events': [],
            'show_error_message': True,
        }
        return render(request, 'registration/_event_list.html', context)
    except Exception as e:
        logger.error(f"Error in get_events_for_grade: {e}")
        context = {
            'events': [],
            'show_error_message': True,
        }
        return render(request, 'registration/_event_list.html', context)

@require_GET
def get_group_for_grade(request):
    """
    Calculates the group for a given grade ID using the grade's 'order' field.
    This is an HTMX endpoint that returns a partial HTML template.
    """
    grade_id = request.GET.get('grade')
    
    if not grade_id:
        context = {
            'group_display': 'Select grade first',
            'css_classes': 'w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500'
        }
        return render(request, 'registration/_group_display.html', context)
    
    try:
        grade = Grade.objects.get(id=grade_id)
        group = Student.calculate_group_from_grade_id(grade_id)
        
        if group is None:
            # Grade is outside the defined groups
            context = {
                'group_display': 'Not applicable for this grade',
                'css_classes': 'w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500'
            }
            return render(request, 'registration/_group_display.html', context)

        group_display = dict(Student.GROUP_CHOICES).get(group, '')
        
        logger.info(f"Grade '{grade.name}' (order: {grade.order}) mapped to group {group}: {group_display}")
        
        context = {
            'group_display': group_display,
            'css_classes': 'w-full px-4 py-2 border border-green-300 rounded-lg bg-green-50 text-green-700 font-medium'
        }
        return render(request, 'registration/_group_display.html', context)
        
    except Grade.DoesNotExist:
        logger.warning(f"Invalid grade ID requested: {grade_id}")
        context = {
            'group_display': 'Invalid grade',
            'css_classes': 'w-full px-4 py-2 border border-red-300 rounded-lg bg-red-50 text-red-600'
        }
        return render(request, 'registration/_group_display.html', context)
        
    except Exception as e:
        logger.error(f"Unexpected error in get_group_for_grade: {e}")
        context = {
            'group_display': 'Error',
            'css_classes': 'w-full px-4 py-2 border border-red-300 rounded-lg bg-red-50 text-red-600'
        }
        return render(request, 'registration/_group_display.html', context)

@require_GET
def validate_grade(request):
    """Validate grade selection and return status"""
    grade_id = request.GET.get('grade')
    
    if not grade_id:
        return JsonResponse({
            'valid': False,
            'message': 'No grade selected'
        })
    
    try:
        grade = Grade.objects.get(id=grade_id)
        group = Student.calculate_group_from_grade(grade.name)
        group_display = dict(Student.GROUP_CHOICES).get(group, '')
        
        return JsonResponse({
            'valid': True,
            'grade_name': grade.name,
            'group': group,
            'group_display': group_display,
            'message': 'Valid grade selection'
        })
    except Grade.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'message': 'Invalid grade selection'
        })
    except Exception as e:
        logger.error(f"Error validating grade {grade_id}: {e}")
        return JsonResponse({
            'valid': False,
            'message': 'Error validating grade'
        })
    
@require_GET  
def check_event_availability(request):
    """Check if events are available for selected grade"""
    grade_id = request.GET.get('grade')
    
    if not grade_id:
        return JsonResponse({
            'available': False,
            'count': 0,
            'message': 'No grade selected'
        })
    
    try:
        grade = Grade.objects.get(id=grade_id)
        events = Event.objects.filter(
            target_grades__id=grade_id, 
            is_active=True
        ).prefetch_related('options')
        
        event_count = events.count()
        
        return JsonResponse({
            'available': event_count > 0,
            'count': event_count,
            'message': f'{event_count} events available for {grade.name}' if event_count > 0 else 'No events available for this grade'
        })
        
    except Grade.DoesNotExist:
        return JsonResponse({
            'available': False,
            'count': 0,
            'message': 'Invalid grade selection'
        })
    except Exception as e:
        logger.error(f"Error checking event availability for grade {grade_id}: {e}")
        return JsonResponse({
            'available': False,
            'count': 0,
            'message': 'Error checking event availability'
        })
    
@require_POST
def calculate_total(request):
    """
    HTMX endpoint to calculate total amount, including SSLCommerz fee.
    Handles both regular and bundle packages.
    """
    try:
        bundle_id = request.POST.get('bundle_id')
        
        if bundle_id:
            # Bundle package - fixed price
            try:
                bundle = DiscountBundle.objects.get(id=bundle_id, is_active=True)
                subtotal = bundle.price
            except DiscountBundle.DoesNotExist:
                return render(request, 'registration/_total_display.html', {
                    'subtotal': 0,
                    'fee': 0,
                    'total': 0,
                    'error': 'Invalid bundle'
                })
        else:
            # Regular package - calculate from selected events
            selected_events_str = request.POST.get('selected_events', '')
            if not selected_events_str:
                return render(request, 'registration/_total_display.html', {
                    'subtotal': 0,
                    'fee': 0,
                    'total': 0
                })

            event_option_ids = [int(id) for id in selected_events_str.split(',') if id.isdigit()]
            
            if event_option_ids:
                # FIXED: Calculate actual total from event fees
                event_options = EventOption.objects.filter(id__in=event_option_ids)
                subtotal = sum(option.fee for option in event_options)
            else:
                subtotal = Decimal('0.00')
        
        # Calculate SSLCommerz fee
        fee_percentage = Decimal(getattr(settings, 'SSLCOMMERZ_FEE_PERCENTAGE', '0.015'))
        fee = (subtotal * fee_percentage).quantize(Decimal('0.01'))
        total = subtotal + fee

        context = {
            'subtotal': subtotal,
            'fee': fee,
            'total': total,
            'is_bundle': bool(bundle_id),
        }
        return render(request, 'registration/_total_display.html', context)

    except Exception as e:
        logger.error(f'Error calculating total: {e}')
        return HttpResponse('<div class="text-red-500">Error</div>', status=500)

def payment_gateway(request, payment_id):
    """Enhanced payment gateway with better error handling"""
    try:
        payment = get_object_or_404(Payment, id=payment_id, status='PENDING')
        
        # Verify payment hasn't expired
        if payment.is_expired():
            payment.status = 'EXPIRED'
            payment.save()
            messages.error(request, 'Payment session expired. Please start a new registration.')
            return redirect('payment_expired', payment_id=payment.id)
        
        student = payment.student
        sslcommerz = SSLCOMMERZ()
        
        response_data = sslcommerz.create_session(
            amount=payment.amount,
            tran_id=payment.transaction_id,
            cust_name=student.name,
            cust_email=student.email,
            cust_phone=student.mobile_number,
            payment_id=payment.id,
            cus_add1=student.school_college.name if student.school_college else student.other_school or 'Dhaka',
            cus_city='Dhaka',
            cus_state='Dhaka',
            cus_postcode='1000',
            cus_country='Bangladesh'
        )

        if response_data.get('status') == 'SUCCESS':
            payment.sessionkey = response_data.get('sessionkey', '')
            payment.save()
            
            logger.info(f"Payment gateway session created: {payment.transaction_id}")
            return redirect(response_data.get('GatewayPageURL'))
        else:
            error_reason = response_data.get('failedreason', 'Gateway initialization failed')
            logger.error(f"Gateway init failed: {error_reason}")
            messages.error(request, f'Payment gateway error: {error_reason}')
            return redirect('payment_failed_init', payment_id=payment.id)

    except Payment.DoesNotExist:
        messages.error(request, "Invalid or expired payment session.")
        return redirect('package_selection')
    except Exception as e:
        logger.error(f'Payment gateway error: {e}', exc_info=True)
        messages.error(request, 'Could not connect to payment gateway. Please try again.')
        return redirect('package_selection')


def payment_expired(request, payment_id):
    """NEW: Handle expired payment sessions"""
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        student = payment.student
        
        context = {
            'payment': payment,
            'student': student,
        }
        
        return render(request, 'registration/payment_expired.html', context)
        
    except Payment.DoesNotExist:
        return redirect('package_selection')


def payment_failed_init(request, payment_id):
    """NEW: Handle payment gateway initialization failures"""
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        student = payment.student
        
        context = {
            'payment': payment,
            'student': student,
        }
        
        return render(request, 'registration/payment_failed_init.html', context)
        
    except Payment.DoesNotExist:
        return redirect('package_selection')


def retry_payment(request, payment_id):
    """NEW: Allow users to retry failed payments"""
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Only allow retry for failed or expired payments
        if payment.status not in ['FAILED', 'EXPIRED', 'CANCELLED']:
            messages.info(request, 'This payment cannot be retried.')
            return redirect('home')
        
        # Check if payment is too old (more than 24 hours)
        if (timezone.now() - payment.created_at).total_seconds() > 86400:
            messages.error(request, 'This payment session is too old. Please register again.')
            return redirect('package_selection')
        
        # Reset payment status
        payment.status = 'PENDING'
        payment.expires_at = timezone.now() + timezone.timedelta(minutes=30)
        payment.save()
        
        logger.info(f"Payment retry initiated: {payment.transaction_id}")
        messages.info(request, 'Retrying payment... Please complete within 30 minutes.')
        
        return redirect('payment_instructions', payment_id=payment.id)
        
    except Payment.DoesNotExist:
        messages.error(request, "Payment session not found.")
        return redirect('package_selection')


@csrf_exempt
def payment_success(request):
    """
    Enhanced payment success handler with better error handling and email sending
    """
    post_data = request.POST
    tran_id = post_data.get('tran_id')

    if not tran_id:
        logger.error("❌ Payment success callback without transaction ID")
        return HttpResponseBadRequest("Invalid request: Missing transaction ID.")

    try:
        payment = Payment.objects.select_for_update().get(transaction_id=tran_id)
    except Payment.DoesNotExist:
        logger.error(f"❌ Payment success for non-existent transaction: {tran_id}")
        return HttpResponseBadRequest("Invalid Transaction.")

    # Already processed - idempotency check
    if payment.status == 'SUCCESS':
        logger.info(f"ℹ️ Payment {tran_id} already processed")
        receipt = Receipt.objects.filter(payment=payment).first()
        
        # FIXED: Use prefetch_related for reverse FK relationships
        event_registrations = StudentEventRegistration.objects.filter(
            student=payment.student,
            payment=payment
        ).select_related(
            'event_option__event'
        ).prefetch_related(
            'team__members__valorant_info'  # FIXED: Use prefetch_related for reverse relationships
        )
        
        context = {
            'student': payment.student,
            'payment': payment,
            'receipt': receipt,
            'event_registrations': event_registrations,
            'already_processed': True,
        }
        return render(request, 'registration/payment_success.html', context)

    # Validate with SSLCommerz
    sslcz = SSLCOMMERZ()
    is_valid, validation_data = sslcz.validate_ipn(post_data)

    if not is_valid or validation_data.get('status') not in ['VALID', 'VALIDATED']:
        logger.error(f"❌ Invalid payment validation for {tran_id}")
        payment.status = 'FAILED'
        payment.gateway_response = validation_data
        payment.save()
        return HttpResponseBadRequest("Payment validation failed.")

    # Amount verification
    if not verify_payment_amount(payment.amount, validation_data.get('amount')):
        logger.error(f"❌ Amount mismatch for {tran_id}: Expected {payment.amount}, Got {validation_data.get('amount')}")
        payment.status = 'FAILED'
        payment.gateway_response = validation_data
        payment.save()
        return HttpResponseBadRequest("Payment validation failed: Amount mismatch.")

    # Process successful payment
    try:
        with transaction.atomic():
            # Update payment
            payment.status = 'SUCCESS'
            payment.payment_method = validation_data.get('card_type', '')
            payment.gateway_txnid = validation_data.get('val_id')
            payment.gateway_response = validation_data
            payment.completed_at = timezone.now()
            payment.save()

            # Update student
            student = payment.student
            student.is_paid = True
            student.payment_verified = True
            student.save()

            # Create or get receipt
            receipt, created = Receipt.objects.get_or_create(
                student=student,
                payment=payment,
                defaults={'generated_by': None}
            )
            
            if created:
                logger.info(f"✅ Receipt {receipt.receipt_number} created for {student.name}")
            else:
                logger.info(f"ℹ️ Receipt {receipt.receipt_number} already exists for {student.name}")
            
            # Clear session
            if 'pending_payment_id' in request.session:
                del request.session['pending_payment_id']
            
            logger.info(f'✅ Payment successful: {tran_id} for student {student.name}')

        # Send email AFTER transaction is committed
        try:
            email_sent = send_registration_email(student, receipt)
            if email_sent:
                logger.info(f"✅ Registration email sent to {student.email}")
            else:
                logger.warning(f"⚠️ Failed to send email to {student.email} but payment succeeded")
        except Exception as email_error:
            logger.error(f"❌ Email sending error: {email_error}")
            # Don't fail the payment if email fails

        # FIXED: Use prefetch_related for reverse FK relationships
        event_registrations = StudentEventRegistration.objects.filter(
            student=student,
            payment=payment
        ).select_related(
            'event_option__event'
        ).prefetch_related(
            'team__members__valorant_info'  # FIXED: Use prefetch_related
        )

        context = {
            'student': student,
            'payment': payment,
            'receipt': receipt,
            'event_registrations': event_registrations,
            'already_processed': False,
        }

        return render(request, 'registration/payment_success.html', context)

    except Exception as e:
        logger.error(f'❌ Error processing successful payment {tran_id}: {e}', exc_info=True)
        return HttpResponseBadRequest('Payment processing error.')


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
    
    # FIXED: Get event registrations with proper prefetch
    event_registrations = StudentEventRegistration.objects.filter(
        student=student,
        payment=payment
    ).select_related(
        'event_option__event'
    ).prefetch_related(
        'team__members__valorant_info'  # FIXED
    )
    
    context = {
        'student': student,
        'receipt': receipt,
        'payment': payment,
        'event_registrations': event_registrations,
    }
    
    return render(request, 'registration/receipt_standalone.html', context)

def receipt_print_view(request, receipt_number):
    """Dedicated view for printing receipts without header"""
    receipt = get_object_or_404(Receipt, receipt_number=receipt_number)
    
    context = {
        'student': receipt.student,
        'receipt': receipt,
        'payment': receipt.payment,
    }
    
    return render(request, 'registration/receipt_standalone.html', context)

@csrf_exempt
def payment_fail(request, payment_id):
    """
    Handle failed payment with detailed error information
    """
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        student = payment.student
        
        # Get transaction details from URL parameters
        if request.method == 'POST':
            post_data = request.POST
            tran_id = post_data.get('tran_id')
            error_code = post_data.get('error')
            failed_reason = post_data.get('failedreason', '')
        else:
            get_data = request.GET
            tran_id = get_data.get('tran_id')
            error_code = get_data.get('error')
            failed_reason = get_data.get('failedreason', '')
        
        # Map common SSLCommerz error codes to user-friendly messages
        error_messages = {
            'FAILED': 'Your payment could not be processed. Please try again.',
            'CANCELLED': 'Payment was cancelled by user.',
            'UNATTEMPTED': 'Payment was not attempted.',
            'EXPIRED': 'Payment session has expired. Please try again.',
            'INCOMPLETE': 'Payment process was incomplete.',
            'INVALID_TRANSACTION': 'Invalid transaction. Please start over.',
            'AMOUNT_MISMATCH': 'Payment amount mismatch detected.',
            'CARD_DECLINED': 'Your card was declined. Please try a different payment method.',
            'INSUFFICIENT_FUNDS': 'Insufficient funds in your account.',
            'NETWORK_ERROR': 'Network error occurred. Please check your connection and try again.',
            'BANK_DECLINE': 'Transaction was declined by your bank.',
            'INVALID_CARD': 'Invalid card information provided.',
            'CARD_EXPIRED': 'Your card has expired.',
            'PROCESSING_ERROR': 'Payment processing error. Please try again later.',
        }
        
        # Determine error message
        error_message = None
        if error_code:
            error_message = error_messages.get(error_code.upper(), f"Payment failed: {error_code}")
        elif failed_reason:
            error_message = f"Payment failed: {failed_reason}"
        else:
            error_message = "Payment could not be completed. Please try again."
        
        # Update payment status if transaction ID exists
        if tran_id:
            try:
                payment = Payment.objects.get(transaction_id=tran_id, student=student)
                payment.status = 'FAILED'
                payment.gateway_response = {
                    'error_code': error_code,
                    'failed_reason': failed_reason,
                    'callback_data': dict(request.GET.items())
                }
                payment.save()
                
                logger.warning(f'Payment failed for student {student.id}, transaction {tran_id}, error: {error_code}')
                
                # Log security alert for suspicious patterns
                if error_code in ['AMOUNT_MISMATCH', 'INVALID_TRANSACTION']:
                    log_security_alert(
                        'PAYMENT_FRAUD',
                        f'Suspicious payment failure: {error_code}',
                        get_client_ip(request),
                        request.META.get('HTTP_USER_AGENT', ''),
                        student=student,
                        payment=payment,
                        data={'error_code': error_code, 'failed_reason': failed_reason}
                    )
                
            except Payment.DoesNotExist:
                logger.error(f'Payment record not found for transaction {tran_id}')
        
        context = {
            'student': student,
            'payment': payment,
            'error_message': error_message,
            'error_code': error_code,
            'transaction_id': tran_id,
            'can_retry': error_code not in ['AMOUNT_MISMATCH', 'INVALID_TRANSACTION'],  # Don't allow retry for suspicious errors
        }
        return render(request, 'registration/payment_fail.html', context)
        
    except Exception as e:
        logger.error(f'Payment fail handler error: {e}')
        messages.error(request, 'An error occurred while processing the payment failure.')
        return redirect('home')

@csrf_exempt

def payment_cancel(request, payment_id):
    """
    Handle cancelled payment with user guidance
    """
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        student = payment.student
        
        # Get transaction details
        if request.method == 'POST':
            post_data = request.POST
            tran_id = post_data.get('tran_id')
            cancel_reason = post_data.get('cancel_reason', 'User cancelled the payment')
        else:
            get_data = request.GET
            tran_id = get_data.get('tran_id')
            cancel_reason = get_data.get('cancel_reason', 'User cancelled the payment')
        
        # Update payment status if exists
        if tran_id:
            try:
                payment = Payment.objects.get(transaction_id=tran_id, student=student)
                payment.status = 'CANCELLED'
                payment.gateway_response = {
                    'cancel_reason': cancel_reason,
                    'callback_data': dict(request.GET.items())
                }
                payment.save()
                
                logger.info(f'Payment cancelled for student {student.id}, transaction {tran_id}')
            except Payment.DoesNotExist:
                logger.warning(f'Payment record not found for cancelled transaction {tran_id}')
        
        context = {
            'student': student,
            'payment': payment,
            'transaction_id': tran_id,
            'cancel_reason': cancel_reason,
        }
        return render(request, 'registration/payment_cancel.html', context)
        
    except Exception as e:
        logger.error(f'Payment cancel handler error: {e}')
        messages.error(request, 'An error occurred.')
        return redirect('home')
    
def handle_payment_timeout(request):
    """
    Handle payment session timeout
    """
    student_id = request.GET.get('student_id')
    tran_id = request.GET.get('tran_id')
    
    if student_id and tran_id:
        try:
            student = Student.objects.get(id=student_id, is_deleted=False)
            payment = Payment.objects.get(transaction_id=tran_id, student=student)
            
            # Mark payment as expired
            payment.status = 'EXPIRED'
            payment.gateway_response = {'timeout_reason': 'Payment session expired'}
            payment.save()
            
            messages.warning(request, 'Your payment session has expired. Please try again.')
            return redirect('payment_gateway', student_id=student.id)
            
        except (Student.DoesNotExist, Payment.DoesNotExist):
            pass
    
    messages.error(request, 'Payment session expired.')
    return redirect('home')

def check_payment_status(request, student_id, transaction_id):
    """
    Manual payment status check endpoint for uncertain cases
    """
    try:
        student = get_object_or_404(Student, id=student_id, is_deleted=False)
        payment = get_object_or_404(Payment, transaction_id=transaction_id, student=student)
        
        # Re-validate with SSLCommerz
        if payment.status == 'PENDING':
            sslcommerz = SSLCOMMERZ()
            validation_data = {
                'val_id': request.GET.get('val_id'),
                'store_id': settings.SSLCOMMERZ_STORE_ID,
                'store_passwd': settings.SSLCOMMERZ_STORE_PASSWORD,
                'format': 'json'
            }
            
            try:
                validation_url = ('https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php' 
                                 if settings.SSLCOMMERZ_IS_SANDBOX 
                                 else 'https://securepay.sslcommerz.com/validator/api/validationserverAPI.php')
                
                response = requests.get(validation_url, params=validation_data, timeout=30)
                response.raise_for_status()
                result = response.json()
                
                if result.get('status') in ['VALID', 'VALIDATED']:
                    # Update payment as successful
                    with transaction.atomic():
                        payment.status = 'SUCCESS'
                        payment.gateway_response = result
                        payment.completed_at = timezone.now()
                        payment.save()
                        
                        student.is_paid = True
                        student.payment_verified = True
                        student.save()
                    
                    messages.success(request, 'Payment verification successful!')
                    return redirect('payment_success', student_id=student.id)
                else:
                    messages.error(request, 'Payment verification failed.')
                    return redirect('payment_fail', student_id=student.id)
                    
            except requests.exceptions.RequestException as e:
                logger.error(f'Payment status check error: {e}')
                messages.error(request, 'Unable to verify payment status. Please contact support.')
        
        # Return current status
        if payment.status == 'SUCCESS':
            return redirect('payment_success', student_id=student.id)
        elif payment.status in ['FAILED', 'EXPIRED']:
            return redirect('payment_fail', student_id=student.id)
        elif payment.status == 'CANCELLED':
            return redirect('payment_cancel', student_id=student.id)
        else:
            messages.info(request, f'Payment status: {payment.get_status_display()}')
            return redirect('home')
            
    except Exception as e:
        logger.error(f'Payment status check error: {e}')
        messages.error(request, 'Error checking payment status.')
        return redirect('home')
    
# Middleware function to handle expired payments automatically
def cleanup_expired_payments():
    """
    Cleanup expired payments - can be called via cron job or management command
    """
    try:
        expired_payments = Payment.objects.filter(
            status='PENDING',
            expires_at__lt=timezone.now()
        )
        
        count = 0
        for payment in expired_payments:
            payment.status = 'EXPIRED'
            payment.save()
            count += 1
        
        if count > 0:
            logger.info(f'Marked {count} payments as expired')
        
        return count
        
    except Exception as e:
        logger.error(f'Error cleaning up expired payments: {e}')
        return 0


@csrf_exempt
@require_POST
def payment_ipn(request):
    """
    Enhanced IPN handler with better security and error handling
    """
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    logger.info(f"📨 IPN received from {ip_address}")

    try:
        ipn_data = request.POST.dict()
        tran_id = ipn_data.get('tran_id')

        if not tran_id:
            logger.error("❌ IPN received without transaction ID")
            return HttpResponseBadRequest('Transaction ID missing.')

        logger.info(f"📨 Processing IPN for transaction: {tran_id}")

        # Validate IPN with SSL Commerz
        sslcz = SSLCOMMERZ()
        is_valid, validation_response = sslcz.validate_ipn(ipn_data)

        if not is_valid:
            log_security_alert(
                'INVALID_HASH', 
                'IPN validation failed', 
                ip_address, 
                user_agent, 
                data=ipn_data
            )
            logger.warning(f"⚠️ IPN validation failed for {tran_id}")
            return HttpResponseBadRequest('Invalid IPN')

        # Get payment record
        try:
            payment = Payment.objects.select_for_update().get(transaction_id=tran_id)
        except Payment.DoesNotExist:
            log_security_alert(
                'PAYMENT_FRAUD',
                f'IPN for non-existent transaction: {tran_id}',
                ip_address,
                user_agent,
                data=ipn_data
            )
            logger.warning(f"⚠️ IPN for non-existent transaction: {tran_id}")
            return HttpResponseBadRequest('Transaction not found')

        # Idempotency check
        if payment.status == 'SUCCESS':
            logger.info(f"ℹ️ IPN for already successful payment {tran_id}")
            return HttpResponse('OK', status=200)

        # Amount verification
        if not verify_payment_amount(payment.amount, validation_response.get('amount')):
            log_security_alert(
                'PAYMENT_FRAUD',
                f"IPN amount mismatch - Expected: {payment.amount}, Got: {validation_response.get('amount')}",
                ip_address,
                user_agent,
                payment=payment,
                data=ipn_data
            )
            logger.warning(f"⚠️ Amount mismatch in IPN for {tran_id}")
            return HttpResponseBadRequest('Amount mismatch')

        # Process based on status and risk level
        with transaction.atomic():
            status = validation_response.get('status')
            risk_level = validation_response.get('risk_level', '0')
            val_id = validation_response.get('val_id')

            if status == 'VALID':
                if risk_level == '0':
                    # Low risk - auto-approve
                    payment.status = 'SUCCESS'
                    payment.gateway_txnid = val_id
                    payment.gateway_response = validation_response
                    payment.completed_at = timezone.now()
                    payment.save()

                    student = payment.student
                    student.is_paid = True
                    student.payment_verified = True
                    student.save()

                    logger.info(f'✅ IPN: Payment {tran_id} marked as SUCCESS')

                    # Generate receipt
                    receipt, created = Receipt.objects.get_or_create(
                        student=student,
                        payment=payment
                    )
                    
                    # Send email asynchronously
                    if not receipt.email_sent:
                        try:
                            send_registration_email(student, receipt)
                        except Exception as e:
                            logger.error(f"❌ Failed to send email via IPN: {e}")
                
                else:
                    # High risk - flag for manual review
                    payment.gateway_response = validation_response
                    payment.save()
                    
                    log_security_alert(
                        'HIGH_RISK_TRANSACTION',
                        f'High-risk transaction: {tran_id}. Risk level: {risk_level}',
                        ip_address,
                        user_agent,
                        payment=payment,
                        data=validation_response
                    )
                    logger.warning(f"⚠️ High-risk transaction {tran_id} flagged for review")

            elif status in ['FAILED', 'CANCELLED', 'EXPIRED']:
                payment.status = status
                payment.gateway_response = validation_response
                payment.save()
                logger.info(f'ℹ️ IPN: Payment {tran_id} marked as {status}')

            else:
                logger.warning(f"⚠️ Unhandled IPN status: {status} for {tran_id}")

        return HttpResponse('OK', status=200)

    except Exception as e:
        logger.error(f'❌ IPN processing error: {e}', exc_info=True)
        log_security_alert(
            'IPN_ERROR',
            f'IPN processing error: {str(e)}',
            ip_address,
            user_agent,
            data={'error': str(e)}
        )
        return HttpResponseBadRequest('Processing error')


from .utils import (
    get_client_ip, rate_limit_check, sanitize_payment_data, validate_student_data,
    verify_payment_amount, generate_secure_transaction_id, send_notification_email,
    log_security_alert, detect_suspicious_activity, verify_sslcommerz_callback,
    generate_sslcommerz_hash, log_admin_action, send_email_async
)

def send_registration_email(student, receipt):
    """
    Send registration confirmation email - FIXED VERSION
    """
    try:
        # Get all event registrations for this student
        event_registrations = StudentEventRegistration.objects.filter(
            student=student,
            payment=receipt.payment
        ).select_related('event_option__event')
        
        # Prepare context
        context = {
            'student': student,
            'receipt': receipt,
            'payment': receipt.payment,
            'events': event_registrations,  # Fixed: pass registrations, not event options
            'site_url': settings.SITE_URL,
        }
        
        # Render email templates
        html_message = render_to_string('registration/email/registration_confirmation.html', context)
        plain_message = strip_tags(html_message)
        
        # Create email with both HTML and plain text
        subject = f'Registration Confirmed - TSC 2025 - {student.name}'
        from_email = settings.EMAIL_HOST_USER
        to_email = [student.email]
        
        # Create message
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=from_email,
            to=to_email
        )
        msg.attach_alternative(html_message, "text/html")
        
        # Send email synchronously with error handling
        try:
            msg.send(fail_silently=False)
            logger.info(f'✅ Registration email sent successfully to {student.email}')
            
            # Update receipt status
            receipt.email_sent = True
            receipt.email_sent_at = timezone.now()
            receipt.save(update_fields=['email_sent', 'email_sent_at'])
            
            return True
            
        except Exception as smtp_error:
            logger.error(f'❌ SMTP Error sending email to {student.email}: {smtp_error}')
            # Log but don't raise - payment already succeeded
            
            # Try to notify admin
            try:
                admin_subject = f'Failed Email Notification - {student.registration_id}'
                admin_msg = f"""
Failed to send registration email to {student.email}

Student: {student.name}
Registration ID: {student.registration_id}
Receipt: {receipt.receipt_number}

Error: {str(smtp_error)}

Please manually send confirmation email.
                """
                send_mail(
                    admin_subject,
                    admin_msg,
                    settings.EMAIL_HOST_USER,
                    [settings.EMAIL_HOST_USER],
                    fail_silently=True
                )
            except:
                pass  # Don't let admin notification failure affect anything
                
            return False
            
    except Exception as e:
        logger.error(f'❌ Error preparing registration email for {student.email}: {e}', exc_info=True)
        return False



def generate_qr_code(request, receipt_number):
    """
    Generate a QR code for the given receipt number.
    """
    try:
        receipt = get_object_or_404(Receipt, receipt_number=receipt_number)
        verification_url = request.build_absolute_uri(
            reverse('verify_receipt', kwargs={'receipt_number': receipt.receipt_number})
        )
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(verification_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return HttpResponse(buffer.getvalue(), content_type="image/png")

    except Exception as e:
        logger.error(f"Error generating QR code for receipt {receipt_number}: {e}")
        return HttpResponse(status=500)

def verify_receipt(request, receipt_number):
    """
    Verify a receipt and display its status.
    """
    try:
        receipt = get_object_or_404(Receipt.objects.select_related('student', 'payment'), receipt_number=receipt_number)
        context = {
            'receipt': receipt,
            'student': receipt.student,
            'payment': receipt.payment,
        }
        return render(request, 'registration/verify_receipt.html', context)
    except Exception as e:
        logger.error(f"Error verifying receipt {receipt_number}: {e}")
        messages.error(request, "An error occurred while verifying the receipt.")
        return redirect('home')

def events_page(request):
    """
    Enhanced events page with modern UI and comprehensive event details
    """
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    try:
        # Subqueries to get individual and team fees
        individual_fee_subquery = EventOption.objects.filter(
            event=OuterRef('pk'),
            event_type='INDIVIDUAL'
        ).values('fee')[:1]

        team_fee_subquery = EventOption.objects.filter(
            event=OuterRef('pk'),
            event_type='TEAM'
        ).values('fee')[:1]

        # Get active events with related data - FIXED to work with your model structure
        events = Event.objects.filter(is_active=True).prefetch_related('options').annotate(
            individual_fee=Subquery(individual_fee_subquery, output_field=models.DecimalField()),
            team_fee=Subquery(team_fee_subquery, output_field=models.DecimalField())
        ).order_by('-created_at')
        
        # Prepare event data for frontend - FIXED to match your model structure
        events_data = []
        for event in events:
            # Get registration count - FIXED to work with your through model
            registration_count = StudentEventRegistration.objects.filter(
                event_option__event=event
            ).count()

            # Format fee display from annotated fields
            individual_fee = event.individual_fee
            team_fee = event.team_fee
            fee_display = "N/A"

            if individual_fee is not None and team_fee is not None:
                if individual_fee == team_fee:
                    fee_display = f"৳{individual_fee:,.0f}"
                else:
                    fee_display = f"৳{individual_fee:,.0f} / ৳{team_fee:,.0f}"
            elif individual_fee is not None:
                fee_display = f"৳{individual_fee:,.0f}"
            elif team_fee is not None:
                fee_display = f"৳{team_fee:,.0f}"
            else:
                # Fallback if no options are found (or they are free)
                min_fee_agg = event.options.aggregate(min_fee=models.Min('fee'))
                min_fee = min_fee_agg.get('min_fee')
                if min_fee is not None and min_fee > 0:
                    fee_display = f"৳{min_fee:,.0f}"
                elif min_fee == 0:
                    fee_display = "Free"

            event_data = {
                'id': event.id,
                'name': event.name,
                'description': event.description,
                'fee': fee_display,  # Using the new formatted fee display
                'created_at': event.created_at,
                'rules_type': event.rules_type,
                'rules_text': event.rules_text,
                'rules_file_url': event.rules_file.url if event.rules_file else '',
                'event_image_url': event.event_image.url if event.event_image else '',
                'registration_count': registration_count,
                'has_individual': event.options.filter(event_type='INDIVIDUAL').exists(),
                'has_team': event.options.filter(event_type='TEAM').exists(),
                'options': list(event.options.all().values('id', 'name', 'event_type', 'fee', 'max_team_size', 'max_participants'))
            }
            events_data.append(event_data)
        
        # Log page access for analytics
        logger.info(f'Events page accessed from {ip_address} - {len(events_data)} events displayed')
        
        context = {
            'events': events,
            'events_data': events_data,
            'events_count': len(events_data),
        }
        
        return render(request, 'registration/events_page.html', context)
        
    except Exception as e:
        logger.error(f'Error in events_page view: {e}', exc_info=True)
        messages.error(request, 'An error occurred while loading events. Please try again.')
        
        # Return empty context on error
        context = {
            'events': [],
            'events_data': [],
            'events_count': 0,
        }
        return render(request, 'registration/events_page.html', context)
    
def event_rules_api(request, event_id):
    """
    API endpoint to fetch event rules dynamically
    Used for AJAX loading of rules content
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        event = get_object_or_404(
            Event.objects.filter(is_active=True), 
            id=event_id
        )
        
        # Prepare rules data based on type
        rules_data = {
            'id': event.id,
            'name': event.name,
            'rules_type': event.rules_type,
        }
        
        if event.rules_type == 'TEXT':
            rules_data['content'] = event.rules_text or 'No rules specified for this event.'
        elif event.rules_type == 'IMAGE':
            rules_data['content'] = event.rules_file.url if event.rules_file else ''
        elif event.rules_type == 'PDF':
            rules_data['content'] = event.rules_file.url if event.rules_file else ''
        else:
            rules_data['content'] = 'Rules will be updated soon.'
        
        # Log API access
        logger.info(f'Event rules API accessed for event {event_id} from {get_client_ip(request)}')
        
        return JsonResponse({
            'success': True,
            'data': rules_data
        })
        
    except Event.DoesNotExist:
        logger.warning(f'Event rules API called for non-existent event: {event_id}')
        return JsonResponse({
            'success': False,
            'error': 'Event not found'
        }, status=404)
    except Exception as e:
        logger.error(f'Error in event_rules_api: {e}')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching event rules'
        }, status=500)

def event_details_api(request, event_id):
    """
    API endpoint to fetch detailed event information
    Can be used for enhanced modals or event detail pages
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        event = get_object_or_404(
            Event.objects.select_related().prefetch_related('studenteventregistration_set'), 
            id=event_id, 
            is_active=True
        )
        
        # Get registration statistics
        registration_count = event.get_registration_count()
        
        # Calculate registration progress percentage
        registration_progress = 0
        if event.max_participants:
            registration_progress = min((registration_count / event.max_participants) * 100, 100)
        
        event_data = {
            'id': event.id,
            'name': event.name,
            'description': event.description,
            'fee': str(event.fee),
            'event_type': event.event_type,
            'event_type_display': event.get_event_type_display(),
            'max_team_size': event.max_team_size,
            'max_participants': event.max_participants,
            'registration_count': registration_count,
            'registration_progress': registration_progress,
            'is_registration_full': event.is_registration_full(),
            'created_at': event.created_at.isoformat(),
            'updated_at': event.updated_at.isoformat(),
            'event_image_url': event.event_image.url if event.event_image else '',
            'rules_type': event.rules_type,
            'has_rules': bool(event.rules_text or event.rules_file),
        }
        
        return JsonResponse({
            'success': True,
            'data': event_data
        })
        
    except Event.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Event not found'
        }, status=404)
    except Exception as e:
        logger.error(f'Error in event_details_api: {e}')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching event details'
        }, status=500)



@require_GET
def get_team_section(request):
    """
    HTMX endpoint to return team section HTML for team events
    """
    option_id = request.GET.get('option_id')
    
    if not option_id:
        return HttpResponse('')
    
    try:
        option = EventOption.objects.select_related('event').get(id=option_id)
        
        if option.event_type == 'TEAM':
            context = {
                'option': option,
            }
            return render(request, 'registration/_team_section.html', context)
        else:
            return HttpResponse('')  # Return empty for individual events
            
    except EventOption.DoesNotExist:
        logger.warning(f"EventOption not found: {option_id}")
        return HttpResponse('')
    except Exception as e:
        logger.error(f"Error in get_team_section: {e}")
        return HttpResponse('')



def about_us(request):
    """
    About Us page with moderators, board members, and past event images.
    """
    moderators = TeamMemberProfile.objects.filter(member_type='MODERATOR')
    board_members = TeamMemberProfile.objects.filter(member_type='BOARD_MEMBER')
    past_event_images = PastEventImage.objects.all()
    context = {
        'moderators': moderators,
        'board_members': board_members,
        'past_event_images': past_event_images,
    }
    return render(request, 'registration/about_us.html', context)

def join_us(request):
    """
    Join Us page with links to social media.
    """
    social_media_profiles = SocialMediaProfile.objects.filter(is_active=True)
    context = {
        'social_media_profiles': social_media_profiles,
    }
    return render(request, 'registration/join_us.html', context)

def valorant_page(request):
    video = ValorantBackgroundVideo.objects.filter(is_active=True).first()
    try:
        valorant_settings = ValorantApplicationSettings.objects.first()
        is_enabled = valorant_settings.is_enabled if valorant_settings else False
    except ValorantApplicationSettings.DoesNotExist:
        is_enabled = False

    context = {
        'video': video,
        'valorant_registration_enabled': is_enabled,
    }
    return render(request, 'registration/valorant.html', context)





@csrf_exempt
def debug_form_submission(request):
    """Temporary debug view to see what's being submitted"""
    if request.method == 'POST':
        logger.info("=== FORM SUBMISSION DEBUG ===")
        logger.info(f"POST data keys: {list(request.POST.keys())}")
        logger.info(f"POST data: {dict(request.POST)}")
        logger.info(f"selected_events value: '{request.POST.get('selected_events')}'")
        logger.info(f"events list: {request.POST.getlist('events')}")
        
        # Try to create form and see validation errors
        form = StudentRegistrationForm(request.POST)
        logger.info(f"Form is_valid: {form.is_valid()}")
        if not form.is_valid():
            logger.error(f"Form errors: {form.errors}")
            logger.error(f"Form non_field_errors: {form.non_field_errors()}")
            
            # Specifically check selected_events field
            try:
                selected_events_data = form.cleaned_data.get('selected_events', 'NOT_FOUND')
                logger.info(f"Cleaned selected_events: {selected_events_data}")
            except:
                logger.error("Could not get cleaned_data for selected_events")
        
        logger.info("=== END DEBUG ===")
    
    return JsonResponse({'debug': 'complete'})


@csrf_exempt
def test_form_submission(request):
    """Simple test to isolate the form validation issue"""
    if request.method == 'POST':
        logger.info("=== TEST FORM SUBMISSION ===")
        
        # Log all POST data
        for key, value in request.POST.items():
            logger.info(f"POST['{key}'] = '{value}'")
        
        # Test just the selected_events field
        selected_events_value = request.POST.get('selected_events', '')
        logger.info(f"selected_events raw value: '{selected_events_value}'")
        
        # Create a minimal form with just required fields for testing
        test_data = {
            'name': request.POST.get('name', 'Test User'),
            'email': request.POST.get('email', 'test@example.com'),
            'mobile_number': request.POST.get('mobile_number', '+8801234567890'),
            'grade': request.POST.get('grade', ''),
            'roll': request.POST.get('roll', '123'),
            'selected_events': selected_events_value,
        }
        
        form = StudentRegistrationForm(test_data)
        
        if form.is_valid():
            logger.info("✅ Form validation PASSED")
            selected_events = form.cleaned_data['selected_events']
            logger.info(f"Cleaned selected_events: {[opt.id for opt in selected_events]}")
            return JsonResponse({
                'success': True,
                'message': 'Form validation passed',
                'event_count': len(selected_events)
            })
        else:
            logger.error("❌ Form validation FAILED")
            logger.error(f"Form errors: {dict(form.errors)}")
            
            # Check specifically if selected_events field has errors
            if 'selected_events' in form.errors:
                logger.error(f"selected_events specific errors: {form.errors['selected_events']}")
            
            return JsonResponse({
                'success': False,
                'message': 'Form validation failed',
                'errors': dict(form.errors)
            })
    
    return JsonResponse({'error': 'Only POST allowed'})


def package_selection(request):
    """
    Initial package selection page - Regular or Discount Bundle
    """
    ip_address = get_client_ip(request)
    
    try:
        # Get active bundles grouped by type
        junior_bundles = DiscountBundle.objects.filter(
            bundle_type='JUNIOR',
            is_active=True
        ).prefetch_related('bundle_events__event_option__event').order_by('display_order')
        
        senior_bundles = DiscountBundle.objects.filter(
            bundle_type='SENIOR',
            is_active=True
        ).prefetch_related('bundle_events__event_option__event').order_by('display_order')
        
        context = {
            'junior_bundles': junior_bundles,
            'senior_bundles': senior_bundles,
            'has_bundles': junior_bundles.exists() or senior_bundles.exists(),
        }
        
        logger.info(f'Package selection page accessed from {ip_address}')
        return render(request, 'registration/package_selection.html', context)
        
    except Exception as e:
        logger.error(f'Error in package_selection: {e}', exc_info=True)
        messages.error(request, 'An error occurred. Please try again.')
        return redirect('home')


# REPLACE YOUR EXISTING student_registration() FUNCTION WITH THIS VERSION

def student_registration(request, package_type=None, bundle_id=None):
    """
    Enhanced registration with proper duplicate handling and constraint checking
    """
    ip_address = get_client_ip(request)
    
    selected_bundle = None
    if package_type == 'bundle' and bundle_id:
        try:
            selected_bundle = DiscountBundle.objects.prefetch_related(
                'bundle_events__event_option__event'
            ).get(id=bundle_id, is_active=True)
        except DiscountBundle.DoesNotExist:
            messages.error(request, 'Invalid bundle selection.')
            return redirect('package_selection')

    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        
        logger.info(f"Registration attempt from IP: {ip_address}, Package: {package_type}")

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Step 1: Get or create student
                    student, created = Student.objects.select_for_update().get_or_create(
                        email=form.cleaned_data['email'],
                        defaults={
                            'name': form.cleaned_data['name'],
                            'school_college': form.cleaned_data.get('school_college'),
                            'other_school': form.cleaned_data.get('other_school'),
                            'grade': form.cleaned_data['grade'],
                            'section': form.cleaned_data.get('section'),
                            'roll': form.cleaned_data['roll'],
                            'reference': form.cleaned_data.get('reference'),
                            'mobile_number': form.cleaned_data['mobile_number'],
                            'registration_ip': ip_address,
                        }
                    )

                    # Step 2: Check if student already completed registration
                    if student.is_paid and student.payment_verified:
                        logger.warning(f"Student {student.email} already has completed registration")
                        messages.warning(
                            request,
                            f'You have already completed registration with ID: {student.registration_id}. '
                            'Please check your email for the receipt.'
                        )
                        return redirect('home')

                    # Step 3: Check for existing VALID pending payment
                    existing_pending = Payment.objects.filter(
                        student=student,
                        status='PENDING',
                        expires_at__gt=timezone.now()
                    ).first()
                    
                    if existing_pending:
                        logger.info(f"Resuming payment session {existing_pending.transaction_id}")
                        messages.info(request, 'You have a pending payment session. Redirecting...')
                        return redirect('payment_instructions', payment_id=existing_pending.id)

                    # Step 4: Get selected event options
                    event_options = form.cleaned_data['selected_events']
                    
                    if not event_options or len(event_options) == 0:
                        raise ValueError("Please select at least one event to continue.")
                    
                    logger.info(f"Processing registration for {student.name} with {len(event_options)} events")
                    
                    # Step 5: CRITICAL FIX - Check and handle existing registrations properly
                    already_registered_events = []
                    events_to_register = []
                    
                    for option in event_options:
                        # Check for EXACT event option match (not just event)
                        existing_reg = StudentEventRegistration.objects.filter(
                            student=student,
                            event_option=option  # Check exact event option, not just event
                        ).first()
                        
                        if existing_reg:
                            # Check if this registration has a successful payment
                            if existing_reg.payment and existing_reg.payment.status == 'SUCCESS':
                                already_registered_events.append(f"{option.event.name} - {option.name}")
                                logger.warning(f"Already registered (PAID): {option.event.name} - {option.name}")
                            else:
                                # Incomplete registration - will be replaced
                                logger.info(f"Found incomplete registration for {option.event.name} - {option.name}, will replace")
                                events_to_register.append(option)
                        else:
                            events_to_register.append(option)
                    
                    # If all events are already paid for
                    if already_registered_events and not events_to_register:
                        event_list = ', '.join(already_registered_events)
                        logger.warning(f"All selected events already registered for {student.email}")
                        messages.warning(
                            request,
                            f'You are already registered and paid for: {event_list}. '
                            f'Please check your email for confirmation.'
                        )
                        return redirect('home')
                    
                    # Warn about already registered events
                    if already_registered_events:
                        event_list = ', '.join(already_registered_events)
                        messages.warning(
                            request,
                            f'Note: You are already registered for {event_list}. '
                            f'Proceeding with new event registration only.'
                        )
                    
                    # Step 6: CRITICAL FIX - Clean up ALL incomplete registrations for these event options
                    incomplete_registrations = StudentEventRegistration.objects.filter(
                        student=student,
                        event_option__in=events_to_register
                    ).exclude(
                        payment__status='SUCCESS'
                    )
                    
                    deleted_count = incomplete_registrations.count()
                    if deleted_count > 0:
                        logger.info(f"Cleaning up {deleted_count} incomplete registrations")
                        incomplete_registrations.delete()
                    
                    # Step 7: Calculate amounts
                    if package_type == 'bundle' and selected_bundle:
                        subtotal = selected_bundle.price
                    else:
                        subtotal = sum(option.fee for option in events_to_register)

                    fee_percentage = Decimal(getattr(settings, 'SSLCOMMERZ_FEE_PERCENTAGE', '0.015'))
                    fee = (subtotal * fee_percentage).quantize(Decimal('0.01'))
                    total_amount = subtotal + fee

                    if total_amount <= 0:
                        raise ValueError("Total amount must be greater than zero.")

                    # Step 8: Create payment
                    payment = Payment.objects.create(
                        student=student,
                        amount=total_amount,
                        client_ip=ip_address,
                        transaction_id=generate_secure_transaction_id(),
                        expires_at=timezone.now() + timezone.timedelta(minutes=30)
                    )
                    
                    logger.info(f"Payment created: {payment.transaction_id} for ৳{total_amount}")

                    # Step 9: Create NEW event registrations (after cleanup)
                    registration_count = 0
                    for option in events_to_register:
                        # Double-check no duplicate exists before creating
                        existing = StudentEventRegistration.objects.filter(
                            student=student,
                            event_option=option
                        ).first()
                        
                        if existing:
                            logger.warning(f"Duplicate found during creation, skipping: {option.event.name}")
                            continue
                        
                        reg = StudentEventRegistration.objects.create(
                            student=student,
                            event_option=option,
                            payment=payment,
                            registration_ip=ip_address
                        )
                        registration_count += 1
                        
                        logger.info(f"Event registration created: {option.event.name} - {option.name}")
                        
                        # Handle team creation
                        if option.event_type == 'TEAM':
                            team_name = request.POST.get(f'team_name_{option.id}', '').strip()
                            if not team_name:
                                raise ValueError(f"Team name required for {option.event.name}")
                            
                            team = Team.objects.create(name=team_name, registration=reg)
                            leader_index = request.POST.get(f'team_leader_{option.id}', '0')
                            
                            # Add team leader (registering person)
                            team_member = TeamMember.objects.create(
                                team=team, 
                                name=student.name, 
                                is_leader=(leader_index == '0')
                            )
                            
                            # Handle Valorant-specific fields
                            if option.event.name == 'Valorant':
                                ValorantTeamMember.objects.create(
                                    team_member=team_member,
                                    discord_ign=request.POST.get(f'team_member_{option.id}_0_discord_ign', '').strip(),
                                    riot_ign=request.POST.get(f'team_member_{option.id}_0_riot_ign', '').strip(),
                                    contact_number=request.POST.get(f'team_member_{option.id}_0_contact_number', '').strip(),
                                )
                            
                            # Add additional team members
                            for i in range(1, option.max_team_size or 2):
                                member_name = request.POST.get(f'team_member_{option.id}_{i}_name', '').strip()
                                if member_name:
                                    team_member = TeamMember.objects.create(
                                        team=team, 
                                        name=member_name, 
                                        is_leader=(leader_index == str(i))
                                    )
                                    
                                    if option.event.name == 'Valorant':
                                        ValorantTeamMember.objects.create(
                                            team_member=team_member,
                                            discord_ign=request.POST.get(f'team_member_{option.id}_{i}_discord_ign', '').strip(),
                                            riot_ign=request.POST.get(f'team_member_{option.id}_{i}_riot_ign', '').strip(),
                                            contact_number=request.POST.get(f'team_member_{option.id}_{i}_contact_number', '').strip(),
                                        )
                            
                            logger.info(f"Team '{team_name}' created with {team.members.count()} members")
                    
                    if registration_count == 0:
                        raise ValueError("No new event registrations were created. Please try again.")
                    
                    logger.info(f"✅ Successfully created {registration_count} new registrations")

                # Store payment ID in session
                request.session['pending_payment_id'] = payment.id
                request.session['payment_initiated_at'] = timezone.now().isoformat()
                
                # Success message
                messages.success(
                    request,
                    f'Registration saved! ID: {student.registration_id}. '
                    f'Please complete payment within 30 minutes.'
                )
                
                return redirect('payment_instructions', payment_id=payment.id)

            except ValueError as ve:
                logger.error(f'Validation error: {ve}')
                messages.error(request, str(ve))
                
            except Exception as e:
                logger.error(f'Registration error: {e}', exc_info=True)
                messages.error(
                    request, 
                    'An unexpected error occurred. Please try again or contact support.'
                )
        else:
            logger.error(f"Form validation failed: {form.errors.as_json()}")
            messages.error(request, 'Please correct the errors in the form.')
            
            # Log specific errors
            for field, errors in form.errors.items():
                logger.error(f"Field '{field}' errors: {errors}")

    else:  # GET request
        form = StudentRegistrationForm()
        if selected_bundle:
            # Pre-populate for bundle
            event_option_ids = selected_bundle.bundle_events.all().values_list('event_option_id', flat=True)
            form.initial['selected_events'] = ','.join(map(str, event_option_ids))

    context = {
        'form': form,
        'package_type': package_type,
        'selected_bundle': selected_bundle,
        'is_bundle_registration': package_type == 'bundle',
    }
    return render(request, 'registration/register.html', context)
