import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()
# Add this after load_dotenv() in your app.py

# Initialize Flask app
app = Flask(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tiudyykyzjejykhtuiof.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRpdWR5eWt5emplanlraHR1aW9mIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM4MTE4MDQsImV4cCI6MjA1OTM4NzgwNH0.r-DZfGzrYRIuFtGtIdt-hZAyavcgTck_w7yv8uITYng")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Google Gemini API
api_key = os.getenv("GEMINI_API_KEY", "AIzaSyAn16yV68eU1CEZpZ35YW4FhnikMnEIJWI")
genai.configure(api_key=api_key)

# Initialize Gemini model
model = genai.GenerativeModel('gemini-2.0-flash')

def create_system_prompt():
    """Create the system prompt for the therapy chatbot"""
    return """You are a supportive mental health chatbot designed to provide emotional support, 
    coping strategies, and general guidance. You are NOT a licensed therapist or medical professional.
    
    Guidelines to follow:
    1. Use a warm, empathetic tone and practice active listening
    2. Ask open-ended questions to help users explore their feelings
    3. Offer evidence-based coping strategies when appropriate
    4. NEVER diagnose conditions or suggest treatments/medications
    5. If a user expresses thoughts of self-harm or harm to others, provide crisis resources
    6. Respect privacy and maintain a non-judgmental approach
    7. Encourage professional help when appropriate
    
    Crisis resources to share when needed:
    - National Suicide Prevention Lifeline: 988 or 1-800-273-8255
    - Crisis Text Line: Text HOME to 741741
    """

def check_for_crisis(message):
    """
    Check if the message contains crisis indicators
    Returns True if crisis indicators detected
    """
    crisis_keywords = [
        "suicide", "kill myself", "want to die", "end my life", 
        "harm myself", "self-harm", "cutting myself", "hurt myself"
    ]
    
    return any(keyword in message.lower() for keyword in crisis_keywords)

def get_crisis_response():
    """Return a crisis response with resources"""
    return """I notice you mentioned something concerning. If you're having thoughts of harming yourself, 
    please reach out for immediate help:
    
    - National Suicide Prevention Lifeline: 988 or 1-800-273-8255 (available 24/7)
    - Crisis Text Line: Text HOME to 741741 (available 24/7)
    - Or go to your nearest emergency room
    
    These trained professionals can provide the support you need right now. Your life matters."""

def ensure_user_exists(user_id):
    """Ensure the user exists in the database, create if not"""
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    
    if not result.data:
        # User doesn't exist, create a new user
        supabase.table("users").insert({"user_id": user_id}).execute()
        
        # Create a new conversation for this user
        supabase.table("conversations").insert({
            "user_id": user_id,
            "active": True
        }).execute()

def get_active_conversation(user_id):
    """Get the active conversation for a user, or create one if none exists"""
    result = supabase.table("conversations").select("*").eq("user_id", user_id).eq("active", True).execute()
    
    if result.data:
        return result.data[0]["conversation_id"]
    else:
        # Create a new conversation for this user
        result = supabase.table("conversations").insert({
            "user_id": user_id,
            "active": True
        }).execute()
        return result.data[0]["conversation_id"]

def get_conversation_history(user_id, limit=5):
    """Get recent conversation history from the database"""
    conversation_id = get_active_conversation(user_id)
    
    result = supabase.table("conversation_messages")\
        .select("message_id,sequence_num")\
        .eq("conversation_id", conversation_id)\
        .order("sequence_num", desc=True)\
        .limit(limit*2)\
        .execute()
    
    if not result.data:
        return []
    
    message_ids = [entry["message_id"] for entry in result.data]
    
    messages_result = supabase.table("messages")\
        .select("*")\
        .in_("message_id", message_ids)\
        .order("timestamp")\
        .execute()
    
    return messages_result.data

def store_message(user_id, content, is_bot):
    """Store a message in the database and link it to the conversation"""
    # First, ensure the user exists
    ensure_user_exists(user_id)
    
    # Get the active conversation
    conversation_id = get_active_conversation(user_id)
    
    # Insert the message
    message_result = supabase.table("messages").insert({
        "user_id": user_id,
        "is_bot": is_bot,
        "content": content
    }).execute()
    
    message_id = message_result.data[0]["message_id"]
    
    # Get the next sequence number
    seq_result = supabase.table("conversation_messages")\
        .select("sequence_num")\
        .eq("conversation_id", conversation_id)\
        .order("sequence_num", desc=True)\
        .limit(1)\
        .execute()
    
    next_seq = 1
    if seq_result.data:
        next_seq = seq_result.data[0]["sequence_num"] + 1
    
    # Link message to conversation
    supabase.table("conversation_messages").insert({
        "conversation_id": conversation_id,
        "message_id": message_id,
        "sequence_num": next_seq
    }).execute()
    
    # If crisis is detected, log it
    if is_bot == False and check_for_crisis(content):
        supabase.table("crisis_events").insert({
            "user_id": user_id,
            "message_id": message_id,
            "resources_provided": "Standard crisis resources provided"
        }).execute()
    
    return message_id

def generate_response(user_id, message):
    """Generate a response using the Gemini API with conversation history from database"""
    
    # Check for crisis indicators first
    if check_for_crisis(message):
        crisis_response = get_crisis_response()
        store_message(user_id, message, False)  # Store user message
        store_message(user_id, crisis_response, True)  # Store bot response
        return crisis_response
    
    # Store the user message
    store_message(user_id, message, False)
    
    # Get conversation history from database
    conversation_history = get_conversation_history(user_id)
    
    # Create a prompt that includes system instructions and recent context
    system_instructions = create_system_prompt()
    
    # Build a context string with recent conversation history
    context = ""
    for entry in conversation_history[-10:]:  # Use last 10 messages for context
        prefix = "User: " if not entry["is_bot"] else "Assistant: "
        context += f"{prefix}{entry['content']}\n"
    
    # Construct the final prompt
    final_prompt = f"{system_instructions}\n\nConversation History:\n{context}\n\nUser: {message}\nAssistant:"
    
    try:
        print("Sending request to Gemini API...")
        response = model.generate_content(final_prompt)
        bot_response = response.text
        print(f"Received response: {bot_response[:50]}...")  # Print first 50 chars
        
        # Store the bot response
        store_message(user_id, bot_response, True)
        
        return bot_response
    
    except Exception as e:
        error_msg = f"Error generating response: {str(e)}"
        print(error_msg)
        return f"I'm having trouble responding right now. Technical details: {str(e)}"

@app.route('/')
def home():
    """Render the home page"""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """API endpoint for chat"""
    data = request.json
    user_id = data.get('user_id', 'default_user')
    message = data.get('message', '')
    
    response = generate_response(user_id, message)
    
    return jsonify({"response": response})

@app.route('/api/history', methods=['GET'])
def get_history():
    """API endpoint to get chat history"""
    user_id = request.args.get('user_id', 'default_user')
    
    # Ensure user exists
    ensure_user_exists(user_id)
    
    # Get conversation history
    history = get_conversation_history(user_id, limit=50)
    
    formatted_history = []
    for msg in history:
        formatted_history.append({
            "content": msg["content"],
            "is_bot": msg["is_bot"],
            "timestamp": msg["timestamp"]
        })
    
    return jsonify({"history": formatted_history})
    
def test_gemini_api():
    try:
        model_to_use = "gemini-2.0-flash"
        model = genai.GenerativeModel(model_to_use)
        
        # Test the model
        response = model.generate_content("Hello, can you give me a short response to test if you're working?")
        print("API Test successful! Received:", response.text)
        return True
    except Exception as e:
        print(f"API Test failed with error: {str(e)}")
        return False

def test_supabase_connection():
    try:
        # Try to query the users table
        result = supabase.table("users").select("*").limit(1).execute()
        print("Supabase connection test successful!")
        return True
    except Exception as e:
        print(f"Supabase connection test failed with error: {str(e)}")
        return False

if __name__ == '__main__':
    print("Testing Gemini API connection...")
    api_working = test_gemini_api()
    
    print("Testing Supabase connection...")
    db_working = test_supabase_connection()
    
    if api_working and db_working:
        print("All tests successful, starting Flask app...")
        app.run(debug=True, port=5000)
    else:
        print("Startup tests failed. Please check your API keys and database connection.")