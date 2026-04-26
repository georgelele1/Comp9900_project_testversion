"""
Full test suite for Whispr refiner

Covers:
1. Single-turn cleaning + formatting
2. App-aware formatting
3. Session / follow-up awareness

Run:
    python tests/test_refiner_full.py
"""

from app import transcribe_and_enhance_impl
from agents.plugins.session import clear_session


# =========================================================
# Single-turn tests
# =========================================================

TEST_CASES = [
    {
        "name": "filler removal",
        "app": "Notes",
        "input": "uh so basically i think we should start the meeting now",
        "must_contain": ["I think", "start the meeting"],
        "must_not_contain": ["uh", "basically"],
    },
    {
        "name": "list formatting",
        "app": "Google Docs",
        "input": "first open the file then run the code and then check the output",
        "must_contain": ["1.", "2.", "3."],
        "must_not_contain": ["first open"],
    },
    {
        "name": "chat style",
        "app": "Slack",
        "input": "hey can you please send me the file when you have time",
        "must_contain": ["send me the file"],
        "must_not_contain": ["Subject:"],
    },
    {
        "name": "email generation",
        "app": "Mail",
        "input": "write an email to professor saying sorry i will be late today",
        "must_contain": ["sorry", "late"],
        "must_not_contain": ["uh"],
    },
    {
        "name": "terminal command",
        "app": "Terminal",
        "input": "install numpy pandas matplotlib",
        "must_contain": ["pip install", "numpy"],
        "must_not_contain": ["```"],
    },
    {
        "name": "meaning preserved",
        "app": "Notes",
        "input": "i do not want to skip the llm process",
        "must_contain": ["do not want"],
        "must_not_contain": ["skip the process"],
    },
]


# =========================================================
# Session / follow-up tests
# =========================================================

SESSION_TEST_CASES = [
    {
        "name": "shorten previous output",
        "turns": [
            ("Notes", "write a paragraph about why Whispr is useful"),
            ("Notes", "make it shorter"),
        ],
        "must_contain_last": ["Whispr"],
    },
    {
        "name": "politeness change",
        "turns": [
            ("Mail", "write an email to professor saying I will submit tomorrow"),
            ("Mail", "make it more polite"),
        ],
        "must_contain_last": ["professor", "submit"],
    },
    {
        "name": "add extra step",
        "turns": [
            ("Google Docs", "first check the dataset then train the model"),
            ("Google Docs", "also add evaluate the result"),
        ],
        "must_contain_last": ["evaluate"],
    },
]


# =========================================================
# Core check functions
# =========================================================

def check_case(case):
    result = transcribe_and_enhance_impl(
        audio_path="",
        app_name=case["app"],
        target_language="",
        _raw_text_override=case["input"],
    )

    output = result.get("final_text", "")

    print("\n" + "=" * 80)
    print(f"CASE: {case['name']}")
    print(f"APP: {case['app']}")
    print(f"INPUT: {case['input']}")
    print(f"OUTPUT: {output}")

    if not result.get("ok"):
        return False, f"Pipeline failed: {result.get('error')}"

    for text in case.get("must_contain", []):
        if text.lower() not in output.lower():
            return False, f"Missing: {text}"

    for text in case.get("must_not_contain", []):
        if text.lower() in output.lower():
            return False, f"Should not contain: {text}"

    return True, "PASS"


def check_session_case(case):
    clear_session()

    last_output = ""

    print("\n" + "=" * 80)
    print(f"SESSION CASE: {case['name']}")

    for app, text in case["turns"]:
        result = transcribe_and_enhance_impl(
            audio_path="",
            app_name=app,
            target_language="",
            _raw_text_override=text,
        )

        last_output = result.get("final_text", "")

        print(f"\nAPP: {app}")
        print(f"INPUT: {text}")
        print(f"OUTPUT: {last_output}")

        if not result.get("ok"):
            return False, f"Pipeline failed: {result.get('error')}"

    for text in case.get("must_contain_last", []):
        if text.lower() not in last_output.lower():
            return False, f"Missing in final turn: {text}"

    return True, "PASS"


# =========================================================
# Run tests
# =========================================================

def main():
    passed = 0
    failed = 0

    print("\n========== SINGLE TURN TESTS ==========")

    for case in TEST_CASES:
        ok, reason = check_case(case)

        if ok:
            print("✅ PASS")
            passed += 1
        else:
            print(f"❌ FAIL: {reason}")
            failed += 1

    print("\n========== SESSION TESTS ==========")

    for case in SESSION_TEST_CASES:
        ok, reason = check_session_case(case)

        if ok:
            print("✅ PASS")
            passed += 1
        else:
            print(f"❌ FAIL: {reason}")
            failed += 1

    print("\n" + "=" * 80)
    print(f"FINAL RESULT: {passed} passed, {failed} failed")

    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()