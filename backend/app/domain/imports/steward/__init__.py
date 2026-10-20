"""The Data steward: an agent that onboards a file the standard pipeline has not seen before.

Code profiles the file and reports its drift from the known export; the steward (a model) reads that, writes one
normaliser step, and tries it in DOMAIN's sandbox; code checks the result the way the load gate does. Nothing here
loads data: the output is a proposed step, findings and flashcard questions for a person.
"""
