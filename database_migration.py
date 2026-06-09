"""
Prism - MongoDB Atlas Data Layer Migration Architecture
Selected Partner Track: MongoDB
"""
import os
from pymongo import MongoClient

# MongoDB Atlas Connection String (Configured via Environment Variables for Security)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://<username>:<password>@prism-cluster.mongodb.net/?retryWrites=true&w=majority")

def get_mongodb_client():
    """
    Initializes a secure connection to the MongoDB Atlas cluster.
    Powers the flexible document storage required for deep telemetry tracks.
    """
    try:
        client = MongoClient(MONGO_URI)
        # Test connection
        client.admin.command('ping')
        print("Successfully connected to MongoDB Atlas!")
        return client
    except Exception as e:
        print(f"MongoDB Atlas connection failed: {e}")
        return None

def save_user_telemetry_document(user_token: str, telemetry_data: dict):
    """
    Serializes unstable, deeply nested health metrics and multi-turn chat records
    directly into a flexible MongoDB Collection without rigid schema locks.
    """
    client = get_mongodb_client()
    if not client:
        return False
        
    db = client["prism_performance_db"]
    collection = db["user_telemetry"]
    
    # Upsert metric data dynamically mapping to the user token
    result = collection.update_one(
        {"user_token": user_token},
        {"$set": telemetry_data},
        upsert=True
    )
    return result.acknowledged