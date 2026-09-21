def forward_outcome(closes, index, horizons=(1,5,20)):
    entry=closes[index]
    out={}
    for h in horizons:
        j=index+h
        if j>=len(closes): continue
        change=(closes[j]/entry-1)*100 if entry else None
        out[h]=change
    return out

def event_record(symbol,timeframe,index,expected,closes):
    return {"symbol":symbol,"timeframe":timeframe,"index":index,
            "what_robi_expected":expected,
            "outcomes_pct":forward_outcome(closes,index)}
