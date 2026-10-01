# make an app using fastapi where you can track the items that are:
# 1. borrowed from you
# 2. or lent to you

# there can also be a bundle of items counted as a single mega_item to be lent, borrowed or exchanged for another

# before an item or mega_item is lent to someone, an exact date of return must be agreed upon by both parties
# if the item is being lent for more than 7 days, then the borrower must provide pictures of the item every
# week showing the item is not broken, failure to do so would mean breach of contract
# if an item is being withheld by a borrower past the return date, then that is a breach of contract
# the contract by default restricts the borrower from becoming a lien (google this shit) and it must be signed
# before the borrowing is executed
# ALSO, the lender can choose to have the item remain to the borrower for free or charge a fee every week
# along with the conditions above

# actually no, the minimum for lending an item is one week

from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, Boolean, select, ForeignKey, update, delete, CheckConstraint
from sqlalchemy.dialects.postgresql import insert
import os
from dotenv import load_dotenv
from typing import Annotated, Optional
from auth_utils import helper_jwt, router as auth_router
from pydantic import BaseModel, Json
import shutil
from pathlib import Path
from database import engine, users, items, interested, megaitems, proof_images, borrows, day_counter
import uvicorn
from urllib.parse import quote
import uuid
from websocket_et_al import ws_router

load_dotenv("private.env")
app = FastAPI()
app.include_router(auth_router)
app.include_router(ws_router)
app.mount("/item_images", StaticFiles(directory="item_images"), name="item_images")

class Address(BaseModel):
    addr: str

@app.post("/set_shipping_address")
async def set_shipping_address(address: Address, user_id: Annotated[str, Depends(helper_jwt)]):
    if address.addr.strip() == "":
        raise HTTPException(400, "you gotta write your address")
    with engine.begin() as conn:
        insert_addr = (update(users).where(users.c.user_id == user_id)
                       .values(shipping_address=address.addr))
        conn.execute(insert_addr)
    return 200

