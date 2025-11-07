# README.md
# SJIS Math Club Registration System

A comprehensive Django web application for managing student registrations for the SJIS Math Club 2025. Features include online registration, SSL Commerz payment integration, automated email confirmations, and a powerful admin dashboard.

## Features

### Student Features
- **Online Registration**: Easy-to-use registration form with real-time validation
- **Event Selection**: Multiple event selection with automatic fee calculation
- **Secure Payments**: SSL Commerz integration supporting bKash, Rocket, Nagad, and cards
- **Automatic Grouping**: Students automatically grouped by grade (Grade 3-5: Group A, 6-8: Group B, 9-10: Group C, 11-12: Group D)
- **Email Confirmations**: Automated registration confirmation emails with receipts
- **Mobile Responsive**: Works seamlessly on all devices

### Admin Features
- **Comprehensive Dashboard**: Real-time statistics and analytics
- **Student Management**: View, search, filter, and manage all registrations
- **Payment Tracking**: Monitor all payment transactions and statuses
- **Event Management**: Create and manage competition events
- **Report Generation**: Detailed reports on registrations, payments, and events
- **Activity Logging**: Complete audit trail of all admin actions
- **Email Management**: Send confirmation emails and manage communications

### Technical Features
- **Django + HTMX**: Modern, dynamic frontend without JavaScript complexity
- **SSL Commerz Integration**: Secure payment processing
- **Responsive Design**: Built with Tailwind CSS
- **Database Optimization**: Efficient queries with proper indexing
- **Security**: CSRF protection, SQL injection prevention, secure payment handling
- **Scalable Architecture**: Well-structured code for easy maintenance and expansion

## Installation & Setup

### Prerequisites
- Python 3.8 or higher
- PostgreSQL (optional, SQLite included for development)
- Git

### Step-by-Step Installation

1. **Clone the Repository**
```bash
git clone <repository-url>
cd sjis_math_club
```

2. **Create Virtual Environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Environment Configuration**
```bash
cp .env.example .env
# Edit .env file with your configuration
```

5. **Database Setup**
```bash
python manage.py makemigrations
python manage.py migrate
```

6. **Create Superuser**
```bash
python manage.py create_superuser --username admin --email admin@example.com --password admin123
```

7. **Set Up Events**
```bash
python manage.py setup_events
```

8. **Generate Test Data (Optional)**
```bash
python manage.py generate_test_data --students 50
```

9. **Run Development Server**
```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000` to access the application.

## SSL Commerz Configuration

