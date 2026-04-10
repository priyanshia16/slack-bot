from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import requests
import os
from datetime import datetime

# ==============================
# SLACK CONFIG
# ==============================

app = App(
    token="xoxb-XXXX",  # keep your token
    signing_secret="XXXX"
)

# ==============================
# AIRTABLE CONFIG
# ==============================

AIRTABLE_TOKEN = "YOUR_AIRTABLE_TOKEN"
BASE_ID = "apphLcvA4OO7gKjl9"

TABLE_REPLIES = "Slack Company Replies"
TABLE_NOSHOWS = "NoShows"

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

# ==============================
# FLASK SETUP
# ==============================

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# ==============================
# HELPER: GET USER NAME
# ==============================

def get_user_name(user_id):
    try:
        response = app.client.users_info(user=user_id)
        if response["ok"]:
            return response["user"]["real_name"]
    except Exception as e:
        print("User fetch error:", e)

    return user_id  # fallback

# ==============================
# ROUTES
# ==============================

@flask_app.route("/")
def home():
    return "Bot is running ✅"

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():

    data = request.get_json(silent=True)

    if data and data.get("type") == "url_verification":
        return data["challenge"], 200, {"Content-Type": "text/plain"}

    return handler.handle(request)

# ==============================
# EVENT LISTENER
# ==============================

@app.event("message")
def handle_message_events(body, logger):

    event = body["event"]

    # ❌ Ignore bot messages
    if "subtype" in event:
        return

    text = event.get("text")
    channel = event.get("channel")
    user_id = event.get("user")
    ts = event.get("ts")

    # 🔥 Thread ID logic
    thread_id = event.get("thread_ts") or event.get("ts")

    print("Message:", text)
    print("Thread ID:", thread_id)

    # ==============================
    # GET USER NAME
    # ==============================

    user_name = get_user_name(user_id)

    # ==============================
    # CREATE SLACK LINK
    # ==============================

    ts_formatted = ts.replace(".", "")
    slack_link = f"https://slack.com/archives/{channel}/p{ts_formatted}"

    # ==============================
    # CHECK NOSHOWS MATCH
    # ==============================

    url_noshows = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NOSHOWS}"

    params = {
        "view": "DNT - NoShows Report change status",
        "filterByFormula": f"{{slackThreadId}}='{thread_id}'"
    }

    response = requests.get(url_noshows, headers=HEADERS, params=params)
    records = response.json().get("records", [])

    print(f"Matching NoShows records: {len(records)}")

    # ==============================
    # GET COMPANY NAME (if exists)
    # ==============================

    company_name = ""
    if records:
        company_name = records[0]["fields"].get("companyName", "")

    # ==============================
    # STORE IN REPLIES TABLE (FOR ALL MESSAGES)
    # ==============================

    url_replies = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_REPLIES}"

    data_replies = {
        "fields": {
            "slackLink": slack_link,
            "threadId": thread_id,
            "channelName": channel,
            "message": text,
            "Date": datetime.utcnow().isoformat(),
            "companyName": company_name,
            "senderId": user_id,
            "senderName": user_name
        }
    }

    res = requests.post(url_replies, json=data_replies, headers=HEADERS)
    print("Replies table:", res.status_code)

    # ==============================
    # UPDATE NOSHOWS ONLY IF MATCH FOUND
    # ==============================

    if records:
        for rec in records:
            record_id = rec["id"]

            update_url = f"{url_noshows}/{record_id}"

            update_data = {
                "fields": {
                    "Issue Raised by Company": "New Message"
                }
            }

            update_res = requests.patch(update_url, json=update_data, headers=HEADERS)
            print("Updated NoShows:", update_res.status_code)

# ==============================
# RUN SERVER
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
