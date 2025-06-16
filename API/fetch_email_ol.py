import requests
from auth import get_token, refresh_access_token
from flask_sqlalchemy import SQLAlchemy
import pymysql
from flask import Flask, jsonify, request, session, redirect, render_template, send_file
from flask_migrate import Migrate
from datetime import datetime, timedelta
from dateutil import parser
import pytz
import os
import pandas as pd
import io
from urllib.parse import quote
import logging
from sqlalchemy import func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/EmailLogOlAcountng'
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
    replied_at = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(50))
    reply_subject = db.Column(db.Text, nullable=True)
    reply_sender = db.Column(db.String(255), nullable=True)
    replied_message_id = db.Column(db.String(255), nullable=True)

class LastFetch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    folder = db.Column(db.String(50), unique=True, nullable=False)
    last_fetch_time = db.Column(db.DateTime, nullable=False)

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
    logger.info(f"Session: {session}")
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        fetch_result = fetch_emails('messages')
        update_result = update_replied_at_from_replies()
        logger.info(f"Fetch result: {fetch_result}, Update result: {update_result}")
        return redirect('/analytics_dash')
    except Exception as e:
        logger.error(f"Failed to fetch emails: {str(e)}")
        return jsonify({"error": f"Failed to fetch emails: {str(e)}"}), 500

@app.route('/dashboard')
def dashboard():
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        filter_type = request.args.get('filter_type', 'all')
        filter_date = request.args.get('date')
        ist = pytz.timezone('Asia/Kolkata')
        filter_label = "All Emails"

        query = EmailLogOl.query.filter_by(source='messages')

        if filter_type == 'total_received':
            filter_label = "Total Emails Received"
        elif filter_type in ['received_today', 'received_yesterday', 'received_day_before'] and filter_date:
            try:
                start_date = datetime.strptime(filter_date, '%Y-%m-%d').replace(tzinfo=ist)
                end_date = start_date + timedelta(days=1)
                query = query.filter(
                    EmailLogOl.received_time >= start_date,
                    EmailLogOl.received_time < end_date
                )
                filter_label = f"Emails Received on {start_date.strftime('%B %d, %Y')}"
            except ValueError:
                logger.warning(f"Invalid date format: {filter_date}")
        elif filter_type in ['replied_today', 'replied_yesterday', 'replied_day_before'] and filter_date:
            try:
                start_date = datetime.strptime(filter_date, '%Y-%m-%d').replace(tzinfo=ist)
                end_date = start_date + timedelta(days=1)
                query = query.filter(
                    EmailLogOl.received_time >= start_date,
                    EmailLogOl.received_time < end_date,
                    EmailLogOl.replied_at != None
                )
                filter_label = f"Emails Received and Replied on {start_date.strftime('%B %d, %Y')}"
            except ValueError:
                logger.warning(f"Invalid date format: {filter_date}")

        emails = query.all()
        email_data = []
        for email in emails:
            email_data.append({
                'id': email.id,
                'message_id': email.message_id,
                'thread_id': email.thread_id,
                'sender': email.sender,
                'recipient': email.recipient,
                'subject': email.subject,
                'received_time': email.received_time,
                'replied_at': email.replied_at,
                'source': email.source,
                'reply_subject': email.reply_subject,
                'reply_sender': email.reply_sender,
                'replied_message_id': email.replied_message_id
            })
        try:
            return render_template('dashboard.html', emails=email_data, filter_label=filter_label)
        except Exception as e:
            logger.error(f"Failed to load dashboard.html: {str(e)}")
            try:
                return render_template('dashboard/dashboard.html', emails=email_data, filter_label=filter_label)
            except Exception as e2:
                logger.error(f"Failed to load dashboard/dashboard.html: {str(e2)}")
                return jsonify({"error": f"Failed to load dashboard template: {str(e2)}"}), 500
    except Exception as e:
        logger.error(f"Failed to query database: {str(e)}")
        return jsonify({"error": f"Failed to query database: {str(e)}"}), 500

