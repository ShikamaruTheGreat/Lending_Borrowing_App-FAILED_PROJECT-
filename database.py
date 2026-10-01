from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Float, Boolean,
                        select, ForeignKey, update, delete, insert, CheckConstraint,
                        UniqueConstraint, case, or_)
import os
from dotenv import load_dotenv

load_dotenv("private.env")
engine = create_engine(os.environ.get("DB_URL"))
meta = MetaData()

users = Table(
    "users",
    meta,
    Column("user_id", Integer, primary_key=True),
    Column("email", String, nullable=False),
    Column("username", String),
    Column("password", String),
    Column("shipping_address", String, unique=True)
)

items = Table(
    "items",
    meta,
    Column("item_id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.user_id")),
    Column("image_filename", String), # image filename
    Column("item_name", String, nullable=False),
    Column("is_megaitem", Boolean),
) # it has to be borrow_id XOR exchange_id, whichever one it is, the other one will be null

interested = Table(
    "interested",
    meta,
    Column("interested_id", Integer, primary_key=True),
    Column("item_id", Integer, ForeignKey("items.item_id")),
    Column("user_id", Integer, ForeignKey("users.user_id")),
    Column("comment", String),

    UniqueConstraint("item_id", "user_id", name="MAD")
    # this constraint means that the two columns promise that they will never appear as duplicate combinations
    # like, if one row has item_id=4 and user_id=15, then that combination will never appear again
    # this ensures that users can show interest in multiple items, but never the same item twice
)

megaitems = Table( # this table would unpack the megaitem into subitems
    "megaitems",
    meta,
    Column("megaitem_id", Integer, primary_key=True),
    Column("item_id", Integer, ForeignKey("items.item_id")),
    Column("subitem_name", String, nullable=False)
) # there are many megaitem_ids for one item_id

proof_images = Table( # any item held for more than a week comes here
    "proof_images",
    meta,
    Column("proof_id", Integer, primary_key=True),
    Column("item_id", Integer, ForeignKey("items.item_id")),
    Column("borrow_id", Integer, ForeignKey("borrows.borrow_id")),
    Column("filename", String),
) # if current_week == weeks_borrowed then no more rows from that item_id will be created
  # also, there are many image_ids to one item_id here
  # there needs to be an equal amount of rows here for the number of current_week in the borrows table

borrows = Table(
    "borrows",
    meta,
    Column("borrow_id", Integer, primary_key=True),
    Column("lender_id", Integer, ForeignKey("users.user_id"), nullable=False),
    Column("borrower_id", Integer, ForeignKey("users.user_id"), nullable=False),
    Column("item_id", Integer, ForeignKey("items.item_id")),
    Column("weeks_borrowed", Integer),
    Column("current_week", Integer),
    Column("has_finished", Boolean),
    Column("payment_per_week", Float), # this being 0 means there's no payment
    Column("borrower_address", String, ForeignKey("users.shipping_address")),
    Column("lender_address", String, ForeignKey("users.shipping_address")),
    Column("has_shipped", Boolean), # this if true starts a timer that counts days and updates
                                               # the current_week column
    Column("is_counting", Boolean),
    Column("is_returned", Boolean),

    CheckConstraint("lender_id <> borrower_id", name="differentiate_ownership"),
    CheckConstraint("borrower_address <> lender_address", name="differentiate_address")
) # if current_week == weeks_borrowed then has_finished will become true

day_counter = Table(
    "day_counter",
    meta,
    Column("borrow_id", Integer, ForeignKey("borrows.borrow_id"), primary_key=True),
    Column("day_count", Integer, default=0)
)

chat_room = Table(
    "chat_room",
    meta,
    Column("message_id", Integer, primary_key=True),
    Column("borrow_id", Integer, ForeignKey("borrows.borrow_id")),
    Column("lender_id", Integer, ForeignKey("users.user_id")),
    Column("borrower_id", Integer, ForeignKey("users.user_id")),
    Column("message", String),

    CheckConstraint("(lender_id IS NOT NULL AND borrower_id IS NULL) OR "
                    "(borrower_id IS NOT NULL AND lender_id IS NULL)", name="the_other_has_to_be_null")
)

contact_breachers = Table(
    "contact_breachers",
    meta,
    Column("breach_id", Integer, primary_key=True),
    Column("breacher_id", Integer, ForeignKey("users.user_id")),
    Column("threat_level", Integer)
    # threat_level = 1 if only return is delayed,
    # 2 if that and the proof image row count is less than or equals to half of the weeks_borrowed value
)

meta.create_all(engine)