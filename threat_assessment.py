from database import contact_breachers, engine, select, proof_images, borrows
from sqlalchemy import func

async def get_weeks_borrowed(borrow_id: int, conn):
    w_b = select(borrows.c.weeks_borrowed).where(borrows.c.borrow_id == borrow_id)
    weeks_borrowed = conn.execute(w_b).scalar()
    return weeks_borrowed

async def get_borrower_id(borrow_id: int, conn):
    b_id = select(borrows.c.borrower_id).where(borrows.c.borrow_id == borrow_id)
    breacher_id = conn.execute(b_id).scalar()
    return breacher_id

async def threat_assessor(borrow_id: int):
    with engine.begin() as conn:
        proxy = (select(func.count()).select_from(proof_images)
                           .where(proof_images.c.borrow_id == borrow_id))
        proof_img_count = conn.execute(proxy).scalar()
        weeks_borrowed = await get_weeks_borrowed(borrow_id, conn)
        breacher_id = await get_borrower_id(borrow_id, conn)

        if proof_img_count <= (weeks_borrowed / 2):
            insert_t = contact_breachers.insert().values(breacher_id=breacher_id, threat_level=2)
            conn.execute(insert_t)
        else:
            insert_t = contact_breachers.insert().values(breacher_id=breacher_id, threat_level=1)
            conn.execute(insert_t)