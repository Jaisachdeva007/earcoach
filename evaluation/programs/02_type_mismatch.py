# Bug type: integer/string type mismatch
# Expected: print a greeting with the user's age
# Actual: TypeError — cannot concatenate str and int

name = "Alice"
age = 21

print("Hello " + name + ", you are " + age + " years old.")
# Fix: str(age)