@app.route('/analytics_dash')
def analytics_dash():
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)

        # Total emails received
        total_received = db.session.query(func.count(EmailLogOl.id)).filter(EmailLogOl.source == 'messages').scalar()
        
        # Total replied to
        total_replied = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.replied_at != None
        ).scalar()
        
        # Total not replied
        total_not_replied = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.replied_at == None
        ).scalar()
        
        # Received today
        received_today = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= today,
            EmailLogOl.received_time < today + timedelta(days=1)
        ).scalar()
        
        # Received yesterday
        received_yesterday = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= yesterday,
            EmailLogOl.received_time < today
        ).scalar()
        
        # Received day before yesterday
        received_day_before = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= day_before,
            EmailLogOl.received_time < yesterday
        ).scalar()
        
        # Replied to for emails received today
        replied_today = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= today,
            EmailLogOl.received_time < today + timedelta(days=1),
            EmailLogOl.replied_at != None
        ).scalar()
        
        # Replied to for emails received yesterday
        replied_yesterday = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= yesterday,
            EmailLogOl.received_time < today,
            EmailLogOl.replied_at != None
        ).scalar()
        
        # Replied to for emails received day before yesterday
        replied_day_before = db.session.query(func.count(EmailLogOl.id)).filter(
            EmailLogOl.source == 'messages',
            EmailLogOl.received_time >= day_before,
            EmailLogOl.received_time < yesterday,
            EmailLogOl.replied_at != None
        ).scalar()

        stats = {
            'total_received': total_received or 0,
            'total_replied': total_replied or 0,
            'total_not_replied': total_not_replied or 0,
            'received_today': received_today or 0,
            'received_yesterday': received_yesterday or 0,
            'received_day_before': received_day_before or 0,
            'replied_today': replied_today or 0,
            'replied_yesterday': replied_yesterday or 0,
            'replied_day_before': replied_day_before or 0
        }

        return render_template('analytics_dash.html', stats=stats)
    except Exception as e:
        logger.error(f"Failed to load analytics_dash: {str(e)}")
        return jsonify({"error": f"Failed to load dashboard: {str(e)}"}), 500


@app.route('/download_excel')
def download_excel():
    if not session.get('access_token'):
        return redirect('/login')
    
    try:
        emails = EmailLogOl.query.all()
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
                'Replied At': email.replied_at.strftime('%Y-%m-%d %H:%M:%S %Z') if email.replied_at else 'Not Replied',
                'Source': email.source or 'N/A',
                'Reply Subject': email.reply_subject or 'N/A',
                'Reply Sender': email.reply_sender or 'N/A',
                'Replied Message ID': email.replied_message_id or 'N/A'
            })
        
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Email Log')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name='email_log_ol.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    
    except Exception as e:
        logger.error(f"Failed to generate Excel file: {str(e)}")
        return jsonify({"error": f"Failed to generate Excel file: {str(e)}"}), 500

def fetch_emails(folder, save_to_db=True):
    token = session.get('access_token')
    if not token:
        return {"error": "Not authenticated. Please login via /login"}, 401

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    last_fetch = LastFetch.query.filter_by(folder=folder).first()
    if last_fetch:
        last_fetch_time = last_fetch.last_fetch_time
    else:
        last_fetch_time = datetime.now(pytz.UTC) - timedelta(days=7)
    
    filter_time = last_fetch_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = (f"{GRAPH_API_ENDPOINT}/me/{folder}?$select=subject,sender,from,toRecipients,receivedDateTime,sentDateTime,conversationId"
           f"&$filter=receivedDateTime ge {quote(filter_time)}&$top=50")

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

                if save_to_db and folder == 'messages':
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

            current_time = datetime.now(pytz.UTC)
            if last_fetch:
                last_fetch.last_fetch_time = current_time
            else:
                last_fetch = LastFetch(folder=folder, last_fetch_time=current_time)
                db.session.add(last_fetch)
            db.session.commit()

            url = data.get("@odata.nextLink")

        return {"message": f"Successfully fetched {len(all_emails)} emails from {folder}"}
    except Exception as e:
        logger.error(f"Error fetching emails from {folder}: {str(e)}")
        return {"error": f"Error fetching emails: {str(e)}"}, 500

