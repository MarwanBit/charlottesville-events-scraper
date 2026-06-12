from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import random
import time
from typing import Any, Optional

import requests
from cachetools import TTLCache
from jsonschema import validate


_CACHE_TTL_SECONDS = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "86400"))  # 24h
_CACHE_MAXSIZE = int(os.environ.get("LLM_CACHE_MAXSIZE", "2048"))
_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()

_llm_rate_lock = threading.Lock()
_last_llm_call_time = 0.0

def _is_debug_enabled() -> bool:
    return os.environ.get("ADDISON_INDEPENDENT_LLM_DEBUG", "").strip().lower() in ("1", "true", "yes", "y")


def ensure_env_loaded() -> dict[str, Any]:
    """
    Minimal .env loader (no extra deps).

    Loads a .env file from repo root if CLAUDE_API_KEY/ANTHROPIC_API_KEY isn't already set.
    Returns some diagnostic info (no secrets).
    """
    debug = _is_debug_enabled()

    already_has_key = bool(os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    env_path = None
    loaded = False
    keys_set: list[str] = []

    if already_has_key:
        if debug:
            print("[LLM][env] Claude key already present; skipping .env load.", flush=True)
        return {"already_has_key": True, "env_path": None, "loaded": False, "keys_set": []}

    try:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        env_path = str(repo_root / ".env")
        if os.path.exists(env_path):
            loaded_any = 0
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if not k:
                        continue
                    if k in os.environ and os.environ.get(k):
                        continue
                    os.environ[k] = v
                    loaded_any += 1
                    keys_set.append(k)

            loaded = loaded_any > 0
        else:
            loaded = False
    except Exception as e:
        if debug:
            print(f"[LLM][env] .env load failed: {e}", flush=True)
        loaded = False

    # Always emit a small non-secret diagnostic when we had to load .env.
    if not already_has_key:
        print(
            "[LLM][env] .env load attempt "
            f"loaded={loaded} env_path={env_path} "
            f"CLAUDE_API_KEY_present={bool(os.environ.get('CLAUDE_API_KEY') or os.environ.get('ANTHROPIC_API_KEY'))} "
            f"keys_set_count={len(keys_set)}",
            flush=True,
        )

    if debug:
        print(
            "[LLM][env] loaded="
            f"{loaded} already_has_key={already_has_key} env_path={env_path} keys_set_count={len(keys_set)} "
            f"keys_set_sample={keys_set[:5]}",
            flush=True,
        )
        print(
            "[LLM][env] after-load CLAUDE_API_KEY present="
            f"{bool(os.environ.get('CLAUDE_API_KEY') or os.environ.get('ANTHROPIC_API_KEY'))} "
            f"CLAUDE_BASE_URL={os.environ.get('CLAUDE_BASE_URL')} CLAUDE_MODEL={os.environ.get('CLAUDE_MODEL')}",
            flush=True,
        )

    return {
        "already_has_key": already_has_key,
        "env_path": env_path,
        "loaded": loaded,
        "keys_set": keys_set,
    }


_CLAUDE_DEFAULT_URL = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com/v1/messages")
_CLAUDE_DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-latest")


_RE_US_PHONE = re.compile(r"\b(\d{3})[-.\s]*(\d{3})[-.\s]*(\d{4})\b")


def _normalize_us_phone(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = _RE_US_PHONE.search(s)
    if not m:
        return None
    return f"({m.group(1)}){m.group(2)}-{m.group(3)}"


def _extract_first_json_object(text: str) -> Optional[dict[str, Any]]:
    """
    Best-effort extraction of the first JSON object found in `text`.
    This is defensive because some models occasionally wrap JSON in prose.
    """
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


_ADDISON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
    },
    "required": ["address", "description", "phone"],
    "additionalProperties": False,
}


