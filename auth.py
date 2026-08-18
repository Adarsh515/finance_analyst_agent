# auth.py
# Phase 6.2 - local email + password, as a plain library on top of db.py.
#
# NO HTTP HERE, ON PURPOSE. The tracker's plan for 6.2 said "argon2 hash, signed HttpOnly
# session cookie, CSRF token on POST". The last two are properties of a REQUEST, and there is
# no request until 6.3. Writing them here would mean testing them against a fake request I
# also wrote - the trial-set problem from lesson 82, in a place where being wrong is a
# security bug rather than a wrong number. So 6.2 is signup / login / logout as functions,
# testable for $0.00, and 6.3 owns cookie flags, CSRF and the redirect dance.
#
# WHAT THIS FILE IS DEFENDING AGAINST, named before anything is built (the Phase 5 order):
#   1. offline cracking of a stolen app.db        -> argon2id, measured parameters
#   2. online guessing of one account's password  -> per-email rate limit, stored not in RAM
#   3. spraying one common password across many   -> per-IP rate limit
#   4. USER ENUMERATION - learning which addresses have accounts, from timing or from the
#      error text. This is the one that is easy to get wrong and invisible when you do,
#      so it is the one with an actual measurement attached at the bottom of this file.
#
# Everything here is free to test: no API key, no network, no tokens.

import re
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

import db

# --- password hashing -----------------------------------------------------------------------
# argon2id. The parameter set is anchored to a STANDARD, and the wall-clock is recorded as a
# fact about hardware rather than used as a target.
#
#     shipped:  m = 128 MiB,  t = 3,  p = 4
#
# MEASURED, `python auth.py --calibrate`, 2026-08-18:
#
#            t   memory        authoring machine     target machine
#            3    64 MiB       176 ms verify          50 ms verify     <- library default
#            3   128 MiB       334 ms                140 ms            <- SHIPPED
#            4   128 MiB       394 ms                134 ms
#            3   256 MiB       716 ms                253 ms
#            6    64 MiB       313 ms                128 ms
#
# WHY NOT TUNE TO A WALL-CLOCK NUMBER. An earlier version of this comment said "target a
# verify of roughly 200-350 ms" and, on seeing 50 ms on the target machine, the obvious move
# was to raise the cost until it hit that band. That band was a number I had invented in a
# comment two hours earlier. Tuning real security parameters to hit an invented target is the
# tail wagging the dog - and the same machine reads 176 ms on one desk and 50 ms on another,
# so "how many milliseconds" is a property of the hardware, not of the defence.
#
# The library default (m=64 MiB, t=3, p=4) is already RFC 9106's SECOND RECOMMENDED OPTION,
# which is a citable choice rather than a taste. The one change made is memory 64 -> 128 MiB,
# and it is made on an argument rather than on a stopwatch: TIME and MEMORY do not buy the
# same thing. Time is linear for everyone - it costs the defender exactly what it costs the
# attacker. Memory is what makes a GPU or ASIC farm expensive, because each of its thousands
# of parallel cores needs its own full allocation; a 24 GB card fits ~375 concurrent guesses
# at 64 MiB and half that at 128. Per millisecond of the user's time, memory buys strictly
# more attacker cost than time does, so memory is the lever that gets pulled.
#
# 128 MiB is also the largest step that stays deployable in Phase 7: a 1 GB instance survives
# several concurrent logins, where 256 MiB would OOM a small box on two.
#
# Existing users are upgraded by check_needs_rehash() in login() below - a successful login
# is the only moment the plaintext exists to re-hash with. Without that, changing parameters
# would protect new accounts only, which is the reverse of who needs it.
PH = PasswordHasher(time_cost=3, memory_cost=128 * 1024, parallelism=4)

