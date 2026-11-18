# Formal proofs of the security rules

telegram-reader stands on a few rules: Claude reads only chats of the selected folders, the
server sends and changes nothing, and any failure closes access. The ordinary tests check
these rules on examples. This directory proves them for every input, in
[Bend 2](https://bend-lang.com), a language with dependent types whose compiler checks proofs.

The Python code stays the real thing. Nothing here replaces it: next to it sits a small model
of its security logic, the laws stated over the model, their proofs, and tests that hold the
model and the code together.

```
proofs/
  LAWS.bend       the laws: plain words in a comment, then the formal claim
  PROOF.bend      a proof of every law
  model/          the models: access, features, guard, sanitize
  harness/        entry point of the binary the differential tests talk to
tests/test_bend_model.py   the model against the real code, with Hypothesis
```

## Running

```bash
curl -fsSL https://bend-lang.com/install.sh | sh    # installs into ~/.bend, no sudo
export PATH="$HOME/.bend/bin:$PATH" BEND_NO_TELEMETRY=1

bend proofs/PROOF.bend                  # must print ALL PROOFS CHECK
uv run pytest tests/test_bend_model.py  # the model against the Python code
```

CI runs both in the `bend-proofs` job with Bend 2.0.40 (sha256 pinned). Building the harness
binary needs clang 14 or newer. Read `bend guide` before writing any Bend: the syntax is new
and unlike Bend 1.

`bend proofs/PROOF.bend --verdict` rechecks the proofs with Bend's small Lean-verified kernel.
It needs Lean 4 installed and is not part of CI.

## What is proven

Laws carry the names used in `LAWS.bend`. All 44 are proven; none uses `@unsafe` or `def f?`.

| Rule | Laws | In words |
| --- | --- | --- |
| A1 | `a1_found_is_allowed`, `a1_unknown_id_is_denied`, `a1_unknown_title_is_denied`, `a1_unknown_numeric_string_is_denied` | `resolve` returns only a whitelisted chat; a reference that fits none is `AccessDenied` |
| A2 | `a2_two_matches_are_ambiguous`, `a2_found_is_the_only_match`, `a2_shared_title_is_ambiguous` | Two or more matches are always `AmbiguousChat`; a chat is returned only as the single match |
| A3 | `a3_int_is_matched_by_id_only`, `a3_int_finds_that_id` | An int is looked up by id only; what it finds has that id |
| A4 | `a4_numeric_string_falls_back_to_title` (with A1) | A numeric-looking string that is no whitelisted id is looked up by title |
| A5 | `a5_failed_refresh_locks`, `a5_failed_refresh_raises`, `a5_locked_stays_locked`, `a5_fail_closed` | A failed refresh empties the whitelist and the PeerGuard list; nothing resolves until a refresh succeeds |
| A6 | `a6_mismatch_fails_refresh`, `a6_mismatch_locks`, `a6_mismatch_raises` | A refresh under a config for another account is `AccountMismatch` and locks |
| B1 | `b1_no_feature_no_extra`, `b1_non_read_is_refused`, `b1_client_non_read_is_refused` | With no feature enabled only reads pass `ensure_read_only`; through the client, only reads and `DOWNLOAD_REQUESTS` |
| B2 | `b2_unavailable_adds_nothing`, `b2_shipped_registry_adds_nothing` | A feature that is not available adds no request, even when enabled |
| B3 | `b3_peer_outside_whitelist_is_refused`, `b3_peer_ok_means_whitelisted`, `b3_unverifiable_peer_is_refused`, `b3_self_needs_known_account` | One peer outside the whitelist, in any field or any place of a list, refuses the request |
| B4 | `b4_peerless_passes_only_if_listed`, `b4_id_outside_whitelist_is_refused`, `b4_id_is_checked_as_peer` | A request without a peer field passes only from `_PEERLESS_ALLOWED` or by exact extra name; `_ID_PEERS` ids are checked as peers |
| B5 | `b5_read_only_checks_every_request`, `b5_check_checks_every_request`, `b5_one_refused_refuses_the_batch` | A batch passes only if every request in it passes |
| B6 | `b6_filter_leaves_only_whitelisted`, `b6_kept_means_whitelisted`, `b6_message_without_peer_is_dropped`, `b6_message_with_odd_peer_is_dropped` | `filter_response` leaves only messages of whitelisted chats |
| C1 | `c1_clip_fits_the_limit`, `c1_no_mark_without_hidden` | Without the mark, `clip` returns at most `limit` characters |
| C2 | `c2_clip_ends_with_the_mark`, `c2_clean_ends_with_the_mark`, `c2_nothing_removed_without_hidden`, `c2_removal_means_hidden` | If something was removed, the whole mark is the end of the result |
| C3 | `c3_clip_has_no_hidden`, `c3_clean_has_no_hidden` | The result of `clean` and `clip` holds no hidden character |

Two laws are worded with more care than the short rule, because the code does more than the
rule says:

- **B1.** `ReadOnlyTelegramClient._call` always adds `DOWNLOAD_REQUESTS` to the allowed names.
  Two of them, `ReuploadCdnFileRequest` and `ExportAuthorizationRequest`, are not reads by
  prefix. So the rule "no feature, no non-read" holds for `ensure_read_only` itself
  (`b1_non_read_is_refused`) and, for the client, reads "a read or one of `DOWNLOAD_REQUESTS`"
  (`b1_client_non_read_is_refused`).
- **A5, A6.** `Access` checks the account and Telegram only when it refreshes. While the cache
  is valid (same `Config` object, under `FOLDER_TTL_SECONDS`) no refresh runs, so the laws say
  "a refresh that fails" and "a refresh under another account", not "any call".

## How the model maps to the code

| Python | Bend model | Notes |
| --- | --- | --- |
| `models.ChatInfo` | `access.bend` `Chat{id, title}` | only what `_match` reads; a title is the class of `access._norm(title)` |
| `access._as_id`, `access._norm` on a reference | `Ref`: `RInt{id}`, `RStr{as_id, title}` | the two functions are inputs to the model, not modelled |
| `access._match` | `matches`, `select`, `fits`, `or_else` | |
| `Access.resolve` (after the refresh) | `resolve`, `pick` | `Denied` = `AccessDenied`, `Ambiguous` = `AmbiguousChat` |
| `Access._refresh` | `outcome`, `refresh_as`, `refresh_tg` | account check first, then Telegram's answer as an input (`Tg`) |
| `Access._ensure_fresh` | `skips`, `next`, `next_if`, `apply` | `Call.cached` is the cache test apart from `_refreshed_at is not None` |
| `Access._lock_down` | `locked` | empty whitelist, empty PeerGuard list, cache invalid |
| `Access.resolve`, end to end | `answer`, `run` | |
| `features.Feature`, `FEATURES` | `features.bend` `Feature`, `registry` | `registry` mirrors the shipped registry; a test fails if it drifts |
| `features.allowed_requests` | `allowed_requests` | |
| a Telethon request | `guard.bend` `Req{name, reads, denied, fields, kind}` | `reads`: name has a `_READ_PREFIXES` prefix; `denied`: name in `_DENIED_READS`; `fields`: the `_PEER_FIELDS` that are not `None`; `kind`: `_ID_PEERS`, `_PEERLESS_ALLOWED` or neither |
| `tg.ensure_read_only` | `read_only`, `read_ok` | |
| `PeerGuard._peer_id` | `Peer`: `PId`, `PUserSelf`, `PPeerSelf`, `PBad` | Telethon's id arithmetic is not modelled: a peer is the id it computes, or "cannot be verified" |
| `PeerGuard._check` | `peer_ok`, `id_ok`, `field_ok`, `ids_ok` | |
| `PeerGuard.check_request` | `check`, `check_one`, `check_parts`, `peerless_ok` | |
| `ReadOnlyTelegramClient._call` | `call_ok`, `passes`, `extra_of` | both guards, with `extra_requests | DOWNLOAD_REQUESTS` |
| `PeerGuard._keep`, `filter_response` | `keeps`, `filter_msgs` | a message is its `peer_id`: missing, not a peer, or a chat id |
| `sanitize._strip` | `sanitize.bend` `strip` | over character classes: plain, hidden, space |
| `" ".join(text.split())` | `flat`, `words` | |
| `sanitize.clip` | `clip`, `clip_body`, `cut`, `mark_if` | |
| `sanitize.clean` | `clean` | |

The "inputs to the model" are where a proof stops and a test takes over.
`tests/test_bend_model.py` generates the abstract input and the concrete one together (real
`ChatInfo`, real Telethon requests and results, real strings), runs the real code and the
model on them, and fails on any difference with a minimal example. Each property runs 500
examples.

## What the model does not cover

- Telethon itself, the network, the keychain, MTProto. `utils.get_peer_id`, the entity cache
  and Telethon's own requests are trusted as they are.
- `access._norm` and `access._as_id` (case folding, whitespace, what counts as a number), and
  the chat metadata cache inside `Access._refresh` (which `ChatInfo` is reused, forum topics,
  warnings). The model takes the whitelist a refresh produced as given.
- Concurrency: the `asyncio.Lock` in `Access`, a cancellation between two awaits.
- The contents of the tables `_READ_PREFIXES`, `_DENIED_READS`, `_PEERLESS_ALLOWED`,
  `_ID_PEERS`, `DOWNLOAD_REQUESTS`. The laws say what the guards do with a request that is or
  is not in a table, not whether the right names are in it. A request with a read prefix and a
  whitelisted peer passes, whatever it does on Telegram's side.
- `filter_response` looks at the `messages` and `new_messages` lists of a result. Messages
  nested elsewhere (inside `updates`, for one) are outside the model, as they are outside the
  code.
- `sanitize`: real Unicode, the zero-width joiner rule of `_strip_zwj`, `looks_like_injection`
  and `new_nonce`.
- The MCP tools in `server.py`, formatting, files and links.

## Changing the code or the laws

A change in `access.py`, `tg.py`, `features.py` or `sanitize.py` needs the model updated to
match, `bend proofs/PROOF.bend` passing and `uv run pytest` green. If a proof no longer goes
through, find out first where the error is: the model, the law or the Python. Laws are not
weakened to make a proof pass; a change to a law needs the owner's explicit agreement.
