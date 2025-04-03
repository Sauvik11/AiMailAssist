from flask import Flask, jsonify,request
import base64
from email.mime.text import MIMEText
import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import requests
from flask_cors import CORS
from datetime import datetime
from flask_migrate import Migrate
import pymysql

from flask_sqlalchemy import SQLAlchemy





app = Flask(__name__)
CORS(app) 




# Define the required Gmail API scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly","https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.modify"]

AI_Client_API_KEY = "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" #openrouter API key


app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/email_assist'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


pymysql.install_as_MySQLdb()

db = SQLAlchemy(app)

migrate = Migrate(app, db) 
class EmailLog(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    subject = db.Column(db.String(255))
    received_time = db.Column(db.DateTime)
    sent_time = db.Column(db.DateTime)
    sender_email = db.Column(db.String(255))
    receiver_email = db.Column(db.String(255))





def authenticate_gmail():
    """Authenticates the user and returns Gmail API service."""
    creds = None
    
    # Load existing token if available
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # If no valid credentials, authenticate user
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for future use
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    print(creds, "creds1")
    return creds
def get_email_body(msg_data):
    """Extracts the full email body."""
    payload = msg_data["payload"]
    
    # Case 1: Directly in payload body
    if "body" in payload and "data" in payload["body"]:
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

    # Case 2: Check parts (handle multipart emails)
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] in ["text/plain", "text/html"] and "body" in part and "data" in part["body"]:
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
    
    return "No full email content available."
def fetch_unread_emails():
    """Fetches the last 5 unread emails."""
   
    creds = authenticate_gmail()
   
    service = build("gmail", "v1", credentials=creds)
    query = "category:primary"

    # Get unread emails
    results = service.users().messages().list(userId="me", labelIds=["INBOX"], q='category:primary is:unread', maxResults=10).execute()
    messages = results.get("messages", [])
    
    if not messages:
        print("No unread emails found.")
        return

    emails = []
    for msg in messages:
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        headers = msg_data["payload"]["headers"]
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown Sender")
        sender_email = next((h["value"] for h in headers if h["name"] == "Return-Path"), sender)
        snippet = msg_data.get("snippet", "No preview available")
        full_body = get_email_body(msg_data)
        received_time = datetime.fromtimestamp(int(msg_data["internalDate"]) / 1000)
        msg_id = msg["id"]

        existing_email = EmailLog.query.filter_by(id=msg["id"]).first()
        print( existing_email, "existing_email")
        if not existing_email:
            print(  "existing_email")
            email_log = EmailLog(
                id= msg_id,
                subject=subject,
                received_time=received_time,
                sender_email=sender_email,
                receiver_email="m.sauvik11@gmail.com"  # Assuming the recipient is the logged-in user
            )
            db.session.add(email_log)
            db.session.commit()

        emails.append({
            "id": msg["id"],
            "subject": subject,
            "sender": sender,
            "snippet": snippet,
            "sender_email": sender_email,
            "full_body": full_body,
            "reply": analyze_email_with_AI(subject, snippet)
        })
    
    return emails

def analyze_email_with_AI(subject, body):
    """Uses OpenRouter API to categorize email and generate a reply."""
    prompt = f"""
    Analyze the following email and categorize it into one of these categories: Work, Personal, Urgent, Payment, Spam.
    Then, generate a smart and professional AI reply.
    
    Email Subject: {subject}
    Email Content: {body}

    Response format:
    Category: [Category Name]
    Reply: [Generated Reply]
    """

    headers = {"Authorization": f"Bearer {AI_Client_API_KEY}", "X-Title": "Gmail AI Assistant",
        "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [{"role": "system", "content": prompt}],
        "temperature": 0.7,
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)
   
    if response.status_code == 200:
        ai_response = response.json()["choices"][0]["message"]["content"]
        
        if "Reply:" in ai_response:
            reply_text = ai_response.split("Reply:")[1].strip()
            # print( reply_text, "response")
        else:
            reply_text = "AI-generated reply unavailable."
        return reply_text
    else:
        return "Error generating reply."
def mark_email_as_read(email_id):
    """Marks an email as read by removing the UNREAD label."""
    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().modify(
        userId="me", 
        id=email_id, 
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()    
@app.route("/fetch-emails", methods=["GET"])
def get_emails():
    """API endpoint to fetch emails."""
    
    try:
        emails = fetch_unread_emails()
        return jsonify(emails)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
  
def send_email(to, subject, reply,email_id,msg_id):
    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    
    message = MIMEText(reply)
    message["to"] = to
    message["subject"] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    
    send_message = {"raw": raw_message}
    sent = service.users().messages().send(userId="me", body=send_message).execute()
    mark_email_as_read(email_id)
    email_log = EmailLog.query.filter_by(id=msg_id).first()
    if email_log:
        email_log.sent_time = datetime.now()
        db.session.commit()
    return sent

@app.route("/send-email", methods=["POST"])
def send_email_api():
    data = request.json
    email_id = data.get("emailId")
    to = data.get("to")
    subject = data.get("subject")
    reply = data.get("reply")
    msg_id = data.get("msg_id")
    
    try:
        response = send_email(to, subject, reply,email_id,msg_id)
        
        return jsonify({"success": True, "message_id": response["id"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
@app.route("/email-logs", methods=["GET"])
def get_email_logs():
    email_logs = EmailLog.query.order_by(EmailLog.received_time.desc()).all()
    return jsonify([
        {
            "subject": email.subject,
            "sender_email": email.sender_email,
            "received_time": email.received_time.strftime("%Y-%m-%d %H:%M:%S"),
            "sent_time": email.sent_time.strftime("%Y-%m-%d %H:%M:%S") if email.sent_time else "Not Sent",
            # "time_taken": str(email.received_time - email.sent_time) if email.sent_time else "Not Sent"
        }
        for email in email_logs
    ])
if __name__ == "__main__":
    app.run(debug=True, port=5000)


