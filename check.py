from django.core.management.base import BaseCommand
import base64
from pymongo import MongoClient
from groq import Groq

class Command(BaseCommand):  # ✅ Make sure class is named 'Command'
    help = "Checks vehicle speed and saves violations to MongoDB"

    def handle(self, *args, **kwargs):
        # Function to encode the image in Base64
        def encode_image(image_path):
            try:
                with open(image_path, "rb") as image_file:
                    return base64.b64encode(image_file.read()).decode('utf-8')
            except FileNotFoundError:
                self.stdout.write(self.style.ERROR("Error: Image file not found. Please enter a valid path."))
                return None

        # Function to connect to MongoDB and insert data
        def save_to_mongodb(speed, license_plate):
            client = MongoClient("mongodb://localhost:27017/")
            db = client["TrafficDB"]
            collection = db["Violations"]
            record = {"speed": speed, "license_plate": license_plate}
            collection.insert_one(record)
            self.stdout.write(self.style.SUCCESS("Record saved to MongoDB."))

        # Get user inputs
        speed = int(input("Enter speed in km/h: "))
        image_path = input("Enter the path of the image: ")

        # Encode image
        base64_image = encode_image(image_path)
        if not base64_image:
            return

        # Initialize Groq client with API key
        client = Groq(api_key="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")

        # Make the API call to Groq
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the license plate number from this image and show only license plate no. extracted."},
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

        # Get the extracted license plate number
        license_plate = chat_completion.choices[0].message.content.strip()
        self.stdout.write(f"Speed: {speed} km/h | License Plate: {license_plate}")

        # Save to MongoDB if speed > 80 km/h
        if speed > 80:
            save_to_mongodb(speed, license_plate)
        else:
            self.stdout.write(self.style.WARNING("Speed is within the limit. No violation recorded."))