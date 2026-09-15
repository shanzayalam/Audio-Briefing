"""
Email Notification Service

Supports SMTP (Gmail, Outlook) for email notifications.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from logger_config import setup_logger, log_with_context

load_dotenv()


class EmailNotifier:
    """Send email notifications for briefing completion"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.smtp_from_email = os.getenv("SMTP_FROM_EMAIL", self.smtp_user)
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        
        # Determine which service to use
        if self.sendgrid_api_key:
            self.provider = "sendgrid"
        elif self.smtp_user and self.smtp_password:
            self.provider = "smtp"
        else:
            self.provider = None
    
    def send_notification(
        self,
        to_email: str,
        request_id: str,
        user_id: str,
        status: str,
        audio_filepath: Optional[str] = None,
        script_filepath: Optional[str] = None,
        duration: Optional[int] = None,
        error: Optional[str] = None
    ):
        """
        Send email notification about briefing completion
        
        Args:
            to_email: Recipient email address
            request_id: Unique request identifier
            user_id: User identifier
            status: Job status (complete/failed)
            audio_filepath: Path to generated audio file
            script_filepath: Path to script file
            duration: Audio duration in seconds
            error: Error message if failed
        """
        if not self.provider:
            raise ValueError(
                "Email service not configured. Set SMTP credentials or SENDGRID_API_KEY in .env file.\n"
                "For SMTP (Gmail): SMTP_USER, SMTP_PASSWORD, SMTP_HOST=smtp.gmail.com, SMTP_PORT=587\n"
                "For SendGrid: SENDGRID_API_KEY"
            )
        
        # Create email content
        subject = self._create_subject(status, user_id)
        html_body = self._create_html_body(
            request_id, user_id, status, audio_filepath, 
            script_filepath, duration, error
        )
        
        # Send via configured provider
        if self.provider == "sendgrid":
            self._send_via_sendgrid(to_email, subject, html_body)
        else:
            self._send_via_smtp(to_email, subject, html_body)
        
        log_with_context(
            self.logger, "info",
            f"Email notification sent to {to_email}",
            request_id=request_id,
            provider=self.provider
        )
    
    def _create_subject(self, status: str, user_id: str) -> str:
        """Create email subject line"""
        if status == "complete":
            return f"✅ Your Audio Briefing is Ready - {user_id}"
        else:
            return f"❌ Audio Briefing Failed - {user_id}"
    
    def _create_html_body(
        self,
        request_id: str,
        user_id: str,
        status: str,
        audio_filepath: Optional[str],
        script_filepath: Optional[str],
        duration: Optional[int],
        error: Optional[str]
    ) -> str:
        """Create HTML email body"""
        
        if status == "complete":
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "N/A"
            audio_name = Path(audio_filepath).name if audio_filepath else "N/A"
            script_name = Path(script_filepath).name if script_filepath else "N/A"
            
            return f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                              color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .info-box {{ background: white; padding: 15px; margin: 15px 0; border-radius: 5px; 
                                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .label {{ color: #667eea; font-weight: bold; }}
                    .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                    .success {{ color: #10b981; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎤 Audio Briefing Ready!</h1>
                        <p style="margin: 0; opacity: 0.9;">Your personalized news briefing has been generated</p>
                    </div>
                    <div class="content">
                        <p>Hi <strong>{user_id}</strong>,</p>
                        <p class="success"><strong>✅ Your audio briefing has been successfully generated!</strong></p>
                        
                        <div class="info-box">
                            <p><span class="label">Request ID:</span> {request_id}</p>
                            <p><span class="label">Audio Duration:</span> {duration_str}</p>
                            <p><span class="label">Audio File:</span> {audio_name}</p>
                            <p><span class="label">Script File:</span> {script_name}</p>
                        </div>
                        
                        <p>Your audio briefing files are ready in the output directory. You can now listen to your personalized news update!</p>
                        
                        <p style="margin-top: 20px;">
                            <strong>Next Steps:</strong><br>
                            • Check the output folder for your audio file<br>
                            • Review the script transcript if needed<br>
                            • Share your feedback with us
                        </p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message from Audio Briefing System</p>
                        <p>Powered by OpenAI, LangGraph, and Redis Queue</p>
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            return f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); 
                              color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .error-box {{ background: #fee2e2; padding: 15px; margin: 15px 0; border-radius: 5px; 
                                  border-left: 4px solid #ef4444; }}
                    .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>❌ Briefing Generation Failed</h1>
                        <p style="margin: 0; opacity: 0.9;">There was an issue generating your audio briefing</p>
                    </div>
                    <div class="content">
                        <p>Hi <strong>{user_id}</strong>,</p>
                        <p>Unfortunately, your audio briefing could not be generated.</p>
                        
                        <div class="error-box">
                            <p><strong>Request ID:</strong> {request_id}</p>
                            <p><strong>Error:</strong> {error or 'Unknown error occurred'}</p>
                        </div>
                        
                        <p>Please try again or contact support if the issue persists.</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message from Audio Briefing System</p>
                    </div>
                </div>
            </body>
            </html>
            """
    
    def _send_via_smtp(self, to_email: str, subject: str, html_body: str):
        """Send email via SMTP (Gmail, Outlook, etc.)"""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_from_email
        msg['To'] = to_email
        
        # Attach HTML body
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send email
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
    
    def _send_via_sendgrid(self, to_email: str, subject: str, html_body: str):
        """Send email via SendGrid API"""
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
        except ImportError:
            raise ImportError("SendGrid not installed. Run: pip install sendgrid")
        
        message = Mail(
            from_email=self.smtp_from_email or 'noreply@audiobriefing.com',
            to_emails=to_email,
            subject=subject,
            html_content=html_body
        )
        
        sg = SendGridAPIClient(self.sendgrid_api_key)
        response = sg.send(message)
        
        if response.status_code not in [200, 202]:
            raise Exception(f"SendGrid API error: {response.status_code}")
