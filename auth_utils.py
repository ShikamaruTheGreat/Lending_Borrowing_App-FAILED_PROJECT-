from fastapi import FastAPI, Request, Response, HTTPException, Depends, APIRouter, WebSocket, WebSocketException
from pydantic import BaseModel, field_validator, Field
from werkzeug.security import generate_password_hash, check_password_hash
from email_verify import verify_email
import jwt
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, select, ForeignKey, update, delete, insert
from datetime import datetime
from database import engine, users

load_dotenv("private.env")
SECRET = os.environ.get("JWT_SECRET")
router = APIRouter()

class Register(BaseModel):
    email: str
    username: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str):
        exists_check = verify_email(value)
        if not exists_check:
            raise ValueError("This email doesn't seem to exist")
        elif "@" not in value or value.startswith(".") or value.endswith("."):
            raise ValueError("Enter an actual email dude")
        else:
            return value

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str):
        if len(value) < 5:
            raise ValueError("Username is too short")
        slurs = ["nigga", "rape", "slave", "bitch", "pedophile"]
        for slur in slurs:
            if slur in value:
                raise ValueError("Username can't have slurs in it, you bitch")
        return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str):
        if len(value) < 12:
            raise ValueError("Password can't be less than 12 characters")
        has_nums = False
        has_symbols = False
        keyboard_symbols = [
            ',', '.', ';', ':', "'", '"', '!', '?',
            '(', ')', '[', ']', '{', '}', '<', '>',
            '+', '-', '=', '*', '/', '\\', '^', '~', '_',
            '@', '#', '$', '%', '&', '|', '`'
        ]
        for char in value:
            if char.isdigit():
                has_nums = True
            if char in keyboard_symbols:
                has_symbols = True
        if has_nums and has_symbols:
            return value
        else:
            raise ValueError("Password must have at least one symbol and one number")

class Login(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str):
        exists_check = verify_email(value)
        if "@" not in value or value.startswith(".") or value.endswith("."):
            raise ValueError("Enter an actual email dude")
        elif not exists_check:
            raise ValueError("This email doesn't seem to exist")
        else:
            return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str):
        if len(value) < 12:
            raise ValueError("Password can't be less than 12 characters")
        has_nums = False
        has_symbols = False
        keyboard_symbols = [
            ',', '.', ';', ':', "'", '"', '!', '?',
            '(', ')', '[', ']', '{', '}', '<', '>',
            '+', '-', '=', '*', '/', '\\', '^', '~', '_',
            '@', '#', '$', '%', '&', '|', '`'
        ]
        for char in value:
            if char.isdigit():
                has_nums = True
            if char in keyboard_symbols:
                has_symbols = True
        if has_nums and has_symbols:
            return value
        else:
            raise ValueError("Password must have at least one symbol and one number")

@router.post("/register")
def register(auth: Register, response: Response):
    with engine.begin() as conn:
        email_exists_check = select(users.c.email).where(users.c.email == auth.email)
        username_exists_check = select(users.c.username).where(users.c.username == auth.username)
        email_result = conn.execute(email_exists_check).scalar()
        username_result = conn.execute(username_exists_check).scalar()
        if email_result is not None:
            raise HTTPException(400, "this email is already taken")
        if username_result is not None:
            raise HTTPException(400, "this username is already taken")

        hashed_pass = generate_password_hash(auth.password)
        user = insert(users).values(email=auth.email, username=auth.username, password=hashed_pass)
        result = conn.execute(user)
        user_id = result.inserted_primary_key[0]
    payload = {
        "user_id": user_id,
        "exp": datetime.now().timestamp() + 1_296_000
    }
    token = jwt.encode(payload, SECRET, "HS256")
    response.set_cookie(key="jw_token", value=token, max_age=1_296_000, httponly=True)
    return 200

def helper_jwt(request: Request):
    if "jw_token" not in request.cookies:
        raise HTTPException(404, "where's my cookie :( (redirect to login page IMMEDIATELY)")
    jw_token = request.cookies.get("jw_token")
    try:
        payload = jwt.decode(jw_token, SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
        with engine.begin() as conn:
            id_exist_test = select(users.c.username).where(users.c.user_id == user_id)
            result = conn.execute(id_exist_test).scalar()
            if result is None:
                raise HTTPException(404, "Have you tampered with your cookie?")
            else:
                return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(400, "JWT is expired, redirect to login page IMMEDIATELY")
    except jwt.InvalidSignatureError:
        raise HTTPException(400, "Someone has tampered with my sweet cookie ⸨◺_◿⸩")
    except jwt.DecodeError:
        raise HTTPException(400, "Someone has tampered with my sweet cookie ⸨◺_◿⸩")



def helper_jwt_w(websocket: WebSocket):
    if "jw_token" not in websocket.cookies:
        raise WebSocketException(1008, "where's my cookie :( (redirect to login page IMMEDIATELY)")
    jw_token = websocket.cookies.get("jw_token")
    try:
        payload = jwt.decode(jw_token, SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
        with engine.begin() as conn:
            id_exist_test = select(users.c.username).where(users.c.user_id == user_id)
            result = conn.execute(id_exist_test).scalar()
            if result is None:
                raise WebSocketException(1008, "Have you tampered with your cookie?")
            else:
                return user_id
    except jwt.ExpiredSignatureError:
        raise WebSocketException(1008, "JWT is expired, redirect to login page IMMEDIATELY")
    except jwt.InvalidSignatureError:
        raise WebSocketException(1008, "Someone has tampered with my sweet cookie ⸨◺_◿⸩")


@router.post("/login")
def login(response: Response, auth: Login):
    with engine.begin() as conn:
        email_check = select(users.c.email).where(users.c.email == auth.email)
        result = conn.execute(email_check).scalar()
        if result is None:
            raise HTTPException(400, "your email doesn't exist in our database")
        password_check = select(users.c.password).where(users.c.email == auth.email)
        hashed_pass = conn.execute(password_check).scalar()
        password_matches = check_password_hash(hashed_pass, auth.password)
        if not password_matches:
            raise HTTPException(400, "your password is incorrect")
        id_fetch = (select(users.c.user_id)
                    .where(users.c.email == auth.email, users.c.password == hashed_pass))
        user_id = conn.execute(id_fetch).scalar()

    payload = {
        "user_id": user_id,
        "exp": datetime.now().timestamp() + 1_296_000
    }
    new_jwt = jwt.encode(payload, SECRET, "HS256")
    response.set_cookie(key="jw_token", value=new_jwt, max_age=1_296_000, httponly=True)
    return 200
