import subprocess
import os
import sys
import signal
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from functools import wraps
from pymongo import MongoClient
from datetime import datetime, timedelta
import json
from bson import json_util
import pandas as pd
import io
from utils.email_sender import ViolationEmailSender

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key

# MongoDB connection
import os
from pymongo import MongoClient

# Replace with your actual MongoDB URI
mongo_uri = 'mongodb+srv://parvebrahmbhatt1008:<8005723987>@cluster0.qxxrq.mongodb.net/'
client = MongoClient(mongo_uri)
db = client['aonix_test']  # Replace with your database name

# Global variable to store the speed.py subprocess
speed_process = None

# Initialize email sender with your SMTP settings
email_sender = ViolationEmailSender(
    smtp_server='smtp.gmail.com',
        smtp_port=587,
        sender_email='shuklamayank015@gmail.com',
        sender_password='wtro mydp ojlv pibm' 
)

# Function to start speed.py
def start_speed_script():
    global speed_process
    # Get the directory where app.py is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Construct the path to speed.py
    speed_script_path = os.path.join(script_dir, 'speed.py')
    
    # Check if speed.py exists
    if not os.path.exists(speed_script_path):
        print(f"Error: {speed_script_path} does not exist.")
        sys.exit(1)
    
    # Start speed.py as a separate process
    try:
        speed_process = subprocess.Popen([sys.executable, speed_script_path])
        print("speed.py started successfully.")
    except Exception as e:
        print(f"Failed to start speed.py: {e}")
        sys.exit(1)

# Function to handle graceful shutdown
def handle_exit(signum, frame):
    global speed_process
    if speed_process:
        speed_process.terminate()
        speed_process.wait()
        print("speed.py terminated.")
    sys.exit(0)

# Register the signal handler for graceful shutdown
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Start speed.py before running the Flask app
start_speed_script()

# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            # Convert password to integer since it's stored as int32 in MongoDB
            password = int(request.form.get('password'))
        except (ValueError, TypeError):
            flash('Invalid password format', 'error')
            return render_template('login.html')
        
        # Find user in MongoDB
        user = db.users.find_one({
            'email': email,
            'password': password  # Password is now int32
        })
        
        if user:
            # Store user info in session
            session['user'] = {
                'email': user['email'],
                'fullname': user['fullname']
            }
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # Fetch real-time violations from MongoDB
    violations = list(db.voilations.find())
    
    # Calculate monthly violations
    current_month = datetime.now().month
    monthly_violations = db.violation_record.count_documents({
        'Violation Date': {
            '$gte': datetime(datetime.now().year, current_month, 1),
            '$lt': datetime(datetime.now().year, current_month + 1, 1)
        }
    })
    
    # Calculate zone-wise violations (assuming you have a zone field)
    zone_violations = db.violation_record.count_documents({'Zone': {'$exists': True}})
    
    # Calculate speed violations
    speed_violations = db.violation_record.count_documents({'Violation Type': 'Speed'})
    
    # Fetch recent violation records
    recent_violations = list(db.violation_record.find().sort('Violation Date', -1).limit(10))
    
    return render_template('dashboard.html', 
                         violations=violations,
                         recent_violations=recent_violations,
                         monthly_violations=monthly_violations,
                         zone_violations=zone_violations,
                         speed_violations=speed_violations)

@app.route('/management')
@login_required
def management():
    # Fetch vehicle information
    vehicles = list(db.vehicle_info.find())
    
    # Fetch violation records
    violation_records = list(db.violation_record.find())
    
    # Group vehicles by owner
    owners = {}
    for vehicle in vehicles:
        owner_name = vehicle['Owner\'s Name']
        if owner_name not in owners:
            owners[owner_name] = {
                'contact': vehicle['Owner\'s Contact'],
                'vehicles': []
            }
        owners[owner_name]['vehicles'].append(vehicle['License Plate'])
    
    return render_template('management.html',
                         vehicles=vehicles,
                         violation_records=violation_records,
                         owners=owners)

@app.route('/add_vehicle', methods=['POST'])
@login_required
def add_vehicle():
    if request.method == 'POST':
        new_vehicle = {
            'License Plate': request.form.get('vehicle-plate'),
            'Vehicle Make': request.form.get('vehicle-make'),
            'Vehicle Model': request.form.get('vehicle-model'),
            'Owner\'s Name': request.form.get('owner-name'),
            'Owner\'s Contact': request.form.get('owner-contact')
        }
        
        db.vehicle_info.insert_one(new_vehicle)
        flash('Vehicle added successfully!', 'success')
        return redirect(url_for('management'))

@app.route('/setting')
@login_required
def setting():
    return render_template('setting.html')

@app.route('/logout')
def logout():
    session.clear()  # Clear all session data
    return redirect(url_for('login'))

# API endpoints for AJAX requests
@app.route('/api/search_vehicles')
@login_required
def search_vehicles():
    search_term = request.args.get('term', '')
    vehicles = list(db.vehicle_info.find({
        'License Plate': {'$regex': search_term, '$options': 'i'}
    }))
    # Convert ObjectId to string for JSON serialization
    for vehicle in vehicles:
        vehicle['_id'] = str(vehicle['_id'])
    return jsonify(vehicles)

@app.route('/api/search_violations')
@login_required
def search_violations():
    license_plate = request.args.get('license_plate', '')
    violations = list(db.violation_record.find({
        'License Plate': license_plate
    }))
    # Convert ObjectId to string for JSON serialization
    for violation in violations:
        violation['_id'] = str(violation['_id'])
    return jsonify(violations)

