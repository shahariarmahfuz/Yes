import os
import threading
import time
import json
import secrets
from datetime import datetime, timedelta
import requests
import random
import string
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
import google.generativeai as genai
from google.generativeai import types
import smtplib
from email.message import EmailMessage

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this for production

# Configuration
USER_DATA_FILE = 'users.json'
SESSION_TIMEOUT = timedelta(hours=72)
RAPIDAPI_HOST = "facebook-reel-and-video-downloader.p.rapidapi.com"
RAPIDAPI_KEY = "d4cc664bddmshad58db8819652d6p19e7adjsn6bcd66d66ef4"
VERIFICATION_EXPIRE_MINUTES = 30

# Email Configuration
EMAIL_ADDRESS = 'nekotoolcontact@gmail.com'
EMAIL_PASSWORD = 'tgwb truz wnzi kvqv'

# Gemini API keys
GEMINI_API_KEYS = [
    "AIzaSyBMNhMXZRitaMHtfzWi8WuB9BpxKeiXrok",
    "AIzaSyAbuuYt4H3GfRc24Piod6TckCw64mZXH8I",
    "AIzaSyBTyMOEXRq-CA7ITiah6YBd-w8zdMj5UF0",
]

current_key_index = 0
key_lock = threading.Lock()

generation_config = {
    "temperature": 0.8,
    "top_p": 0.9,
    "top_k": 30,
    "max_output_tokens": 600,
    "response_mime_type": "text/plain",
}

INITIAL_HISTORY = [
    {
        "role": "user",
        "parts": ["Who are you?"]
    },
    {
        "role": "model", 
        "parts": ["I am Echo, created by Shahariar Mahfuz from Evolving Intelligence. I'm an AI assistant specialized in natural conversation."]
    }
]

user_sessions = {}

# Helper Functions
def get_next_api_key():
    global current_key_index
    with key_lock:
        current_key = GEMINI_API_KEYS[current_key_index]
        current_key_index = (current_key_index + 1) % len(GEMINI_API_KEYS)
        print(f"Using API Key: {current_key} (Index: {current_key_index})")
    return current_key

def generate_user_api_key():
    """Generate an API key in the format X0X0-XX00-00XX-X0X0"""
    key_parts = []
    format_pattern = "X0X0-XX00-00XX-X0X0"
    
    for char in format_pattern:
        if char == 'X':
            key_parts.append(random.choice(string.ascii_uppercase))
        elif char == '0':
            key_parts.append(str(random.randint(0, 9)))
        else:
            key_parts.append(char)
    
    return ''.join(key_parts)

def load_users():
    if not os.path.exists(USER_DATA_FILE):
        return {}
    with open(USER_DATA_FILE, 'r') as file:
        users = json.load(file)
        # Convert old user format to new format
        for email in users:
            if 'verified' not in users[email]:
                users[email]['verified'] = True
                users[email]['verification_token'] = None
                users[email]['token_sent_time'] = None
                users[email]['resend_count'] = 0
        return users

def save_users(users):
    with open(USER_DATA_FILE, 'w') as file:
        json.dump(users, file, indent=4)

def get_user_by_api_key(api_key):
    users = load_users()
    for email, data in users.items():
        if data.get('api_key') == api_key:
            return email, data
    return None, None

def deduct_credits(email, amount):
    users = load_users()
    if email in users:
        if users[email]['credits'] >= amount:
            users[email]['credits'] -= amount
            save_users(users)
            return True
    return False

def is_identity_question(question):
    """Enhanced identity detection with more keywords"""
    identity_keywords = [
        "your name", "who are you", "what's your name", "what is your name",
        "who created you", "who made you", "your creator", "made by",
        "who developed you", "who made you", "your version", "version number",
        "which company made you", "what company created you", "future technology",
        "who designed you", "are you human", "are you ai", "what are you",
        "tell me about yourself"
    ]
    question_lower = question.lower()
    return any(keyword in question_lower for keyword in identity_keywords)

def clean_inactive_sessions():
    while True:
        current_time = datetime.now()
        for user_id in list(user_sessions.keys()):
            if current_time - user_sessions[user_id]["last_active"] > SESSION_TIMEOUT:
                del user_sessions[user_id]
        time.sleep(300)

