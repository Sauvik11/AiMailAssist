import requests
from auth import get_token, refresh_access_token
from flask_sqlalchemy import SQLAlchemy
import pymysql
from flask import Flask, jsonify, request, session, redirect, render_template,send_file
from flask_migrate import Migrate
from datetime import datetime
from dateutil import parser
import pytz
import os
import pandas as pd
import tempfile
import io


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/email_log_ol'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'any-secret')

db = SQLAlchemy(app)
migrate = Migrate(app, db)

pymysql.install_as_MySQLdb()

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
    from auth import get_auth_url
    return redirect(get_auth_url())

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "No code provided"}), 400
    
    try:
        token_data = get_token(code)
        session['access_token'] = token_data['access_token']
        session['refresh_token'] = token_data.get('refresh_token')
        return jsonify({"message": "Login successful", "access_token": token_data['access_token']})
    except Exception as e:
        return jsonify({"error": f"Authentication failed: {str(e)}"}), 401

@app.route('/logout')
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})

@app.route('/fetch')
def fetch_and_log():
    print(f"Session: {session}")
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        fetch_result = fetch_emails('messages')
        update_result = update_sent_times_from_replies()
        print(f"Fetch result: {fetch_result}, Update result: {update_result}")
        return redirect('/dashboard')
    except Exception as e:
        return jsonify({"error": f"Failed to fetch emails: {str(e)}"}), 500

def fetch_emails(folder, save_to_db=True):
    token = session.get('access_token')
    if not token:
        return {"error": "Not authenticated. Please login via /login"}, 401

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Fetch all unread emails with pagination
    url = f"{GRAPH_API_ENDPOINT}/me/{folder}?$top=10&$filter=isRead eq false&$select=subject,sender,from,toRecipients,receivedDateTime,sentDateTime,conversationId"
    ist = pytz.timezone('Asia/Kolkata')
    all_emails = []

    try:
        while url:
            response = requests.get(url, headers=headers)
            if response.status_code == 401:
                refresh_token = session.get('refresh_token')
                if refresh_token:
                    try:
                        new_token_data = refresh_access_token(refresh_token)
                        session['access_token'] = new_token_data['access_token']
                        session['refresh_token'] = new_token_data.get('refresh_token')
                        headers["Authorization"] = f"Bearer {new_token_data['access_token']}"
                        response = requests.get(url, headers=headers)
                    except Exception as e:
                        return {"error": f"Token refresh failed: {str(e)}"}, 401
                else:
                    return {"error": "No refresh token available. Please re-authenticate via /login"}, 401

            if response.status_code != 200:
                return {"error": f"Failed to fetch emails: {response.text}"}, response.status_code

            data = response.json()
            emails = data.get("value", [])
            all_emails.extend(emails)

            for email in emails:
                message_id = email.get("id")
                thread_id = email.get("conversationId")
                subject = email.get("subject", "No Subject")
                sender = email.get("from", {}).get("emailAddress", {}).get("address", "Unknown Sender")
                recipient_list = [r['emailAddress']['address'] for r in email.get("toRecipients", [])]
                recipients = ", ".join(recipient_list) if recipient_list else "No Recipients"
                received_time = email.get("receivedDateTime")
                parsed_time = parser.isoparse(received_time).astimezone(ist) if received_time else None

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
                            source=folder
                        )
                        db.session.add(email_log_ol)
                        db.session.commit()

            url = data.get("@odata.nextLink")  # Get next page URL, if any

        return {"message": f"Successfully fetched {len(all_emails)} unread emails from {folder}"}
    except Exception as e:
        return {"error": f"Error fetching emails: {str(e)}"}, 500
@app.route('/dashboard')
def dashboard():
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        # Fetch all entries from EmailLogOl
        emails = EmailLogOl.query.all()
        return render_template('dashboard.html', emails=emails)
    except Exception as e:
        return jsonify({"error": f"Failed to load dashboard: {str(e)}"}), 500
    
def update_sent_times_from_replies():
    token = session.get('access_token')
    if not token:
        return {"error": "Not authenticated"}, 401

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{GRAPH_API_ENDPOINT}/me/mailFolders/sentItems/messages?$top=25&$select=subject,from,toRecipients,sentDateTime,conversationId"
    ist = pytz.timezone('Asia/Kolkata')

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            refresh_token = session.get('refresh_token')
            if refresh_token:
                try:
                    new_token_data = refresh_access_token(refresh_token)
                    session['access_token'] = new_token_data['access_token']
                    session['refresh_token'] = new_token_data.get('refresh_token')
                    headers["Authorization"] = f"Bearer {new_token_data['access_token']}"
                    response = requests.get(url, headers=headers)
                except Exception as e:
                    return {"error": f"Token refresh failed: {str(e)}"}, 401
            else:
                return {"error": "No refresh token available. Please re-authenticate via /login"}, 401

        if response.status_code != 200:
            return {"error": f"Failed to fetch sent mails: {response.text}"}, response.status_code

        sent_emails = response.json().get("value", [])
        for sent in sent_emails:
            thread_id = sent.get("conversationId")
            sent_time_raw = sent.get("sentDateTime")
            to_list = sent.get("toRecipients", [])
            if not sent_time_raw or not to_list or not thread_id:
                continue

            sent_time = parser.isoparse(sent_time_raw).astimezone(ist)
            recipient_email = to_list[0]['emailAddress']['address']

            matching_inbox = EmailLogOl.query.filter(
                EmailLogOl.thread_id == thread_id,
                EmailLogOl.sender == recipient_email,
                EmailLogOl.sent_time == None
            ).order_by(EmailLogOl.received_time.desc()).first()

            if matching_inbox:
                received_time = matching_inbox.received_time
                if received_time.tzinfo is None:
                    received_time = ist.localize(received_time)
                if sent_time > received_time:
                    matching_inbox.sent_time = sent_time
                    db.session.commit()

        return {"message": "Sent times updated successfully"}
    except Exception as e:
        return {"error": f"Error updating sent times: {str(e)}"}, 500
@app.route('/download_excel')
def download_excel():
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        # Fetch all entries from EmailLogOl
        emails = EmailLogOl.query.all()
        
        # Prepare data for Excel
        data = []
        for email in emails:
            data.append({
                'ID': email.id,
                'Message ID': email.message_id,
                'Thread ID': email.thread_id or 'N/A',
                'Sender': email.sender,
                'Recipient': email.recipient,
                'Subject': email.subject,
                'Received Time': email.received_time.strftime('%Y-%m-%d %H:%M:%S %Z') if email.received_time else 'N/A',
                'Sent Time': email.sent_time.strftime('%Y-%m-%d %H:%M:%S %Z') if email.sent_time else 'Not Replied',
                'Source': email.source or 'N/A'
            })
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Write to BytesIO buffer
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Email Log')
        output.seek(0)
        
        # Send the file
        return send_file(
            output,
            as_attachment=True,
            download_name='email_log_ol.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    
    except Exception as e:
        return jsonify({"error": f"Failed to generate Excel file: {str(e)}"}), 500
if __name__ == "__main__":
    app.run(debug=True)