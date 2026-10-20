# Watcher

One event stream for the app, the agents and the scenarios (`backend/app/watcher.py` writes it; this folder reads it).

    python -m watcher.correlate <run_id>     one run's story, from request to finish
    make scenarios                           fire, injection, fraud on a fresh app playing recordings; each read back from the stream
    make scenario S=fire                     the same against the running app
