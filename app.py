from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import requests
import os
import threading
from datetime import datetime

# ==============================
# SLACK CONFIG
# ==============================

app = App(
    token="xoxb-1259594035652-10740645182023-sVPgUXYxX8gRElqYO2VsIkZ9",
    signing_secret="86c4027a79f6abfc5b2ef5c44567cbab"
)

# ==============================
# AIRTABLE CONFIG
# ==============================

AIRTABLE_TOKEN = "patMhjMqmVkMf0Gpc.b42cc2035d97a186f37b0c8b0b96c008966e7fb3f9008c44771486d7721eaf85"
BASE_ID = "apphLcvA4OO7gKjl9"

TABLE_REPLIES = "Slack Company Replies"
TABLE_NOSHOWS = "NoShows"

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

SLACK_TOKEN = "xoxb-1259594035652-10740645182023-sVPgUXYxX8gRElqYO2VsIkZ9"

# ==============================
# FLASK SETUP
# ==============================

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# ==============================
# HELPER: GET USER NAME (direct API call)
# ==============================

def get_user_name(user_id):
    try:
        res = requests.get(
            "https://slack.com/api/users.info",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            params={"user": user_id}
        )
        data = res.json()
        print("User API raw response:", data)
        if data.get("ok"):
            user = data["user"]
            name = (
                user.get("real_name")
                or user.get("profile", {}).get("display_name")
                or user_id
            )
            print("Resolved user name:", name)
            return name
        else:
            print("User API error:", data.get("error"))
    except Exception as e:
        print("User fetch exception:", e)
    return user_id

# ==============================
# HELPER: GET CHANNEL NAME (direct API call)
# ==============================

def get_channel_name(channel_id):
    try:
        res = requests.get(
            "https://slack.com/api/conversations.info",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            params={"channel": channel_id}
        )
        data = res.json()
        print("Channel API raw response:", data)
        if data.get("ok"):
            name = data["channel"].get("name", channel_id)
            print("Resolved channel name:", name)
            return name
        else:
            print("Channel API error:", data.get("error"))
    except Exception as e:
        print("Channel fetch exception:", e)
    return channel_id

# ==============================
# BACKGROUND PROCESSOR
# ==============================

def process_message(event):
    text = event.get("text")
    channel = event.get("channel")
    user_id = event.get("user")
    ts = event.get("ts")
    thread_id = event.get("thread_ts") or ts

    print("--- Processing message in background ---")
    print("Text:", text)
    print("Raw channel:", channel)
    print("Raw user_id:", user_id)

    # Resolve names
    user_name = get_user_name(user_id)
    channel_name = get_channel_name(channel)

    print("Final user_name:", user_name)
    print("Final channel_name:", channel_name)

    # Slack link
    ts_formatted = ts.replace(".", "")
    slack_link = f"https://slack.com/archives/{channel}/p{ts_formatted}"

    # Check NoShows
    url_noshows = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NOSHOWS}"
    params = {
        "view": "DNT - NoShows Report change status",
        "filterByFormula": f"{{slackThreadId}}='{thread_id}'"
    }
    response = requests.get(url_noshows, headers=HEADERS, params=params)
    records = response.json().get("records", [])
    print(f"Matching NoShows records: {len(records)}")

    company_name = ""
    if records:
        company_name = records[0]["fields"].get("companyName", "")

    # Store in Replies table
    url_replies = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_REPLIES}"
    data_replies = {
        "fields": {
            "slackLink": slack_link,
            "threadId": thread_id,
            "channelName": channel_name,
            "message": text,
            "Date": datetime.utcnow().isoformat(),
            "companyName": company_name,
            "senderId": user_id,
            "senderName": user_name
        }
    }
    res = requests.post(url_replies, json=data_replies, headers=HEADERS)
    print("Replies table status:", res.status_code)
    print("Replies table response:", res.json())

    # Update NoShows if match found
    if records:
        for rec in records:
            record_id = rec["id"]
            update_url = f"{url_noshows}/{record_id}"
            update_data = {"fields": {"Issue Raised by Company": "New Message"}}
            update_res = requests.patch(update_url, json=update_data, headers=HEADERS)
            print("Updated NoShows:", update_res.status_code)

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

    # ✅ Acknowledge Slack immediately
    if data and "event" in data:
        event = data["event"]
        if event.get("type") == "message" and "subtype" not in event:
            threading.Thread(target=process_message, args=(event,)).start()

    return "", 200

# ==============================
# RUN SERVER
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)
