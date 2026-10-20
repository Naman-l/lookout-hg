# organism/dev

Developer tools and test fixtures, not used by the running app: `fakes.py` (in-memory stand-ins for the services, loaded only when `LOOKOUT_FAKE_SERVICES=1`, as the unit tests do), `smoke.py` (`make smoke-agent`), `fire.py` and `bench.py` (work an item or the whole bench live and print the story). Each CLI needs the item key: there is no default. They may name Halden's items; nothing outside this folder does.