def _sanitize_address(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-")
    if not s:
        return None
    # Cut any accidental spillover into contact/boilerplate.
    s = re.split(r"\b(Contact|More info|More information|Tickets?|www\.)\b", s, maxsplit=1, flags=re.IGNORECASE)[
        0
    ].strip(" ,.;:-")
    return s or None


def _sanitize_description(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    # Remove obvious boilerplate tails.
    s = re.split(
        r"\b(Contact|More info|More information|Tickets?|www\.)\b",
        s,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" ,.;:-")
    return s or None


def extract_addison_independent_fields(
    *,
    title: str,
    event_body_text: str,
    start_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """
    LLM-extract address/description/phone from a single Addison Independent <p> event block.

    Returns:
      { "address": str|None, "description": str|None, "phone": str|None }
    """
    if not title or not event_body_text:
        return {"address": None, "description": None, "phone": None}

    # Ensure .env is loaded if caller didn't do it.
    ensure_env_loaded()

    # Accept common env var names for Anthropic/Claude.
    model = model or _CLAUDE_DEFAULT_MODEL
    api_key = api_key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing CLAUDE_API_KEY/ANTHROPIC_API_KEY (required for LLM extraction).")

    model_candidates: list[str] = [model]
    fallbacks_raw = os.environ.get("CLAUDE_MODEL_FALLBACKS", "").strip()
    if not fallbacks_raw:
        # Common models (some may not be enabled for your account; we'll fallback on 404 not_found_error).
        fallbacks_raw = "claude-3-5-sonnet-latest,claude-3-opus-20240229,claude-3-sonnet-20240229,claude-2.1,claude-3-haiku-20240307"
    if fallbacks_raw:
        for x in fallbacks_raw.split(","):
            x = x.strip()
            if x and x not in model_candidates:
                model_candidates.append(x)
    model_i = 0

    if _is_debug_enabled():
        print(
            f"[LLM][models][page] candidates={model_candidates} starting_with={model_candidates[model_i]}",
            flush=True,
        )

    if _is_debug_enabled():
        print(
            f"[LLM][models] candidates={model_candidates} starting_with={model_candidates[model_i]}",
            flush=True,
        )

    # Cache key based on content + title only (times included as text in event_body_text usually).
    key_material = f"{title}\n{event_body_text}\n{start_date}\n{start_time}\n{end_time}"
    cache_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    with _cache_lock:
        if cache_key in _cache:
            cached = _cache[cache_key]
            if _is_debug_enabled():
                print(
                    f"[LLM][cache hit] key={cache_key[:10]} address_len={len(cached.get('address') or '')} "
                    f"description_len={len(cached.get('description') or '')} phone={cached.get('phone')}",
                    flush=True,
                )
            return {
                "address": cached.get("address"),
                "description": cached.get("description"),
                "phone": cached.get("phone"),
            }
        if _is_debug_enabled():
            print(
                f"[LLM][cache miss] key={cache_key[:10]} title_len={len(title)} body_len={len(event_body_text)}",
                flush=True,
            )

    system_prompt = (
        "You are an extraction assistant for event calendars. "
        "Given a single event paragraph from Addison Independent, extract structured fields. "
        "The <strong>/<b> text is the event title. After that comes time info and then a free-form paragraph "
        "containing address/venue (if present), description, and contact/registration/boilerplate."
    )
    user_prompt = (
        "Extract the following fields from the event text.\n\n"
        f"Title (bold): {title}\n\n"
        f"Event paragraph text (includes time/address/description/contact):\n{event_body_text}\n\n"
        "Rules:\n"
        "1) address: return the venue/location portion (e.g. 'Town Hall Theater, 76 Merchants Row, Middlebury, VT'). "
        "If no explicit address exists, infer a best-available venue/location from the title or text (must include town and 'VT' if present).\n"
        "2) description: return only the narrative description. Do NOT include phone numbers, email addresses, 'Contact ...', "
        "'More information/More info', 'Tickets', or 'www.' URL text.\n"
        "3) phone: extract the phone number if present and normalize to '(AAA)BBB-CCCC'. Otherwise null.\n"
        "4) Output MUST be valid JSON only, matching the schema.\n"
        f"start_date: {start_date or 'NULL'}\n"
        f"start_time: {start_time or 'NULL'}\n"
        f"end_time: {end_time or 'NULL'}\n"
    )

    body = {
        "model": model,
        "temperature": 0,
        # Claude uses a top-level "system" field for system instructions.
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "600")),
    }

    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "5"))
    base_wait = float(os.environ.get("LLM_RETRY_BASE_SECONDS", "1.0"))
    min_interval = float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", "0.6"))

    if _is_debug_enabled():
        print(
            f"[LLM][request] url={_CLAUDE_DEFAULT_URL} model={model} max_tokens={body['max_tokens']} "
            f"timeout={os.environ.get('LLM_TIMEOUT_SECONDS', '40')}",
            flush=True,
        )

    last_err: Optional[Exception] = None
    payload: Optional[dict[str, Any]] = None
    for attempt in range(max_retries + 1):
        # Cross-thread rate limiting: ensure at least `min_interval` seconds between LLM calls.
        with _llm_rate_lock:
            global _last_llm_call_time
            now = time.time()
            elapsed = now - _last_llm_call_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            _last_llm_call_time = time.time()

        try:
            resp = requests.post(
                _CLAUDE_DEFAULT_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": os.environ.get("ANTHROPIC_API_VERSION", "2023-06-01"),
                    "content-type": "application/json",
                },
                json=body,
                timeout=int(os.environ.get("LLM_TIMEOUT_SECONDS", "40")),
            )
            # If it's an HTTP error, attempt retry (especially for 429).
            resp.raise_for_status()
            payload = resp.json()
            last_err = None
            break
        except requests.HTTPError as e:
            last_err = e
            status = getattr(resp, "status_code", None) if "resp" in locals() else None
            retry_after = None
            err_text = None
            try:
                retry_after_raw = resp.headers.get("Retry-After") if "resp" in locals() else None
                if retry_after_raw:
                    retry_after = float(retry_after_raw)
            except Exception:
                retry_after = None
            try:
                if "resp" in locals() and resp is not None:
                    err_text = resp.text
            except Exception:
                err_text = None

            if _is_debug_enabled():
                print(
                    f"[LLM][request failed] attempt={attempt}/{max_retries} status={status} retry_after={retry_after} err={e}",
                    flush=True,
                )
                if err_text:
                    snippet = err_text.strip().replace("\n", " ")
                    if len(snippet) > 800:
                        snippet = snippet[:800] + "..."
                    print(f"[LLM][request failed body] {snippet}", flush=True)

            if attempt >= max_retries:
                payload = None
                break

            # If it's a quota/billing-related 429, retries won't help.
            # Examples often contain phrases like "insufficient_quota" / "quota" / "billing".
            if status == 429 and err_text:
                low = err_text.lower()
                if any(k in low for k in ["insufficient_quota", "insufficient quota", "quota", "billing", "payment_required"]):
                    raise RuntimeError(f"LLM quota/billing issue (429): {err_text}")
            # Claude may also return 400 for insufficient credits.
            if status == 400 and err_text:
                low = err_text.lower()
                if any(k in low for k in ["credit balance is too low", "insufficient credits", "purchase credits", "plans & billing", "upgrade"]):
                    raise RuntimeError(f"LLM credit/billing issue (400): {err_text}")

            # Exponential backoff with jitter. If Retry-After exists, prefer it.
            if retry_after is not None:
                wait_s = retry_after
            else:
                wait_s = base_wait * (2 ** attempt)
            wait_s = max(wait_s, 0.2) + random.uniform(0, 0.25)
            if _is_debug_enabled():
                print(f"[LLM][request retry] waiting {wait_s:.2f}s", flush=True)
            time.sleep(wait_s)

    if last_err is not None and payload is None:
        raise last_err

    # Claude messages response: { content: [ { type: "text", text: "..." } ] }
    content = None
    try:
        content = payload.get("content", [{}])[0].get("text")
    except Exception:
        content = None
    if not content:
        raise RuntimeError(f"LLM returned no content. Raw payload keys: {list(payload.keys())}")

    if _is_debug_enabled():
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        print(f"[LLM][raw content snippet] {snippet}", flush=True)

    extracted = _extract_first_json_object(content)
    if not extracted:
        raise RuntimeError("LLM response did not contain valid JSON.")

    try:
        validate(instance=extracted, schema=_ADDISON_SCHEMA)
    except Exception as e:
        if _is_debug_enabled():
            print(f"[LLM][json validation failed] error={e} extracted={extracted}", flush=True)
        raise

    address = _sanitize_address(extracted.get("address"))
    description = _sanitize_description(extracted.get("description"))
    phone = _normalize_us_phone(extracted.get("phone")) if extracted.get("phone") else None

    result = {"address": address, "description": description, "phone": phone}
    if _is_debug_enabled():
        print(
            f"[LLM][extracted] address_len={len(address or '')} description_len={len(description or '')} phone={phone}",
            flush=True,
        )
    with _cache_lock:
        _cache[cache_key] = result
    return result


