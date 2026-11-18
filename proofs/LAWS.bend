# The security laws of telegram-reader, stated over the models in ./model.
#
# Each law is an open claim here; PROOF.bend proves it, and `bend
# proofs/PROOF.bend` checks every proof for all inputs. The models are tied to
# the Python code by tests/test_bend_model.py (see proofs/README.md).
#
# Do not weaken a law without the owner's explicit agreement.
import Base
import ./model/access.bend as A
import ./model/features.bend as F
import ./model/guard.bend as G
import ./model/sanitize.bend as S

# A. Choosing a chat: access.py
# =============================

# A1. Access.resolve returns only a chat of the whitelist.
# access.py: Access.resolve, _match
law a1_found_is_allowed:
  for +ref: A.Ref
  for +chats: List<&2, A.Chat>
  for +c: A.Chat
  for e: {A.resolve(ref, chats) == A.Found{c} : A.Res}
  {A.mem(c, chats) == True{} : Bool}

# A1. An int that is the id of no whitelisted chat is refused (AccessDenied).
# access.py: Access.resolve, _match
law a1_unknown_id_is_denied:
  for +i: Nat
  for +chats: List<&2, A.Chat>
  for e: {A.known(A.ById{i}, chats) == False{} : Bool}
  {A.resolve(A.RInt{i}, chats) == A.Denied{} : A.Res}

# A1. A name that is the title of no whitelisted chat is refused.
# access.py: Access.resolve, _match
law a1_unknown_title_is_denied:
  for +t: Nat
  for +chats: List<&2, A.Chat>
  for e: {A.known(A.ByTitle{t}, chats) == False{} : Bool}
  {A.resolve(A.RStr{None{}, t}, chats) == A.Denied{} : A.Res}

# A1. A numeric-looking string that is neither an id nor a title of a
# whitelisted chat is refused.
# access.py: Access.resolve, _match
law a1_unknown_numeric_string_is_denied:
  for +i: Nat
  for +t: Nat
  for +chats: List<&2, A.Chat>
  for ei: {A.known(A.ById{i}, chats) == False{} : Bool}
  for et: {A.known(A.ByTitle{t}, chats) == False{} : Bool}
  {A.resolve(A.RStr{Some{i}, t}, chats) == A.Denied{} : A.Res}

# A2. Two or more matches always give AmbiguousChat.
# access.py: Access.resolve
law a2_two_matches_are_ambiguous:
  for +ref: A.Ref
  for +chats: List<&2, A.Chat>
  for +a: A.Chat
  for +b: A.Chat
  for +rest: List<&2, A.Chat>
  for e: {A.matches(ref, chats) == a <> b <> rest : List<&2, A.Chat>}
  {A.resolve(ref, chats) == A.Ambiguous{} : A.Res}

# A2. A chat is returned only when it is the single match: never "the first".
# access.py: Access.resolve
law a2_found_is_the_only_match:
  for +ref: A.Ref
  for +chats: List<&2, A.Chat>
  for +c: A.Chat
  for e: {A.resolve(ref, chats) == A.Found{c} : A.Res}
  {A.matches(ref, chats) == [c] : List<&2, A.Chat>}

# A2. Two or more whitelisted chats with the wanted title give AmbiguousChat.
# access.py: Access.resolve, _match
law a2_shared_title_is_ambiguous:
  for +t: Nat
  for +chats: List<&2, A.Chat>
  for +k: Nat
  for e: {A.count(A.ByTitle{t}, chats) == 2n+k : Nat}
  {A.resolve(A.RStr{None{}, t}, chats) == A.Ambiguous{} : A.Res}

# A3. An int reference is looked up by id only: the titles play no part.
# access.py: _match (`if by_id or isinstance(ref, int): return by_id`)
law a3_int_is_matched_by_id_only:
  for +i: Nat
  for +chats: List<&2, A.Chat>
  {A.matches(A.RInt{i}, chats) == A.select(A.ById{i}, chats) : List<&2, A.Chat>}

