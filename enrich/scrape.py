"""Website research: read a company's own site, then have the customer's own
OpenAI key say what that business actually does.

The whole point of this module is doing that ONCE PER DOMAIN. A four-hundred
row contact list is usually ninety companies, and the slow part -- the HTTP
fetch and the summary -- should happen ninety times, not four hundred. The
ScrapedSite table, keyed on (account_id, domain), is that cache, and every
decision below is arranged around keeping it honest: re-summarising is cheap
and happens whenever the ask changes, re-fetching is slow and rude to the
site, so it only happens when we have nothing saved or someone forces it.

Nothing here raises. The runner calls process_row() in a loop over somebody's
spreadsheet; one unreachable URL has to cost that row, not the job.

The customer's key pays OpenAI directly. It is decrypted at the moment of the
call and never logged, flashed, returned or written into an error string.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import requests as http
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError

from app import db

from enrich import core
from enrich.models import DEFAULT_MODEL, EnrichRow, ScrapedSite


def _utcnow():
    """Naive UTC, matching what SQLite and Postgres hand back on a read.

    ScrapedSite.scraped_at is written by SQLAlchemy's default as an aware
    datetime but comes back naive, so anything that subtracts two of them has
    to agree on one shape. Everything in this module writes naive.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# A personal mailbox is not a company website. Someone who lists a gmail
# address has told us nothing about their employer, and fetching gmail.com
# four hundred times would be the opposite of research.
PERSONAL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "me.com", "msn.com", "live.com", "comcast.net",
    "verizon.net", "protonmail.com", "proton.me", "mail.com", "gmx.com",
    "yandex.com", "qq.com", "163.com",
})

# Column headers that obviously mean "website", used only when the job's
# mapping is silent. Guessing here beats failing a whole upload because
# nobody clicked a dropdown.
WEBSITE_HEADERS = (
    "website", "web site", "website url", "web address", "url", "domain",
    "site", "homepage", "home page", "company website", "company url",
)

# Plain Chrome. A default python-requests agent is blocked or served a stub
# by a large share of small-business hosts, which would read to the customer
# as "your tool doesn't work".
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_BYTES = 2_000_000          # one enormous page must not stall a whole job
HTML_TYPES = ("text/html", "application/xhtml+xml", "application/html")

DROP_TAGS = ("script", "style", "noscript", "svg", "head", "nav", "footer",
             "form", "iframe", "template")

# A site that was down for ten minutes should not be marked broken forever,
# but re-fetching a dead domain once per row is exactly the stall this module
# exists to prevent. So a failure is cached, briefly.
FAILED_RETRY_AFTER = timedelta(hours=6)

SUMMARY_MAX_TOKENS = 320       # four sentences of prose, with headroom
ESTIMATE_OUT_TOKENS = 160      # what four sentences actually costs

SUMMARY_SYSTEM = (
    "You are briefing a salesperson who is about to email this company cold. "
    "Working only from the text of the company's own website, write three or "
    "four sentences of plain prose that cover: what they actually sell, who "
    "they sell it to, roughly how big they look (solo operator, small local "
    "team, regional, national, enterprise), and one specific concrete detail "
    "worth mentioning on a call -- a named service, a location they serve, a "
    "client, an award, a piece of equipment, something they are visibly proud "
    "of.\n"
    "Rules. No bullet points, no headings, no markdown, no labels. Do not "
    "open with \"This company\", \"The website\" or any other preamble; start "
    "with the business itself. Invent nothing: every claim must be on the "
    "page. If the page does not say enough to brief anyone, say exactly that "
    "in one sentence and stop rather than guessing."
)