_ADDISON_PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "address": {"type": ["string", "null"]},
                    "organizer": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "phone": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                    "cost": {"type": ["number", "string", "null"]},
                    "contact": {"type": ["string", "null"]},
                    "image_url": {"type": ["string", "null"]},
                },
                "required": [
                    "idx",
                    "start_date",
                    "end_date",
                    "start_time",
                    "end_time",
                    "address",
                    "organizer",
                    "description",
                    "phone",
                    "email",
                    "cost",
                    "contact",
                    "image_url",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


def extract_addison_independent_events_from_page(
    *,
    url: str,
    events_inputs: list[dict[str, Any]],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    """
    LLM-extract fields from the whole Addison Independent calendar page.

    `events_inputs` should be a list of { idx, title, paragraph_text }.
    Returns a list of { idx, address, description, phone }.
    """
    if not events_inputs:
        return []

    ensure_env_loaded()

    model = model or _CLAUDE_DEFAULT_MODEL
    api_key = api_key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing CLAUDE_API_KEY/ANTHROPIC_API_KEY (required for LLM extraction).")

    model_candidates: list[str] = [model]
    fallbacks_raw = os.environ.get("CLAUDE_MODEL_FALLBACKS", "").strip()
    if not fallbacks_raw:
        fallbacks_raw = "claude-3-5-sonnet-latest,claude-3-opus-20240229,claude-3-sonnet-20240229,claude-2.1,claude-3-haiku-20240307"
    if fallbacks_raw:
        for x in fallbacks_raw.split(","):
            x = x.strip()
            if x and x not in model_candidates:
                model_candidates.append(x)
    model_i = 0

    # Cache key: hash of url + input list.
    if _is_debug_enabled():
        print(
            f"[LLM][models][page] candidates={model_candidates} starting_with={model_candidates[model_i]}",
            flush=True,
        )

    key_material = f"{url}\n{json.dumps(events_inputs, ensure_ascii=False, sort_keys=True)}"
    cache_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    with _cache_lock:
        if cache_key in _cache:
            cached = _cache[cache_key]
            if _is_debug_enabled():
                print(
                    f"[LLM][cache hit][page] key={cache_key[:10]} events={len(cached)}",
                    flush=True,
                )
            return cached

    system_prompt = (
        "You are an extraction assistant for event calendars. "
        "You will be given multiple event paragraphs from Addison Independent. "
        "Return a JSON object with one entry per provided event idx. "
        "Extract the requested fields from each paragraph only; do not invent missing values."
    )

    # We pass the events_inputs JSON to make indexing deterministic.
    user_prompt = (
        "Extract structured fields for each provided event paragraph.\n\n"
        f"URL: {url}\n\n"
        f"EVENTS_INPUTS_JSON:\n{json.dumps(events_inputs, ensure_ascii=False)}\n\n"
        "Return JSON only in the following shape:\n"
        "{ \"events\": [ {"
        "\"idx\": <same idx>, "
        "\"start_date\": <string|null>, "
        "\"end_date\": <string|null>, "
        "\"start_time\": <string|null>, "
        "\"end_time\": <string|null>, "
        "\"address\": <string|null>, "
        "\"organizer\": <string|null>, "
        "\"description\": <string|null>, "
        "\"phone\": <string|null>, "
        "\"email\": <string|null>, "
        "\"cost\": <number|null>, "
        "\"contact\": <string|null>, "
        "\"image_url\": <string|null>"
        " }, ... ] }\n\n"
        "Field rules:\n"
        "1) start_date/end_date: return ISO format YYYY-MM-DD if present, else null.\n"
        "2) start_time/end_time: return 24h time HH:MM if present (e.g. 15:30), else null.\n"
        "3) address: return the venue/location portion if present; otherwise infer from the title/text. Must include town and VT if present.\n"
        "4) organizer: if the paragraph contains a named organizer/contact/host, return that name; otherwise null.\n"
        "5) description: narrative only; exclude phone, email, 'Contact ...', 'More information/More info', 'Tickets', and 'www.' URL fragments.\n"
        "6) phone: if present, normalize to '(AAA)BBB-CCCC' (US format). Otherwise null.\n"
        "7) email: if present in the paragraph, return the email string. Otherwise null.\n"
        "8) cost: if there are explicit dollar amounts, return a single numeric value. If it's a range like '$5-$10', use the first number. Otherwise null.\n"
        "9) contact: if there is a 'Contact Name' style person name, return the name; otherwise null.\n"
        "10) image_url: if an image URL is explicitly present in the paragraph, return it; otherwise null.\n"
    )

    body = {
        "model": model_candidates[model_i],
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "900")),
    }

    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "5"))
    base_wait = float(os.environ.get("LLM_RETRY_BASE_SECONDS", "1.0"))
    min_interval = float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", "0.6"))

    if _is_debug_enabled():
        print(
            f"[LLM][request][page] url={_CLAUDE_DEFAULT_URL} model={model} events_in={len(events_inputs)} "
            f"max_tokens={body['max_tokens']} timeout={os.environ.get('LLM_TIMEOUT_SECONDS', '40')}",
            flush=True,
        )

    last_err: Optional[Exception] = None
    payload: Optional[dict[str, Any]] = None
    for attempt in range(max_retries + 1):
        with _llm_rate_lock:
            global _last_llm_call_time
            now = time.time()
            elapsed = now - _last_llm_call_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            _last_llm_call_time = time.time()

        try:
            resp = requests.post(
                _CLAUDE_DEFAULT_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": os.environ.get("ANTHROPIC_API_VERSION", "2023-06-01"),
                    "content-type": "application/json",
                },
                json=body,
                timeout=int(os.environ.get("LLM_TIMEOUT_SECONDS", "40")),
            )
            resp.raise_for_status()
            payload = resp.json()
            last_err = None
            break
        except requests.HTTPError as e:
            last_err = e
            status = getattr(resp, "status_code", None) if "resp" in locals() else None
            retry_after = None
            err_text = None
            try:
                if "resp" in locals() and resp is not None:
                    retry_after_raw = resp.headers.get("Retry-After")
                    if retry_after_raw:
                        retry_after = float(retry_after_raw)
                    err_text = resp.text
            except Exception:
                retry_after = None
                err_text = None

            if _is_debug_enabled():
                print(
                    f"[LLM][request failed][page] attempt={attempt}/{max_retries} status={status} retry_after={retry_after} err={e}",
                    flush=True,
                )
                if err_text:
                    snippet = err_text.strip().replace("\n", " ")
                    if len(snippet) > 800:
                        snippet = snippet[:800] + "..."
                    print(f"[LLM][request failed body][page] {snippet}", flush=True)
            else:
                # Always surface 404s: these usually indicate misconfigured endpoint/model/provider.
                if status == 404 and err_text:
                    snippet = err_text.strip().replace("\n", " ")
                    if len(snippet) > 800:
                        snippet = snippet[:800] + "..."
                    print(
                        f"[LLM][request failed][page] status=404 url={_CLAUDE_DEFAULT_URL} model={model} "
                        f"err={e} body_snippet={snippet}",
                        flush=True,
                    )

            if attempt >= max_retries:
                payload = None
                break

            low = (err_text or "").lower()
            if status == 429 and any(k in low for k in ["insufficient_quota", "insufficient quota", "quota", "billing", "payment_required"]):
                raise RuntimeError(f"LLM quota/billing issue (429): {err_text}")
            if status == 400 and any(k in low for k in ["credit balance is too low", "insufficient credits", "purchase credits", "plans & billing", "upgrade"]):
                raise RuntimeError(f"LLM credit/billing issue (400): {err_text}")

            # If the model is not found, try fallbacks (no backoff/retries needed).
            if status == 404 and err_text and "not_found_error" in err_text.lower() and "model:" in err_text.lower():
                if model_i + 1 < len(model_candidates):
                    model_i += 1
                    body["model"] = model_candidates[model_i]
                    if _is_debug_enabled():
                        print(
                            f"[LLM][model fallback][page] switched to model={body['model']} (model_i={model_i})",
                            flush=True,
                        )
                    continue
                # Exhausted all candidates: fail fast with a helpful message.
                raise RuntimeError(
                    "Claude model not available for this API key/account (404 not_found_error). "
                    f"Tried models: {model_candidates}. "
                    "Set CLAUDE_MODEL to one of the models shown as available in your Anthropic dashboard "
                    "or set CLAUDE_MODEL_FALLBACKS."
                )

            if retry_after is not None:
                wait_s = retry_after
            else:
                wait_s = base_wait * (2 ** attempt)
            wait_s = max(wait_s, 0.2) + random.uniform(0, 0.25)
            if _is_debug_enabled():
                print(f"[LLM][request retry][page] waiting {wait_s:.2f}s", flush=True)
            time.sleep(wait_s)

    if last_err is not None and payload is None:
        raise last_err

    # Extract Claude content
    content = None
    try:
        content = payload.get("content", [{}])[0].get("text") if payload else None
    except Exception:
        content = None
    if not content:
        raise RuntimeError(f"LLM returned no content. Raw payload keys: {list((payload or {}).keys())}")

    if _is_debug_enabled():
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 900:
            snippet = snippet[:900] + "..."
        print(f"[LLM][raw content snippet][page] {snippet}", flush=True)

    extracted = _extract_first_json_object(content)
    if not extracted:
        raise RuntimeError("LLM page response did not contain valid JSON.")

    validate(instance=extracted, schema=_ADDISON_PAGE_SCHEMA)

    # Sanitize outputs
    out: list[dict[str, Optional[Any]]] = []
    for ev in extracted.get("events", []):
        def _norm_date(s: Optional[str]) -> Optional[str]:
            if not s:
                return None
            s = str(s).strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                return s
            return None

        def _norm_time(s: Optional[str]) -> Optional[str]:
            if not s:
                return None
            s = str(s).strip()
            m = re.fullmatch(r"(?P<h>\d{1,2}):(?P<m>\d{2})", s)
            if not m:
                return None
            return f"{int(m.group('h')):02d}:{int(m.group('m')):02d}"

        start_date = _norm_date(ev.get("start_date"))
        end_date = _norm_date(ev.get("end_date"))
        start_time = _norm_time(ev.get("start_time"))
        end_time = _norm_time(ev.get("end_time"))

        address = _sanitize_address(ev.get("address"))
        organizer = ev.get("organizer")
        if isinstance(organizer, str):
            organizer = re.sub(r"\s+", " ", organizer).strip(" .;:-,")
            if not organizer:
                organizer = None

        description = _sanitize_description(ev.get("description"))
        phone = _normalize_us_phone(ev.get("phone")) if ev.get("phone") else None

        email = ev.get("email")
        if isinstance(email, str):
            m = re.search(r"\b[\w\.-]+@[\w\.-]+\.[A-Za-z]{2,}\b", email)
            email = m.group(0) if m else None
        else:
            email = None

        cost = ev.get("cost")
        if isinstance(cost, str):
            # Try to parse the first number from strings like "$5-$10"
            m = re.search(r"(\d+(?:\.\d+)?)", cost)
            cost = float(m.group(1)) if m else None
        elif isinstance(cost, (int, float)):
            cost = float(cost)
        else:
            cost = None

        contact = ev.get("contact")
        if isinstance(contact, str):
            contact = re.sub(r"\s+", " ", contact).strip(" .;:-,")
            if not contact:
                contact = None
        else:
            contact = None

        image_url = ev.get("image_url")
        if isinstance(image_url, str):
            image_url = image_url.strip()
            if image_url and not image_url.lower().startswith(("http://", "https://")):
                image_url = None
        else:
            image_url = None

        out.append(
            {
                "idx": ev.get("idx"),
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "address": address,
                "organizer": organizer,
                "description": description,
                "phone": phone,
                "email": email,
                "cost": cost,
                "contact": contact,
                "image_url": image_url,
            }
        )

    with _cache_lock:
        _cache[cache_key] = out

    return out

