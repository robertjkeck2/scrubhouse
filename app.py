from datetime import datetime, timedelta
import json
import os
from os.path import join, dirname
import urllib.request
import urllib.parse
import urllib.error

from dateutil import parser
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import oauth2 as oauth
import pytz
import requests

dotenv_path = join(dirname(__file__), ".env")
load_dotenv(dotenv_path)

app = Flask(__name__)

app.debug = False

discord_base_url = "https://discord.com/api"
discord_invite_base_url = "https://discord.gg/"
request_token_url = "https://api.twitter.com/oauth/request_token"
access_token_url = "https://api.twitter.com/oauth/access_token"
authorize_url = "https://api.twitter.com/oauth/authorize"
show_user_url = "https://api.twitter.com/1.1/users/show.json"

app.config["TWITTER_API_KEY"] = os.getenv("TWITTER_API_KEY")
app.config["TWITTER_API_SECRET"] = os.getenv("TWITTER_API_SECRET")
app.config["DISCORD_BOT_TOKEN"] = os.getenv("DISCORD_BOT_TOKEN")
app.config["DISCORD_GENERAL_CHANNEL"] = os.getenv("DISCORD_GENERAL_CHANNEL")
app.config["DISCORD_GUILD_ID"] = os.getenv("DISCORD_GUILD_ID")
app.config["DISCORD_PUBLIC_KEY"] = os.getenv("DISCORD_PUBLIC_KEY")
app.config["DISCORD_VOICE_PARENT_ID"] = os.getenv("DISCORD_VOICE_PARENT_ID")


oauth_store = {}


@app.route("/")
def start():
    app_callback_url = url_for("twitter", _external=True)
    consumer = oauth.Consumer(
        app.config["TWITTER_API_KEY"], app.config["TWITTER_API_SECRET"]
    )
    client = oauth.Client(consumer)
    resp, content = client.request(
        request_token_url,
        "POST",
        body=urllib.parse.urlencode({"oauth_callback": app_callback_url}),
    )

    if resp["status"] != "200":
        return render_template("error.html")

    request_token = dict(urllib.parse.parse_qsl(content))
    oauth_token = request_token[b"oauth_token"].decode("utf-8")
    oauth_token_secret = request_token[b"oauth_token_secret"].decode("utf-8")

    oauth_store[oauth_token] = oauth_token_secret
    return redirect("{0}?oauth_token={1}".format(authorize_url, oauth_token))


@app.route("/twitter")
def twitter():
    oauth_token = request.args.get("oauth_token")
    oauth_verifier = request.args.get("oauth_verifier")
    oauth_denied = request.args.get("denied")

    if oauth_denied:
        if oauth_denied in oauth_store:
            del oauth_store[oauth_denied]
        return render_template("error.html")

    if not oauth_token or not oauth_verifier:
        return render_template("error.html")

    if oauth_token not in oauth_store:
        return render_template("error.html")

    oauth_token_secret = oauth_store[oauth_token]
    consumer = oauth.Consumer(
        app.config["TWITTER_API_KEY"], app.config["TWITTER_API_SECRET"]
    )
    token = oauth.Token(oauth_token, oauth_token_secret)
    token.set_verifier(oauth_verifier)
    client = oauth.Client(consumer, token)
    resp, content = client.request(access_token_url, "POST")
    access_token = dict(urllib.parse.parse_qsl(content))
    user_id = access_token[b"user_id"].decode("utf-8")
    real_oauth_token = access_token[b"oauth_token"].decode("utf-8")
    real_oauth_token_secret = access_token[b"oauth_token_secret"].decode("utf-8")
    real_token = oauth.Token(real_oauth_token, real_oauth_token_secret)
    real_client = oauth.Client(consumer, real_token)
    real_resp, real_content = real_client.request(
        show_user_url + "?user_id=" + user_id, "GET"
    )

    if real_resp["status"] != "200":
        return render_template("error.html")

    response = json.loads(real_content.decode("utf-8"))
    followers_count = response.get("followers_count", 0)
    created_at = response.get("created_at")

    del oauth_store[oauth_token]

    if created_at:
        created_at_datetime = parser.parse(created_at)
        last_week_datetime = datetime.utcnow() - timedelta(days=7)
        last_week_datetime = last_week_datetime.replace(tzinfo=pytz.utc)
        if created_at_datetime > last_week_datetime:
            return render_template("too-soon.html")
        if followers_count < 1000:
            invite = get_discord_invite()
            if invite:
                return render_template("welcome.html", invite=invite)
            else:
                return render_template("error.html")
        else:
            return render_template("too-popular.html")
    return render_template("error.html")


