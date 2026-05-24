# Bug type: undefined variable
# Expected: compute and print the average of a list
# Actual: NameError — 'total' is not defined

def average(numbers):
    for n in numbers:
        running_total += n          # 'running_total' never initialised
    return running_total / len(numbers)

data = [10, 20, 30, 40, 50]
print("Average:", average(data))
