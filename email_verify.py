# make a function that takes an email as an argument and returns whether it's true(verified) or not

import requests
import os
from dotenv import load_dotenv

def verify_email(email):
    load_dotenv("private.env")
    api_key = os.environ.get("API_KEY")
    headers = {
        "apikey": api_key
    }
    response = requests.get(f"https://api.apilayer.com/email_verification/{email}", headers=headers)

    if response.status_code == 200:
        return response.json()["can_connect_smtp"]
    else:
        return None