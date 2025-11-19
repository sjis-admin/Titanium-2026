from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from django.utils import timezone
from decimal import Decimal
from registration.models import Payment, Student, Receipt, StudentEventRegistration, EventOption, Event, Team, TeamMember

class PaymentViewTests(TestCase):
    def setUp(self):
        # Create some basic data for tests
        self.client = Client()
        self.student = Student.objects.create(
            name='Test Student',
            email='test@example.com',
            mobile_number='01700000000',
            registration_ip='127.0.0.1'
        )
        self.event = Event.objects.create(name='Test Event', is_active=True)
        self.event_option = EventOption.objects.create(event=self.event, name='Option 1', fee=Decimal('100.00'), event_type='TEAM') # Changed to TEAM type

        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal('500.00'),
            transaction_id='TEST-TXN-123',
            status='PENDING',
            expires_at=timezone.now() + timezone.timedelta(hours=1)
        )
        
        self.student_event_registration = StudentEventRegistration.objects.create(
            student=self.student,
            event_option=self.event_option,
            payment=self.payment
        )

        # Create Team and TeamMember for the event option, linking to student_event_registration
        self.team = Team.objects.create(name='Test Team', registration=self.student_event_registration)
        TeamMember.objects.create(team=self.team, name=self.student.name, is_leader=True)

        self.success_url = reverse('registration:payment_success')

    @patch('registration.sslcommerz.SSLCOMMERZ')
    @patch('registration.views.send_registration_email')
    def test_payment_success_valid_post_data(self, mock_send_email, mock_sslcommerz_class):
        """
        Test that a valid POST request to payment_success updates payment status
        and renders success page.
        """
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (True, {
            'status': 'VALID',
            'amount': str(self.payment.amount),
            'tran_id': self.payment.transaction_id,
            'val_id': 'MOCKVAL123',
            'card_type': 'VISA'
        })
        mock_send_email.return_value = True

        response = self.client.post(self.success_url, {
            'tran_id': self.payment.transaction_id,
            'status': 'VALID',
            'amount': str(self.payment.amount),
            'val_id': 'MOCKVAL123',
            'card_type': 'VISA'
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_success.html')

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')
        self.assertTrue(self.student.is_paid)
        self.assertTrue(self.student.payment_verified)
        self.assertTrue(Receipt.objects.filter(payment=self.payment).exists())
        mock_send_email.assert_called_once()
        mock_sslcommerz_instance.validate_ipn.assert_called_once()

    @patch('registration.sslcommerz.SSLCOMMERZ')
    def test_payment_success_already_processed(self, mock_sslcommerz_class):
        """
        Test that payment_success gracefully handles an already successful payment.
        """
        self.payment.status = 'SUCCESS'
        self.payment.save()
        Receipt.objects.create(student=self.student, payment=self.payment) # Create a receipt
        
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (True, {
            'status': 'VALID',
            'amount': str(self.payment.amount),
            'tran_id': self.payment.transaction_id,
            'val_id': 'MOCKVAL123',
            'card_type': 'VISA'
        })

        response = self.client.post(self.success_url, {
            'tran_id': self.payment.transaction_id,
            'status': 'VALID'
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_success.html')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'SUCCESS')
        mock_sslcommerz_instance.validate_ipn.assert_not_called() # Should not call IPN validation again

    @patch('registration.sslcommerz.SSLCOMMERZ')
    def test_payment_success_invalid_validation(self, mock_sslcommerz_class):
        """
        Test that invalid SSLCommerz validation leads to payment_error page.
        """
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (False, {
            'status': 'FAILED',
            'failedreason': 'Invalid hash'
        })

        response = self.client.post(self.success_url, {
            'tran_id': self.payment.transaction_id,
            'status': 'FAILED'
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_error.html')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'FAILED')

    @patch('registration.sslcommerz.SSLCOMMERZ')
    def test_payment_success_amount_mismatch(self, mock_sslcommerz_class):
        """
        Test that amount mismatch leads to payment_error page.
        """
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (True, {
            'status': 'VALID',
            'amount': '100.00', # Mismatched amount
            'tran_id': self.payment.transaction_id
        })

        response = self.client.post(self.success_url, {
            'tran_id': self.payment.transaction_id,
            'status': 'VALID'
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_error.html')
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'FAILED')

    def test_payment_success_no_tran_id(self):
        """
        Test that a request without transaction ID returns HttpResponseBadRequest.
        """
        response = self.client.post(self.success_url, {})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Missing transaction ID", response.content)

    @patch('registration.sslcommerz.SSLCOMMERZ')
    def test_payment_success_payment_not_found(self, mock_sslcommerz_class):
        """
        Test handling of transaction ID not found in database.
        """
        # Mock the validate_ipn to return a valid response,
        # but the Payment.objects.get will fail in the view
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (True, {
            'status': 'VALID',
            'amount': '500.00',
            'tran_id': 'NONEXISTENT-TXN'
        })

        response = self.client.post(self.success_url, {
            'tran_id': 'NONEXISTENT-TXN',
            'status': 'VALID'
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_error.html')
        self.assertIn(b"Payment record not found", response.content)

    @patch('registration.sslcommerz.SSLCOMMERZ')
    @patch('registration.views.send_registration_email')
    def test_payment_success_post_without_status_and_pending_payment(self, mock_send_email, mock_sslcommerz_class):
        """
        Test scenario where POST data has no 'status' and payment is pending.
        Should lead to 'Payment verification pending' error.
        """
        # Payment is already PENDING from setUp
        # Mock IPN validation to pass, but the logic should not reach it due to missing 'status'
        mock_sslcommerz_instance = MagicMock()
        mock_sslcommerz_class.return_value = mock_sslcommerz_instance
        mock_sslcommerz_instance.validate_ipn.return_value = (True, {}) # This shouldn't even be called if 'status' is missing

        response = self.client.post(self.success_url, {
            'tran_id': self.payment.transaction_id,
            # No 'status' field in POST data
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/payment_error.html')
        self.assertIn(b"Payment verification pending", response.content)
        mock_sslcommerz_instance.validate_ipn.assert_not_called()
        mock_send_email.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PENDING') # Should remain PENDING
