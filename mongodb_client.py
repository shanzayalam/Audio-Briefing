"""
MongoDB Client Configuration

Handles connection to AWS DocumentDB (MongoDB-compatible database)
for persistent storage of briefing data, articles, and metadata.
"""

import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from typing import Optional
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class MongoDBClient:
    """
    MongoDB client singleton for audio briefing system
    
    Connects to AWS DocumentDB with SSL support for production
    or local MongoDB for development.
    """
    
    _instance: Optional['MongoDBClient'] = None
    _client: Optional[MongoClient] = None
    _db = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MongoDBClient, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MongoDB connection"""
        if self._client is None:
            self._connect()
    
    def _connect(self):
        """Establish connection to MongoDB"""
        try:
            mongodb_uri = os.getenv('MONGODB_URI')
            
            if not mongodb_uri:
                logger.warning("MONGODB_URI not set, MongoDB features disabled")
                return
            
            # DocumentDB/MongoDB connection options
            connection_options = {
                'serverSelectionTimeoutMS': 5000,
                'connectTimeoutMS': 10000,
                'socketTimeoutMS': 10000,
            }
            
            # Add SSL for AWS DocumentDB (if ssl=true in URI)
            if 'ssl=true' in mongodb_uri.lower():
                # For AWS DocumentDB, SSL is handled via connection string
                # Certificate bundle path (if needed)
                ssl_ca_cert = os.getenv('MONGODB_SSL_CA_CERT')
                if ssl_ca_cert and os.path.exists(ssl_ca_cert):
                    connection_options['tlsCAFile'] = ssl_ca_cert
                    logger.info("Using SSL certificate for DocumentDB")
            
            logger.info("Connecting to MongoDB...")
            self._client = MongoClient(mongodb_uri, **connection_options)
            
            # Test connection
            self._client.admin.command('ping')
            
            # Get database name from URI or use default
            db_name = os.getenv('MONGODB_DATABASE', 'audio_briefing')
            self._db = self._client[db_name]
            
            logger.info(f"✅ Connected to MongoDB database: {db_name}")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            self._client = None
            self._db = None
        except Exception as e:
            logger.error(f"❌ MongoDB connection error: {e}")
            self._client = None
            self._db = None
    
    @property
    def client(self) -> Optional[MongoClient]:
        """Get MongoDB client instance"""
        return self._client
    
    @property
    def db(self):
        """Get database instance"""
        return self._db
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MongoDB"""
        if self._client is None:
            return False
        try:
            self._client.admin.command('ping')
            return True
        except:
            return False
    
    def close(self):
        """Close MongoDB connection"""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
            self._client = None
            self._db = None
    
    # Collection accessors
    @property
    def briefings(self):
        """Briefings collection"""
        return self._db.briefings if self._db is not None else None
    
    @property
    def articles(self):
        """Articles collection"""
        return self._db.articles if self._db is not None else None
    
    @property
    def users(self):
        """Users collection"""
        return self._db.users if self._db is not None else None
    
    @property
    def jobs(self):
        """Jobs collection (for job history)"""
        return self._db.jobs if self._db is not None else None


# Global MongoDB client instance
_mongo_client = None


def get_mongo_client() -> MongoDBClient:
    """
    Get MongoDB client singleton
    
    Returns:
        MongoDBClient: MongoDB client instance
    """
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoDBClient()
    return _mongo_client


def close_mongo_connection():
    """Close MongoDB connection"""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None


# Convenience functions
def save_briefing(briefing_data: dict) -> Optional[str]:
    """
    Save briefing to MongoDB
    
    Args:
        briefing_data: Briefing data dictionary
        
    Returns:
        str: Inserted document ID or None if failed
    """
    try:
        mongo = get_mongo_client()
        if not mongo.is_connected:
            logger.warning("MongoDB not connected, skipping save")
            return None
        
        # Use replace_one with upsert=True to ensure we update existing records 
        # for the same request_id instead of creating duplicates.
        # This guarantees that re-runs or updates to the same job replace the old data.
        request_id = briefing_data.get("request_id")
        if request_id:
            result = mongo.briefings.replace_one(
                {"request_id": request_id},
                briefing_data,
                upsert=True
            )
            
            # Return _id (either upserted or matched)
            doc_id = result.upserted_id or mongo.briefings.find_one({"request_id": request_id})["_id"]
            logger.info(f"Briefing saved/updated in MongoDB: {doc_id} (upsert={result.upserted_id is not None})")
            return str(doc_id)
        else:
            # Fallback for missing request_id (shouldn't happen)
            result = mongo.briefings.insert_one(briefing_data)
            logger.info(f"Briefing saved to MongoDB (new): {result.inserted_id}")
            return str(result.inserted_id)
            
    except Exception as e:
        logger.error(f"Failed to save briefing to MongoDB: {e}")
        return None


def get_briefing(briefing_id: str) -> Optional[dict]:
    """
    Get briefing from MongoDB
    
    Args:
        briefing_id: Briefing request ID
        
    Returns:
        dict: Briefing data or None if not found
    """
    try:
        mongo = get_mongo_client()
        if not mongo.is_connected:
            return None
        
        briefing = mongo.briefings.find_one({"request_id": briefing_id})
        return briefing
        
    except Exception as e:
        logger.error(f"Failed to get briefing from MongoDB: {e}")
        return None


def save_job_history(job_data: dict) -> Optional[str]:
    """
    Save job execution history to MongoDB
    
    Args:
        job_data: Job data dictionary
        
    Returns:
        str: Inserted document ID or None if failed
    """
    try:
        mongo = get_mongo_client()
        if not mongo.is_connected:
            return None
        
        result = mongo.jobs.insert_one(job_data)
        logger.info(f"Job history saved to MongoDB: {result.inserted_id}")
        return str(result.inserted_id)
        
    except Exception as e:
        logger.error(f"Failed to save job history to MongoDB: {e}")
        return None


if __name__ == "__main__":
    # Test connection
    mongo = get_mongo_client()
    if mongo.is_connected:
        print("✅ MongoDB connection successful")
        print(f"Database: {mongo.db.name}")
        print(f"Collections: {mongo.db.list_collection_names()}")
    else:
        print("❌ MongoDB connection failed")