async def check_shipping_address(request: Request, user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        ship_addr = select(users.c.shipping_address).where(users.c.user_id == user_id)
        result = conn.execute(ship_addr).scalar()
        if result is None:
            raise HTTPException(400, f"you gotta have the shipping address: "
                                     f"{str(request.url_for('set_shipping_address'))}")


class Item(BaseModel):
    item_name: str
    is_megaitem: bool
    subitem_list: Optional[list[str]] = None

@app.post("/post_item", dependencies=[Depends(check_shipping_address)])
async def post_item(item: Json[Item], item_image: UploadFile, user_id: Annotated[str, Depends(helper_jwt)]):
    # i used this json[] thing cause postman/my code was bugging with 422 unprocessable content
    if item_image.size > 3_500_000:
        raise HTTPException(413, "image size is too big")
    if item.is_megaitem and not item.subitem_list:
        raise HTTPException(400, "if it's a megaitem, you gotta say what items are within it")
    if not item.is_megaitem and item.subitem_list:
        raise HTTPException(400, "we don't need this extra shit when it's not a megaitem")

    file_format = Path(item_image.filename).suffix
    accepted_formats = [".jpg", ".png", ".jpeg"]
    if file_format not in accepted_formats:
        raise HTTPException(400, "the image file needs to be either a JPEG or PNG")

    new_filename = f"{uuid.uuid4()}{file_format}"

    user_dir = Path(f"item_images/user_{user_id}")
    if not user_dir.is_dir():
        user_dir.mkdir(parents=True, exist_ok=True)

    destination_path = user_dir / new_filename

    try:
        with destination_path.open("wb") as buffer:
            shutil.copyfileobj(item_image.file, buffer) # false warning
    finally:
        item_image.file.close()

    with engine.begin() as conn:
        insert_item = (items.insert().values(user_id=user_id, image_filename=new_filename,
                                             item_name=item.item_name, is_megaitem=item.is_megaitem))
        result = conn.execute(insert_item)
        item_id = result.inserted_primary_key[0]
    if item.is_megaitem and item.subitem_list:
        with engine.begin() as conn:
            for subitem in item.subitem_list:
                insert_subitem = megaitems.insert().values(item_id=item_id, subitem_name=subitem)
                conn.execute(insert_subitem)

    return 200

@app.get("/show_item_listings", dependencies=[Depends(check_shipping_address)])
async def show_item_listings(user_id: Annotated[str, Depends(helper_jwt)], request: Request, offset_val: int = None):
    if offset_val is None:
        offset_val = 0
    with engine.begin() as conn:
        filtering = select(borrows.c.item_id)

        # this means where item_ids from items table is not in item_ids from borrow table
        # ~ means not

        # and the "items.c.user_id != user_id" for the user to not see their own items that they listed
        # for lending

        select_items = (select(items).limit(20)
                        .where(~items.c.item_id.in_(filtering), items.c.user_id != user_id)
                        .order_by(items.c.item_id.desc()).offset(offset_val))

        proxy_list = conn.execute(select_items)
        item_list = []
        for row in proxy_list:
            img_url = f"http://127.0.0.1:8000/item_images/user_{row.user_id}/{quote(row.image_filename)}"
            item_list.append({"item_id": row.item_id,
                              "item_name": row.item_name, "is_megaitem": row.is_megaitem,
                              "image_url": img_url,
                              "listing_url": str(request.url_for("item_listing",
                                                                 item_id=row.item_id,
                                                                 item_name=quote(row.item_name))
                                                 .include_query_params(image_url=img_url,
                                                                       is_megaitem=row.is_megaitem))})
    return item_list, (str(request.url_for("show_item_listings")
                           .include_query_params(offset_val=offset_val+20)))

@app.get("/item_listing/{item_id}/{item_name}", dependencies=[Depends(helper_jwt), Depends(check_shipping_address)])
async def item_listing(request: Request, item_id, item_name, image_url: str = None, is_megaitem: bool = None):
    with engine.begin() as conn:
        proxy_select = select(borrows.c.item_id).where(borrows.c.item_id == item_id)
        is_in_borrows = conn.execute(proxy_select).scalar()
        if is_in_borrows is not None:
            raise HTTPException(400, "this item is not available anymore :(")
    bundle = [item_id, item_name, image_url, is_megaitem]
    interest_url = str(request.url_for("show_interest", item_id=item_id))
    return bundle, interest_url

class Comment(BaseModel):
    cmnt: str

@app.post("/show_interest/{item_id}", dependencies=[Depends(check_shipping_address)])
async def show_interest(item_id, comment: Comment, user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        proxy_select = select(borrows.c.item_id).where(borrows.c.item_id == item_id)
        is_in_borrows = conn.execute(proxy_select).scalar()
        if is_in_borrows is not None:
            raise HTTPException(400, "this item is not available anymore :(")

        insert_interest = interested.insert().values(item_id=item_id, user_id=user_id, comment=comment.cmnt)
        conn.execute(insert_interest)
    return 200


@app.get("/view_interests_all", dependencies=[Depends(check_shipping_address)])
async def view_interests_all(user_id: Annotated[str, Depends(helper_jwt)], request: Request):
    with engine.begin() as conn:
        select_items = select(items).where(items.c.user_id == user_id)
        exc_items = conn.execute(select_items)
        items_to_seekers = {}
        for item in exc_items:
            items_to_seekers[item.item_name] = []
            seeker_index = 0

            select_seekers = (select(interested.c.user_id, interested.c.comment)
                              .where(interested.c.item_id == item.item_id))
            seekers = conn.execute(select_seekers)
            for seeker in seekers:
                items_to_seekers[item.item_name].append({"username": None, "comment": None, "item_id": None,
                                                         "link": None})

                items_to_seekers[item.item_name][seeker_index]["comment"] = seeker.comment
                select_username = select(users.c.username).where(users.c.user_id == seeker.user_id)
                username = conn.execute(select_username).scalar()
                items_to_seekers[item.item_name][seeker_index]["username"] = username
                items_to_seekers[item.item_name][seeker_index]["item_id"] = item.item_id
                items_to_seekers[item.item_name][seeker_index]["link"] = str(request.url_for
                                                                             ("select_candidate_to_lend",
                                                                              b_username=username,
                                                                              item_id=item.item_id))
                seeker_index += 1
    return items_to_seekers


class WeekPlan(BaseModel):
    weeks_lent: int
    weekly_payment: float

@app.post("/select_candidate_to_lend/{b_username}/{item_id}", dependencies=[Depends(check_shipping_address)])
async def select_candidate_to_lend(user_id: Annotated[str, Depends(helper_jwt)], b_username, item_id,
                                   week: WeekPlan):
    with engine.begin() as conn:
        fetch_borrower_id = select(users.c.user_id).where(users.c.username == b_username)
        borrower_id = conn.execute(fetch_borrower_id).scalar()



        if borrower_id is None:
            raise HTTPException(400, "dude, you messed with the username in the URL")
        item_exists = select(items.c.item_id).where(items.c.item_id == item_id,
                                                    items.c.user_id == user_id)
        item_exist = conn.execute(item_exists).scalar()
        if item_exist is None:
            raise HTTPException(400, "dude, you messed with the item_id in the URL")
        borrow_row_exists = (select(borrows.c.borrow_id).where(borrows.c.lender_id == user_id,
                                                               borrows.c.item_id == item_id))
        row_exists = conn.execute(borrow_row_exists).scalar()
        if row_exists:
            raise HTTPException(400, "you've already offered another for the item, you can only"
                                     " make one offer per item")
        b_interested_in_item = (select(interested.c.user_id)
                                       .where(interested.c.user_id == borrower_id,
                                              interested.c.item_id == item_id))
        borrower_interested_in_item = conn.execute(b_interested_in_item).scalar()
        if borrower_interested_in_item is None:
            raise HTTPException(400, "dude, you can't just tamper with the URL")



        fetch_lender_addr = select(users.c.shipping_address).where(users.c.user_id == user_id)
        lender_addr = conn.execute(fetch_lender_addr).scalar()

        borrow_offer = (borrows.insert().values(
            lender_id=user_id, borrower_id=borrower_id,
            item_id=item_id, weeks_borrowed=week.weeks_lent,
            payment_per_week=week.weekly_payment, lender_address=lender_addr,
            is_counting=False, is_returned=False
        ))
        conn.execute(borrow_offer)

    return 200

@app.get("/check_for_offers")
async def check_for_offers(user_id: Annotated[str, Depends(helper_jwt)], request: Request):
    with engine.begin() as conn:
        check_offers = select(borrows).where(borrows.c.borrower_id == user_id,
                                             borrows.c.current_week.is_(None), borrows.c.has_finished.is_(None),
                                             borrows.c.borrower_address.is_(None), borrows.c.has_shipped.is_(None),
                                             borrows.c.is_counting.is_(False), borrows.c.is_returned.is_(False))
        offers = conn.execute(check_offers)
        offers_list = []
        for offer in offers:
            get_item_name = select(items.c.item_name).where(items.c.item_id == offer.item_id)
            item_name = conn.execute(get_item_name).scalar()
            get_lender_name = select(users.c.username).where(users.c.user_id == offer.lender_id)
            lender_name = conn.execute(get_lender_name).scalar()
            weeks_borrowed = offer.weeks_borrowed
            payment = offer.payment_per_week
            if payment == 0:
                payment = "Free"
            offer_dict = {"acceptance_url": str(request.url_for('accept_offer', offer_id=offer.borrow_id)),
                          "rejection_url": str(request.url_for('reject_offer', offer_id=offer.borrow_id)),
                          "item_name": item_name,
                          "lender_name": lender_name,
                          "weeks_borrowed": weeks_borrowed, "payment_per_week": payment}
            offers_list.append(offer_dict)
    return offers_list

@app.post("/accept_offer/{offer_id}")
async def accept_offer(offer_id: int, user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        borrower_id_f = select(borrows.c.borrower_id).where(borrows.c.borrower_id == user_id,
                                                            borrows.c.borrow_id == offer_id)
        borrower_id = conn.execute(borrower_id_f).scalar()
        if borrower_id is None:
            raise HTTPException(400, "you are not the borrower for this deal")

        lender_check = select(borrows.c.lender_id).where(borrows.c.borrow_id == offer_id)
        lender_id = conn.execute(lender_check).scalar()
        if user_id == lender_id:
            raise HTTPException(400, "dude, you're the lender, you can't accept your own offer")

        get_item_id = select(borrows.c.item_id).where(borrows.c.borrow_id == offer_id)
        item_id = conn.execute(get_item_id).scalar()
        if item_id is None:
            raise HTTPException(400, "looks like you fiddled with the path parameter")
        delete_interest = delete(interested).where(interested.c.item_id == item_id,
                                                   interested.c.user_id == user_id)
        conn.execute(delete_interest)

        b_address = select(users.c.shipping_address).where(users.c.user_id == user_id)
        borrower_address = conn.execute(b_address).scalar()
        row_full = (update(borrows).where(borrows.c.borrow_id == offer_id)
                          .values(current_week=0, has_finished=False,
                                  borrower_address=borrower_address, has_shipped=True, is_counting=False))
        conn.execute(row_full)

        day_count_insert = insert(day_counter).values(borrow_id=offer_id, day_count=0)
        conn.execute(day_count_insert)
        # here, has_shipped becomes true, which would in turn allow the while loop to run
        # i didn't implement any actual shipping logic cause that's too advanced for me at this point
    return f"trust the email: {os.environ.get('SENDER_EMAIL')}, so it can send you critical intel"

@app.delete("/reject_offer/{offer_id}")
async def reject_offer(offer_id: int, user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        offer_given_to_user = (select(borrows.c.borrow_id)
                                  .where(borrows.c.borrow_id == offer_id,
                                         borrows.c.borrower_id == user_id, borrows.c.has_shipped.is_(None)))
        is_offer_given_to_user = conn.execute(offer_given_to_user).scalar()
        if is_offer_given_to_user is None:
            raise HTTPException(400, "this is not yours offer to reject")

        get_item_id = select(borrows.c.item_id).where(borrows.c.borrow_id == offer_id)
        item_id = conn.execute(get_item_id).scalar()
        delete_interest = delete(interested).where(interested.c.item_id == item_id,
                                                   interested.c.user_id == user_id)
        conn.execute(delete_interest)

        get_lender_id = select(borrows.c.lender_id).where(borrows.c.borrower_id == user_id,
                                                          borrows.c.item_id == item_id)
        lender_id = conn.execute(get_lender_id).scalar()
        delete_offer = delete(borrows).where(borrows.c.borrower_id == user_id,
                                             borrows.c.item_id == item_id, borrows.c.lender_id == lender_id)
        conn.execute(delete_offer)
    return 200

@app.get("/check_offer_status")
async def check_offer_status(user_id: Annotated[str, Depends(helper_jwt)]):
    with engine.begin() as conn:
        select_statuses = select(borrows).where(borrows.c.current_week == 0,
                                                borrows.c.lender_id == user_id)
        statuses = conn.execute(select_statuses)
        status_dict = {}
        for status in statuses:
            select_username = select(users.c.username).where(users.c.user_id == status.borrower_id)
            username = conn.execute(select_username).scalar()
            select_item_name = select(items.c.item_name).where(items.c.item_id == status.item_id)
            item_name = conn.execute(select_item_name).scalar()
            status_dict[status.borrower_id] = f"{username} has accepted your offer for {item_name}"
        if not status_dict:
            return "no candidates have accepted your offers"
    return status_dict


@app.get("/ghost_ping")
async def ghost_ping():
    return 200


if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)