"""
EarCoach evaluation runner.
Sends all 5 buggy programs through the /hint endpoint 4 times each (20 events total).
Session logs are written automatically to ~/earcoach_sessions/
Run with:  python run_evaluation.py
"""

import json
import time
import urllib.request

PROGRAMS = [
    {
        "name": "01_off_by_one",
        "language": "python",
        "cursor_line": 7,
        "code": (
            "def print_items(items):\n"
            "    for i in range(len(items) + 1):\n"
            "        print(items[i])\n"
            "\n"
            "scores = [88, 92, 75, 61, 99]\n"
            "print_items(scores)\n"
        ),
        "diagnostics": [{"message": "IndexError: list index out of range",
                          "line": 3, "severity": "error", "source": "python"}],
    },
    {
        "name": "02_type_mismatch",
        "language": "python",
        "cursor_line": 5,
        "code": (
            "name = 'Alice'\n"
            "age = 21\n"
            "print('Hello ' + name + ', you are ' + age + ' years old.')\n"
        ),
        "diagnostics": [{"message": "TypeError: can only concatenate str (not 'int') to str",
                          "line": 3, "severity": "error", "source": "python"}],
    },
    {
        "name": "03_infinite_loop",
        "language": "python",
        "cursor_line": 3,
        "code": (
            "def countdown(n):\n"
            "    while n > 0:\n"
            "        print(n)\n"
            "\n"
            "countdown(5)\n"
        ),
        "diagnostics": [],
    },
    {
        "name": "04_wrong_conditional",
        "language": "python",
        "cursor_line": 4,
        "code": (
            "numbers = [3, 15, 7, 42, 9, 23, 5]\n"
            "for n in numbers:\n"
            "    if n < 10:\n"
            "        print(n)\n"
        ),
        "diagnostics": [],
    },
    {
        "name": "05_undefined_variable",
        "language": "python",
        "cursor_line": 4,
        "code": (
            "def average(numbers):\n"
            "    for n in numbers:\n"
            "        running_total += n\n"
            "    return running_total / len(numbers)\n"
            "\n"
            "data = [10, 20, 30, 40, 50]\n"
            "print('Average:', average(data))\n"
        ),
        "diagnostics": [{"message": "UnboundLocalError: local variable 'running_total' referenced before assignment",
                          "line": 3, "severity": "error", "source": "python"}],
    },
]

REPEATS = 4  # 5 programs x 4 = 20 events

def send_hint(program, run_number):
    payload = {
        "trigger": "manual",
        "language": program["language"],
        "file_name": program["name"] + ".py",
        "cursor_line": program["cursor_line"],
        "code": program["code"],
        "diagnostics": program["diagnostics"],
    }
    req = urllib.request.Request(
        "http://localhost:8000/hint",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read().decode("utf-8"))
            hint = result.get("hint", "(no hint returned)")
            print(f"  hint: {hint[:80]}...")
            return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

total = 0
for program in PROGRAMS:
    for i in range(1, REPEATS + 1):
        total += 1
        print(f"\n[{total}/20] {program['name']} — run {i}/{REPEATS}")
        ok = send_hint(program, i)
        if ok:
            print(f"  done")
        if total < 20:
            print(f"  waiting 5s before next request...")
            time.sleep(5)

print("\nAll 20 events complete. Check ~/earcoach_sessions/ for logs.")