# ------------------------------------------------------------- the key
def normalize_domain(url_or_text):
    """Anything a human might type in a Website column -> one cache key.

    This function IS the deduplication. If it returns different strings for
    the same company, the account pays twice; if it collides two companies,
    one of them gets the other's summary in a sales email, which is worse.
    So it normalises hard on noise (scheme, www, path, query, port, case,
    trailing dot) and not at all on anything that distinguishes a registered
    domain -- notably hyphens, because tap-room.com and taproom.com really
    are two different businesses.

    Returns "" for a personal mailbox domain or for anything that is not a
    domain at all, which the caller treats as "nothing to research here".
    """
    s = str(url_or_text or "").strip().strip("<>\"'()[],;")
    if not s:
        return ""
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", s)
    s = re.split(r"[/?#\\\s]", s, maxsplit=1)[0]
    if "@" in s:
        # A bare email, a mailto:, or user:pass@host -- the host is last.
        s = s.rsplit("@", 1)[-1]
    s = s.split(":")[0]
    s = s.strip().strip(".").lower()
    if s.startswith("www."):
        s = s[4:]
    if not s or len(s) > 253:
        return ""
    if not s.isascii():
        try:
            s = s.encode("idna").decode("ascii")
        except (UnicodeError, ValueError):
            return ""
    if not _DOMAIN_RE.match(s) or not _TLD_RE.search(s):
        return ""
    if s in PERSONAL_DOMAINS:
        return ""
    return s


_LABEL = r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?"
_DOMAIN_RE = re.compile(r"^%s(?:\.%s)+$" % (_LABEL, _LABEL))
_TLD_RE = re.compile(r"\.[a-z]{2,63}$")   # also rejects bare IPv4 addresses


def prompt_fingerprint(model, instructions):
    """Identifies the ask, so a changed ask re-summarises and nothing else does.

    Deliberately covers only the model and the customer's own extra steer, not
    SUMMARY_SYSTEM. If our house prompt were in here, improving it would
    silently re-bill every customer for every domain they have ever scraped on
    their next run. That has to be a choice someone makes, not a deploy.
    """
    raw = "%s|%s" % (model or "", (instructions or "").strip())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------- fetch
def fetch_site(url, timeout=15, max_chars=12000):
    """-> {ok, final_url, title, text, error}. Never raises.

    `error` is always a sentence a non-technical person can act on. A raw
    ConnectionError traceback in a spreadsheet cell helps nobody and makes the
    product look broken when the customer's list is what's broken.
    """
    out = {"ok": False, "final_url": "", "title": "", "text": "", "error": ""}
    raw = str(url or "").strip()
    if not raw:
        out["error"] = "There was no website address to look at."
        return out

    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", raw):
        attempts = [raw]
    else:
        attempts = ["https://" + raw, "http://" + raw]

    got = None
    for attempt in attempts:
        got = _fetch_once(attempt, timeout, max_chars)
        if got["ok"] or not got.get("retryable"):
            break
    got.pop("retryable", None)
    return got