# A3. The chat an int reference resolves to has that id.
# access.py: Access.resolve, _match
law a3_int_finds_that_id:
  for +i: Nat
  for +chats: List<&2, A.Chat>
  for +c: A.Chat
  for e: {A.resolve(A.RInt{i}, chats) == A.Found{c} : A.Res}
  {A.fits(A.ById{i}, c) == True{} : Bool}

# A4. A numeric-looking string that is no whitelisted id is looked up by title
# (a chat named "2026"). By A1 the chat found is still a whitelisted one.
# access.py: _match
law a4_numeric_string_falls_back_to_title:
  for +i: Nat
  for +t: Nat
  for +chats: List<&2, A.Chat>
  for e: {A.known(A.ById{i}, chats) == False{} : Bool}
  {A.matches(A.RStr{Some{i}, t}, chats) == A.select(A.ByTitle{t}, chats) : List<&2, A.Chat>}

# A5. A refresh that raises empties the whitelist and the PeerGuard list.
# access.py: Access._ensure_fresh, Access._lock_down
law a5_failed_refresh_locks:
  for +state: A.State
  for +call: A.Call
  for +err: A.Err
  for ran: {A.skips(state, call) == False{} : Bool}
  for fail: {A.outcome(call) == A.Failed{err} : A.Outcome}
  {A.next(state, call) == A.State{[], [], False{}} : A.State}

# A5. The call whose refresh raised resolves nothing: it raises.
# access.py: Access.resolve, Access._ensure_fresh
law a5_failed_refresh_raises:
  for +state: A.State
  for +call: A.Call
  for +ref: A.Ref
  for +err: A.Err
  for ran: {A.skips(state, call) == False{} : Bool}
  for fail: {A.outcome(call) == A.Failed{err} : A.Outcome}
  {A.answer(state, call, ref) == A.Raised{err} : A.Ans}

# A5. While every refresh keeps failing, the whitelist stays locked.
# access.py: Access._ensure_fresh, Access._lock_down
law a5_locked_stays_locked:
  for +calls: List<&2, A.Call>
  for fails: {A.all_fail(calls) == True{} : Bool}
  {A.run(calls, A.locked()) == A.locked() : A.State}

# A5. Fail closed: after a failed refresh, however many failed calls follow,
# the next call whose refresh fails resolves nothing. Only a successful refresh
# opens the whitelist again.
# access.py: Access.resolve, Access._ensure_fresh, Access._lock_down
law a5_fail_closed:
  for +state: A.State
  for +first: A.Call
  for +err0: A.Err
  for +calls: List<&2, A.Call>
  for +call: A.Call
  for +ref: A.Ref
  for +err: A.Err
  for ran: {A.skips(state, first) == False{} : Bool}
  for fail0: {A.outcome(first) == A.Failed{err0} : A.Outcome}
  for fails: {A.all_fail(calls) == True{} : Bool}
  for fail: {A.outcome(call) == A.Failed{err} : A.Outcome}
  {A.answer(A.run(calls, A.next(state, first)), call, ref) == A.Raised{err} : A.Ans}

# A6. A refresh under a config whose account_id differs from the session's
# account fails with AccountMismatch, whatever Telegram would answer.
# access.py: Access._refresh
law a6_mismatch_fails_refresh:
  for +cached: Bool
  for +cfg_acct: Maybe<&2, Nat>
  for +sess_acct: Maybe<&2, Nat>
  for +tg: A.Tg
  for diff: {A.acct_eq(cfg_acct, sess_acct) == False{} : Bool}
  {A.outcome(A.Call{cached, cfg_acct, sess_acct, tg}) == A.Failed{A.Mismatch{}} : A.Outcome}

# A6. ...and that refresh locks the whitelist.
# access.py: Access._refresh, Access._lock_down
law a6_mismatch_locks:
  for +state: A.State
  for +cached: Bool
  for +cfg_acct: Maybe<&2, Nat>
  for +sess_acct: Maybe<&2, Nat>
  for +tg: A.Tg
  for ran: {A.skips(state, A.Call{cached, cfg_acct, sess_acct, tg}) == False{} : Bool}
  for diff: {A.acct_eq(cfg_acct, sess_acct) == False{} : Bool}
  {A.next(state, A.Call{cached, cfg_acct, sess_acct, tg}) == A.State{[], [], False{}} : A.State}