1. **Get SSL Commerz Credentials**
   - Visit [SSL Commerz](https://www.sslcommerz.com/)
   - Create a merchant account
   - Get your Store ID and Store Password

2. **Update Environment Variables**
```bash
SSLCOMMERZ_STORE_ID=your_store_id
SSLCOMMERZ_STORE_PASSWORD=your_store_password
SSLCOMMERZ_IS_SANDBOX=True  # Set to False for production
```

3. **Configure Webhooks**
   - Set success URL: `https://yourdomain.com/payment/success/{student_id}/`
   - Set fail URL: `https://yourdomain.com/payment/fail/{student_id}/`
   - Set cancel URL: `https://yourdomain.com/payment/cancel/{student_id}/`
   - Set IPN URL: `https://yourdomain.com/payment/ipn/`

## Email Configuration

1. **Gmail Setup**
```bash
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password  # Use App Password, not regular password
```

2. **Get Gmail App Password**
   - Enable 2-factor authentication on Gmail
   - Generate an App Password
   - Use the App Password in EMAIL_HOST_PASSWORD

## Project Structure

sjis_math_club/
├── sjis_math_club/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── registration/
│   ├── models.py          # Database models
│   ├── views.py           # Public views
│   ├── admin_views.py     # Admin dashboard views
│   ├── forms.py           # Django forms
│   ├── admin.py           # Django admin configuration
│   ├── urls.py            # URL routing
│   ├── utils.py           # Utility functions
│   └── management/
│       └── commands/      # Custom Django commands
├── templates/
│   ├── base.html          # Base template
│   ├── registration/      # Registration templates
│   └── admin/            # Admin dashboard templates
├── static/               # Static files (CSS, JS, images)
├── requirements.txt      # Python dependencies
├── .env                 # Environment variables
└── README.md           # Project documentation
```

## Management Commands

The application includes several useful management commands:

### Setup Events
```bash
python manage.py setup_events
```
Creates default events for the carnival.

### Generate Test Data
```bash
python manage.py generate_test_data --students 100
```
Generates test student registrations for development.

### Send Pending Emails
```bash
python manage.py send_pending_emails
```
Sends confirmation emails to students who have paid but haven't received emails.

### Cleanup Incomplete Registrations
```bash
python manage.py cleanup_incomplete_registrations --hours 24
```
Removes incomplete registrations older than specified hours.

### Create Superuser
```bash
python manage.py create_superuser --username admin --email admin@example.com
```
Creates an admin user for the application.

## API Endpoints

### Public Endpoints
- `/` - Home page
- `/register/` - Registration form
- `/get-group/` - HTMX endpoint for group selection
- `/calculate-total/` - HTMX endpoint for fee calculation
- `/payment/{student_id}/` - Payment gateway
- `/payment/success/{student_id}/` - Payment success handler
- `/payment/fail/{student_id}/` - Payment failure handler
- `/payment/cancel/{student_id}/` - Payment cancellation handler
- `/payment/ipn/` - SSL Commerz IPN handler

### Admin Endpoints
- `/dashboard/` - Admin dashboard
- `/dashboard/students/` - Student management
- `/dashboard/payments/` - Payment management
- `/dashboard/events/` - Event management
- `/dashboard/reports/` - Reports and analytics
- `/dashboard/logs/` - Admin activity logs

## Database Schema

### Key Models
- **Student**: Stores student information and registration details
- **Event**: Manages competition events
- **Payment**: Tracks payment transactions
- **Receipt**: Manages receipt generation and email sending
- **AdminLog**: Logs all admin activities for audit trail
- **StudentEventRegistration**: Many-to-many relationship between students and events

## Security Features

- **CSRF Protection**: All forms protected against cross-site request forgery
- **SQL Injection Prevention**: Using Django ORM prevents SQL injection
- **Payment Security**: SSL Commerz integration with proper validation
- **Admin Activity Logging**: Complete audit trail of all admin actions
- **Input Validation**: Comprehensive form validation and sanitization
- **Secure Headers**: Security headers configured for production

## Deployment

### Production Checklist

1. **Environment Variables**
```bash
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
SECRET_KEY=generate-a-new-secret-key
```

2. **Database**
   - Set up PostgreSQL database
   - Update database configuration in settings

3. **Static Files**
```bash
python manage.py collectstatic
```

4. **SSL Certificate**
   - Configure HTTPS
   - Update SSL Commerz URLs

5. **Server Configuration**
   - Configure Gunicorn
   - Set up Nginx reverse proxy
   - Configure firewall

### Sample Deployment Commands
```bash
# Install production dependencies
pip install -r requirements.txt

# Migrate database
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Run with Gunicorn
gunicorn sjis_math_club.wsgi:application --bind 0.0.0.0:8000
```

## Troubleshooting

### Common Issues

1. **Payment Gateway Issues**
   - Verify SSL Commerz credentials
   - Check webhook URLs
   - Ensure proper network connectivity

2. **Email Not Sending**
   - Verify email configuration
   - Check Gmail App Password
   - Confirm firewall settings

3. **Database Connection Issues**
   - Check database credentials
   - Ensure database server is running
   - Verify network connectivity

4. **Static Files Not Loading**
   - Run `python manage.py collectstatic`
   - Check STATIC_URL and STATIC_ROOT settings
   - Verify web server configuration

## Support

For technical support or questions about the application:
- Create an issue in the repository
- Contact the development team
- Check the documentation

## License

This project is licensed under the MIT License. See LICENSE file for details.

# Development Notes

## Code Organization
- Models are organized by functionality
- Views are separated into public and admin
- Templates follow Django best practices
- Static files are organized by component

## Database Design
- Proper foreign key relationships
- Indexes on frequently queried fields
- Automatic timestamping
- Data integrity constraints

## Security Considerations
- All user inputs validated
- CSRF protection enabled
- SQL injection prevention
- Secure payment handling
- Activity logging for audit

## Performance Optimization
- Database query optimization
- Proper use of select_related and prefetch_related
- Efficient pagination
- Static file optimization

## Extensibility
- Modular design for easy feature addition
- Well-documented code
- Configurable settings
- Plugin-friendly architecture

This application is designed to be production-ready while maintaining simplicity and ease of use. The codebase is well-structured to allow for easy maintenance and future enhancements.

# docker-compose.yml (Optional)
version: '3.8'

services:
  db:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data/
    environment:
      POSTGRES_DB: sjis_math_club
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/code
    ports:
      - "8000:8000"
    depends_on:
      - db
    environment:
      - DB_HOST=db
      - DB_NAME=sjis_math_club
      - DB_USER=postgres
      - DB_PASSWORD=postgres

volumes:
  postgres_data:

# Dockerfile (Optional)
FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]# sjis_math_club
