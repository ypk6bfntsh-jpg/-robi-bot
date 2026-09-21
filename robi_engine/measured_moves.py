def box_target(box_high,box_low,direction):
    h=box_high-box_low
    return box_high+h if direction=="up" else box_low-h

def swing_target(start,end,correction,direction):
    move=abs(end-start)
    return correction+move if direction=="up" else correction-move

def triangle_target(resistance,support,direction):
    h=resistance-support
    return resistance+h if direction=="up" else support-h
