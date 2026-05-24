# Bug type: wrong conditional direction
# Expected: print only numbers greater than 10
# Actual: prints numbers less than or equal to 10 instead

numbers = [3, 15, 7, 42, 9, 23, 5]

for n in numbers:
    if n < 10:          # should be n > 10
        print(n)
