# app.py

import requests
import json
import base64
import io
import os
import re
import pytz
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify, session, redirect, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from PyPDF2 import PdfReader
from dateutil import parser
from openai import OpenAI
from auth import get_token, refresh_access_token, get_auth_url



app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "any-secret")

# DB setup
app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root:@localhost/email_log_ol"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
NGROK_URL = os.getenv("NGROK_URL") 

# DB Model
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
    is_invoice = db.Column(db.Boolean, default=False)
    invoice_details = db.Column(db.Text, nullable=True)

# -------------------- ROUTES --------------------

@app.route("/login")
def login():
    return redirect(get_auth_url())

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing code"}), 400
    try:
        token_data = get_token(code)
        session["access_token"] = token_data["access_token"]
        session["refresh_token"] = token_data.get("refresh_token")
        return redirect("/dashboard")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route("/dashboard")
def dashboard():
    if not session.get("access_token"):
        return redirect("/login")

    try:
        emails = EmailLogOl.query.all()
        data = []
        for email in emails:
            invoice = json.loads(email.invoice_details) if email.invoice_details else {}
            data.append({
                "id": email.id,
                "message_id": email.message_id,
                "thread_id": email.thread_id,
                "sender": email.sender,
                "recipient": email.recipient,
                "subject": email.subject,
                "received_time": email.received_time,
                "sent_time": email.sent_time,
                "source": email.source,
                "is_invoice": email.is_invoice,
                "invoice_details": invoice,
            })
        return render_template("dashboard.html", emails=data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download_excel")
def download_excel():
    if not session.get("access_token"):
        return redirect("/login")

    emails = EmailLogOl.query.all()
    data = []
    for email in emails:
        invoice = json.loads(email.invoice_details) if email.invoice_details else {}
        data.append({
            "ID": email.id,
            "Sender": email.sender,
            "Recipient": email.recipient,
            "Subject": email.subject,
            "Received": email.received_time,
            "Sent": email.sent_time or "Not Replied",
            "Source": email.source,
            "Invoice?": "Yes" if email.is_invoice else "No",
            **invoice
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="email_log.xlsx")

# -------------------- WEBHOOK LISTENER --------------------

@app.route("/listen", methods=["POST", "GET"])
def listen():
    # Validation challenge from Microsoft
    if request.method == "GET" and "validationToken" in request.args:
        return request.args.get("validationToken"), 200

    # Actual notification
    content = request.json
    for notification in content.get("value", []):
        resource = notification.get("resource")  # /me/messages/{id}
        message_id = resource.split("/")[-1]
        access_token = session.get("access_token")

        if not access_token:
            access_token = refresh_access_token(session.get("refresh_token"))
            session["access_token"] = access_token

        message = fetch_email_by_id(message_id, access_token)
        log_email(message)

    return "", 202

# -------------------- SUPPORT --------------------

def fetch_email_by_id(message_id, token):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}"
    response = requests.get(url, headers=headers)
    return response.json()

def log_email(message):
    existing = EmailLogOl.query.filter_by(message_id=message["id"]).first()
    if existing:
        return

    sender = message.get("from", {}).get("emailAddress", {}).get("address")
    recipient = ", ".join([r["emailAddress"]["address"] for r in message.get("toRecipients", [])])
    subject = message.get("subject", "")
    received_time = parser.isoparse(message.get("receivedDateTime"))
    thread_id = message.get("conversationId", "")
    attachments = message.get("hasAttachments", False)

    # Attachment processing (via /attachments if needed)
    is_invoice = False
    invoice_data = {}
    if attachments:
        att_res = requests.get(f"https://graph.microsoft.com/v1.0/me/messages/{message['id']}/attachments",
                               headers={"Authorization": f"Bearer {session['access_token']}"})
        for att in att_res.json().get("value", []):
            if "contentBytes" in att:
                content_bytes = base64.b64decode(att["contentBytes"])
                result = analyze_attachment(content_bytes, att["contentType"])
                if result.get("is_invoice"):
                    is_invoice = True
                    invoice_data = result
                    break

    db.session.add(EmailLogOl(
        message_id=message["id"],
        thread_id=thread_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        received_time=received_time,
        source="Outlook",
        is_invoice=is_invoice,
        invoice_details=json.dumps(invoice_data) if invoice_data else None
    ))
    db.session.commit()

def analyze_attachment(content, content_type):
    try:
        if content_type == "application/pdf":
            reader = PdfReader(io.BytesIO(content))
            text = "".join([page.extract_text() or "" for page in reader.pages])
            prompt = f"""Is this an invoice? If yes, return JSON with:
            invoice_number, invoice_date, total_amount, vendor.
            Text: {text[:4000]}"""
        else:
            base64_content = base64.b64encode(content).decode("utf-8")
            prompt = [{
                "type": "text",
                "text": "Is this an invoice? Return JSON with invoice_number, invoice_date, total_amount, vendor."
            }, {
                "type": "image_url",
                "image_url": {"url": f"data:{content_type};base64,{base64_content}"}
            }]
        
        res = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        result = res.choices[0].message.content.strip()
        return json.loads(re.sub(r"```json|```", "", result))
    except Exception as e:
        print(f"Attachment parsing failed: {e}")
        return {"is_invoice": False}

# -------------------- MAIN --------------------
if __name__ == "__main__":
    app.run(debug=True)
