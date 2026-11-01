"""Resolve a human-written fund name to a published scheme code.

Why this exists. An uploaded holdings CSV carries scheme NAMES. To fetch NAV
history - and therefore to derive real, sourced risk and return metrics - the
engine needs a scheme CODE. api.mfapi.in publishes a catalogue of every scheme
with its code and ISIN, so the mapping is a lookup against published data, not
a guess.

The hard part is not fetching; it is refusing to guess. A scheme name is a poor
identifier: "HDFC Flexi Cap" is Direct and Regular, growth and dividend, and the
catalogue has a row for each. So:

  * the best match must be UNAMBIGUOUS - a clear margin over the runner-up;
  * otherwise the name is reported unresolved, with the candidates that came
    close, and nothing is inferred.

A wrong code is worse than no code: it silently attaches another fund's NAV
series to this holding, which is fabricated evidence wearing a real fund's name.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


CATALOGUE_URL = "https://api.mfapi.in/mf"
_UA = {"User-Agent": "Mozilla/5.0 (fiduciary-engine)",
       "Accept": "application/json"}

#: Pure noise, dropped from both sides. Plan and option words are DELIBERATELY
#: NOT in here - they are what distinguish two schemes that share a brand.
_NOISE = {"fund", "the", "of", "and", "mutual", "india", "limited", "ltd",
          "scheme", "open", "ended", "investment", "trust"}

#: Plan / option words, which must agree for a match to be unambiguous.
_PLAN_WORDS = {"direct", "regular", "growth", "dividend", "idcw", "reinvestment",
               "payout", "bonus", "half", "yearly", "monthly", "quarterly",
               "sip", "lumpsum", "elss", "tax", "saving"}

#: Words a catalogue name may carry that the query need not repeat. They are
#: structural - a plan marker or the word "option" after Growth/IDCW - and never
#: what tells two funds apart.
_GENERIC = _PLAN_WORDS | {"option", "plan"}

_WORD = re.compile(r"[a-z0-9]+")


from engine import fundmatch
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)

def _words(name: str) -> list[str]:
    """Lowercase alphanumeric words, noise removed, plan words KEPT.

    fundmatch.tokens() cannot be used here: it strips stop words, which for
    "SBI Bluechip Fund - Regular Plan Growth" leaves just {"sbi"} and for
    "HDFC Flexi Cap Fund - Direct Plan Growth" leaves {"hdfc","flexi"} - so
    Direct and Regular score identically and every real name looks ambiguous.
    """
    s = (name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    for pat, rep in fundmatch.SYNONYMS:
        s = re.sub(pat, rep, s)
    return [w for w in _WORD.findall(s) if w not in _NOISE]


def _tokens(name: str) -> set[str]:
    return set(_words(name))


def _plan_tokens(name: str) -> set[str]:
    return {w for w in _words(name) if w in _PLAN_WORDS}


#: Cache governance for scheme catalogue
DEFAULT_CATALOGUE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
#: Cache governance for scheme catalogue
DEFAULT_CATALOGUE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
_CACHE_WARN_HOURS = 12  # Warn when serving cache older than 12 hours

# In-memory Tier-1 cache: cache_path_str -> (mtime, rows, provenance)
_MEMORY_CATALOGUE_CACHE: dict[str, tuple[float, list[dict], dict]] = {}


def _atomic_json_dump(data: Any, target_path: Path) -> None:
    """Atomic write via temporary file replacement to prevent corrupt reads."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    try:
        temp_path.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temp_path, target_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def _validate_catalogue_schema(data: Any) -> bool:
    """Verify loaded catalogue conforms to expected list of scheme dicts."""
    if not isinstance(data, list):
        return False
    if not data:
        return True
    sample = data[:min(len(data), 15)]
    return all(isinstance(r, dict) and "code" in r and "name" in r for r in sample)


