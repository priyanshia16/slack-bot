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

# ==============================
# FLASK SETUP
# ==============================

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

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

    # 🔥 ONLY process thread replies
    if "thread_ts" not in event:
        return

    text = event.get("text")
    channel = event.get("channel")
    thread_id = event.get("thread_ts")
    ts = event.get("ts")

    print("Message:", text)
    print("Thread ID:", thread_id)

    # ==============================
    # CREATE SLACK LINK
    # ==============================

    ts_formatted = ts.replace(".", "")
    slack_link = f"https://slack.com/archives/{channel}/p{ts_formatted}"

    # ==============================
    # FETCH FROM NOSHOWS (CHECK VALID THREAD)
    # ==============================

    url_noshows = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NOSHOWS}"

    params = {
        "view": "DNT - NoShows Report change status",
        "filterByFormula": f"{{slackThreadId}}='{thread_id}'"
    }

    response = requests.get(url_noshows, headers=HEADERS, params=params)
    records = response.json().get("records", [])

    print(f"Matching NoShows records: {len(records)}")

    # ❌ Ignore if not our bot thread
    if not records:
        return

    # ✅ Get companyName
    company_name = records[0]["fields"].get("companyName", "")

    # ==============================
    # STORE IN REPLIES TABLE
    # ==============================

    url_replies = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_REPLIES}"

    data_replies = {
        "fields": {
            "slackLink": slack_link,
            "threadId": thread_id,
            "channelName": channel,  # (keeping same field as before)
            "message": text,
            "Date": datetime.utcnow().isoformat(),
            "companyName": company_name
        }
    }

    res = requests.post(url_replies, json=data_replies, headers=HEADERS)
    print("Replies table:", res.status_code)

    # ==============================
    # UPDATE NOSHOWS TABLE
    # ==============================

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
    import os

port = int(os.environ.get("PORT", 10000))
flask_app.run(host="0.0.0.0", port=port)

