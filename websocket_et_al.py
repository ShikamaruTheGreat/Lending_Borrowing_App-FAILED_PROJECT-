from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, WebSocketException, UploadFile
from database import engine, select, borrows, users, insert, chat_room, case, day_counter, proof_images, items
from auth_utils import helper_jwt_w, helper_jwt
from typing import Annotated
import shutil
from pathlib import Path
import uuid
from PIL import Image

ws_router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, borrow_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(borrow_id, []).append(websocket)

    def disconnect(self, borrow_id: int, websocket: WebSocket):
        self.active_connections[borrow_id].remove(websocket)
        if not self.active_connections[borrow_id]: # if the list is empty for that key
            del self.active_connections[borrow_id] # remove the entire key-value pair

    async def send_personal_message(self, borrow_id: int, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, borrow_id: int, message: str):
        for connection in self.active_connections.get(borrow_id, []):
            await connection.send_text(message)

manager = ConnectionManager()


@ws_router.websocket("/lender_borrower_chat/{borrow_id}")
async def lender_borrower_chat(websocket: WebSocket, borrow_id: int):
    # a websocket route CAN'T accept the request object, so we use the websocket object instead
    # a websocket route CAN'T have HTTPExceptions, it must have WebSocketExceptions instead
    # a websocket route can only have one await websocket.accept() which here is handled by the object manager
    # if it has two of those then it connects then disconnects immediately

    client_id = helper_jwt_w(websocket)

    if client_id is None:
        raise WebSocketException(1008, "you aren't logged in or signed up")

    user_tag = None
    username = None
    with engine.begin() as conn:
        c_lender = (select(borrows.c.lender_id)
                        .where(borrows.c.borrow_id == borrow_id, borrows.c.lender_id == client_id))
        check_lender = conn.execute(c_lender).scalar()
        c_borrower = (select(borrows.c.borrower_id)
                        .where(borrows.c.borrow_id == borrow_id, borrows.c.borrower_id == client_id))
        check_borrower = conn.execute(c_borrower).scalar()
        if check_lender is not None and check_borrower is not None:
            raise WebSocketException(1008, "woah wtf, there's a borrows row with lender and borrower "
                                                      "being the same value")
        if check_lender is None and check_borrower is None:
            raise WebSocketException(1008, "you don't belong here")

        if check_lender is not None and check_borrower is None:
            user_tag = "lender"
            fetch_u = select(users.c.username).where(users.c.user_id == check_lender)
            username = conn.execute(fetch_u).scalar()
        if check_lender is None and check_borrower is not None:
            user_tag = "borrower"
            fetch_u = select(users.c.username).where(users.c.user_id == check_borrower)
            username = conn.execute(fetch_u).scalar()
    await manager.connect(borrow_id, websocket)
    try:
        has_fetched = False

        while True:
            if not has_fetched:
                with engine.begin() as conn:
                    fetch_msgs = (select(chat_room,
                                         case((chat_room.c.lender_id.is_not(None), chat_room.c.lender_id),
                                              else_=chat_room.c.borrower_id).label("identity"))
                                  .where(chat_room.c.borrow_id == borrow_id)
                                  .order_by(chat_room.c.message_id.desc())
                                  .limit(10))
                    fetchings = conn.execute(fetch_msgs)

                    message_history = []
                    history_usernames = []
                    for fetch in fetchings:
                        fetch_username = (select(users.c.username)
                                          .where(users.c.user_id == fetch.identity))
                        history_username = conn.execute(fetch_username).scalar()
                        history_usernames.append(history_username)
                        message_history.append(fetch.message)
                    for index in range(len(message_history)):
                        await manager.broadcast(borrow_id,
                                                f"{history_usernames[index]}: {message_history[index]}")
                    has_fetched = True

            data = await websocket.receive_text()


            with engine.begin() as conn:
                if user_tag == "lender":
                    insert_msg = chat_room.insert().values(borrow_id=borrow_id, lender_id=client_id,
                                                           message=data)
                    conn.execute(insert_msg)
                elif user_tag == "borrower":
                    insert_msg = chat_room.insert().values(borrow_id=borrow_id, borrower_id=client_id,
                                                           message=data)
                    conn.execute(insert_msg)

            await manager.broadcast(borrow_id, f"{username} [{user_tag}]: {data}")
    except WebSocketDisconnect:
        manager.disconnect(borrow_id, websocket)
        await manager.broadcast(borrow_id, f"{username} has left the chat")