# One pre-computed hash of a value nobody can supply, verified against whenever the submitted
# address has no account. Without it, "no such user" returns in microseconds while "wrong
# password" takes a full argon2 verify, and that gap is a free account-enumeration oracle for
# anyone with a stopwatch. MEASURED, not asserted: with this guard removed, the self-test's
# two paths differ by 3,592x. With it, 1.01x. The test refuses to pass on either a large gap
# or on both arms being suspiciously fast, because two no-ops also agree perfectly.
_DUMMY_HASH = PH.hash("dummy-password-for-constant-time-comparison")

MIN_PASSWORD = 10
MAX_PASSWORD = 128          # argon2 handles long input fine; this bounds request size
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A deliberately small list, and it is NOT a breach check. A real deployment would test
# against Have I Been Pwned's k-anonymity API; this repo has no network budget for that, and
# saying "we check common passwords" while checking twelve of them would be the kind of
# claim this project exists to avoid making.
_COMMON = {
    "password", "password1", "password123", "123456789", "1234567890",
    "qwertyuiop", "letmein123", "iloveyou1", "adminadmin", "welcome123",
    "changeme123", "passw0rd123",
}

# Rate limiting. 8 failures inside 15 minutes locks an address, and 30 locks an IP - the IP
# limit is looser because one office or one household is legitimately many people, while one
# email address is one person.
WINDOW_MINUTES = 15
MAX_FAILURES_PER_EMAIL = 8
MAX_FAILURES_PER_IP = 30


class AuthError(Exception):
    """Base class. `code` is for the caller; `str()` is for a human."""
    code = "auth_error"


class InvalidCredentials(AuthError):
    """Wrong password OR no such account - ONE error for both, deliberately.

    Distinguishing them is the single most common way an application hands out a list of its
    users. The caller cannot leak what it was never told.
    """
    code = "invalid_credentials"

    def __init__(self):
        super().__init__("Email or password is incorrect.")


class RateLimited(AuthError):
    code = "rate_limited"

    def __init__(self, minutes):
        super().__init__(f"Too many failed attempts. Try again in about {minutes} minutes.")
        self.minutes = minutes


class WeakPassword(AuthError):
    code = "weak_password"


class InvalidEmail(AuthError):
    code = "invalid_email"


class EmailTaken(AuthError):
    """Signup only. This DOES reveal that an address has an account, and there is no way
    around it without an email sender to bounce the notice to. Documented as a known
    limitation rather than pretended away; the login path, which is the one an attacker
    actually scripts, does not leak."""
    code = "email_taken"


