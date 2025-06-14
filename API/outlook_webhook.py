from flask import Flask, request
from pyngrok import ngrok
from dotenv import load_dotenv
import os
import webbrowser

# Load and update .env
def update_env_redirect_uri(new_uri):
    env_path = ".env"
    lines = []
    key_found = False

    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("REDIRECT_URI="):
                lines.append(f"REDIRECT_URI={new_uri}/callback\n")
                key_found = True
            else:
                lines.append(line)

    if not key_found:
        lines.append(f"REDIRECT_URI={new_uri}/callback\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    print("✅ Updated .env with:", f"{new_uri}/callback")

# Step 1: Start Flask app
app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    return f"Authorization code received: {code}"

# Step 2: Run Flask on localhost
def run_flask():
    app.run(port=5000)

# Step 3: Main auth logic
if __name__ == '__main__':
    # Start Flask in background thread (optional)
    import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # Step 4: Open ngrok tunnel
    public_url = ngrok.connect(5000).public_url
    print("🔗 Public URL:", public_url)

    # Step 5: Update .env
    update_env_redirect_uri(public_url)

    # Step 6: Load env values
    load_dotenv()
    client_id = os.getenv("ol_CLIENT_ID")
    redirect_uri = os.getenv("REDIRECT_URI")

    # Step 7: Generate auth URL
    scopes = "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"
    auth_url = (
        "https://login.microsoftonline.com/4fa8a7aa-076f-4fb3-9362-f7e08e7985a1/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&response_mode=query"
        f"&scope={scopes}"
    )

    print("\n🔗 Visit the URL below to log in:")
    print(auth_url)
    webbrowser.open(auth_url)