@ws_router.get("/urls_for_chat")
async def urls_for_chat(request: Request, user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        select_borrows = (select(borrows.c.borrow_id).where(borrows.c.borrower_id == user_id,
                                                     borrows.c.has_finished == False,
                                                     borrows.c.has_shipped == True))
        borrow_ids = conn.execute(select_borrows).scalars().all()

        urls = []
        for id_ in borrow_ids:
            ws_url = request.url_for("lender_borrower_chat", borrow_id=id_).replace(scheme="ws")
            urls.append(str(ws_url))

    return urls

@ws_router.post("/upload_insurance_image/{borrow_id}")
async def upload_insurance_image(insurance_image: UploadFile, borrow_id: int,
                                 user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        borrower_id_f = select(borrows.c.borrower_id).where(borrows.c.borrower_id == user_id,
                                                          borrows.c.borrow_id == borrow_id)
        borrower_id = conn.execute(borrower_id_f).scalar()
        if borrower_id is None:
            raise HTTPException(400, "you are not the borrower for this deal")

        check_days = select(day_counter.c.day_count).where(day_counter.c.borrow_id == borrow_id)
        days = conn.execute(check_days).scalar()

        if days is None:
            raise HTTPException(400, "dude, your borrow period hasn't even started yet")

        if days == 0:
            raise HTTPException(400, "chill, you gotta upload image on saturday")
        if days % 7 == 0:
            raise HTTPException(400, "you're a day too late")

        if (days+1) % 7 == 0:
            if insurance_image.size > 5_500_000:
                raise HTTPException(400, "file size is too big")
            file_format = Path(insurance_image.filename).suffix
            accepted_formats = [".jpg", ".png", ".jpeg"]
            if file_format not in accepted_formats:
                raise HTTPException(400, "the image file needs to be either a JPEG or PNG")

            new_filename = f"{uuid.uuid4()}{file_format}"
            borrow_dir = Path(f"insurance_images/borrow_{borrow_id}")
            if not borrow_dir.is_dir():
                borrow_dir.mkdir(parents=True, exist_ok=True)

            destination_path = borrow_dir / new_filename
            try:
                with destination_path.open("wb") as buffer:
                    shutil.copyfileobj(insurance_image.file, buffer)
            finally:
                insurance_image.file.close()
        else:
            raise HTTPException(400, "it's not saturday of this week yet")


    return "image uploaded successfully for this week"

@ws_router.get("/urls_for_uploading_insurance_images")
async def urls_for_uploading_insurance_images(user_id: Annotated[str, Depends(helper_jwt)], request: Request):
    with engine.begin() as conn:
        select_borrows = (select(borrows.c.borrow_id).where(borrows.c.borrower_id == user_id,
                                                     borrows.c.has_finished == False,
                                                     borrows.c.has_shipped == True))
        borrow_ids = conn.execute(select_borrows).scalars().all()

        urls = []
        for id_ in borrow_ids:
            urls.append(str(request.url_for("upload_insurance_image", borrow_id=id_)))
    return urls

@ws_router.get("/see_uploaded_images")
async def see_uploaded_images(user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        mega_dict = {}
        borrow_ids_f = select(borrows.c.borrow_id).where(borrows.c.lender_id == user_id)
        borrow_ids = conn.execute(borrow_ids_f).scalars().all()

        for id_ in borrow_ids:
            path = Path(f"insurance_images/borrow_{id_}")
            formats = [".png", ".jpg", ".jpeg"]
            images = []

            for file in path.glob("*"):
                if file.suffix.lower() in formats:
                    image = Image.open(file)
                    exif_data = image.getexif()
                    if exif_data.get(36867):
                        capture_date = exif_data.get(36867)
                    elif exif_data.get(306):
                        capture_date = exif_data.get(306)
                    else:
                        capture_date = "not found"

                    images.append(
                        {"img": f"http://127.0.0.1:8000/item_images/borrow_{id_}/{file.name}",
                         "capture_date": capture_date
                         })

            item_name_f = (select(items.c.item_name).join(borrows, items.c.item_id == borrows.c.item_id)
                         .where(borrows.c.borrow_id == id_))
            item_name = conn.execute(item_name_f).scalar()

            mega_dict[item_name] = images
    return mega_dict

@ws_router.post("/return_item/{borrow_id}")
async def return_item(user_id: Annotated[str, Depends(helper_jwt)], borrow_id: int):
    with engine.begin() as conn:
        borrower_id_f = select(borrows.c.borrower_id).where(borrows.c.borrower_id == user_id,
                                                            borrows.c.borrow_id == borrow_id)
        borrower_id = conn.execute(borrower_id_f).scalar()
        if borrower_id is None:
            raise HTTPException(400, "you are not the borrower for this deal")

        check_days = select(day_counter.c.day_count).where(day_counter.c.borrow_id == borrow_id)
        days = conn.execute(check_days).scalar()
        weeks_borrowed_f = select(borrows.c.weeks_borrowed).where(borrows.c.borrow_id == borrow_id)
        weeks_borrowed = conn.execute(weeks_borrowed_f).scalar()

        if days is None:
            raise HTTPException(400, "dude, your borrow period hasn't even started yet")

        if days % 7 == 0:
            weeks = days // 7
            if weeks == weeks_borrowed:
                update_row = borrows.update().values(is_returned=True).where(borrows.c.borrow_id == borrow_id,
                                                                             borrows.c.borrower_id == user_id)
                conn.execute(update_row)
            elif weeks < weeks_borrowed:
                raise HTTPException(400, "you're too early to return the item, has to be on "
                                         "sunday of the last week")
            else:
                raise HTTPException(400, "YOU'RE LATE, a bounty has been placed on your head")
        else:
            borrow_days = weeks_borrowed * 7
            if days > borrow_days:
                raise HTTPException(400, "YOU'RE LATE, a bounty has been placed on your head")
            else:
                raise HTTPException(400, "you're too early to return the item, has to be on "
                                         "sunday of the last week")

    return "item returned successfully"