import requests
from auth import get_token
from flask_sqlalchemy import SQLAlchemy
import pymysql
from flask import Flask, jsonify,request
from flask_migrate import Migrate
from datetime import datetime
from dateutil import parser
import pytz
from flask import Flask, redirect, request, session, jsonify
from auth import get_auth_url, get_token
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/email_log_ol'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


pymysql.install_as_MySQLdb()

app.secret_key = 'any-secret' 


class EmailLogOl(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(255), unique=True)
    thread_id = db.Column(db.String(255), nullable=True)
    sender = db.Column(db.String(255))
    recipient = db.Column(db.Text)
    subject = db.Column(db.Text)
    received_time = db.Column(db.DateTime)
    sent_time = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(50))  


GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"


@app.route('/login')
def login():
    return redirect(get_auth_url())

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_data = get_token(code)
    session['access_token'] = token_data['access_token']
    token_data["message"] = "Login successful!"
    return jsonify(token_data)

@app.route('/fetch')

def fetch_and_log():
    if not session.get('access_token'):
        return redirect('/login')
    
    fetch_emails('messages')
    update_sent_times_from_replies()
    return "✅ Emails fetched and logged to DB"


def fetch_emails(folder,save_to_db=True):
    
    token = session.get('access_token')
    if not token:
        return "Not authenticated. Please login via /login"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{GRAPH_API_ENDPOINT}/me/{folder}?$top=10&$select=subject,sender,from,toRecipients,receivedDateTime,sentDateTime"

    response = requests.get(url, headers=headers)
    
    print(f"\n🔹 {folder.upper()}:")
    if response.status_code == 200:
        emails = response.json().get("value", [])
        
        for email in emails:
            message_id = email.get("id")
            print("conversationID",email )
            thread_id = email.get("conversationId")
            subject = email.get("subject", "No Subject")
            sender = email.get("from", {}).get("emailAddress", {}).get("address", "Unknown Sender")
            recipient_list = [r['emailAddress']['address'] for r in email.get("toRecipients", [])]
            recipients = ", ".join(recipient_list) if recipient_list else "No Recipients"
            received_time = email.get("receivedDateTime", None)
            ist = pytz.timezone('Asia/Kolkata')
            parsed_time = parser.isoparse(received_time).astimezone(ist) if received_time else None
            

            print(f"📨 Subject: {subject}")
            print(f"   From: {sender}")
            print(f"   To: {recipients}")
            print(f"   Received: {received_time}")
           
            if save_to_db:
                    existing = EmailLogOl.query.filter_by(message_id=message_id).first()
                    if not existing:
                        email_log_ol = EmailLogOl(
                            message_id=message_id,
                            thread_id=thread_id,
                            sender=sender,
                            recipient=recipients,
                            subject=subject,
                            received_time=parsed_time,
                            
                            
                        )
                        db.session.add(email_log_ol)
                        db.session.commit()
        
    else:
        print(f"❌ Failed to fetch emails: {response.text}")

def update_sent_times_from_replies():
    token = session.get('access_token')
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{GRAPH_API_ENDPOINT}/me/mailFolders/sentItems/messages?$top=25&$select=subject,from,toRecipients,sentDateTime"

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        sent_emails = response.json().get("value", [])
        for sent in sent_emails:
            sent_subject = sent.get("subject", "")
            sent_time_raw = sent.get("sentDateTime", "")
            to_list = sent.get("toRecipients", [])

            if not sent_time_raw or not to_list:
                continue

            # Parse sent time
           
            ist = pytz.timezone('Asia/Kolkata')
            sent_time = parser.isoparse(sent_time_raw).astimezone(ist)

            # Get first recipient email (assuming single)
            recipient_email = to_list[0]['emailAddress']['address']

            # Try to find a matching inbox message
            matching_inbox = EmailLogOl.query.filter(
                EmailLogOl.sender == recipient_email,
                EmailLogOl.subject.in_([sent_subject, sent_subject.replace("Re: ", ""), sent_subject.replace("RE: ", "")]),
                EmailLogOl.sent_time == None
            ).order_by(EmailLogOl.received_time.desc()).first()
            print(f"Matching inbox: {matching_inbox}")
            if matching_inbox:
                received_time = matching_inbox.received_time
                if received_time.tzinfo is None:
                    received_time = ist.localize(received_time)
                print(f"Matching inbox: {matching_inbox}")
                if sent_time > received_time:
                    matching_inbox.sent_time = sent_time
                    db.session.commit()
                    print(f"✅ Matched & updated reply for: {sent_subject}")

    else:
        print(f"❌ Failed to fetch sent mails: {response.text}")

if __name__ == "__main__":
    app.secret_key = 'any-secret'  # Required for sessions
    app.run(debug=True)