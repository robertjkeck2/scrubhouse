import os
from os.path import join, dirname

from dotenv import load_dotenv
import requests

dotenv_path = join(dirname(__file__), ".env")
load_dotenv(dotenv_path)

app_base_url = "https://scrubhouse.herokuapp.com"

API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN")


def refresh_rooms():
    headers = {"Authorization": "Bearer {}".format(API_AUTH_TOKEN)}
    refresh_url = app_base_url + "/refresh-rooms"
    response = requests.post(refresh_url, headers=headers)
    if response.status_code == 200:
        return True
    return False


refresh_rooms()