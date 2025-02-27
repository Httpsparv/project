from typing import List, Dict  # Add this line to import Dict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import time

class ViolationEmailSender:
    def __init__(self, smtp_server: str, smtp_port: int, sender_email: str, sender_password: str):
        """
        Initialize the email sender with SMTP settings
        
        Args:
            smtp_server: SMTP server address (e.g., 'smtp.gmail.com')
            smtp_port: SMTP port (e.g., 587 for TLS)
            sender_email: Email address to send from
            sender_password: Password or app-specific password for the email account
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Set up logging configuration"""
        logger = logging.getLogger('ViolationEmailSender')
        logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler('email_sender.log')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        
        return logger

    def _create_email_message(self, violation_data: Dict) -> str:
        """
        Create email content from template and violation data
        """
        template = """Dear {owner_name},

This is to inform you that your vehicle with license plate {license_plate} was recorded exceeding 
the speed limit of {speed_limit} km/h on {violation_date} at {violation_time}.

Recorded Speed: {recorded_speed} km/h
Location: {location}

Please ensure compliance with speed limits for everyone's safety.

Best regards,
Speed Monitoring System"""

        return template.format(**violation_data)

    def send_bulk_violations(self, violations: List[Dict]) -> Dict[str, List]:
        successful = []
        failed = []
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)

            for violation in violations:
                try:
                    if not all(key in violation for key in ['owner_email', 'owner_name', 'license_plate', 'speed_limit', 'recorded_speed', 'violation_date', 'violation_time', 'location']):
                        self.logger.error(f"Missing required data in violation: {violation}")
                        continue

                    msg = MIMEMultipart()
                    msg['From'] = self.sender_email
                    msg['To'] = violation['owner_email']
                    msg['Subject'] = f"Speed Violation Notice - {violation['license_plate']}"

                    email_body = self._create_email_message(violation)
                    msg.attach(MIMEText(email_body, 'plain'))

                    server.send_message(msg)
                    
                    successful.append(violation['owner_email'])
                    self.logger.info(f"Successfully sent email to {violation['owner_email']}")

                except Exception as e:
                    failed.append(violation['owner_email'])
                    self.logger.error(f"Failed to send email to {violation['owner_email']}: {str(e)}")

            server.quit()

        except smtplib.SMTPException as e:
            self.logger.error(f"SMTP error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {str(e)}")
        finally:
            server.quit()

        return {'successful': successful, 'failed': failed}

# Example usage:
if __name__ == "__main__":
    email_sender = ViolationEmailSender(
        smtp_server='smtp.gmail.com',
        smtp_port=587,
        sender_email='shuklamayank015@gmail.com',
        sender_password='wtro mydp ojlv pibm'  # Use app-specific password
    )

    violations = [
        {
            'owner_email': 'violator1@example.com',
            'owner_name': 'John Doe',
            'license_plate': 'ABC123',
            'speed_limit': 60,
            'recorded_speed': 75,
            'violation_date': '2024-02-27',
            'violation_time': '14:30',
            'location': 'Main Street'
        },
        {
            'owner_email': 'violator2@example.com',
            'owner_name': 'Jane Smith',
            'license_plate': 'XYZ789',
            'speed_limit': 60,
            'recorded_speed': 80,
            'violation_date': '2024-02-27',
            'violation_time': '15:45',
            'location': 'Highway 101'
        }
    ]

    result = email_sender.send_bulk_violations(violations)
    print(f"Successfully sent: {len(result['successful'])} emails")
    print(f"Failed to send: {len(result['failed'])} emails")
