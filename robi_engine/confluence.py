from .models import Evidence

def classify(evidence):
    bull=[e for e in evidence if e.direction=="bullish"]
    bear=[e for e in evidence if e.direction=="bearish"]
    neutral=[e for e in evidence if e.direction not in {"bullish","bearish"}]
    if bull and bear:
        state="CONFLICT"
    elif bull:
        state="BULLISH_EVIDENCE"
    elif bear:
        state="BEARISH_EVIDENCE"
    else:
        state="NEUTRAL"
    return {"state":state,"supporting":[e.__dict__ for e in bull+bear],
            "neutral":[e.__dict__ for e in neutral],
            "conflicting": [e.__dict__ for e in (bull if bear else [])] if bull and bear else []}
