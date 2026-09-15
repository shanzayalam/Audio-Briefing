"""
S3 Uploader - Handles file uploads to Amazon S3

Uploads audio briefings and transcripts to S3 for cloud storage.
"""

import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Enable/disable S3 uploads
S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"


def get_s3_client():
    """
    Create and return S3 client
    
    Returns:
        boto3.client: Configured S3 client
    
    Raises:
        NoCredentialsError: If AWS credentials not configured
    """
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise NoCredentialsError("AWS credentials not configured in environment")
    
    return boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )


def upload_file_to_s3(local_file_path: str, s3_key: str, 
                      content_type: str = "audio/mpeg",
                      public: bool = True) -> Optional[str]:
    """
    Upload a file to S3 bucket
    
    Args:
        local_file_path: Path to local file
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of file
        public: Make file publicly accessible
    
    Returns:
        S3 URL if successful, None if failed
    
    Example:
        url = upload_file_to_s3(
            "output/briefing_123.mp3",
            "briefings/user123/briefing_123.mp3"
        )
    """
    if not S3_ENABLED:
        print(f"S3 uploads disabled. File saved locally: {local_file_path}")
        return None
    
    if not S3_BUCKET_NAME:
        print("S3_BUCKET_NAME not configured. Skipping upload.")
        return None
    
    if not os.path.exists(local_file_path):
        print(f"File not found: {local_file_path}")
        return None
    
    try:
        s3_client = get_s3_client()
        
        # Prepare upload arguments
        extra_args = {'ContentType': content_type}
        # Note: ACL removed - bucket uses bucket policy for public access
        
        # Upload file
        s3_client.upload_file(
            local_file_path,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs=extra_args
        )
        
        # Generate public URL
        s3_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
        
        print(f"✓ Uploaded to S3: {s3_url}")
        print(f"DEBUG: S3 URL generated: {s3_url}")  # Added debug log
        return s3_url
        
    except NoCredentialsError:
        print("AWS credentials not found. Please configure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        return None
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"S3 upload failed [{error_code}]: {error_message}")
        print(f"DEBUG: S3 upload failed for key: {s3_key}")
        return None
    
    except Exception as e:
        print(f"Unexpected error during S3 upload: {e}")
        return None


def upload_briefing_package(user_id: str, job_id: str, 
                           audio_file: str, script_file: Optional[str] = None,
                           analysis_file: Optional[str] = None) -> dict:
    """
    Upload complete briefing package (audio + script + analysis) to S3
    
    Args:
        user_id: User identifier
        job_id: Job identifier
        audio_file: Path to audio file
        script_file: Path to script file (optional)
        analysis_file: Path to analysis file (optional)
    
    Returns:
        dict: URLs for uploaded files
        {
            "audio_url": "https://...",
            "script_url": "https://...",
            "analysis_url": "https://..."
        }
    """
    results = {
        "audio_url": None,
        "script_url": None,
        "analysis_url": None
    }
    
    # Upload audio file
    if audio_file and os.path.exists(audio_file):
        audio_extension = os.path.splitext(audio_file)[1]
        content_type = {
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.opus': 'audio/opus',
            '.wav': 'audio/wav'
        }.get(audio_extension, 'audio/mpeg')
        
        s3_key = f"briefings/{user_id}/{job_id}{audio_extension}"
        results["audio_url"] = upload_file_to_s3(audio_file, s3_key, content_type)
    
    # Upload script file
    if script_file and os.path.exists(script_file):
        s3_key = f"briefings/{user_id}/{job_id}_script.txt"
        results["script_url"] = upload_file_to_s3(script_file, s3_key, "text/plain")
    
    # Upload analysis file
    if analysis_file and os.path.exists(analysis_file):
        s3_key = f"briefings/{user_id}/{job_id}_analysis.json"
        results["analysis_url"] = upload_file_to_s3(analysis_file, s3_key, "application/json")
    
    return results


def delete_file_from_s3(s3_key: str) -> bool:
    """
    Delete a file from S3 bucket
    
    Args:
        s3_key: S3 object key to delete
    
    Returns:
        True if successful, False otherwise
    """
    if not S3_ENABLED or not S3_BUCKET_NAME:
        return False
    
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        print(f"✓ Deleted from S3: {s3_key}")
        return True
    
    except Exception as e:
        print(f"Failed to delete from S3: {e}")
        return False


def check_s3_connection() -> bool:
    """
    Test S3 connection and bucket access
    
    Returns:
        True if connection successful, False otherwise
    """
    if not S3_ENABLED:
        print("S3 uploads are disabled (S3_ENABLED=false)")
        return False
    
    if not S3_BUCKET_NAME:
        print("S3_BUCKET_NAME not configured")
        return False
    
    try:
        s3_client = get_s3_client()
        s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
        print(f"✓ S3 connection successful. Bucket: {S3_BUCKET_NAME}")
        return True
    
    except NoCredentialsError:
        print("✗ AWS credentials not configured")
        return False
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"✗ Bucket '{S3_BUCKET_NAME}' does not exist")
        elif error_code == '403':
            print(f"✗ Access denied to bucket '{S3_BUCKET_NAME}'")
        else:
            print(f"✗ S3 error: {e}")
        return False


if __name__ == "__main__":
    print("Testing S3 Uploader Configuration...\n")
    
    print(f"S3_ENABLED: {S3_ENABLED}")
    print(f"S3_BUCKET_NAME: {S3_BUCKET_NAME or 'Not configured'}")
    print(f"AWS_REGION: {AWS_REGION}")
    print(f"AWS credentials: {'Configured' if AWS_ACCESS_KEY_ID else 'Not configured'}\n")
    
    if S3_ENABLED:
        check_s3_connection()
    else:
        print("Enable S3 by setting S3_ENABLED=true in .env")
