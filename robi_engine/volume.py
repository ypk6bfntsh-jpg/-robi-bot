def relative_volume(volumes, n=20):
    if not volumes or len(volumes)<n+1:return None
    baseline=sum(volumes[-n-1:-1])/n
    return None if baseline==0 else volumes[-1]/baseline

def volume_snapshot(volumes,n=20):
    rv=relative_volume(volumes,n)
    return {"current":volumes[-1] if volumes else None,"relative":rv,
            "spike": bool(rv is not None and rv>=2.0)}
