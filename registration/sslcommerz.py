# registration/sslcommerz.py - FIXED VERSION
from django.conf import settings
import requests
import hashlib
from urllib.parse import urlencode
import logging

logger = logging.getLogger(__name__)

class SSLCOMMERZ:
    def __init__(self):
        self.store_id = settings.SSLCOMMERZ_STORE_ID
        self.store_password = settings.SSLCOMMERZ_STORE_PASSWORD
        self.api_url = settings.SSLCOMMERZ_API_URL
        self.validation_url = settings.SSLCOMMERZ_VALIDATION_URL
        self.is_sandbox = settings.SSLCOMMERZ_IS_SANDBOX

    def create_session(self, amount, tran_id, cust_name, cust_email, cust_phone, payment_id, cus_add1, cus_city, cus_state, cus_postcode, cus_country):
        # Ensure URLs are properly formatted
        site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')
        if site_url.endswith('/'):
            site_url = site_url[:-1]  # Remove trailing slash
        
        post_data = {
            'store_id': self.store_id,
            'store_passwd': self.store_password,
            'total_amount': str(amount),
            'currency': 'BDT',
            'tran_id': tran_id,
            # Fixed URLs with proper formatting
            'success_url': f"{site_url}/payment/success/",
            'fail_url': f"{site_url}/payment/fail/{payment_id}/",
            'cancel_url': f"{site_url}/payment/cancel/{payment_id}/",
            'ipn_url': f"{site_url}/payment/ipn/",
            'cus_name': cust_name[:50],  # Limit length to prevent issues
            'cus_email': cust_email,
            'cus_phone': cust_phone,
            'cus_add1': cus_add1[:100] if cus_add1 else 'Dhaka',  # Provide default and limit length
            'cus_city': cus_city or 'Dhaka',
            'cus_state': cus_state or 'Dhaka',
            'cus_postcode': cus_postcode or '1000',
            'cus_country': cus_country or 'Bangladesh',
            'shipping_method': 'NO',
            'product_name': 'TSC 2025 Registration',
            'product_category': 'Registration',
            'product_profile': 'general',
            # Add security parameters
            'value_a': str(payment_id),  # Pass payment ID for verification
            'value_b': hashlib.sha256(f"{tran_id}{payment_id}{amount}".encode()).hexdigest(),  # Security hash
        }

        try:
            logger.info(f"Initiating SSL Commerz session for transaction {tran_id}")
            logger.info(f"API URL: {self.api_url}")
            logger.info(f"Success URL: {post_data['success_url']}")
            
            response = requests.post(self.api_url, data=post_data, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            logger.info(f"SSL Commerz response status: {response_data.get('status')}")
            
            return response_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"SSLCommerz API Error: {e}")
            return {'status': 'FAILED', 'failedreason': str(e)}
        except ValueError as e:
            logger.error(f"SSLCommerz JSON Error: {e}")
            return {'status': 'FAILED', 'failedreason': 'Invalid response format'}

    def validate_ipn(self, post_data):
        """Validate IPN using SSL Commerz validation API"""
        store_id = self.store_id
        store_password = self.store_password

        # The IPN data from SSLCommerz
        tran_id = post_data.get('tran_id')
        val_id = post_data.get('val_id')
        
        if not val_id:
            return False, {'status': 'INVALID', 'failed_reason': 'Missing val_id'}

        # Prepare the validation request to SSLCommerz
        validation_params = {
            'val_id': val_id,
            'store_id': store_id,
            'store_passwd': store_password,
            'format': 'json'
        }

        try:
            logger.info(f"Validating IPN for transaction {tran_id}, val_id: {val_id}")
            response = requests.get(self.validation_url, params=validation_params, timeout=30)
            response.raise_for_status()
            validation_response = response.json()

            logger.info(f"Validation response: {validation_response.get('status')}")

            if validation_response.get('status') in ['VALID', 'VALIDATED']:
                return True, validation_response
            else:
                return False, validation_response

        except requests.exceptions.RequestException as e:
            logger.error(f"SSLCommerz Validation Error: {e}")
            return False, {'status': 'HTTP_ERROR', 'failed_reason': str(e)}
        except ValueError as e:
            logger.error(f"SSLCommerz Validation JSON Error: {e}")
            return False, {'status': 'JSON_ERROR', 'failed_reason': str(e)}