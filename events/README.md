# Shared event store

Filings from the extraction runs grouped into corporate-action events, for any agent to use.

| File | What it does |
|---|---|
| `store.py` | Loads rights offerings, mergers and tender offers into `Event`s and shows an event as of any date. Copied from `agents/client_briefing/event_store.py`. |
| `versioning.py` | Replays an event's filings in order and lists what each one changed. Used by the amendment impact agent. |
| `parsers.py` | Turns extracted text into dates, prices and ratios. Copied from the briefing agent. |
| `config.py` | Input paths and the rights grouping window. |

How filings become events:

- **Tender offers:** one event per SEC file number. A new Schedule TO filed after the last offer expired starts a new event.
- **Mergers:** the same deal-specific file number (333-, 005-), or the same acquirer and target.
- **Rights offerings:** one issuer's filings, split when they are more than 120 days apart.

The client briefing agent still uses its own copy. A test in `agents/amendment_impact/tests` checks that both copies
build the same events. Moving the briefing agent onto this package is the next step, so a fix is made once.

```python
from events import load_events
from events.versioning import replay

for event in load_events(("tender_offer",)):
    for version in replay(event)[1:]:
        print(event.title, version.filing.form, [c.key for c in version.changes])
```
