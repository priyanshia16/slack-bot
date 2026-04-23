import os
import json
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# ==============================
# CONFIG
# ==============================

SLACK_TOKEN    = os.environ.get("SLACK_TOKEN", "xoxb-1259594035652-10740645182023-sVPgUXYxX8gRElqYO2VsIkZ9")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "patMhjMqmVkMf0Gpc.b42cc2035d97a186f37b0c8b0b96c008966e7fb3f9008c44771486d7721eaf85")
BASE_ID        = os.environ.get("AIRTABLE_BASE_ID", "apphLcvA4OO7gKjl9")

# Tables
TABLE_THREAD_TRAILS = os.environ.get("AIRTABLE_TABLE_NAME", "Slack Thread Trails 2 copy copy")
TABLE_REPLIES       = "Slack Company Replies"
TABLE_NOSHOWS       = "NoShows"

SLACK_HEADERS = {"Authorization": f"Bearer {SLACK_TOKEN}"}
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

IST = timezone(timedelta(hours=5, minutes=30))

# ==============================
# FLASK SETUP
# ==============================

flask_app = Flask(__name__)

# ==============================
# USER NAME CACHE
# ==============================

user_cache = {}

def get_user_name(user_id):
    if user_id in user_cache:
        return user_cache[user_id]
    try:
        res = requests.get(
            "https://slack.com/api/users.info",
            headers=SLACK_HEADERS,
            params={"user": user_id}
        )
        data = res.json()
        if data.get("ok"):
            user = data["user"]
            name = (
                user.get("real_name")
                or user.get("profile", {}).get("display_name")
                or user_id
            )
            user_cache[user_id] = name
            return name
    except Exception as e:
        print(f"User fetch error for {user_id}:", e)
    user_cache[user_id] = user_id
    return user_id


# ==============================
# GET CHANNEL NAME
# ==============================

def get_channel_name(channel_id):
    try:
        res = requests.get(
            "https://slack.com/api/conversations.info",
            headers=SLACK_HEADERS,
            params={"channel": channel_id}
        )
        data = res.json()
        if data.get("ok"):
            return data["channel"].get("name", channel_id)
    except Exception as e:
        print(f"Channel fetch error for {channel_id}:", e)
    return channel_id


# ==============================
# CODE 1 — THREAD TRAIL HELPERS
# ==============================

def get_thread_replies(channel_id, thread_ts):
    res = requests.get(
        "https://slack.com/api/conversations.replies",
        headers=SLACK_HEADERS,
        params={"channel": channel_id, "ts": thread_ts}
    )
    data = res.json()
    if data.get("ok"):
        return data.get("messages", [])
    print(f"Thread fetch error: {data.get('error')}")
    return []


def build_slack_link_thread(channel_id, thread_ts):
    ts_formatted = thread_ts.replace(".", "")
    return f"https://slack.com/archives/{channel_id}/p{ts_formatted}?thread_ts={thread_ts}&cid={channel_id}"


def find_airtable_record(thread_id):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_THREAD_TRAILS}"
    params = {
        "filterByFormula": f'{{threadId}}="{thread_id}"',
        "maxRecords": 1
    }
    res = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
    data = res.json()
    records = data.get("records", [])
    if records:
        return records[0]["id"]
    return None


def upsert_thread_trail(record):
    thread_id = record["threadId"]
    existing_record_id = find_airtable_record(thread_id)

    if existing_record_id:
        url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_THREAD_TRAILS}/{existing_record_id}"
        res = requests.patch(url, json={"fields": record}, headers=AIRTABLE_HEADERS)
        if res.status_code == 200:
            print(f"  🔄 Updated thread {thread_id} in #{record['channelName']}")
        else:
            print(f"  ❌ Update error: {res.status_code}", res.json())
    else:
        url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_THREAD_TRAILS}"
        res = requests.post(url, json={"fields": record}, headers=AIRTABLE_HEADERS)
        if res.status_code == 200:
            print(f"  ✅ Created thread {thread_id} in #{record['channelName']}")
        else:
            print(f"  ❌ Create error: {res.status_code}", res.json())


