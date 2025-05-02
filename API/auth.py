import msal
import os
from dotenv import load_dotenv
from urllib.parse import urlencode

load_dotenv()

CLIENT_ID = os.getenv("ol_CLIENT_ID")
CLIENT_SECRET = os.getenv("ol_CLIENT_SECRET")
TENANT_ID = os.getenv("ol_TENANT_ID")
REDIRECT_URI = os.getenv("ol_REDIRECT_URI")
AUTHORITY = os.getenv("ol_AUTHORITY")
SCOPE = os.getenv("SCOPE")  # e.g., "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"

# Filter out reserved scopes for MSAL
RESERVED_SCOPES = ['openid', 'offline_access', 'profile']
SCOPES = [scope for scope in SCOPE.split() if scope not in RESERVED_SCOPES]  # e.g., ["https://graph.microsoft.com/Mail.Read", "https://graph.microsoft.com/Mail.Send", "https://graph.microsoft.com/User.Read"]

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPE  # Use the full space-separated string including offline_access
    }
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"

def get_token(code=None):
    print(f"get_token called with code: {code}")  # Debug
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    
    try:
        if code:
            # Handle authorization code flow
            result = app.acquire_token_by_authorization_code(
                code=code,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI
            )
        else:
            # Try silent token acquisition
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(SCOPES, account=accounts[0])
            else:
                # Fallback to device flow
                flow = app.initiate_device_flow(scopes=SCOPES)
                if "user_code" not in flow:
                    raise Exception("Failed to create device flow")
                print(f"🔑 Go to {flow['verification_uri']} and enter code: {flow['user_code']}")
                result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            return result
        else:
            raise Exception(f"Token error: {result.get('error_description', 'Unknown error')}")
    except Exception as e:
        raise Exception(f"Authentication failed: {str(e)}")

def refresh_access_token(refresh_token):
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "access_token" in result:
        return result
    else:
        raise Exception(f"Refresh token error: {result.get('error_description', 'Unknown error')}")