# A6. ...and the call raises AccountMismatch instead of resolving.
# access.py: Access.resolve, Access._refresh
law a6_mismatch_raises:
  for +state: A.State
  for +cached: Bool
  for +cfg_acct: Maybe<&2, Nat>
  for +sess_acct: Maybe<&2, Nat>
  for +tg: A.Tg
  for +ref: A.Ref
  for ran: {A.skips(state, A.Call{cached, cfg_acct, sess_acct, tg}) == False{} : Bool}
  for diff: {A.acct_eq(cfg_acct, sess_acct) == False{} : Bool}
  {A.answer(state, A.Call{cached, cfg_acct, sess_acct, tg}, ref) == A.Raised{A.Mismatch{}} : A.Ans}

# B. Read-only guard: tg.py and features.py
# =========================================

# B1. With no feature enabled, the features add no request name.
# features.py: allowed_requests
law b1_no_feature_no_extra:
  for +reg: List<&2, F.Feature>
  {F.allowed_requests(reg, []) == [] : List<&2, Nat>}

# B1. With no extra name, ensure_read_only lets a request through only if it
# is a read: a read prefix and not in _DENIED_READS.
# tg.py: ensure_read_only
law b1_non_read_is_refused:
  for +reg: List<&2, F.Feature>
  for +name: Nat
  for +reads: Bool
  for +denied: Bool
  for +fields: List<&2, List<&2, G.Peer>>
  for +kind: G.Peerless
  for e: {G.read_only(F.allowed_requests(reg, []), [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool}
  {(reads && Bool.not(denied)) == True{} : Bool}

# B1, as the client runs it. ReadOnlyTelegramClient._call always adds
# DOWNLOAD_REQUESTS to the extra names, so with no feature enabled a request
# gets through only if it is a read or one of DOWNLOAD_REQUESTS.
# tg.py: ReadOnlyTelegramClient._call, ensure_read_only
law b1_client_non_read_is_refused:
  for +reg: List<&2, F.Feature>
  for +dl: List<&2, Nat>
  for +g: G.Guard
  for +name: Nat
  for +reads: Bool
  for +denied: Bool
  for +fields: List<&2, List<&2, G.Peer>>
  for +kind: G.Peerless
  for e: {G.call_ok(reg, [], dl, g, [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool}
  {(F.has(name, dl) || (reads && Bool.not(denied))) == True{} : Bool}

# B2. Features that are not available add no request name, whatever the config
# enables.
# features.py: allowed_requests
law b2_unavailable_adds_nothing:
  for +reg: List<&2, F.Feature>
  for +enabled: List<&2, Nat>
  for e: {F.none_available(reg) == True{} : Bool}
  {F.allowed_requests(reg, enabled) == [] : List<&2, Nat>}

# B2. So the registry as shipped ("write", not available) adds nothing.
# features.py: FEATURES, allowed_requests
law b2_shipped_registry_adds_nothing:
  for +enabled: List<&2, Nat>
  {F.allowed_requests(F.registry(), enabled) == [] : List<&2, Nat>}

# B3. A request with a peer outside the whitelist in any peer field is
# refused, wherever the peer sits: any field, any place in a list of peers.
# tg.py: PeerGuard.check_request, PeerGuard._check
law b3_peer_outside_whitelist_is_refused:
  for +g: G.Guard
  for +extra: List<&2, Nat>
  for +name: Nat
  for +reads: Bool
  for +denied: Bool
  for +kind: G.Peerless
  for +fields_before: List<&2, List<&2, G.Peer>>
  for +peers_before: List<&2, G.Peer>
  for +p: G.Peer
  for +peers_after: List<&2, G.Peer>
  for +fields_after: List<&2, List<&2, G.Peer>>
  for e: {G.peer_ok(g, p) == False{} : Bool}
  {G.check_one(g, extra, G.Req{name, reads, denied,
    List.append(&2, List<&2, G.Peer>, fields_before,
      List.append(&2, G.Peer, peers_before, p <> peers_after) <> fields_after),
    kind}) == False{} : Bool}

# B3. A peer passes only if its id is in the whitelist (the account itself only
# when its own id is in the whitelist; an unverifiable peer never).
# tg.py: PeerGuard._peer_id, PeerGuard._check
law b3_peer_ok_means_whitelisted:
  for +allowed: List<&2, Nat>
  for +self_id: Maybe<&2, Nat>
  for +i: Nat
  {G.peer_ok(G.Guard{allowed, self_id}, G.PId{i}) == F.has(i, allowed) : Bool}

law b3_unverifiable_peer_is_refused:
  for +g: G.Guard
  {G.peer_ok(g, G.PBad{}) == False{} : Bool}

law b3_self_needs_known_account:
  for +allowed: List<&2, Nat>
  {G.peer_ok(G.Guard{allowed, None{}}, G.PPeerSelf{}) == False{} : Bool}

# B4. A request without a peer field passes only if it is in
# _PEERLESS_ALLOWED or named exactly by the extra names.
# tg.py: PeerGuard.check_request
law b4_peerless_passes_only_if_listed:
  for +g: G.Guard
  for +extra: List<&2, Nat>
  for +name: Nat
  for +reads: Bool
  for +denied: Bool
  for +kind: G.Peerless
  for e: {G.check_one(g, extra, G.Req{name, reads, denied, [], kind}) == True{} : Bool}
  {(G.listed(kind) || F.has(name, extra)) == True{} : Bool}

# B4. For _ID_PEERS every item of `id` is checked: one item outside the
# whitelist refuses the request.
# tg.py: PeerGuard.check_request, PeerGuard._check
law b4_id_outside_whitelist_is_refused:
  for +g: G.Guard
  for +extra: List<&2, Nat>
  for +name: Nat
  for +reads: Bool
  for +denied: Bool
  for +ids_before: List<&2, G.Peer>
  for +p: G.Peer
  for +ids_after: List<&2, G.Peer>
  for e: {G.id_ok(g, p) == False{} : Bool}
  {G.check_one(g, extra, G.Req{name, reads, denied, [],
    G.KIdPeers{List.append(&2, G.Peer, ids_before, p <> ids_after)}}) == False{} : Bool}

# B4. An item of `id` is checked exactly like a peer, except InputUserSelf.
# tg.py: PeerGuard._check
law b4_id_is_checked_as_peer:
  for +g: G.Guard
  for +p: G.Peer
  for e: {G.is_user_self(p) == False{} : Bool}
  {G.id_ok(g, p) == G.peer_ok(g, p) : Bool}

# B5. ensure_read_only passes a batch only if it passes every part of it.
# tg.py: ensure_read_only, _requests
law b5_read_only_checks_every_request:
  for +extra: List<&2, Nat>
  for +xs: List<&2, G.Req>
  for +ys: List<&2, G.Req>
  {G.read_only(extra, List.append(&2, G.Req, xs, ys))
    == (G.read_only(extra, xs) && G.read_only(extra, ys)) : Bool}

# B5. PeerGuard.check_request passes a batch only if it passes every part.
# tg.py: PeerGuard.check_request, _requests
law b5_check_checks_every_request:
  for +g: G.Guard
  for +extra: List<&2, Nat>
  for +xs: List<&2, G.Req>
  for +ys: List<&2, G.Req>
  {G.check(g, extra, List.append(&2, G.Req, xs, ys))
    == (G.check(g, extra, xs) && G.check(g, extra, ys)) : Bool}

# B5. A batch holding one request that would be refused alone is refused
# whole, wherever that request sits.
# tg.py: ReadOnlyTelegramClient._call
law b5_one_refused_refuses_the_batch:
  for +extra: List<&2, Nat>
  for +g: G.Guard
  for +before: List<&2, G.Req>
  for +r: G.Req
  for +after: List<&2, G.Req>
  for e: {G.passes(extra, g, [r]) == False{} : Bool}
  {G.passes(extra, g, List.append(&2, G.Req, before, r <> after)) == False{} : Bool}

# B6. filter_response leaves only messages of whitelisted chats.
# tg.py: PeerGuard.filter_response, PeerGuard._keep
law b6_filter_leaves_only_whitelisted:
  for +g: G.Guard
  for +ms: List<&2, G.MsgPeer>
  {G.all_kept(g, G.filter_msgs(g, ms)) == True{} : Bool}

# B6. A message is kept only when its peer_id is a whitelisted chat id.
# tg.py: PeerGuard._keep
law b6_kept_means_whitelisted:
  for +allowed: List<&2, Nat>
  for +self_id: Maybe<&2, Nat>
  for +i: Nat
  {G.keeps(G.Guard{allowed, self_id}, G.MId{i}) == F.has(i, allowed) : Bool}

law b6_message_without_peer_is_dropped:
  for +g: G.Guard
  {G.keeps(g, G.MNone{}) == False{} : Bool}

law b6_message_with_odd_peer_is_dropped:
  for +g: G.Guard
  {G.keeps(g, G.MBad{}) == False{} : Bool}

# C. Cleaning text: sanitize.py
# =============================

# C1. Without the mark, the result of clip is not longer than `limit`.
# sanitize.py: clip
law c1_clip_fits_the_limit:
  for +xs: List<&2, S.Sym>
  for +limit: Nat
  {S.longer(S.clip_body(xs, limit), limit) == False{} : Bool}

# C1. With nothing hidden in the text, clip adds no mark: the result is just
# the clipped text.
# sanitize.py: clip
law c1_no_mark_without_hidden:
  for +xs: List<&2, S.Sym>
  for +limit: Nat
  for e: {S.has_hidden(xs) == False{} : Bool}
  {S.clip(xs, limit) == S.clip_body(xs, limit) : List<&2, S.Sym>}

# C2. If the text held a hidden character, the result of clip ends with a
# space and the whole mark, after the clipped text: the mark is never cut.
# sanitize.py: clip
law c2_clip_ends_with_the_mark:
  for +xs: List<&2, S.Sym>
  for +limit: Nat
  for e: {S.has_hidden(xs) == True{} : Bool}
  {S.clip(xs, limit) == S.push(S.push(S.clip_body(xs, limit), S.Space{}), S.Mark{}) : List<&2, S.Sym>}

# C2. The same for clean.
# sanitize.py: clean
law c2_clean_ends_with_the_mark:
  for +xs: List<&2, S.Sym>
  for e: {S.has_hidden(xs) == True{} : Bool}
  {S.clean(xs) == S.push(S.push(S.strip(xs), S.Space{}), S.Mark{}) : List<&2, S.Sym>}

# C2. "Something was removed" (`stripped != text` in Python) is exactly "the
# text held a hidden character": with none, _strip changes nothing...
# sanitize.py: _strip, clean, clip
law c2_nothing_removed_without_hidden:
  for +xs: List<&2, S.Sym>
  for e: {S.has_hidden(xs) == False{} : Bool}
  {S.strip(xs) == xs : List<&2, S.Sym>}

# C2. ...and if _strip changed nothing, the text held none.
# sanitize.py: _strip, clean, clip
law c2_removal_means_hidden:
  for +xs: List<&2, S.Sym>
  for e: {S.strip(xs) == xs : List<&2, S.Sym>}
  {S.has_hidden(xs) == False{} : Bool}

# C3. The result of clip holds no hidden character.
# sanitize.py: clip
law c3_clip_has_no_hidden:
  for +xs: List<&2, S.Sym>
  for +limit: Nat
  {S.has_hidden(S.clip(xs, limit)) == False{} : Bool}

# C3. The result of clean holds no hidden character.
# sanitize.py: clean
law c3_clean_has_no_hidden:
  for +xs: List<&2, S.Sym>
  {S.has_hidden(S.clean(xs)) == False{} : Bool}