@app.route("/room-request", methods=["POST"])
def room():
    verify_key = VerifyKey(bytes.fromhex(app.config["DISCORD_PUBLIC_KEY"]))

    signature = request.headers["X-Signature-Ed25519"]
    timestamp = request.headers["X-Signature-Timestamp"]
    body = request.data.decode()

    try:
        verify_key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
    except BadSignatureError:
        abort(401, "invalid request signature")

    if request.json["type"] == 1:
        return jsonify({"type": 1})
    else:
        name = request.json.get("data", {}).get("options", [])[0].get("value")
        if name:
            added = add_voice_channel(name)
            if added:
                return jsonify(
                    {
                        "type": 4,
                        "data": {
                            "tts": False,
                            "content": "Your new voice channel has been added!",
                            "embeds": [],
                            "allowed_mentions": [],
                        },
                    }
                )
        return jsonify(
            {
                "type": 4,
                "data": {
                    "tts": False,
                    "content": "There was an issue adding a room. Please try again.",
                    "embeds": [],
                    "allowed_mentions": [],
                },
            }
        )


@app.route("/refresh-rooms", methods=["POST"])
def refresh_rooms():
    num_success = 0
    voice_channels = get_all_voice_channels()
    for channel_id in voice_channels:
        success = remove_voice_channel(channel_id)
        if success:
            num_success = num_success + 1
    return jsonify({"success": num_success > 0, "num_removed": num_success})


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("error.html"), 500


def get_all_voice_channels():
    get_all_channels_url = discord_base_url + "/guilds/{0}/channels".format(
        app.config["DISCORD_GUILD_ID"]
    )
    response = _discord_api_request("GET", get_all_channels_url)
    if response.status_code == 200:
        channels = response.json()
    else:
        return []

    voice_channels = []
    for channel in channels:
        if (
            channel.get("type") == 2
            and channel.get("id") != app.config["DISCORD_GENERAL_CHANNEL"]
        ):
            voice_channels.append(channel.get("id"))
    return voice_channels


def add_voice_channel(name):
    create_channel_url = discord_base_url + "/guilds/{0}/channels".format(
        app.config["DISCORD_GUILD_ID"]
    )
    payload = {
        "name": name,
        "type": 2,
        "parent_id": app.config["DISCORD_VOICE_PARENT_ID"],
    }
    response = _discord_api_request("POST", create_channel_url, payload)
    if response.status_code == 201:
        return True
    return False


def remove_voice_channel(channel_id):
    remove_channel_url = discord_base_url + "/channels/{1}".format(
        app.config["DISCORD_GUILD_ID"], channel_id
    )
    response = _discord_api_request("DELETE", remove_channel_url)
    if response.status_code == 200:
        return True
    return False


def get_discord_invite():
    channel_url = discord_base_url + "/channels/{0}/invites".format(
        app.config["DISCORD_GENERAL_CHANNEL"]
    )
    payload = {"max_age": 3600, "max_uses": 1, "unique": True}
    response = _discord_api_request("POST", channel_url, payload)
    invite_url = None
    if response.status_code == 200:
        invite = response.json()
        invite_url = discord_invite_base_url + invite.get("code")
    return invite_url


def _discord_api_request(request_type, url, payload=None):
    headers = {
        "Authorization": "Bot {}".format(app.config["DISCORD_BOT_TOKEN"]),
        "Content-Type": "application/json",
    }
    if request_type == "GET":
        response = requests.get(url, headers=headers)
    elif request_type == "POST":
        response = requests.post(url, headers=headers, json=payload)
    elif request_type == "DELETE":
        response = requests.delete(url, headers=headers)
    return response


if __name__ == "__main__":
    app.run()
