
import msal
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("ol_CLIENT_ID")
TENANT_ID = os.getenv("ol_TENANT_ID")

AUTHORITY = os.getenv("ol_AUTHORITY")
SCOPES = ["Mail.Read"]

import os
import requests
from urllib.parse import urlencode

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = os.getenv("SCOPE")

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPE
    }
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def get_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    else:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise Exception("Failed to create device flow")

        print(f"🔑 Go to {flow['verification_uri']} and enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)  # <== FIXED LINE

    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Token error: {result}")
    