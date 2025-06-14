import msal
import os
import requests
from dotenv import load_dotenv
from urllib.parse import urlencode
from msal import ConfidentialClientApplication
from datetime import datetime, timedelta

load_dotenv()

CLIENT_ID = os.getenv("ol_CLIENT_ID")
CLIENT_SECRET = os.getenv("ol_CLIENT_SECRET")
TENANT_ID = os.getenv("ol_TENANT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTHORITY = os.getenv("ol_AUTHORITY")
SCOPE = os.getenv("SCOPE")  # e.g., "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"

# Filter out reserved scopes for MSAL
RESERVED_SCOPES = ['openid', 'offline_access', 'profile']
SCOPES = [scope for scope in SCOPE.split() if scope not in RESERVED_SCOPES]  # e.g., ["https://graph.microsoft.com/Mail.Read", "https://graph.microsoft.com/Mail.Send", "https://graph.microsoft.com/User.Read"]

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET ,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPE  # Use the full space-separated string including offline_access
    }
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def get_token(code=None):
    print(f"get_token called with code: {code}")  # Debug
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    
    try:
        if code:
            # Authorization code flow
            result = app.acquire_token_by_authorization_code(
                code=code,
                scopes=SCOPES,  # includes 'offline_access'
                redirect_uri=REDIRECT_URI
            )
        else:
            # Silent or device flow (fallback)
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(SCOPE.split(), account=accounts[0])
            else:
                raise Exception("No accounts available to acquire token silently.")

        if "access_token" in result:
            return result
        else:
            raise Exception(f"Token error: {result.get('error_description', 'Unknown error')}")

    except Exception as e:
        raise Exception(f"Authentication failed: {str(e)}")

def refresh_access_token(refresh_token):
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPE.split())
    if "access_token" in result:
        return result
    else:
        raise Exception(f"Refresh token error: {result.get('error_description', 'Unknown error')}")
def create_subscription(access_token):
    url = "https://graph.microsoft.com/v1.0/subscriptions"
    expiration_time = (datetime.utcnow() + timedelta(minutes=4230)).isoformat() + "Z"

    subscription_data = {
        "changeType": "created",
        "notificationUrl": f"{NGROK_URL}/webhook",
        "resource": "me/mailFolders('inbox')/messages",
        "expirationDateTime": expiration_time,
        "clientState": "s3cr3tVal"
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=subscription_data, headers=headers)
    print("📡 Subscription response:", response.status_code, response.text)