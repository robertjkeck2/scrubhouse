import json
import os
from os.path import join, dirname
import urllib.request
import urllib.parse
import urllib.error

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for
import oauth2 as oauth
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
        error_message = "Invalid response, status {status}, {message}".format(
            status=resp["status"], message=content.decode("utf-8")
        )
        return render_template("error.html", error_message=error_message)

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
        return render_template(
            "error.html", error_message="the OAuth request was denied by this user"
        )

    if not oauth_token or not oauth_verifier:
        return render_template("error.html", error_message="callback param(s) missing")

    if oauth_token not in oauth_store:
        return render_template(
            "error.html", error_message="oauth_token not found locally"
        )

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
    del oauth_store[oauth_token]

    if followers_count < 1000:
        invite = get_discord_invite()
        if invite:
            return render_template("welcome.html", invite=invite)
        else:
            return render_template("error.html")
    else:
        return render_template("too-popular.html")


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("error.html", error_message="uncaught exception"), 500


def get_discord_invite():
    headers = {
        "Authorization": "Bot {}".format(app.config["DISCORD_BOT_TOKEN"]),
        "Content-Type": "application/json",
    }
    channel_url = discord_base_url + "/channels/{0}/invites".format(
        app.config["DISCORD_GENERAL_CHANNEL"]
    )
    payload = {"max_age": 3600, "max_uses": 1, "unique": True}
    response = requests.post(channel_url, headers=headers, json=payload)
    invite_url = None
    if response.status_code == 200:
        invite = response.json()
        invite_url = discord_invite_base_url + invite.get("code")
    return invite_url


if __name__ == "__main__":
    app.run()
