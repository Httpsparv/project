from flask import Flask, request, render_template, jsonify
import os
import logging
from datetime import datetime
import shutil
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import base64
from groq import Groq
import time
from functools import wraps

app = Flask(__name__)

# Configuration
class Config:
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    MONGODB_URI = 'mongodb://localhost:27017/'
    MONGODB_DB = 'aonix_test'
    MONGODB_COLLECTION = 'vehicle_licence_plate'
    RATE_LIMIT_SECONDS = 1
    GROQ_API_KEY = "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"
    CLEANUP_INTERVAL = 3600  # Cleanup temporary files every hour

# Setup logging with both file and console handlers
def setup_logging():
    logger = logging.getLogger('LicensePlateDetection')
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler('license_plate.log')
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

# Automatic cleanup of old files
def cleanup_old_files():
    try:
        if os.path.exists(Config.UPLOAD_FOLDER):
            shutil.rmtree(Config.UPLOAD_FOLDER)
            os.makedirs(Config.UPLOAD_FOLDER)
            logger.info("Cleaned up upload folder")
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")

# Initialize MongoDB
try:
    client = MongoClient(Config.MONGODB_URI)
    db = client[Config.MONGODB_DB]
    collection = db[Config.MONGODB_COLLECTION]
    client.admin.command('ping')
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed: {str(e)}")
    raise

# Initialize Groq client
groq_client = Groq(api_key=Config.GROQ_API_KEY)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def rate_limit(f):
    last_request_time = {}

    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_time = time.time()
        ip_address = request.remote_addr

        if ip_address in last_request_time:
            time_passed = current_time - last_request_time[ip_address]
            if time_passed < Config.RATE_LIMIT_SECONDS:
                return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429

        last_request_time[ip_address] = current_time
        return f(*args, **kwargs)

    return decorated_function

# Function to encode the image in Base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def save_plate_number_to_file(plate_number):
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"plate_numbers.txt"
        file_path = os.path.join('plate_records', filename)

        os.makedirs('plate_records', exist_ok=True)

        with open(file_path, 'a') as f:
            f.write(f"{timestamp}: {plate_number}\n")

        logger.info(f"Plate number saved to file: {plate_number}")
        return True
    except Exception as e:
        logger.error(f"Error saving to file: {str(e)}")
        return False

def save_to_mongodb(plate_number, image_path):
    try:
        document = {
            'plate_number': plate_number,
            'timestamp': datetime.utcnow(),
            'source_image': image_path
        }
        logger.info(f"Attempting to save to MongoDB: {document}")
        collection.insert_one(document)
        logger.info(f"Successfully saved to MongoDB: {plate_number}")

    except Exception as e:
        logger.error(f"MongoDB error: {str(e)}")
        raise

# New function to extract license plate using Groq API
def extract_license_plate(image_path):
    try:
        base64_image = encode_image(image_path)
        
        if not base64_image:
            logger.error("Failed to encode image")
            return None

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the license plate number from this vehicle image. Return only the plate number without any additional text."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            model="llama-3.2-11b-vision-preview",
        )

        detected_text = chat_completion.choices[0].message.content.strip()
        logger.info(f"Detected text from Groq: {detected_text}")
        
        if not detected_text:
            logger.warning("No text detected in the image")
            return None
            
        return detected_text

    except Exception as e:
        logger.error(f"Error in Groq API call: {str(e)}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@rate_limit
def upload():
    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No image selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400

        # Create a unique filename
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        image_path = os.path.join(Config.UPLOAD_FOLDER, unique_filename)
        
        # Ensure upload directory exists
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        file.save(image_path)

        try:
            # Process image
            detected_text = extract_license_plate(image_path)
            
            if not detected_text:
                raise ValueError("No license plate detected")

            # Save results
            save_plate_number_to_file(detected_text)
            save_to_mongodb(detected_text, image_path)

            # Cleanup
            if os.path.exists(image_path):
                os.remove(image_path)

            return jsonify({
                'success': True,
                'plate_number': detected_text
            })

        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large'}), 413

if __name__ == '__main__':
    # Create required directories
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs('plate_records', exist_ok=True)

    # Schedule cleanup
    cleanup_old_files()

    # Run the app
    app.run(host='0.0.0.0', port=5000, debug=False)
