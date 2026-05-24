# Bug type: off-by-one list indexing
# Expected: print each item in the list
# Actual: IndexError on last iteration

def print_items(items):
    for i in range(len(items) + 1):   # should be range(len(items))
        print(items[i])

scores = [88, 92, 75, 61, 99]
print_items(scores)