def update_replied_at_from_replies():
    token = session.get('access_token')
    if not token:
        return {"error": "Not authenticated"}, 401

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    last_fetch = LastFetch.query.filter_by(folder='sentItems').first()
    if last_fetch:
        last_fetch_time = last_fetch.last_fetch_time
    else:
        last_fetch_time = datetime.now(pytz.UTC) - timedelta(days=7)
    
    filter_time = last_fetch_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = (f"{GRAPH_API_ENDPOINT}/me/mailFolders/sentItems/messages?$select=subject,from,toRecipients,sentDateTime,conversationId,id"
           f"&$filter=sentDateTime ge {quote(filter_time)}&$top=50")

    ist = pytz.timezone('Asia/Kolkata')
    updated_count = 0

    try:
        while url:
            logger.info(f"Fetching sent emails with URL: {url}")
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
                        logger.error(f"Token refresh failed: {str(e)}")
                        return {"error": f"Token refresh failed: {str(e)}"}, 401
                else:
                    logger.error("No refresh token available")
                    return {"error": "No refresh token available. Please re-authenticate via /login"}, 401

            if response.status_code != 200:
                logger.error(f"Failed to fetch sent mails: {response.text}")
                return {"error": f"Failed to fetch sent mails: {response.text}"}, response.status_code

            data = response.json()
            sent_emails = data.get("value", [])
            logger.info(f"Fetched {len(sent_emails)} sent emails")
            for sent in sent_emails:
                thread_id = sent.get("conversationId")
                sent_time_raw = sent.get("sentDateTime")
                to_list = sent.get("toRecipients", [])
                from_email = sent.get("from", {}).get("emailAddress", {}).get("address")
                reply_subject = sent.get("subject", "No Subject")
                sent_message_id = sent.get("id")
                if not sent_time_raw or not to_list or not thread_id or not from_email or not sent_message_id:
                    logger.warning(f"Skipping sent email due to missing data: {sent}")
                    continue

                sent_time = parser.isoparse(sent_time_raw).astimezone(ist)
                recipient_email = to_list[0]['emailAddress']['address'].lower()

                logger.info(f"Processing sent email: thread_id={thread_id}, recipient={recipient_email}, from={from_email}, sent_message_id={sent_message_id}")

                matching_inbox = EmailLogOl.query.filter(
                    EmailLogOl.thread_id == thread_id,
                    db.func.lower(EmailLogOl.sender) == recipient_email,
                    EmailLogOl.replied_at == None,
                    EmailLogOl.source == 'messages'
                ).order_by(EmailLogOl.received_time.desc()).first()

                if matching_inbox:
                    received_time = matching_inbox.received_time
                    if received_time.tzinfo is None:
                        received_time = ist.localize(received_time)
                    if sent_time > received_time:
                        matching_inbox.replied_at = sent_time
                        matching_inbox.reply_subject = reply_subject
                        matching_inbox.reply_sender = from_email
                        matching_inbox.replied_message_id = sent_message_id
                        db.session.commit()
                        updated_count += 1
                        logger.info(f"Updated inbox email: message_id={matching_inbox.message_id}, replied_at={sent_time}, replied_message_id={sent_message_id}")
                    else:
                        logger.info(f"Sent time {sent_time} not later than received time {received_time} for message_id={matching_inbox.message_id}")
                else:
                    logger.info(f"No matching inbox email found for thread_id={thread_id}, recipient={recipient_email}")

            current_time = datetime.now(pytz.UTC)
            if last_fetch:
                last_fetch.last_fetch_time = current_time
            else:
                last_fetch = LastFetch(folder='sentItems', last_fetch_time=current_time)
                db.session.add(last_fetch)
            db.session.commit()

            url = data.get("@odata.nextLink")

        return {"message": f"Updated {updated_count} emails with replied_at times"}
    except Exception as e:
        logger.error(f"Error updating replied_at times: {str(e)}")
        return {"error": f"Error updating replied_at times: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(debug=True)