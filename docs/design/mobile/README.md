# Lookout on a phone

Frozen baseline: `frozen-mocks.png` (six screens at 390×844: Today, Item with the approve sheet, Flashcard, Part at the shelf, Ask by voice, Dates). It is the same web app, installable, not a native app.

- **Shell (this PR).** Under 760 px the sidebar becomes five tabs in the thumb zone: Today, Approvals, Ask, Records, More. Ask focuses the one-line Ask box, so the screen's context goes with the question. Records and More list every section the desktop sidebar holds.
- **Installable.** `assets/manifest.webmanifest`, icons, standalone mode. On iPhone it installs from Share → Add to Home Screen.
- **Offline reads.** `sw.js` keeps the last-read screens readable and says "Offline: showing what was last read at hh:mm". It never caches or replays a write: approving needs a connection, and the approve call keeps its payload hash and its 409s. Production builds only.
- **Not in this baseline (Phase 2).** Hand an item to a teammate with a note, ask the agent for a report, saving the steward's answers, push notifications.
- **Not verified on a device.** Voice in the installed iPhone app, and the storage-eviction window for sites that are not installed. iPhone Safari has no BarcodeDetector, so scanning shows only where the browser supports it.
