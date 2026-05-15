"""
EarCoach code runner.

Executes the student's code in a sandboxed subprocess and returns stdout,
stderr, and exit code. This catches runtime errors (IndexError, TypeError,
infinite loops, wrong output) that static analysis tools like Pylance miss.

Supports: Python, JavaScript (Node.js), Java (javac + java), C/C++ (gcc/g++)

Security: code runs in a subprocess with a hard timeout. No network
sandboxing — this is a local dev tool, not a public service.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Optional


TIMEOUT_S = 5  # kill the process after 5 seconds


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    language: str
    error_summary: str  # clean one-line summary for the LLM prompt

    def has_error(self) -> bool:
        return self.timed_out or self.exit_code != 0 or bool(self.stderr.strip())

    def __str__(self) -> str:
        if self.timed_out:
            return "Timed out (possible infinite loop)"
        if self.exit_code != 0 and self.stderr:
            return self.stderr.strip()
        if self.stdout:
            return f"Output: {self.stdout.strip()}"
        return "No output"


def run_code(language: str, code: str) -> Optional[RunResult]:
    """
    Run code and return a RunResult, or None if the language is unsupported
    or the required runtime isn't installed.
    """
    lang = language.lower()
    if lang == "python":
        return _run_python(code)
    elif lang in ("javascript", "typescript"):
        return _run_node(code, lang)
    elif lang == "java":
        return _run_java(code)
    elif lang in ("c", "cpp", "c++"):
        return _run_c(code, lang)
    return None


# ---------------------------------------------------------------------------
# Language runners

def _run_python(code: str) -> RunResult:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        return _exec(["python3", path], "python")
    finally:
        _rm(path)


def _run_node(code: str, lang: str) -> RunResult:
    if not _which("node"):
        return None  # type: ignore
    # Strip TypeScript type annotations for a quick JS run
    if lang == "typescript":
        code = _strip_ts_types(code)
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        return _exec(["node", path], lang)
    finally:
        _rm(path)


def _run_java(code: str) -> Optional[RunResult]:
    if not _which("javac"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "Main.java")
        with open(src, "w") as f:
            f.write(code)
        compile_result = _exec(["javac", src], "java")
        if compile_result.exit_code != 0:
            return compile_result
        return _exec(["java", "-cp", d, "Main"], "java")


def _run_c(code: str, lang: str) -> Optional[RunResult]:
    compiler = "g++" if lang in ("cpp", "c++") else "gcc"
    if not _which(compiler):
        return None
    suffix = ".cpp" if lang in ("cpp", "c++") else ".c"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as src:
        src.write(code)
        src_path = src.name
    out_path = src_path + ".out"
    try:
        compile_result = _exec([compiler, src_path, "-o", out_path], lang)
        if compile_result.exit_code != 0:
            return compile_result
        return _exec([out_path], lang)
    finally:
        _rm(src_path)
        _rm(out_path)


# ---------------------------------------------------------------------------
# Helpers

def _exec(cmd: list[str], language: str) -> RunResult:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        error_summary = _summarise_error(stderr, stdout, proc.returncode)
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode,
            timed_out=False,
            language=language,
            error_summary=error_summary,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            stdout="",
            stderr="",
            exit_code=-1,
            timed_out=True,
            language=language,
            error_summary="Code timed out after 5 seconds — possible infinite loop.",
        )


def _summarise_error(stderr: str, stdout: str, code: int) -> str:
    if not stderr and code == 0:
        return f"Ran successfully. Output: {stdout[:200]}" if stdout else "Ran successfully, no output."
    # Last two lines of stderr are usually the most useful (error type + location)
    lines = [l for l in stderr.splitlines() if l.strip()]
    return "\n".join(lines[-3:]) if lines else f"Exited with code {code}."


def _strip_ts_types(code: str) -> str:
    """Very rough TypeScript → JavaScript strip for quick execution."""
    import re
    code = re.sub(r":\s*(string|number|boolean|any|void|never|unknown)(\[\])?", "", code)
    code = re.sub(r"<[A-Z][a-zA-Z]*>", "", code)
    return code


def _which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


if __name__ == "__main__":
    test_code = textwrap.dedent("""\
        def reverse_list(lst):
            for i in range(len(lst)):
                lst[i] = lst[len(lst) - i]
            return lst

        print(reverse_list([1, 2, 3]))
    """)
    result = run_code("python", test_code)
    print(result)