def send_verification_email(email, token):
    verification_url = url_for('verify_email', token=token, _external=True)
    
    msg = EmailMessage()
    msg['Subject'] = 'Verify Your Email Address'
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = email
    
    html = f"""
    <html>
        <body>
            <h2>Evolving Intelligence Email Verification</h2>
            <p>Please click the link below to verify your email address:</p>
            <a href="{verification_url}">{verification_url}</a>
            <p>This link will expire in {VERIFICATION_EXPIRE_MINUTES} minutes.</p>
            <p>If you didn't request this, please ignore this email.</p>
        </body>
    </html>
    """
    
    msg.add_alternative(html, subtype='html')
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# Authentication Routes
@app.route('/')
def home():
    if 'email' in session:
        return redirect(url_for('account'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'email' in session:
        return redirect(url_for('account'))
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        users = load_users()
        user = users.get(email, {})
        
        if user.get('password') == password:
            if user.get('verified', False):
                session['email'] = email
                return redirect(url_for('account'))
            else:
                session['unverified_email'] = email
                flash('Please verify your email first', 'error')
                return redirect(url_for('verify_send'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'email' in session:
        return redirect(url_for('account'))
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        users = load_users()
        
        if email in users:
            flash('Email already exists', 'error')
        else:
            verification_token = secrets.token_urlsafe(32)
            users[email] = {
                'password': password,
                'credits': 0,  # 0 until verified
                'api_key': None,
                'verified': False,
                'verification_token': verification_token,
                'token_sent_time': datetime.now().isoformat(),
                'resend_count': 0
            }
            save_users(users)
            
            if send_verification_email(email, verification_token):
                session['unverified_email'] = email
                return redirect(url_for('verify_send'))
            else:
                del users[email]
                save_users(users)
                flash('Failed to send verification email', 'error')
    
    return render_template('signup.html')

@app.route('/verify/<token>')
def verify_email(token):
    users = load_users()
    for email, data in users.items():
        if data.get('verification_token') == token:
            token_time = datetime.fromisoformat(data['token_sent_time'])
            if datetime.now() - token_time < timedelta(minutes=VERIFICATION_EXPIRE_MINUTES):
                users[email]['verified'] = True
                users[email]['credits'] = 10
                users[email]['api_key'] = generate_user_api_key()
                users[email]['verification_token'] = None
                save_users(users)
                return render_template('verify_result.html', success=True)
    
    return render_template('verify_result.html', success=False)

@app.route('/verify/send', methods=['GET', 'POST'])
def verify_send():
    if 'unverified_email' not in session:
        return redirect(url_for('login'))
    
    email = session['unverified_email']
    users = load_users()
    user = users.get(email, {})
    
    if request.method == 'POST':
        if not user or user.get('verified', False):
            return redirect(url_for('login'))
        
        last_sent = datetime.fromisoformat(user['token_sent_time'])
        time_since_last = datetime.now() - last_sent
        
        # Resend cooldown logic
        if time_since_last < timedelta(seconds=30):
            flash('Please wait 30 seconds before resending', 'error')
        elif time_since_last < timedelta(minutes=2) and user.get('resend_count', 0) >= 1:
            flash('Please wait 2 minutes before resending', 'error')
        elif time_since_last < timedelta(minutes=5) and user.get('resend_count', 0) >= 2:
            flash('Please wait 5 minutes before resending', 'error')
        else:
            new_token = secrets.token_urlsafe(32)
            users[email]['verification_token'] = new_token
            users[email]['token_sent_time'] = datetime.now().isoformat()
            users[email]['resend_count'] = user.get('resend_count', 0) + 1
            save_users(users)
            
            if send_verification_email(email, new_token):
                flash('New verification link sent!', 'success')
            else:
                flash('Failed to resend verification email', 'error')
    
    return render_template('verify_send.html', email=email)

@app.route('/account', methods=['GET', 'POST'])
def account():
    if 'email' not in session:
        return redirect(url_for('login'))
    
    users = load_users()
    user_email = session['email']
    
    if request.method == 'POST' and 'reset_api_key' in request.form:
        # Generate new API key
        users[user_email]['api_key'] = generate_user_api_key()
        save_users(users)
        flash('API key has been reset successfully!', 'success')
    
    user_data = users.get(user_email, {})
    
    return render_template('account.html', 
                         email=user_email, 
                         credits=user_data.get('credits', 0),
                         api_key=user_data.get('api_key', ''))

@app.route('/logout')
def logout():
    session.pop('email', None)
    session.pop('unverified_email', None)
    return redirect(url_for('login'))

# API Routes
@app.route("/ai", methods=["GET"])
def ai_response():
    question = request.args.get("q")
    user_id = request.args.get("id")
    api_key = request.args.get("key")

    if not question:
        return jsonify({"error": "Missing 'q' parameter"}), 400
    if not user_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    # Verify API key and check credits
    email, user_data = get_user_by_api_key(api_key)
    if not email:
        return jsonify({"error": "Invalid API key"}), 401
    
    if not deduct_credits(email, 1):  # Deduct 1 credit for AI request
        return jsonify({"error": "Insufficient credits"}), 402

    # Initialize session with predefined history
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "history": INITIAL_HISTORY.copy(),
            "last_active": datetime.now()
        }

    user_sessions[user_id]["last_active"] = datetime.now()
    user_sessions[user_id]["history"].append({"role": "user", "parts": [question]})

    try:
        if is_identity_question(question):
            # Enhanced identity responses
            if any(k in question.lower() for k in ["your name", "who are you"]):
                response_text = "My name is Echo, a conversational AI developed by Evolving Intelligence."
            elif "creator" in question.lower() or "made you" in question.lower():
                response_text = "I was created by Shahariar Mahfuz, lead AI engineer at Evolving Intelligence."
            elif "company" in question.lower():
                response_text = "I'm developed and maintained by Evolving Intelligence, an AI research company."
            else:
                response_text = "I'm Echo, an AI assistant created by Shahariar Mahfuz at Evolving Intelligence (version Echo-2m4.2)."
        else:
            current_api_key = get_next_api_key()
            genai.configure(api_key=current_api_key)
            
            model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                generation_config=generation_config,
            )
            
            chat_session = model.start_chat(history=user_sessions[user_id]["history"])
            response = chat_session.send_message(question)
            response_text = response.text

        user_sessions[user_id]["history"].append({"role": "model", "parts": [response_text]})
        return jsonify({"response": response_text})

    except Exception as e:
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500

@app.route("/fb", methods=["GET"])
def get_video_links():
    """Facebook video download endpoint"""
    fb_url = request.args.get("link")
    api_key = request.args.get("key")

    if not fb_url:
        return jsonify({"error": "Missing 'link' parameter"}), 400
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    # Verify API key and check credits
    email, user_data = get_user_by_api_key(api_key)
    if not email:
        return jsonify({"error": "Invalid API key"}), 401
    
    if not deduct_credits(email, 5):  # Deduct 5 credits for FB request
        return jsonify({"error": "Insufficient credits"}), 402

    video_links = fetch_video_links(fb_url)
    
    if video_links:
        return jsonify({
            "status": "success",
            "links": video_links
        })
    else:
        return jsonify({"error": "No video links found"}), 404

def fetch_video_links(fb_url):
    """Fetch video links from RapidAPI"""
    url = f"https://{RAPIDAPI_HOST}/app/main.php?url={fb_url}"
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        links = data.get("links", {})
        
        result = {}
        # HD link
        if "Download High Quality" in links:
            result["hd_url"] = links["Download High Quality"]
        
        # SD link
        if "Download Low Quality" in links:
            result["sd_url"] = links["Download Low Quality"]
        
        return result if result else None
    return None

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive"})

@app.route('/reset-api-key', methods=['POST'])
def reset_api_key():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    email = session['email']
    users = load_users()
    
    if email not in users:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Generate new API key
    new_key = generate_user_api_key()
    users[email]['api_key'] = new_key
    save_users(users)
    
    return jsonify({'success': True, 'new_key': new_key})

if __name__ == "__main__":
    print("Starting server with API key rotation...")
    print(f"Total Gemini API keys available: {len(GEMINI_API_KEYS)}")
    
    threading.Thread(target=clean_inactive_sessions, daemon=True).start()
    app.run(host="0.0.0.0", port=25851)
