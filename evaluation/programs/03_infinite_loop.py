# Bug type: infinite loop — missing decrement
# Expected: countdown from 5 to 1
# Actual: runs forever (EarCoach times out at 5 s)

def countdown(n):
    while n > 0:
        print(n)
        # n -= 1 is missing

countdown(5)
