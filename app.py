import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql

# Replace these with your actual connection details
DATABASE_URL = "postgres://<username>:<password>@<host>:<port>/<database_name>"

# Establishing the connection
conn = psycopg2.connect(postgresql://postgres:[zT9JJxXUa!fgM_&]@db.tiudyykyzjejykhtuiof.supabase.co:5432/postgres)
cur = conn.cursor()

# Example query to fetch data
cur.execute("SELECT * FROM users LIMIT 5;")
rows = cur.fetchall()

# Print the results
for row in rows:
    print(row)

# Closing the cursor and connection
cur.close()
conn.close()

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure Google Gemini API
api_key = "AIzaSyAn16yV68eU1CEZpZ35YW4FhnikMnEIJWI"  # Replace with your actual API key
genai.configure(api_key=api_key)

# Initialize Gemini model
model = genai.GenerativeModel('gemini-2.0-flash')

# Store conversation history
conversations = {}
# Store user profiles
user_profiles = {}
# Track session activity
session_activity = {}

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

def generate_response(user_id, message):
    """Generate a response using the Gemini API with simplified approach"""
    
    # Check for crisis indicators first
    if check_for_crisis(message):
        return get_crisis_response()
    
    # Get conversation history or create new
    if user_id not in conversations:
        conversations[user_id] = []
    
    # Update session activity timestamp
    session_activity[user_id] = datetime.now()
    
    conversation_history = conversations[user_id]
    
    # Get user profile context if available
    user_context = ""
    if user_id in user_profiles:
        user_context = f"""
        User Profile Information:
        - Primary emotions: {', '.join(user_profiles[user_id].get('emotions', ['Unknown']))}
        - Main concerns: {', '.join(user_profiles[user_id].get('concerns', ['Unknown']))}
        - Previous session summary: {user_profiles[user_id].get('last_summary', 'No previous sessions')}
        - Suggested approach: {user_profiles[user_id].get('suggestion', '')}
        """
    
    # Create a prompt that includes system instructions and recent context
    system_instructions = create_system_prompt()
    
    # Build a context string with recent conversation history
    context = ""
    for entry in conversation_history[-5:]:  # Use last 5 messages for context
        context += f"User: {entry['user_message']}\n"
        if "bot_response" in entry:
            context += f"Assistant: {entry['bot_response']}\n"
    
    # Construct the final prompt
    final_prompt = f"{system_instructions}\n\n{user_context}\n\nConversation History:\n{context}\n\nUser: {message}\nAssistant:"
    
    try:
        print("Sending request to Gemini API...")
        response = model.generate_content(final_prompt)
        bot_response = response.text
        print(f"Received response: {bot_response[:50]}...")  # Print first 50 chars
        
        # Store in conversation history
        conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "user_message": message,
            "bot_response": bot_response
        })
        
        # Check if we should analyze the conversation (session length threshold)
        if len(conversation_history) >= 10:  # After 10 exchanges
            # Trigger analysis in the background (would be async in production)
            analyze_conversation(user_id)
        
        return bot_response
    
    except Exception as e:
        error_msg = f"Error generating response: {str(e)}"
        print(error_msg)
        return f"I'm having trouble responding right now. Technical details: {str(e)}"

def analyze_conversation(user_id):
    """Analyze the conversation and update user profile"""
    if user_id not in conversations or len(conversations[user_id]) < 3:
        return  # Not enough conversation to analyze
    
    try:
        # Build the full conversation text for analysis
        conversation_text = ""
        for entry in conversations[user_id][-10:]:  # Use last 10 messages
            if "user_message" in entry:
                conversation_text += f"User: {entry['user_message']}\n"
            if "bot_response" in entry:
                conversation_text += f"Assistant: {entry['bot_response']}\n"
        
        # Create analysis prompt
        analysis_prompt = f"""
        System: Analyze the following mental health support conversation. Extract key information about 
        the user's emotional state, concerns, and progress. Format your response as structured data.

        Conversation: 
        {conversation_text}

        Please provide:
        1. Primary emotions detected (list up to 3)
        2. Main concerns/issues discussed (list up to 3)
        3. Potential triggers identified
        4. Coping strategies mentioned or suggested
        5. Brief summary of the conversation (2-3 sentences)
        6. Level of distress detected (low/medium/high)
        7. Support recommendation for next interaction
        
        Format your response as JSON.
        """
        
        # Get analysis from Gemini
        print("Requesting conversation analysis from Gemini...")
        analysis_response = model.generate_content(analysis_prompt)
        analysis_text = analysis_response.text
        
        # Parse the response - this assumes Gemini returns proper JSON
        # In production, you'd need more robust parsing and error handling
        try:
            # Clean up the response to get just the JSON part
            json_text = analysis_text
            if "```json" in analysis_text:
                json_text = analysis_text.split("```json")[1].split("```")[0]
            elif "```" in analysis_text:
                json_text = analysis_text.split("```")[1].split("```")[0]
                
            analysis_data = json.loads(json_text)
            
            # Create or update user profile
            if user_id not in user_profiles:
                user_profiles[user_id] = {}
            
            # Update profile with new analysis
            user_profiles[user_id].update({
                'emotions': analysis_data.get('Primary emotions detected', []),
                'concerns': analysis_data.get('Main concerns/issues discussed', []),
                'triggers': analysis_data.get('Potential triggers identified', []),
                'coping_strategies': analysis_data.get('Coping strategies mentioned or suggested', []),
                'last_summary': analysis_data.get('Brief summary of the conversation', ''),
                'distress_level': analysis_data.get('Level of distress detected', 'medium'),
                'suggestion': analysis_data.get('Support recommendation for next interaction', ''),
                'last_updated': datetime.now().isoformat()
            })
            
            print(f"Updated user profile for {user_id}")
            
        except json.JSONDecodeError as e:
            print(f"Error parsing analysis response as JSON: {e}")
            print(f"Raw response: {analysis_text}")
        
    except Exception as e:
        print(f"Error analyzing conversation: {e}")

# Check for inactive sessions and trigger analysis
def check_inactive_sessions():
    """Check for inactive sessions and trigger analysis"""
    current_time = datetime.now()
    inactive_threshold = timedelta(minutes=30)  # 30 minutes of inactivity
    
    for user_id, last_active in list(session_activity.items()):
        if current_time - last_active > inactive_threshold:
            # Session is inactive, trigger analysis
            print(f"Session {user_id} inactive, triggering analysis")
            analyze_conversation(user_id)
            # Could remove from session_activity here if desired

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

@app.route('/api/profile/<user_id>', methods=['GET'])
def get_user_profile(user_id):
    """API endpoint to get user profile"""
    if user_id in user_profiles:
        return jsonify(user_profiles[user_id])
    else:
        return jsonify({"error": "User profile not found"}), 404

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

if __name__ == '__main__':
    print("Testing Gemini API connection...")
    api_working = test_gemini_api()
    if api_working:
        print("API test successful, starting Flask app...")
        app.run(debug=True, port=5000)
    else:
        print("API test failed. Please check your API key and internet connection.")