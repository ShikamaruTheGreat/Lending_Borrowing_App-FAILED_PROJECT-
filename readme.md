WHAT THE PROJECT WAS SUPPOSED TO DO:
- lender posts an item on the site
- borrower shows interest to it by writing a comment/letter to the lender
- lender selects the borrower from a pool of interested people, and decides the borrow period and
  how much or if the borrower has to pay money per week, in that case they'd be a renter
- selected borrower looks at these terms and can either reject or accept the deal
- once accepted the item just magically ships to them and the timer starts until the end of the borrow period
- in this borrow period the borrower has to send images to the lender every week on saturday symbolising as
- insurance that their item is not damaged
- at the end of the period they need to return the item back to the lender


this project was just too exhausting, like:

- the more i wrote, the more things (like database state and changes to the database)
  i had to fit forcefully in my mind altogether at all times or at least most times

- along with that, silent bugs kept piling on

it was also that i was doing new things or at least things that i weren't comfortable with yet, like:
- image uploading and showing via the web
- file handling, loading images in-memory, organising file structures, logic-bug handling regarding file names
- websockets
- an automatic while loop/asyncio thingy file where i just piled on a lot of dependent logic and conditional
  database changes

-> i think the main thing was that the:
   - database had many tables that were connected and were constantly updating and changing states based on
     other tables, maybe i couldnt handle that, or the many table alterations were above my skill-level
   - that caused my functions to be dependent on each other and had several implicit states that only kept
     increasing until i couldnt fit it into my head
   - also, setting the borrow periods as weeks was a bad idea