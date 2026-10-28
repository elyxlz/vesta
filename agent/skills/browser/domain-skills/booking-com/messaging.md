# Booking.com: messaging a property and customer service

## Messaging the property by email

- "You have a message from <property>" emails come from `noreply@booking.com`. Replies to that address bounce, even though the footer says Booking processes replies.
- The working relay is the per-reservation address `<booking-number>-<token>@property.booking.com`, the sender of the "Your Request", "Your cancellation request", and "Special Request" emails. Reply to one of those to reach the property.

## Messaging Booking.com customer service

- Help Center > Continue without an account > enter the confirmation number > "Verify with email" (a code is emailed to the booker; the PIN is not accepted here) > Other topics > Something else > Message Customer Service.
- Success shows "Message sent. We'll respond as soon as possible via phone or email."
