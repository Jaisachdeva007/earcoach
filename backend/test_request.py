"""
Manual smoke test: hits /hint with a fake stuck-event so you can hear the
audio without launching VS Code. Run with:

    python test_request.py
"""

import json
import urllib.request

PAYLOAD = {
    "trigger": "long_pause",
    "language": "python",
    "file_name": "reverse_list.py",
    "cursor_line": 4,
    "code": (
        "def reverse_list(items):\n"
        "    out = []\n"
        "    for i in range(len(items)):\n"
        "        out.append(items[len(items) - i])\n"
        "    return out\n"
        "\n"
        "print(reverse_list([1, 2, 3]))\n"
    ),
    "diagnostics": [
        {
            "message": "IndexError: list index out of range",
            "line": 4,
            "severity": "error",
            "source": "python",
        }
    ],
}

req = urllib.request.Request(
    "http://localhost:8000/hint",
    data=json.dumps(PAYLOAD).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.read().decode("utf-8"))
