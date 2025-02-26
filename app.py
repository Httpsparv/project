from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from functools import wraps
from pymongo import MongoClient
from datetime import datetime, timedelta
import json
from bson import json_util
import pandas as pd
import io

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key

# MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['aonix_test']

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

if __name__ == '__main__':
    app.run(debug=True) 