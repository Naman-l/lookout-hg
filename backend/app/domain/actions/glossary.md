<!-- tables: actions, outbox, run_actions -->
- Nothing leaves the system without a person. An **action** is a draft (to a supplier, a supplier link) that waits for approval; approving binds a hash of the exact text, an edit voids it, and sending is simulated into an outbox. A note is a recorded decision, not a send.
- A request goes only to the supplier's contact on file, never to an address found in a message.
