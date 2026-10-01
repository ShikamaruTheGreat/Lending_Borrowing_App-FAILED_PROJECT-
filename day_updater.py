import asyncio
import httpx
from database import engine, day_counter, select, update, borrows, proof_images, users, items
from sqlalchemy.dialects.postgresql import insert
import os
from dotenv import load_dotenv
import smtplib
from threat_assessment import threat_assessor

load_dotenv("private.env")

async def start_countdowns():
    with engine.begin() as conn:
        select_borrows = (select(borrows.c.borrow_id).where(borrows.c.has_shipped == True,
                                                borrows.c.current_week == 0, borrows.c.is_counting == False,
                                                borrows.c.is_returned == False, borrows.c.has_finished == False))
        borrow_ids = conn.execute(select_borrows).scalars().all()
        for b_id in borrow_ids:
            update_counting = update(borrows).where(borrows.c.borrow_id == b_id).values(is_counting=True)
            conn.execute(update_counting)
            asyncio.create_task(countdown(b_id))
            asyncio.create_task(send_pings_email(b_id))
    # issue: how can i call this function on an interval without it making duplicate tasks
    # two different issues:
    # 1. how can i call this on an interval basis -- DONE
    # 2. how can i avoid duplicate tasks -- DONE

async def countdown(borrow_id: int):
    increment = 0
    while True:
        with engine.begin() as conn:
            select_days = select(day_counter.c.day_count).where(day_counter.c.borrow_id == borrow_id)
            days = conn.execute(select_days).scalar()

            if days is None:
                days = 0

            if days > 0 and days % 7 == 0:
                weeks = days // 7
                update_curr_week = (update(borrows).where(borrows.c.borrow_id == borrow_id)
                                    .values(current_week=weeks))
                conn.execute(update_curr_week)

            select_curr_week = select(borrows.c.current_week).where(borrows.c.borrow_id == borrow_id)
            curr_week = conn.execute(select_curr_week).scalar()
            select_weeks_borrowed = select(borrows.c.weeks_borrowed).where(borrows.c.borrow_id == borrow_id)
            weeks_borrowed = conn.execute(select_weeks_borrowed).scalar()

            returned = select(borrows.c.is_returned).where(borrows.c.borrow_id == borrow_id)
            is_returned = conn.execute(returned).scalar()

            if curr_week == weeks_borrowed:
                finish_update = (update(borrows).where(borrows.c.borrow_id == borrow_id)
                                 .values(has_finished=True, is_counting=False))
                conn.execute(finish_update)

                # then in later functions that checks the borrower's legitimacy, the inequivalence
                # between the number of weeks and number of inserted rows of proof_images would argue against it
                # (i know this method isn't exactly the cleanest or the best, but i can't think of anything
                # else to do this, within my current setup)
                folder_path = f"insurance_images/borrow_{borrow_id}"

                try:
                    with os.scandir(folder_path) as entries:
                        fetch_item_id = select(borrows.c.item_id).where(borrows.c.borrow_id == borrow_id)
                        item_id = conn.execute(fetch_item_id).scalar()
                        for entry in entries:
                            if entry.is_file():
                                new_filename = entry.name
                                insert_proof = (proof_images.insert()
                                                .values(item_id=item_id, borrow_id=borrow_id, filename=new_filename))
                                conn.execute(insert_proof)
                except FileNotFoundError:
                    pass

                if not is_returned:
                    await threat_assessor(borrow_id)

                break

        await asyncio.sleep(86400) # might needa remove this
        increment += 1
        try:
            httpx.get("http://127.0.0.1:8000/ghost_ping")

            with engine.begin() as conn:
                insert_counter = insert(day_counter).values(borrow_id=borrow_id)
                do_nothing = insert_counter.on_conflict_do_nothing(index_elements=["borrow_id"])
                conn.execute(do_nothing)
                update_day = (update(day_counter).where(day_counter.c.borrow_id == borrow_id)
                              .values(day_count=day_counter.c.day_count + increment))
                conn.execute(update_day)
            increment = 0
        except httpx.ConnectError:
            continue

async def send_pings_email(borrow_id: int):
    with engine.begin() as conn:
        days_f = select(day_counter.c.day_count).where(day_counter.c.borrow_id == borrow_id)
        days = conn.execute(days_f).scalar()

        if days is None:
            return

        if days > 0 and days % 7 == 0:
            return

        elif days > 0 and (days+1) % 7 == 0:
            borrower_id_f = select(borrows.c.borrower_id).where(borrows.c.borrow_id == borrow_id)
            borrower_id = conn.execute(borrower_id_f).scalar()
            email_f = select(users.c.email).where(users.c.user_id == borrower_id)
            email = conn.execute(email_f).scalar()

            item_name_f = (select(items.c.item_name).join(borrows, items.c.item_id == borrows.c.item_id)
                         .where(borrows.c.borrow_id == borrow_id))
            item_name = conn.execute(item_name_f).scalar()

            # the sender email must have 2-step verification on or smth
            sender = os.environ.get("SENDER_EMAIL")
            receiver = email
            password = os.environ.get("SENDING_PASSWORD")
            subject = "REMINDER: upload an insurance image today for the week"
            body = f"for {item_name} that you borrowed, upload TODAY"
            message = f"""
            From: The Borrower Lender App {sender}
            To: {receiver}
            Subject: {subject}\n
            {body}
            """
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            try:
                server.login(sender, password)
                server.sendmail(sender, receiver, message)
                print(f"email has been sent to {receiver}")
            except smtplib.SMTPAuthenticationError:
                print(f"couldn't sign in to send mail to {receiver}")
        else:
            return

async def main_loop():
    while True:
        await start_countdowns()
        await asyncio.sleep(86400)

if __name__ == "__main__":
    asyncio.run(main_loop())