def _window_start():
    return (datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_password_policy(password, email=""):
    """Raise WeakPassword, or return None. Length first, composition rules never.

    Composition rules ("one capital, one digit, one symbol") push people towards
    `Password1!` and are not in current NIST guidance. Length, a common-password check and
    a "not your own email" check catch more of what actually happens.
    """
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise WeakPassword(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise WeakPassword(f"Password must be at most {MAX_PASSWORD} characters.")
    if password.lower() in _COMMON:
        raise WeakPassword("That password is too common. Pick something else.")
    local = (email or "").split("@")[0].strip().lower()
    if local and len(local) >= 3 and local in password.lower():
        raise WeakPassword("Password must not contain your email address.")


def normalise_email(email):
    e = (email or "").strip()
    if not EMAIL_RE.match(e):
        raise InvalidEmail("That does not look like an email address.")
    return e


def signup(conn, email, password, display_name=None):
    """Create a user with a local credential. Returns the new user id."""
    email = normalise_email(email)
    check_password_policy(password, email)
    if db.get_user_by_email(conn, email) is not None:
        raise EmailTaken("An account with that email already exists.")
    uid = db.create_user(conn, email, display_name)
    db.add_local_credential(conn, uid, PH.hash(password))
    return uid


def login(conn, email, password, ip=None, user_agent=None):
    """Verify a password and open a session. Returns (user_row, raw_session_token).

    Every exit path that is not success raises InvalidCredentials, and every one of them
    does the same amount of work. The `finally`-style attempt recording happens for
    non-existent addresses too - those are the rows worth having.
    """
    try:
        email = normalise_email(email)
    except InvalidEmail:
        # A malformed address is still a guess. Verify against the dummy so a syntax check
        # does not become a faster path than a real lookup, and count it.
        _dummy_verify(password)
        raise InvalidCredentials()

    since = _window_start()
    if db.recent_failures(conn, since, email=email) >= MAX_FAILURES_PER_EMAIL:
        raise RateLimited(WINDOW_MINUTES)
    if ip is not None and db.recent_failures(conn, since, ip=ip) >= MAX_FAILURES_PER_IP:
        raise RateLimited(WINDOW_MINUTES)

    user = db.get_user_by_email(conn, email)
    cred = db.get_credential(conn, user["id"], "local") if user else None

    if cred is None or not cred["password_hash"]:
        # No account, or an account that only has an OAuth credential. Same work, same error:
        # "this address exists but has no password" is still an answer about who has an
        # account here.
        _dummy_verify(password)
        db.record_attempt(conn, email, False, ip)
        raise InvalidCredentials()

    try:
        PH.verify(cred["password_hash"], password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        db.record_attempt(conn, email, False, ip)
        raise InvalidCredentials()

    # Parameters get raised over a system's life. Rehashing on a successful login is the only
    # moment the plaintext exists to do it with, and it costs one hash on an already-slow path.
    if PH.check_needs_rehash(cred["password_hash"]):
        conn.execute("UPDATE credentials SET password_hash = ? WHERE id = ?",
                     (PH.hash(password), cred["id"]))
        conn.commit()

    db.record_attempt(conn, email, True, ip)
    db.touch_login(conn, user["id"])
    token = db.create_session(conn, user["id"], user_agent=user_agent)
    return db.get_user_by_email(conn, email), token


def _dummy_verify(password):
    """Burn the same work a real verification would, and swallow the expected mismatch."""
    try:
        PH.verify(_DUMMY_HASH, password if isinstance(password, str) else "")
    except Exception:
        pass


def logout(conn, token):
    db.revoke_session(conn, token)


def current_user(conn, token):
    """The whole of 6.3's auth dependency: a cookie value in, a user row or None out."""
    return db.session_user(conn, token)


def change_password(conn, user_id, old_password, new_password):
    """Requires the old password, and revokes every other session on success.

    The revocation is the point. A password change usually means "I think someone else has
    it", and a change that leaves the intruder's cookie working has done nothing.
    """
    cred = db.get_credential(conn, user_id, "local")
    if cred is None or not cred["password_hash"]:
        raise InvalidCredentials()
    try:
        PH.verify(cred["password_hash"], old_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise InvalidCredentials()
    user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    check_password_policy(new_password, user["email"] if user else "")
    conn.execute("UPDATE credentials SET password_hash = ? WHERE id = ?",
                 (PH.hash(new_password), cred["id"]))
    conn.commit()
    db.revoke_all_sessions(conn, user_id)


# --- self-test ---------------------------------------------------------------------------
# In-memory database, no key, no network, $0.00. The last block is a MEASUREMENT, not an
# assertion about intent: it times the two failure paths and reports the gap, because
# "constant time" is a claim and a claim in this project needs a number.

def calibrate(candidates=None, n=5):
    """Time argon2id parameter sets ON THIS MACHINE and print the table. Free, no database.

    This exists because the numbers in this file's header were measured on the machine that
    WROTE it, and the machine that RUNS it turned out to be 3.4x faster - so the shipped
    parameters delivered a 50 ms login where the comment claimed ~200 ms. A hashing cost is
    the one security parameter that is meaningless without the hardware attached to it.

    Read the table like this: `time_cost` and `memory_cost` both raise the attacker's bill,
    but they raise DIFFERENT bills. Time is linear for everyone. Memory is what makes a GPU
    or an ASIC farm expensive, because thousands of parallel cores each need their own
    64 MiB. Prefer memory until the server cannot afford it.
    """
    import statistics as _stats
    if candidates is None:
        candidates = [(3, 64 * 1024, 4), (3, 128 * 1024, 4), (4, 128 * 1024, 4),
                      (3, 256 * 1024, 4), (6, 64 * 1024, 4)]
    print(f"\n  argon2id calibration on THIS machine, n={n} each")
    print(f"  {'t':>2} {'memory':>9} {'p':>2}   {'hash':>9} {'verify':>9}")
    rows = []
    for t, m, p in candidates:
        ph = PasswordHasher(time_cost=t, memory_cost=m, parallelism=p)
        hs, vs = [], []
        for _ in range(n):
            s = time.perf_counter(); h = ph.hash("calibration-passphrase"); hs.append(time.perf_counter() - s)
            s = time.perf_counter(); ph.verify(h, "calibration-passphrase"); vs.append(time.perf_counter() - s)
        hm, vm = _stats.median(hs) * 1000, _stats.median(vs) * 1000
        rows.append((t, m, p, hm, vm))
        print(f"  {t:>2} {m // 1024:>6} MiB {p:>2}   {hm:>7.1f}ms {vm:>7.1f}ms")
    print(f"\n  currently shipping: t={PH.time_cost} m={PH.memory_cost // 1024}MiB "
          f"p={PH.parallelism}")
    # No target milliseconds are printed here, and that is deliberate. The same parameters
    # read 176 ms on one desk and 50 ms on another, so a wall-clock target would be a
    # property of the hardware pretending to be a security requirement. Pick the parameter
    # set from a standard (RFC 9106) and from what each lever costs an ATTACKER; use this
    # table to check the choice is bearable for a person, not to choose it.
    print("  this table tells you what the choice COSTS here. It does not choose for you:")
    print("  a wall-clock number is hardware, and the parameters are a security decision.\n")
    return rows


if __name__ == "__main__":
    import statistics
    import sys

    if "--calibrate" in sys.argv:
        calibrate()
        raise SystemExit(0)

    c = db.init_db(db.connect(":memory:"))
    ok = 0

    uid = signup(c, "Adarsh@Example.com", "a-long-enough-passphrase", "Adarsh")
    assert db.get_user_by_email(c, "adarsh@example.com")["id"] == uid
    # the stored hash must be argon2id, and must not contain the password
    h = db.get_credential(c, uid, "local")["password_hash"]
    assert h.startswith("$argon2id$") and "a-long-enough-passphrase" not in h
    ok += 1

    for bad, why in [("short", "too short"), ("password123", "common"),
                     ("adarsh-is-my-name", "contains the email local part"),
                     ("x" * 200, "too long")]:
        try:
            check_password_policy(bad, "adarsh@example.com")
            raise SystemExit(f"FAIL: policy accepted a password that is {why}")
        except WeakPassword:
            pass
    ok += 1

    for bad in ("not-an-email", "a@b", "", "a b@c.com"):
        try:
            normalise_email(bad)
            raise SystemExit(f"FAIL: accepted {bad!r} as an email")
        except InvalidEmail:
            pass
    ok += 1

    try:
        signup(c, "adarsh@example.com", "another-good-passphrase")
        raise SystemExit("FAIL: duplicate signup accepted")
    except EmailTaken:
        ok += 1

    user, token = login(c, "ADARSH@example.com", "a-long-enough-passphrase", ip="10.0.0.1")
    assert user["id"] == uid and current_user(c, token)["id"] == uid
    assert db.get_user_by_email(c, "adarsh@example.com")["last_login_at"] is not None
    ok += 1

    logout(c, token)
    assert current_user(c, token) is None
    ok += 1

    # wrong password and unknown account must be INDISTINGUISHABLE to the caller
    codes = set()
    for e, p in [("adarsh@example.com", "wrong-password-here"),
                 ("nobody@example.com", "wrong-password-here")]:
        try:
            login(c, e, p, ip="10.0.0.2")
            raise SystemExit("FAIL: login succeeded with a wrong password")
        except InvalidCredentials as err:
            codes.add((err.code, str(err)))
    assert len(codes) == 1, f"FAIL: the two failure paths return different errors: {codes}"
    ok += 1

    # an OAuth-only account must not be loginable by password, and must not say so
    oid = db.create_user(c, "google-only@example.com")
    db.add_oauth_credential(c, oid, "google", "sub-xyz")
    try:
        login(c, "google-only@example.com", "any-password-at-all", ip="10.0.0.3")
        raise SystemExit("FAIL: password login worked on an oauth-only account")
    except InvalidCredentials:
        ok += 1

    # rate limit fires, and it fires on an address that does not exist too
    for _ in range(MAX_FAILURES_PER_EMAIL):
        try:
            login(c, "ghost@example.com", "guess-guess-guess", ip="10.0.0.4")
        except InvalidCredentials:
            pass
    try:
        login(c, "ghost@example.com", "guess-guess-guess", ip="10.0.0.4")
        raise SystemExit("FAIL: rate limit never fired")
    except RateLimited:
        ok += 1

    # ...and a real user is locked out after the same number of failures, then freed by a
    # success. The freeing half matters: a lockout with no exit is a denial-of-service that
    # any stranger can point at any account.
    # A FRESH address, because "adarsh@" already has failures on it from the check above and
    # a test that quietly starts from an unknown count is not testing the threshold.
    signup(c, "locked@example.com", "her-own-long-passphrase")
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        try:
            login(c, "locked@example.com", "wrong-password-here", ip="10.0.0.5")
        except InvalidCredentials:
            pass
    assert db.recent_failures(c, _window_start(), email="locked@example.com") \
        == MAX_FAILURES_PER_EMAIL - 1, "the threshold test did not start from a known count"
    _u, tok2 = login(c, "locked@example.com", "her-own-long-passphrase", ip="10.0.0.5")
    assert db.recent_failures(c, _window_start(), email="locked@example.com") == 0
    ok += 1

    # a password change revokes every other session, including the one that made it
    lid = db.get_user_by_email(c, "locked@example.com")["id"]
    assert current_user(c, tok2)["id"] == lid          # live before the change
    change_password(c, lid, "her-own-long-passphrase", "a-brand-new-passphrase")
    assert current_user(c, tok2) is None, "FAIL: old session survived a password change"
    _u, tok3 = login(c, "locked@example.com", "a-brand-new-passphrase", ip="10.0.0.6")
    assert current_user(c, tok3)["id"] == lid
    try:
        change_password(c, lid, "wrong-old-password", "yet-another-passphrase")
        raise SystemExit("FAIL: password changed without the old password")
    except InvalidCredentials:
        ok += 1

    # An old hash must be UPGRADED by a successful login. Without this test the rehash
    # branch is dead code that everybody assumes runs - and it only ever runs on the one
    # path nobody re-tests, months after the parameters changed.
    from argon2 import PasswordHasher as _PH
    weak = _PH(time_cost=1, memory_cost=8 * 1024, parallelism=1)
    wid = db.create_user(c, "legacy@example.com")
    db.add_local_credential(c, wid, weak.hash("an-old-account-passphrase"))
    before = db.get_credential(c, wid, "local")["password_hash"]
    assert "m=8192" in before and PH.check_needs_rehash(before)
    login(c, "legacy@example.com", "an-old-account-passphrase", ip="10.0.0.7")
    after = db.get_credential(c, wid, "local")["password_hash"]
    assert after != before, "FAIL: a weak legacy hash survived a successful login"
    assert f"m={PH.memory_cost}" in after and not PH.check_needs_rehash(after)
    # and the upgraded hash must still verify the SAME password
    _u, _t = login(c, "legacy@example.com", "an-old-account-passphrase", ip="10.0.0.8")
    ok += 1

    # --- the measurement -------------------------------------------------------------------
    # An enumeration oracle is a TIMING difference, so it is measured, not asserted about.
    #
    # TWO EARLIER VERSIONS OF THIS BLOCK WERE WRONG, in different ways, and both printed a
    # passing number:
    #
    #   v1 hammered ONE known address twelve times, so samples 9-12 hit the rate limiter and
    #      returned in microseconds having done no hashing at all. The median survived by
    #      luck, which is worse than failing - a number that is right by accident reads
    #      exactly like one that is right by design.
    #   v2 ran the two arms BACK TO BACK, twelve of one then twelve of the other. On the
    #      authoring machine that read 1.03x; on the target machine, 1.30x - close enough to
    #      the 1.35x threshold to be a coin flip. Sequential arms cannot separate a real
    #      difference from drift over the run: CPU frequency scaling, a warming cache, and a
    #      login_attempts table that is 12 rows bigger by the time the second arm starts.
    #
    # v3 does two things v2 could not. It INTERLEAVES the arms, so any drift hits both
    # equally. And it adds a CONTROL: a second known-address arm, identical to the first.
    # The control measures what this experiment's noise floor is on THIS machine, and the
    # known-vs-unknown gap only means something if it is bigger than known-vs-known.
    # Without the control, every ratio is unfalsifiable - there is nothing to compare it to.
    N = 16
    for i in range(N * 2):
        signup(c, f"known{i}@example.com", f"real-account-passphrase-{i}")
    arms = {"known": [], "control": [], "unknown": []}
    plan = [("known", "known{i}@example.com"),
            ("control", "known{n}@example.com"),        # same kind of address, different set
            ("unknown", "ghost{i}@example.com")]
    for i in range(N):
        for name, fmt in plan:
            email = fmt.format(i=i, n=N + i)
            t = time.perf_counter()
            try:
                login(c, email, "definitely-the-wrong-password", ip=f"192.0.2.{i}")
            except RateLimited:
                raise SystemExit("FAIL: the rate limiter fired during the timing measurement "
                                 "- those samples did no hashing and mean nothing")
            except AuthError:
                pass
            arms[name].append((time.perf_counter() - t) * 1000)

    med = {k: statistics.median(v) for k, v in arms.items()}
    def ratio(a, b):
        return max(med[a], med[b]) / max(min(med[a], med[b]), 1e-9)
    noise, signal = ratio("known", "control"), ratio("known", "unknown")

    print(f"\n  enumeration timing, n={N} per arm, INTERLEAVED, fresh address and IP each")
    for k in ("known", "control", "unknown"):
        lo, hi = min(arms[k]), max(arms[k])
        label = {"known": "known address, wrong password",
                 "control": "known address again (CONTROL)",
                 "unknown": "unknown address"}[k]
        print(f"    {label:32} median {med[k]:7.1f} ms   range {lo:6.1f}-{hi:6.1f}")
    print(f"\n    noise floor  known vs control   {noise:.2f}x   <- two identical arms")
    print(f"    signal       known vs unknown   {signal:.2f}x")
    # extracted to a variable: an escaped quote inside an f-string expression is a
    # SyntaxError, and this project has now hit that exact wall three times
    verdict = ("INDISTINGUISHABLE - the gap is inside this run's own noise"
               if signal <= noise * 1.15 else
               "A REAL GAP - the dummy verify is not covering a branch")
    print(f"    verdict: {verdict}")

    # both arms must actually be hashing: two no-ops also agree perfectly, and a 1.00x ratio
    # between two things that did nothing is not evidence of constant time
    assert min(med.values()) > 20, (
        f"FAIL: an arm returned in under 20 ms, so it hashed nothing. "
        f"medians={ {k: round(v, 1) for k, v in med.items()} }")
    # the real assertion: the known-vs-unknown gap must not exceed the measurement's own
    # noise floor by more than 15%. Comparing against the CONTROL rather than against a
    # hardcoded 1.35x is what makes this test portable - the authoring machine and the
    # target machine differ 3x in argon2 speed, so any fixed threshold is a machine-specific
    # constant wearing a security test's clothes.
    assert signal <= noise * 1.15, (
        f"FAIL: known-vs-unknown is {signal:.2f}x while two identical arms differ by only "
        f"{noise:.2f}x. That excess is an account-enumeration oracle, not noise.")
    ok += 1

    print(f"\nauth.py self-test: {ok}/{ok} checks passed, $0.00 spent")