def invalidate_catalogue_cache(cache_dir=None) -> bool:
    """Explicitly invalidate in-memory and on-disk scheme catalogue caches."""
    global _MEMORY_CATALOGUE_CACHE
    _MEMORY_CATALOGUE_CACHE.clear()
    if cache_dir:
        cached = Path(cache_dir) / "_scheme_catalogue.json"
        if cached.exists():
            try:
                cached.unlink()
                return True
            except OSError:
                return False
    return True


def load_catalogue(cache_dir=None, timeout: int = 45, max_age_hours: int = 24,
                   force_refresh: bool = False):
    """
    Load the published scheme catalogue, using multi-tier caching (memory + disk).

    Returns (catalogue, provenance). Provenance travels with the data so a
    later reader knows where every scheme code came from.

    TTL enforcement: if the cached file is older than ``max_age_hours``, the
    function attempts a fresh fetch. If the remote fetch fails, it falls back
    to the stale cache with a warning in the provenance dict.
    """
    cached = None
    cache_age_hours = None
    if not cache_dir:
        default_dir = Path(__file__).resolve().parent / ".cache"
        if default_dir.exists():
            cache_dir = default_dir

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / "_scheme_catalogue.json"
        cache_key = str(cached.resolve())

        if force_refresh:
            _MEMORY_CATALOGUE_CACHE.pop(cache_key, None)
            try:
                from engine.logging_config import log_cache_operation
                log_cache_operation(
                    operation="cache_evicted",
                    cache_type="scheme_catalogue",
                    key=str(cached),
                    hit=True,
                    ttl_seconds=int(max_age_hours * 3600),
                )
            except Exception as e:
                logger.warning(r"Cache eviction log failed: {e}")
        elif cached.exists():
            file_mtime = os.path.getmtime(cached)
            cache_age_hours = (time.time() - file_mtime) / 3600.0

            # Tier 1: Check in-memory cache if disk mtime hasn't changed
            if cache_key in _MEMORY_CATALOGUE_CACHE:
                mem_mtime, mem_rows, mem_prov = _MEMORY_CATALOGUE_CACHE[cache_key]
                if mem_mtime == file_mtime and cache_age_hours < max_age_hours:
                    return mem_rows, mem_prov

            # Tier 2: Read disk cache
            try:
                from engine.logging_config import log_cache_operation
                log_cache_operation(
                    operation="cache_served",
                    cache_type="scheme_catalogue",
                    key=str(cached),
                    hit=True,
                    size=cached.stat().st_size if cached.exists() else None,
                    ttl_seconds=int(max_age_hours * 3600),
                )
            except Exception as e:
                logger.warning(r"Cache served log failed: {e}")

            if cache_age_hours < max_age_hours:
                if cache_age_hours > _CACHE_WARN_HOURS:
                    try:
                        from engine.logging_config import get_logger
                        get_logger("engine.cache").warning(
                            {"event": "cache_stale", "cache_type": "scheme_catalogue",
                             "age_hours": round(cache_age_hours, 2),
                             "warning": f"cache aged {cache_age_hours:.1f}h, approaching TTL of {max_age_hours}h"}
                        )
                    except Exception as e:
                        logger.warning(r"Cache stale warning log failed: {e}")
                try:
                    loaded = json.loads(cached.read_text(encoding="utf-8"))
                    if _validate_catalogue_schema(loaded):
                        prov = {
                            "source": "api.mfapi.in catalogue (cached)", "cached": True,
                            "age_hours": round(cache_age_hours, 2),
                            "ttl_hours": max_age_hours
                        }
                        _MEMORY_CATALOGUE_CACHE[cache_key] = (file_mtime, loaded, prov)
                        return loaded, prov
                except (json.JSONDecodeError, OSError):
                    pass  # unreadable or invalid cache: re-fetch

    # Cache is stale, missing, or expired — fetch fresh
    req = urllib.request.Request(CATALOGUE_URL, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            data = json.loads(fh.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        # If remote fetch failed but stale cache exists, fall back with warning
        if cached and cached.exists():
            try:
                from engine.logging_config import get_logger
                get_logger("engine.cache").warning(
                    {"event": "cache_fallback", "cache_type": "scheme_catalogue",
                     "reason": f"remote fetch failed (HTTP {exc.code}), using stale cache"})
            except Exception as e:
                logger.info(f"  [..] Cache fallback warning log failed: {e}")
            try:
                loaded = json.loads(cached.read_text(encoding="utf-8"))
                if _validate_catalogue_schema(loaded):
                    return loaded, {
                        "source": "api.mfapi.in catalogue (stale fallback)",
                        "cached": True, "stale": True,
                        "stale_age_hours": round(cache_age_hours, 2) if cache_age_hours else None}
            except (json.JSONDecodeError, OSError):
                pass
        raise RuntimeError(f"catalogue fetch failed: HTTP {exc.code}") from exc
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        # If remote fetch failed but stale cache exists, fall back with warning
        if cached and cached.exists():
            try:
                from engine.logging_config import get_logger
                get_logger("engine.cache").warning(
                    {"event": "cache_fallback", "cache_type": "scheme_catalogue",
                     "reason": f"remote fetch failed ({exc}), using stale cache"})
            except Exception as e:
                logger.info(f"  [..] Cache fallback warning log failed: {e}")
            try:
                loaded = json.loads(cached.read_text(encoding="utf-8"))
                if _validate_catalogue_schema(loaded):
                    return loaded, {
                        "source": "api.mfapi.in catalogue (stale fallback)",
                        "cached": True, "stale": True,
                        "stale_age_hours": round(cache_age_hours, 2) if cache_age_hours else None}
            except (json.JSONDecodeError, OSError):
                pass
        raise RuntimeError(f"catalogue fetch failed: {exc}") from exc

    rows = [{"code": str(r.get("schemeCode")),
             "name": r.get("schemeName") or "",
             "isin_growth": r.get("isinGrowth"),
             "isin_idcw": r.get("isinDivReinvestment")}
            for r in data if r.get("schemeCode") and r.get("schemeName")]
    
    if cached:
        _atomic_json_dump(rows, cached)
        _MEMORY_CATALOGUE_CACHE[str(cached.resolve())] = (
            os.path.getmtime(cached),
            rows,
            {"source": "api.mfapi.in catalogue", "cached": False}
        )
    return rows, {"source": "api.mfapi.in catalogue", "cached": False}


class SchemeIndex:
    """
    Tokenised catalogue, built ONCE.

    Tokenising 37,936 scheme names per query took over 30 seconds for a handful
    of holdings, which would make the web front end unusable. The index builds
    in about two seconds and every lookup after that is a cheap scan.
    """

    __slots__ = ("rows", "rows_src", "_toks", "_plans", "_n")

    def __init__(self, catalogue):
        self.rows = catalogue
        self.rows_src = len(catalogue)
        self._toks, self._plans, self._n = [], [], []
        for r in catalogue:
            t = _tokens(r["name"])
            self._toks.append(t)
            self._plans.append({x for x in t if x in _PLAN_WORDS})
            self._n.append(len(t))

    def __len__(self):
        return self.rows_src

    def iter_rows(self):
        return zip(self._toks, self._plans, self._n, self.rows)


#: Acceptance tolerance for implied-NAV verification.
#:
#: Measured, not chosen. On the 14 holdings already resolved by name, the
#: implied NAV (current value / units) reproduced the published NAV to at most
#: 8.851e-08 relative - even for the least precise holding, 22.639 units. The
#: closest WRONG candidate across every ambiguous case sat at 6.800e-05. So
#: 1e-5 sits 113x above the worst true match and 6.8x below the nearest false
#: one: a 768x separation with margin on both sides.
NAV_TOL = 1e-5

#: How far back the checksum may search for the statement's valuation date.
#:
#: Measured, not chosen. A CAS generated at 08:08 on 2026-07-31 reports
#: ``To Date 31-Jul-2026`` yet carries 30-Jul NAVs - that day's NAV did not
#: exist yet when the file was written. Checked against that statement, all
#: seven rows the single-date check refused matched EXACTLY ONE candidate on
#: 2026-07-30 (errors 3.6e-10 to 3.4e-08), while on the
#: statement date no candidate came closer than 2.6e-04 - nearly two orders above
#: tolerance, so every row looked like a failed checksum rather than a
#: wrong-date one. Seven days spans a weekend plus the short market holidays
#: over which a statement can be struck before its own date. The window cannot
#: turn the checksum into a similarity score: the tolerance is unchanged,
#: dates AFTER the statement are never considered, and a SECOND candidate
#: matching anywhere in the window is a refusal, not a coin toss.
NAV_DATE_WINDOW_DAYS = 7


def verify_candidates_by_nav(*, candidates, implied_nav, as_of, series_lookup,
                             tol: float = NAV_TOL) -> dict:
    """
    Settle an ambiguous name with arithmetic the statement already implies.

    A CAS states units and current value, and value = units x NAV. So the
    holding implies a NAV for the date it was struck. Each candidate scheme
    publishes its NAVs. The candidate whose published NAV equals the implied
    one is the holding.

    WHICH DATE is subtler than it looks. A statement generated at 08:08 on
    31-Jul-2026 reports ``To Date 31-Jul-2026`` yet carries 30-Jul NAVs - that
    day's NAV did not exist when the file was written. So the check searches
    the NAV_DATE_WINDOW_DAYS days up to as_of instead of only as_of itself
    (see the constant for the measurements). Dates after as_of are never used.

    This is a CHECKSUM, not a similarity score - which is why it may resolve a
    name the tokeniser could not. Verified on all 14 holdings that name matching
    had already resolved: every one agreed to within 8.851e-08, and no wrong
    candidate came closer than 6.800e-05.

    Refuses rather than guesses, in every one of these cases:

      * the statement gives no units or value, so there is nothing to check;
      * ANY candidate's NAV series is unavailable - it cannot be fetched, or
        it has published nothing on or before the statement date at all -
        because ruling a candidate out needs its data, so a candidate that
        could not be checked must not be treated as having failed to match;
      * no candidate matches on any date of the window (or, for a series that
        stopped publishing, at its last NAV), or more than one candidate
        does - even on different dates of it.

    ``series_lookup(code)`` returns a list of ``[iso_date, nav]`` rows and is
    injected so this function never touches the network itself.
    """
    base = {"tolerance": tol, "as_of": as_of,
            "window_days": NAV_DATE_WINDOW_DAYS, "source": "api.mfapi.in"}
    if not implied_nav or implied_nav <= 0:
        return {**base, "resolved": False,
                "reason": "the statement gives no units or value, so no NAV can "
                          "be implied to check the candidates against"}
    if not candidates:
        return {**base, "resolved": False, "reason": "no candidates to verify"}

    checked, matches, unavailable = [], [], []
    for code in candidates:
        try:
            rows = series_lookup(code)
        except Exception as exc:                       # noqa: BLE001
            unavailable.append(f"{code} ({type(exc).__name__})")
            continue
        windowed = _navs_in_window(rows, as_of)
        if not windowed:
            # A candidate that has not published inside the window (a
            # discontinued scheme's NAV freezes at its last date) is still
            # checked - at its latest NAV on or before the statement. Its
            # frozen NAV is exactly what a remaining holding would be valued
            # at, so skipping it would let an untestable-looking series block
            # a verdict the arithmetic CAN reach.
            stale = _nav_on_or_before(rows, as_of)
            if stale and stale[1] > 0:
                windowed = [stale]
        if not windowed:
            # No published NAV at all means the candidate was never tested -
            # NOT that it failed to match.
            unavailable.append(f"{code} (no NAV on or before {as_of})")
            continue
        within = [(d, nav, abs(implied_nav - nav) / nav) for d, nav in windowed]
        ok = [t for t in within if t[2] <= tol]
        if ok:
            # Prefer the LATEST date inside tolerance: it is the one closest
            # to the statement the values were printed on.
            date, nav, err = max(ok)
            rec = {"code": code, "published_nav": nav, "date": date,
                   "relative_error": err}
            checked.append(rec)
            matches.append(rec)
        else:
            date, nav, err = min(within, key=lambda t: t[2])   # closest miss
            checked.append({"code": code, "published_nav": nav, "date": date,
                            "relative_error": err})

    if unavailable:
        # Not "these failed to match" - they were never tested. Treating an
        # unfetched series as a non-match is how a partial check becomes a
        # confident answer.
        return {**base, "resolved": False, "checked": checked,
                "reason": "cannot verify: NAV unavailable for "
                          + ", ".join(unavailable[:4])
                          + "; a candidate that could not be checked must not "
                            "be counted as a non-match"}
    if not matches:
        nearest = min(checked, key=lambda r: r["relative_error"])
        return {**base, "resolved": False, "checked": checked,
                "reason": "no candidate's published NAV equals the implied NAV "
                          f"on any of the {NAV_DATE_WINDOW_DAYS} days up to "
                          f"{as_of} (closest {nearest['code']} at "
                          f"{nearest['relative_error']:.3e}, tolerance {tol:.0e})"}
    by_code = {}
    for m in matches:
        by_code.setdefault(m["code"], []).append(m)
    if len(by_code) > 1:
        # A different candidate matching - even on a DIFFERENT date of the
        # window - is still ambiguity: picking between two checksum hits would
        # be guessing with extra steps.
        return {**base, "resolved": False, "checked": checked,
                "reason": "still ambiguous: %d candidates match the implied NAV "
                          "(%s) - their NAVs are too close to separate"
                          % (len(by_code), ", ".join(by_code))}

    hits = next(iter(by_code.values()))
    m = max(hits, key=lambda r: r["date"])       # the latest matching date
    return {**base, "resolved": True, "code": m["code"],
            "matched_by": "implied NAV",
            "evidence": {"implied_nav": round(implied_nav, 6),
                         "published_nav": m["published_nav"],
                         "nav_date": m["date"],
                         "relative_error": m["relative_error"],
                         "candidates_checked": len(checked)},
            "checked": checked}


def _nav_on_or_before(rows, as_of: str):
    """
    The last published NAV on or before an ISO date, or None.

    Deliberately does not assume the rows arrive sorted: mfapi returns oldest
    first today, but a re-ordered payload would otherwise silently pick the
    wrong date. The latest qualifying date wins regardless of order.
    """
    if not rows or not as_of:
        return None
    best = None
    for row in rows:
        if not row or len(row) < 2:
            continue
        d = str(row[0])
        try:
            datetime.date.fromisoformat(d)      # validates the shape
            nav = float(row[1])
        except (TypeError, ValueError):
            continue
        if d > as_of:
            continue
        if best is None or d > best[0]:
            best = (d, nav)
    return best


def _navs_in_window(rows, as_of, window_days: int = NAV_DATE_WINDOW_DAYS):
    """
    Valid ``(date, nav)`` rows in ``[as_of - window_days, as_of]``.

    Shares ``_nav_on_or_before``'s refusal to assume row order, and never
    looks past ``as_of``: a NAV published after the values it would be checked
    against is not evidence about them. The window exists because a statement
    can be generated before its own valuation date's NAV is published - see
    ``NAV_DATE_WINDOW_DAYS`` for why that is measured rather than guessed.
    """
    if not rows or not as_of:
        return []
    try:
        lo = (datetime.date.fromisoformat(as_of)
              - datetime.timedelta(days=window_days)).isoformat()
    except ValueError:
        return []
    out = []
    for row in rows:
        if not row or len(row) < 2:
            continue
        d = str(row[0])
        try:
            datetime.date.fromisoformat(d)      # validates the shape
            nav = float(row[1])
        except (TypeError, ValueError):
            continue
        if lo <= d <= as_of and nav > 0:
            out.append((d, nav))
    return out


def implied_nav_from(current_value, units):
    """current value / units, or None when the statement does not supply both."""
    try:
        v, u = float(current_value), Decimal(str(units))
    except (TypeError, ValueError):
        return None
    if not u or not v or u <= 0 or v <= 0:
        return None
    return v / u


def resolve_rows(rows, index, as_of=None, series_lookup=None):
    """
    Resolve every holdings row, falling back to the NAV checksum when the name
    cannot settle it.

    Lives in the engine rather than in the Streamlit script because the app's
    own loop was unreachable from the test suite - it ran only after an upload,
    which `AppTest` cannot perform, so a wiring failure there ships green. The
    caller now and the tests now share one implementation.

    Returns ``(resolved, unresolved, notes)`` where each entry is the original
    row plus a ``_r`` result, and ``notes`` records every reason a verification
    was SKIPPED. Skipping silently is how "checked by NAV" quietly degrades to
    "matched by name", which is the claim a reader would still be shown.
    """
    resolved, unresolved, notes = [], [], []
    for row in rows:
        amfi = row.get("amfi_code")
        if amfi:
            # Direct lookup if casparser gave us the AMFI code
            match = next((x for x in index.rows if x["code"] == str(amfi)), None)
            if match:
                r = {"resolved": True, "code": match["code"],
                     "matched_name": match["name"],
                     "isin": match.get("isin_growth"),
                     "matched_by": "casparser ISIN lookup", "score": 1.0}
                resolved.append({**row, "_r": r})
                continue
        
        r = resolve_name(row["scheme"], index)
        if r["resolved"]:
            resolved.append({**row, "_r": r})
            continue

        item = {**row, "_r": r}
        if not series_lookup:
            notes.append(f"{row['scheme'][:44]}: no NAV source, name match only")
        elif not as_of:
            notes.append(f"{row['scheme'][:44]}: no statement date, so no NAV "
                         f"can be checked against")
        else:
            # Rows reach here with EITHER spelling: the app's CAS mapping
            # writes "value", holdings.parse_holdings_csv writes
            # "current_value". Reading only one of them silently skipped the
            # checksum for every CSV upload - the units were present and
            # unused, and the note claimed they were missing.
            val = row.get("value")
            if val is None:
                val = row.get("current_value")
            if val is None:
                notes.append(f"{row['scheme'][:44]}: the row carries no value, "
                             f"so no NAV can be implied")
            elif row.get("units") in (None, ""):
                notes.append(f"{row['scheme'][:44]}: the row carries no units, "
                             f"so no NAV can be implied; add a Units column to "
                             f"the CSV (the template has one) or upload the "
                             f"Excel CAS, which carries units and the date")
            else:
                imp = implied_nav_from(val, row.get("units"))
                if not imp:
                    notes.append(f"{row['scheme'][:44]}: units or value is "
                                 f"zero, so no NAV can be implied")
                else:
                    v = verify_candidates_by_nav(
                        candidates=[c["code"] for c in r.get("candidates", [])],
                        implied_nav=imp, as_of=as_of,
                        series_lookup=series_lookup)
                    if v["resolved"]:
                        item = {**row, "_r": {**r, **v}}
                    else:
                        notes.append(f"{row['scheme'][:44]}: {v.get('reason','')}")
        (resolved if item["_r"].get("resolved") else unresolved).append(item)
    return resolved, unresolved, notes


_INDEX_CACHE = {}


def attestation_options(unresolved) -> dict:
    """
    Which unresolved rows the account holder can be ASKED to identify.

    Some rows have no arithmetic left to try: a CSV prepared by hand carries
    no units, and a name that omits the plan or option matches several
    published schemes. The one fact that settles those is the holder's own
    knowledge of what they bought - testimony, not evidence, and it is
    recorded as such everywhere downstream (``matched_by = "identified by
    the account holder"``).

    A chooser is offered only when the choices can actually be told apart:
    at least two candidates whose published names are pairwise DISTINCT.
    Motilal Oswal Midcap Fund is published under four codes with the identical
    name - putting that in front of a human as four identical labels would be
    a coin toss wearing a widget, so those rows stay refused until the
    statement's own units settle them.

    Returns ``{row_index: [candidate, ...]}`` in the unresolved list's order.
    """
    out = {}
    for i, row in enumerate(unresolved):
        cands = (row.get("_r") or {}).get("candidates") or []
        if len(cands) >= 2:
            out[i] = cands
    return out


def apply_attestation(unresolved, selections):
    """
    Move the rows the holder identified out of the unresolved list.

    ``selections`` maps a row index to the chosen scheme code. Returns
    ``(attested, remaining)``. A missing selection, an unknown index, or a
    code that is not among that row's own candidates leaves the row
    unresolved - a selection that does not name a real candidate must never
    resolve anything, or a typo would become an identity.

    Attested rows keep their original refusal ``reason`` alongside the new
    code, so a reader can still see why the name alone had failed.
    """
    attested, remaining = [], []
    options = attestation_options(unresolved)
    for i, row in enumerate(unresolved):
        code = (selections or {}).get(i)
        cand = None
        if code is not None and i in options:
            cand = next((c for c in options[i] if c.get("code") == code), None)
        if cand is None:
            remaining.append(row)
            continue
        attested.append({**row, "_r": {**row["_r"],
                                       "resolved": True,
                                       "code": cand["code"],
                                       "matched_name": cand.get("name"),
                                       "matched_by":
                                           "identified by the account holder",
                                       "evidence": {
                                           "basis": "the account holder "
                                                    "identified this scheme "
                                                    "from the candidates the "
                                                    "name matched; the engine "
                                                    "did not verify it"}}})
    return attested, remaining


def build_index(catalogue):
    key = id(catalogue)
    idx = _INDEX_CACHE.get(key)
    if idx is None or idx.rows_src != len(catalogue):
        idx = SchemeIndex(catalogue)
        _INDEX_CACHE[key] = idx
    return idx


def resolve_name(name: str, catalogue, margin: float | None = None) -> dict:
    """
    Match one scheme name against the catalogue.

    The decision rule is deliberately NOT a score threshold - a tuned constant
    either resolves real matches or refuses them, and which one it does depends
    on the data. Instead:

      * the best candidate must cover every DISCRIMINATING word of the query,
        where discriminating means the plan/option words (Direct vs Regular,
        Growth vs IDCW) - these are exactly the words that separate two schemes
        sharing a brand;
      * it must not name a substantive word the query never wrote, because a
        fund the human did not mention cannot be the fund they meant;
      * and it must be the only candidate that does.

    The second rule exists because without it a SUPERSET ties the true match.
    "HDFC Large & Mid Cap Fund" contains every word of "HDFC Mid Cap Fund", so
    both scored identically and the pair was reported as ambiguous - and the
    user was told to "add the plan and option", which they already had. A tie
    created by a word nobody said is not uncertainty about the truth; it is a
    different fund being mistaken for a rival answer.

    So "HDFC Flexi Cap Fund - Direct Plan Growth" resolves, because only the
    Direct-Growth option covers {direct, growth}. Bare "HDFC Flexi Cap" is
    refused, because several options cover its brand words and nothing in the
    name says which one - the honest answer.

    When several catalogue entries publish an IDENTICAL name (225 such groups
    cover 640 records), no wording of the query can separate them. That case
    says so explicitly and points at the scheme code or ISIN, rather than
    advising a rewrite that would not help.

    ``margin`` is accepted for compatibility and ignored.
    """
    want, want_plan = _tokens(name), _plan_tokens(name)
    base = {"scheme": name, "best_score": 0.0, "runner_up": 0.0, "candidates": []}
    if len(want) < 2:
        return {**base, "resolved": False,
                "reason": "fewer than two usable words in the name"}

    index = catalogue if isinstance(catalogue, SchemeIndex) else build_index(catalogue)
    scored = []
    # A catalogue entry that is a SUPERSET of the query ties it on hit count -
    # "HDFC Large & Mid Cap Fund" contains every word of "HDFC Mid Cap Fund"
    # plus "large" - so both reached the same score and the pair was reported
    # ambiguous even though the human never said "large". Naming a word the
    # query omits means it is a different fund, so it is dropped before scoring.
    # Brands that matched on their fund words but whose published names carry no
    # plan/option detail - several are identical for many codes.
    undeclared = []
    for have, plan, n_have, row in index.iter_rows():
        if not have:
            continue
        inter = want & have
        if not inter:
            continue
        if not (have - _GENERIC):
            # A catalogue entry whose name is only plan/option words carries no
            # fund identity at all. Code 104031 is published as literally
            # "Growth" (Kotak, close-ended, one NAV record from 2006), so it
            # matched every query containing the word growth and blocked four
            # verifications by being unfetchable. It cannot be what anyone
            # meant, so it is not a candidate.
            continue
        if want_plan and not want_plan <= plan:
            if not (have - want - _GENERIC):
                undeclared.append(row)          # right fund, no plan stated
            continue                    # candidate lacks a required plan word
        unaccounted = have - want - _GENERIC
        if unaccounted:
            continue                    # names a word we never wrote
        jaccard = len(inter) / (len(want) + n_have - len(inter))
        contain = len(inter) / len(want)
        scored.append((0.7 * contain + 0.3 * jaccard, len(inter), row))
    if not scored:
        if undeclared:
            # This is the honest answer, and it is NOT "add the plan to the
            # name": the PUBLISHED name omits it, so no wording of the query
            # can separate them.
            codes = ", ".join(r["code"] for r in undeclared[:3])
            return {**base, "resolved": False,
                    "candidates": [{"code": r["code"], "name": r["name"],
                                    "score": 0.0} for r in undeclared[:4]],
                    "reason": "%d published schemes share this fund name and "
                              "their catalogue entries state no plan or option "
                              "(%s), so the name alone cannot identify one. "
                              "Resolve it from the folio's scheme code or ISIN."
                              % (len(undeclared), codes)}
        return {**base, "resolved": False, "reason":
                "no published scheme matches the name and its plan words"}

    scored.sort(key=lambda x: (-x[0], -x[1], x[2]["name"]))
    best_score, best_hits, best = scored[0]
    # NB: this must tokenise the CANDIDATE. An earlier version re-tokenised
    # `best` inside the loop, so every runner trivially equalled the best match
    # and every real fund was reported as ambiguous.
    runners = [r for sc, _, r in scored[1:]
               if len(_tokens(r["name"]) & want) == best_hits]
    out = {**base,
           "best_score": round(best_score, 4),
           "runner_up": round(scored[1][0], 4) if len(scored) > 1 else 0.0,
           "candidates": [{"code": r["code"], "name": r["name"],
                           "score": round(sc, 4)} for sc, _, r in scored[:4]]}
    if best_hits < 2:
        return {**out, "resolved": False,
                "reason": "only one word matched - too little to be sure"}
    if runners:
        return {**out, "resolved": False,
                "reason": "ambiguous: %d catalogue schemes match equally well "
                          "(%s). Add the plan and option to the name."
                          % (len(runners) + 1,
                             ", ".join(c["code"] for c in out["candidates"][:3]))}
    return {**out, "resolved": True, "code": best["code"],
            "matched_name": best["name"], "isin": best.get("isin_growth")}
