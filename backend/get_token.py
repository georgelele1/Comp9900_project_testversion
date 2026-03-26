from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json",
    scopes=["https://www.googleapis.com/auth/calendar.readonly"]
)
creds = flow.run_local_server(port=0)

# Save token for future use
with open("token.json", "w") as f:
    f.write(creds.to_json())