@app.route('/api/monthly_violations_data')
@login_required
def monthly_violations_data():
    # Get the current month's start and end dates
    today = datetime.now()
    start_date = datetime(today.year, today.month, 1)
    if today.month == 12:
        end_date = datetime(today.year + 1, 1, 1)
    else:
        end_date = datetime(today.year, today.month + 1, 1)
    
    # Get all violations for the current month
    violations = list(db.violation_record.find({
        'Violation Date': {
            '$gte': start_date,
            '$lt': end_date
        }
    }).sort('Violation Date', 1))
    
    # Group violations by date
    dates = []
    counts = []
    current_date = start_date
    
    while current_date < end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        count = len([v for v in violations if v['Violation Date'].date() == current_date.date()])
        
        dates.append(date_str)
        counts.append(count)
        
        current_date += timedelta(days=1)
    
    return jsonify({
        'dates': dates,
        'counts': counts
    })

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if 'csv-file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('management'))
    
    file = request.files['csv-file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('management'))
    
    if file and file.filename.endswith('.csv'):
        try:
            df = pd.read_csv(file)
            # Validate the CSV structure
            required_columns = ['License Plate', 'Vehicle Make', 'Vehicle Model', 
                             'Owner\'s Name', 'Owner\'s Contact']
            
            if not all(col in df.columns for col in required_columns):
                flash('Invalid CSV format. Please use the template.', 'error')
                return redirect(url_for('management'))
            
            # Process and insert the data
            for _, row in df.iterrows():
                vehicle_data = {
                    'License Plate': row['License Plate'],
                    'Vehicle Make': row['Vehicle Make'],
                    'Vehicle Model': row['Vehicle Model'],
                    'Owner\'s Name': row['Owner\'s Name'],
                    'Owner\'s Contact': str(row['Owner\'s Contact'])
                }
                db.vehicle_info.insert_one(vehicle_data)
            
            flash(f'Successfully imported {len(df)} vehicles', 'success')
        except Exception as e:
            flash(f'Error processing CSV: {str(e)}', 'error')
    else:
        flash('Invalid file format. Please upload a CSV file.', 'error')
    
    return redirect(url_for('management'))

@app.route('/download_template')
@login_required
def download_template():
    # Create template CSV
    template_data = {
        'License Plate': ['MH-01-AB-1234'],
        'Vehicle Make': ['Maruti'],
        'Vehicle Model': ['Swift'],
        'Owner\'s Name': ['John Doe'],
        'Owner\'s Contact': ['9876543210']
    }
    df = pd.DataFrame(template_data)
    
    # Create buffer
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    
    return send_file(
        io.BytesIO(buffer.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='vehicle_registration_template.csv'
    )

@app.route('/api/send_violation_emails', methods=['POST'])
@login_required
def send_violation_emails():
    try:
        violations = request.json.get('violations', [])
        
        if not violations:
            return jsonify({'success': False, 'message': 'No violations provided'})

        # Send bulk emails
        result = email_sender.send_bulk_violations(violations)

        return jsonify({
            'success': True,
            'successful_count': len(result['successful']),
            'failed_count': len(result['failed']),
            'failed_emails': result['failed']
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

def test_system_components():
    """
    Test all major components of the system
    """
    try:
        print("\n=== Testing System Components ===")
        
        # 1. Test MongoDB Connection
        print("\nTesting MongoDB connection...")
        try:
            db.command('ping')
            print("✓ MongoDB connection successful")
        except Exception as e:
            print(f"✗ MongoDB connection failed: {str(e)}")
            return False

        # 2. Test Email Configuration
        print("\nTesting email configuration...")
        if not app.config.get('SMTP_EMAIL') or not app.config.get('SMTP_PASSWORD'):
            print("✗ Email configuration missing. Please set SMTP_EMAIL and SMTP_PASSWORD in app.config")
            return False
        print("✓ Email configuration present")

        # 3. Test Speed Script
        print("\nTesting speed.py script...")
        speed_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'speed.py')
        if not os.path.exists(speed_script_path):
            print(f"✗ speed.py not found at {speed_script_path}")
            return False
        print("✓ speed.py script found")

        # 4. Test Email Sender
        print("\nTesting email sender initialization...")
        try:
            test_email = ViolationEmailSender(
                smtp_server='smtp.gmail.com',
                smtp_port=587,
                sender_email=app.config['SMTP_EMAIL'],
                sender_password=app.config['SMTP_PASSWORD']
            )
            print("✓ Email sender initialized successfully")
        except Exception as e:
            print(f"✗ Email sender initialization failed: {str(e)}")
            return False

        # 5. Test Required Collections
        print("\nChecking required MongoDB collections...")
        required_collections = ['users', 'vehicle_info', 'violation_record', 'voilations']
        existing_collections = db.list_collection_names()
        for collection in required_collections:
            if collection in existing_collections:
                print(f"✓ Collection '{collection}' exists")
            else:
                print(f"✗ Collection '{collection}' missing")
                return False

        print("\n=== All Components Checked Successfully ===\n")
        return True

    except Exception as e:
        print(f"\n✗ System check failed with error: {str(e)}")
        return False

if __name__ == '__main__':
    # Add these configuration lines before running the app
    app.config['SMTP_EMAIL'] = 'your-email@gmail.com'  # Replace with your email
    app.config['SMTP_PASSWORD'] = 'your-app-specific-password'  # Replace with your password
    
    # Run system check
    if test_system_components():
        print("Starting Flask application...")
        start_speed_script()  # Start speed.py
        app.run(port=50002)
    else:
        print("System check failed. Please fix the issues before starting the application.")
        sys.exit(1)