def build_and_save_thread_trail(channel_id, channel_name, thread_ts):
    replies = get_thread_replies(channel_id, thread_ts)
    if not replies:
        print(f"  ⚠️  No replies found for thread {thread_ts}")
        return

    root_message = replies[0]
    trail = []
    all_participants = set()
    has_reactions = False
    all_reactions = []

    for index, msg in enumerate(replies):
        user_id = msg.get("user", "unknown")
        user_name = get_user_name(user_id)
        all_participants.add(user_name)

        msg_ts = msg.get("ts")
        msg_dt = datetime.fromtimestamp(float(msg_ts), tz=IST)

        msg_reactions = []
        for reaction in msg.get("reactions", []):
            has_reactions = True
            for uid in reaction.get("users", []):
                reaction_entry = {
                    "emoji": reaction.get("name"),
                    "reactedBy": get_user_name(uid),
                    "reactedById": uid
                }
                msg_reactions.append(reaction_entry)
                all_reactions.append({
                    "messageIndex": index + 1,
                    "messageBy": user_name,
                    "emoji": reaction.get("name"),
                    "reactedBy": get_user_name(uid)
                })

        trail.append({
            "index": index + 1,
            "datetime": msg_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "senderId": user_id,
            "senderName": user_name,
            "text": msg.get("text", ""),
            "reactions": msg_reactions,
            "isRootMessage": index == 0
        })

    root_user_id = root_message.get("user", "unknown")
    root_user_name = get_user_name(root_user_id)
    root_dt = datetime.fromtimestamp(float(thread_ts), tz=IST)

    record = {
        "channelId": channel_id,
        "channelName": channel_name,
        "threadId": thread_ts,
        "slackLink": build_slack_link_thread(channel_id, thread_ts),
        "threadDate": root_dt.strftime("%Y-%m-%d"),
        "dayOfWeek": root_dt.strftime("%A"),
        "initialMessage": root_message.get("text", ""),
        "initialSenderId": root_user_id,
        "initialSenderName": root_user_name,
        "initialMessageTs": root_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        "replyCount": max(len(replies) - 1, 0),
        "fullThreadTrail": json.dumps(trail, indent=2, ensure_ascii=False),
        "participants": ", ".join(all_participants),
        "hasReactions": has_reactions,
        "reactionsDetail": json.dumps(all_reactions, indent=2, ensure_ascii=False),
        "extractedAt": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    }

    upsert_thread_trail(record)


# ==============================
# CODE 2 — REPLIES + NOSHOWS (main processor)
# ==============================

def process_message(event):
    text = event.get("text")
    channel = event.get("channel")
    user_id = event.get("user")
    ts = event.get("ts")
    thread_id = event.get("thread_ts") or ts

    print("--- Processing message ---")
    print("Text:", text)
    print("Raw channel:", channel)
    print("Raw user_id:", user_id)

    user_name = get_user_name(user_id)
    channel_name = get_channel_name(channel)

    print("Final user_name:", user_name)
    print("Final channel_name:", channel_name)

    # Slack link
    ts_formatted = ts.replace(".", "")
    slack_link = f"https://slack.com/archives/{channel}/p{ts_formatted}"

    # --- Check NoShows & save to Replies table ---
    url_noshows = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NOSHOWS}"
    params = {
        "view": "DNT - NoShows Report change status",
        "filterByFormula": f"{{slackThreadId}}='{thread_id}'"
    }
    response = requests.get(url_noshows, headers=AIRTABLE_HEADERS, params=params)
    records = response.json().get("records", [])
    print(f"Matching NoShows records: {len(records)}")

    company_name = ""
    if records:
        company_name = records[0]["fields"].get("companyName", "")

    url_replies = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_REPLIES}"
    data_replies = {
        "fields": {
            "slackLink": slack_link,
            "threadId": thread_id,
            "channelId": channel,
            "channelName": channel_name,
            "message": text,
            "Date": datetime.utcnow().isoformat(),
            "companyName": company_name,
            "senderId": user_id,
            "senderName": user_name
        }
    }
    res = requests.post(url_replies, json=data_replies, headers=AIRTABLE_HEADERS)
    print("Replies table status:", res.status_code)

    if records:
        for rec in records:
            record_id = rec["id"]
            update_url = f"{url_noshows}/{record_id}"
            update_data = {"fields": {"Issue Raised by Company": "New Message"}}
            requests.patch(update_url, json=update_data, headers=AIRTABLE_HEADERS)
            print("Updated NoShows for record:", record_id)

    # --- Build and save full thread trail (Code 1 logic) ---
    build_and_save_thread_trail(channel, channel_name, thread_id)


# ==============================
# ROUTES
# ==============================

@flask_app.route("/")
def home():
    return "Bot is running ✅"


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json(silent=True)

    # Slack URL verification
    if data and data.get("type") == "url_verification":
        return data["challenge"], 200, {"Content-Type": "text/plain"}

    # Handle message events
    if data and "event" in data:
        event = data["event"]
        if event.get("type") == "message" and "subtype" not in event:
            threading.Thread(target=process_message, args=(event,)).start()

    return "", 200


# ==============================
# ENTRY POINT
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)