def _fetch_once(url, timeout, max_chars):
    """One GET. `retryable` means "https refused, plain http is worth a try".

    Only a handshake-level failure sets it. A 404 or a DNS miss will fail
    identically over http, and a second doomed request doubles the wait on a
    list that may have hundreds of dead domains in it.
    """
    out = {"ok": False, "final_url": url, "title": "", "text": "",
           "error": "", "retryable": False}
    try:
        r = http.get(url, headers=HEADERS, timeout=timeout,
                     allow_redirects=True, stream=True)
    except http.exceptions.SSLError:
        out["error"] = "That site's security certificate could not be verified."
        out["retryable"] = True
        return out
    except http.exceptions.Timeout:
        out["error"] = "That site did not respond."
        return out
    except http.exceptions.TooManyRedirects:
        out["error"] = "That site kept redirecting and never landed anywhere."
        return out
    except http.exceptions.ConnectionError as e:
        if _is_dns_failure(e):
            out["error"] = "That address did not resolve."
        else:
            out["error"] = "That site did not respond."
            out["retryable"] = True
        return out
    except Exception:
        out["error"] = "That is not a web address we can open."
        return out

    try:
        with r:
            out["final_url"] = r.url or url
            if r.status_code >= 400:
                out["error"] = _status_sentence(r.status_code)
                return out
            ctype = (r.headers.get("content-type") or "").split(";")[0]
            ctype = ctype.strip().lower()
            if ctype and ctype not in HTML_TYPES:
                out["error"] = "That is not a web page."
                return out
            try:
                declared = int(r.headers.get("content-length") or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared > MAX_BYTES:
                out["error"] = "That page is too big to read."
                return out
            body = bytearray()
            for chunk in r.iter_content(65536):
                if chunk:
                    body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break           # the header lied, or there wasn't one
    except Exception:
        out["error"] = "That site stopped responding part way through."
        return out

    title, text = _extract(bytes(body), max_chars)
    out["title"] = title
    if not text:
        # Almost always a site that paints itself with JavaScript. Saying so
        # beats paying OpenAI to summarise an empty string.
        out["error"] = "That page had no readable text on it."
        return out
    out["ok"] = True
    out["text"] = text
    return out


def _is_dns_failure(exc):
    s = str(exc).lower()
    return any(m in s for m in (
        "nameresolutionerror", "getaddrinfo", "name or service not known",
        "nodename nor servname", "temporary failure in name resolution",
        "name does not resolve", "no address associated",
    ))


def _status_sentence(code):
    if code == 404:
        return "That page returned 404."
    if code in (401, 403, 406, 451):
        return "That site refused the request (%s)." % code
    if code == 429:
        return "That site asked us to slow down (429)."
    if code >= 500:
        return "That site is having trouble right now (%s)." % code
    return "That page returned %s." % code


def _extract(body, max_chars):
    """Readable text only, with the title and meta description bolted on front.

    Those two are the densest statement of what a company does that exists on
    a web page -- written for exactly this purpose -- while the body text is
    mostly menus and legal boilerplate. Putting them first means they survive
    the truncation that the body may not.
    """
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return "", ""

    # Read these before dropping <head>, which is where they live.
    title = _collapse(soup.title.get_text(" ")) if soup.title else ""
    desc = _meta_description(soup)

    _drop(soup.find_all(list(DROP_TAGS)))
    _drop(soup.find_all(attrs={"aria-hidden": _is_true}))
    _drop(soup.find_all(attrs={"hidden": True}))

    lead = [b for b in (title, desc) if b]
    body_text = _collapse(soup.get_text(" "))
    if body_text:
        lead.append(body_text)
    return title[:400], _clip("\n".join(lead), max_chars)


def _is_true(value):
    return bool(value) and str(value).strip().lower() == "true"


def _drop(elements):
    for el in elements:
        if getattr(el, "_decomposed", False):
            continue            # already gone with its parent
        el.decompose()


def _meta_description(soup):
    best = ""
    for m in soup.find_all("meta"):
        key = (m.get("name") or m.get("property") or "").strip().lower()
        content = _collapse(m.get("content") or "")
        if not content:
            continue
        if key == "description":
            return content
        if key in ("og:description", "twitter:description") and not best:
            best = content
    return best


_WS_RE = re.compile(r"[\s​‌﻿]+")


def _collapse(s):
    return _WS_RE.sub(" ", str(s or "")).strip()


def _clip(text, limit):
    """Truncate on a word boundary; a half-word is a tell that something broke."""
    limit = max(200, int(limit or 12000))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    edge = max(cut.rfind(" "), cut.rfind("\n"))
    if edge > limit * 0.6:      # don't lose a paragraph chasing a space
        cut = cut[:edge]
    return cut.rstrip() + "..."


# ------------------------------------------------------------- summarise
def summarize(settings, text, title="", url="", model=None, instructions=""):
    """-> {ok, summary, tokens_in, tokens_out, cost, error}. Never raises.

    Billed to the customer's own key at OpenAI's own price; `cost` is what we
    report to them, computed from the tokens OpenAI actually charged, not from
    an estimate. Nothing is marked up.
    """
    out = {"ok": False, "summary": "", "tokens_in": 0, "tokens_out": 0,
           "cost": 0.0, "error": ""}
    text = (text or "").strip()
    if not text:
        out["error"] = "There was no page text to summarise."
        return out

    model = model or getattr(settings, "default_model", "") or DEFAULT_MODEL
    try:
        key = settings.key() if settings is not None else None
    except Exception:
        key = None
    if not key:
        out["error"] = "Add your OpenAI key in Settings before running this."
        return out

    system = SUMMARY_SYSTEM
    extra = (instructions or "").strip()
    if extra:
        # Theirs goes last so it reads as an addition to the brief, but the
        # rules above still stand -- otherwise "be brief" quietly deletes the
        # concrete detail that makes the summary worth paying for.
        system += ("\n\nThe person who asked for this added: " + extra +
                   "\nFollow that as well, keeping everything above.")

    try:
        r = core.complete(key, model, system, _summary_user(title, url, text),
                          max_tokens=SUMMARY_MAX_TOKENS)
    except Exception as e:
        out["error"] = "OpenAI could not be reached (%s)." % type(e).__name__
        return out

    if not r.get("ok"):
        out["error"] = (r.get("error") or "OpenAI did not answer.")[:400]
        return out
    summary = (r.get("text") or "").strip()
    if not summary:
        out["error"] = "OpenAI returned an empty summary."
        return out

    t_in = int(r.get("tokens_in") or 0)
    t_out = int(r.get("tokens_out") or 0)
    out.update(ok=True, summary=summary, tokens_in=t_in, tokens_out=t_out,
               cost=core.price(model, t_in, t_out))
    return out


def _summary_user(title, url, text):
    bits = []
    if title:
        bits.append("Page title: %s" % title)
    if url:
        bits.append("Address: %s" % url)
    bits.append("Website text:\n%s" % text)
    return "\n".join(bits)


# ----------------------------------------------------------- the dedupe
def get_or_scrape(account_id, settings, raw_url, model=None, instructions="",
                  force=False):
    """-> (ScrapedSite or None, reused). The money-saving heart of the module.

    Three outcomes, cheapest first:
      * a saved summary for the same ask           -> reused, costs nothing
      * saved page text but a different ask        -> re-summarise, no fetch
      * nothing saved (or force=True)              -> fetch and summarise

    The middle case is the one worth having: changing the instructions should
    cost a few hundred tokens, not a second round of HTTP against ninety
    small-business servers that already gave us their page once.
    """
    domain = normalize_domain(raw_url)
    if not domain:
        return None, False

    model = model or getattr(settings, "default_model", "") or DEFAULT_MODEL
    fingerprint = prompt_fingerprint(model, instructions)
    site = (ScrapedSite.query
            .filter_by(account_id=account_id, domain=domain).first())

    if site is not None and not force:
        if site.summary:
            if site.prompt_fingerprint == fingerprint:
                return site, True
            if site.text:
                return _resummarize(site, settings, model, instructions,
                                    fingerprint), False
        elif _is_fresh_failure(site):
            return site, True

    timeout = int(getattr(settings, "scrape_timeout", None) or 15)
    max_chars = int(getattr(settings, "scrape_max_chars", None) or 12000)
    got = fetch_site(domain, timeout=timeout, max_chars=max_chars)
    if got["ok"]:
        summed = summarize(settings, got["text"], title=got["title"],
                           url=got["final_url"], model=model,
                           instructions=instructions)
    else:
        summed = {"ok": False, "summary": "", "tokens_in": 0, "tokens_out": 0,
                  "cost": 0.0, "error": got["error"]}

    created = site is None
    if created:
        site = ScrapedSite(account_id=account_id, domain=domain)
        db.session.add(site)
    _apply(site, domain, got, summed, model, fingerprint)
    try:
        db.session.commit()
    except IntegrityError:
        # Two rows of the same job raced onto one new domain. One insert wins,
        # ours rolls back, and the loser reads the winner's work rather than
        # failing a perfectly good row over a few milliseconds of timing.
        db.session.rollback()
        winner = (ScrapedSite.query
                  .filter_by(account_id=account_id, domain=domain).first())
        if winner is not None:
            return winner, True
        return None, False
    except Exception:
        db.session.rollback()
        return None, False
    return site, False


def _resummarize(site, settings, model, instructions, fingerprint):
    """New ask, saved page. Re-ask OpenAI; do not touch the site again."""
    summed = summarize(settings, site.text, title=site.title,
                       url=site.final_url or site.url, model=model,
                       instructions=instructions)
    site.model = (model or "")[:60]
    site.prompt_fingerprint = fingerprint
    site.tokens_in = summed["tokens_in"]
    site.tokens_out = summed["tokens_out"]
    site.cost = summed["cost"]
    if summed["ok"]:
        site.summary = summed["summary"]
        site.status = "ok"
        site.error = ""
        site.summarized_at = _utcnow()
    else:
        site.status = "ai_failed"
        site.error = summed["error"][:400]
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return site


def _apply(site, domain, got, summed, model, fingerprint):
    """Write one fetch-and-summarise onto the cache row."""
    site.domain = domain[:200]
    site.url = ("https://%s" % domain)[:600]
    site.final_url = (got.get("final_url") or "")[:600]
    site.title = (got.get("title") or "")[:400]
    site.text = got.get("text") or ""
    site.text_chars = len(site.text)
    site.model = (model or "")[:60]
    site.tokens_in = summed.get("tokens_in") or 0
    site.tokens_out = summed.get("tokens_out") or 0
    site.cost = summed.get("cost") or 0.0
    site.scraped_at = _utcnow()
    if not got.get("ok"):
        site.status = "fetch_failed"
        site.error = (got.get("error") or "That site could not be read.")[:400]
        site.summary = ""
        site.prompt_fingerprint = ""
        site.summarized_at = None
        return
    if not summed.get("ok"):
        site.status = "ai_failed"
        site.error = (summed.get("error") or "The summary failed.")[:400]
        site.summary = ""
        # No fingerprint on a failure: the next attempt must redo the summary,
        # and it can do it from the text we just saved, for free.
        site.prompt_fingerprint = ""
        site.summarized_at = None
        return
    site.status = "ok"
    site.error = ""
    site.summary = summed.get("summary") or ""
    site.prompt_fingerprint = fingerprint
    site.summarized_at = _utcnow()


def _is_fresh_failure(site):
    """A recent failure is worth trusting; a stale one is worth retrying."""
    if site.summary or site.status == "ok":
        return False
    stamp = site.scraped_at
    if stamp is None:
        return False
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return (_utcnow() - stamp) < FAILED_RETRY_AFTER


# -------------------------------------------------------------- the row
OUT_SUMMARY = "Website Summary"
OUT_TITLE = "Website Title"
OUT_URL = "Scraped URL"
OUT_STATUS = "Scrape Status"
OUT_NOTE = "Scrape Note"


def process_row(job, row, settings):
    """What the runner calls, once per spreadsheet row. Never raises.

    jobs.tick() already catches, but a handler that leans on its caller's
    try/except leaves the row in whatever half-state the exception found it
    in. Everything below sets row.state explicitly.
    """
    try:
        _process_row(job, row, settings)
    except Exception as e:
        row.state = "failed"
        row.reused = False
        row.cost = 0.0
        row.error = ("%s: %s" % (type(e).__name__, e))[:400]
        _write(row, "", "", "", "failed", row.error)


def _process_row(job, row, settings):
    cfg = job.config or {}
    model = cfg.get("model") or job.model or DEFAULT_MODEL
    instructions = (cfg.get("instructions") or "").strip()
    data = row.input

    column = _website_column(job, data)
    if not column:
        # A misconfigured job is not four hundred skipped rows; it is one
        # thing to fix. Say so loudly instead of reporting "Finished".
        row.state = "failed"
        row.reused = False
        row.cost = 0.0
        row.error = "No website column was chosen for this job."
        _write(row, "", "", "", "failed", row.error)
        return

    raw = data.get(column, "")
    domain = normalize_domain(raw)
    if not domain:
        # A blank website cell is normal in a real list, and a gmail address
        # in a website column is normal too. Neither is a failure.
        row.state = "skipped"
        row.domain = ""
        row.reused = False
        row.cost = 0.0
        row.error = ""
        note = ("No website on this row." if not str(raw).strip()
                else "Not a company website: %s" % str(raw)[:120])
        _write(row, "", "", "", "skipped", note)
        return

    site, reused = get_or_scrape(job.account_id, settings, domain,
                                 model=model, instructions=instructions)
    row.domain = domain[:200]
    if site is None:
        row.state = "failed"
        row.reused = False
        row.cost = 0.0
        row.error = "That site could not be saved to your research list."
        _write(row, "", "", "", "failed", row.error)
        return

    row.reused = bool(reused)
    row.cost = 0.0 if reused else float(site.cost or 0)
    summary = site.summary or ""
    if site.status == "ok" and summary:
        row.state = "done"
        row.error = ""
        _write(row, summary, site.title or "",
               site.final_url or site.url or "",
               "reused" if reused else "ok", "")
    else:
        row.state = "failed"
        row.error = (site.error or "That site could not be read.")[:400]
        _write(row, "", site.title or "", site.final_url or site.url or "",
               "failed", row.error)


def _write(row, summary, title, url, status, note):
    """Four stable columns, plus a note only when there is something to say.

    export() builds its header from whatever keys appear, so a clean job gets
    four extra columns and a messy one gets the fifth that explains itself.
    """
    out = {OUT_SUMMARY: summary, OUT_TITLE: title, OUT_URL: url,
           OUT_STATUS: status}
    if note:
        out[OUT_NOTE] = note
    row.output_json = json.dumps(out)


def _website_column(job, data):
    """The mapping wins; a familiar header is the fallback, not an override."""
    column = (job.mapping or {}).get("website")
    if column:
        return str(column)
    lower = {str(k).strip().lower(): k for k in (data or {})}
    for name in WEBSITE_HEADERS:
        if name in lower:
            return lower[name]
    return ""


# ------------------------------------------------------------- estimate
def estimate_job(job, settings):
    """What this run will actually cost, counted in companies, not rows.

    "412 rows, 96 companies, 71 of them new" is the number that makes someone
    press the button, because it is the number they would have worked out by
    hand if they had the patience. Quoting 412 rows would overstate the bill
    by five times and lose the sale.
    """
    cfg = job.config or {}
    model = cfg.get("model") or job.model or DEFAULT_MODEL
    instructions = (cfg.get("instructions") or "").strip()
    max_chars = int(getattr(settings, "scrape_max_chars", None) or 12000)

    rows = (EnrichRow.query
            .filter_by(job_id=job.id, state="pending")
            .order_by(EnrichRow.idx).all())
    domains, without = set(), 0
    for r in rows:
        data = r.input
        column = _website_column(job, data)
        domain = normalize_domain(data.get(column, "")) if column else ""
        if domain:
            domains.add(domain)
        else:
            without += 1

    have = _already_scraped(job.account_id, domains)
    to_fetch = len(domains - have)

    # The page text dominates the input, so estimate against the cap rather
    # than against the system prompt, which is noise beside it.
    prompt_chars = len(SUMMARY_SYSTEM) + len(instructions) + 200
    est = core.estimate(model, to_fetch, prompt_chars,
                        extra_in_chars=max_chars,
                        out_tokens=ESTIMATE_OUT_TOKENS)
    est.update({"unique_domains": len(domains), "already_have": len(have),
                "to_fetch": to_fetch, "pending_rows": len(rows),
                "rows_without_website": without,
                "total_pretty": core.money(est["total"])})
    return est


def _already_scraped(account_id, domains):
    """Which of these we can answer for free. Chunked: SQLite caps an IN()
    list at 999 parameters, and a thousand-company upload is the good case."""
    found = set()
    ordered = sorted(domains)
    for i in range(0, len(ordered), 400):
        chunk = ordered[i:i + 400]
        if not chunk:
            continue
        try:
            q = (db.session.query(ScrapedSite.domain, ScrapedSite.summary)
                 .filter(ScrapedSite.account_id == account_id,
                         ScrapedSite.domain.in_(chunk)))
            found.update(d for d, s in q.all() if s)
        except Exception:
            # An estimate is advisory; it must never be the thing that breaks.
            return found
    return found
