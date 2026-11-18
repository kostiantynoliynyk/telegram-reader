# Proofs of the laws in LAWS.bend. `bend proofs/PROOF.bend` checks them all.
#
# How to read a proof: `match` is case analysis, a recursive call is the
# induction hypothesis, `%e : P` rewrites the goal with the equation e, and
# `{==}` closes a goal whose two sides compute to the same term. Bend cannot
# match on a computed value, so a lemma that needs the value of a test (does
# this chat fit? did the guard pass?) takes it as a parameter `hit` and its
# caller passes the test itself.
import Base
import ./LAWS.bend as Laws
import ./model/access.bend as A
import ./model/features.bend as F
import ./model/guard.bend as G
import ./model/sanitize.bend as S

# Logic
# -----

def IsFalse(b: Bool) -> Type:
  match b:
    case False{}:
      Unit
    case True{}:
      Empty

def IsTrue(b: Bool) -> Type:
  match b:
    case False{}:
      Empty
    case True{}:
      Unit

def false_ne_true(e: {False{} == True{} : Bool}) -> Empty:
  %e : IsFalse(_)
  Unit{}

def true_ne_false(e: {True{} == False{} : Bool}) -> Empty:
  %e : IsTrue(_)
  Unit{}

# Carries a fact about a over to b.
def subst(-T: Type, -P: T -> Type, -a: T, -b: T, e: {a == b : T}, x: P(a)) -> P(b):
  %e : P(_)
  x

def and_left(+a: Bool, +b: Bool, e: {(a && b) == True{} : Bool}) -> {a == True{} : Bool}:
  match a:
    case False{}:
      e
    case True{}:
      {==}

def and_right(+a: Bool, +b: Bool, e: {(a && b) == True{} : Bool}) -> {b == True{} : Bool}:
  match a:
    case False{}:
      Empty.absurd({b == True{} : Bool}, false_ne_true(e))
    case True{}:
      e

# Uses both halves of a conjunction.
def and_use(+a: Bool, +b: Bool, -R: Type, e: {(a && b) == True{} : Bool},
  k: {a == True{} : Bool} -> {b == True{} : Bool} -> R) -> R:
  match a:
    case False{}:
      Empty.absurd(R, false_ne_true(e))
    case True{}:
      k({==}, e)

def and_false_left(+a: Bool, +b: Bool, e: {a == False{} : Bool}) -> {(a && b) == False{} : Bool}:
  match a:
    case False{}:
      {==}
    case True{}:
      Empty.absurd({b == False{} : Bool}, true_ne_false(e))

def and_false_right(+a: Bool, +b: Bool, e: {b == False{} : Bool}) -> {(a && b) == False{} : Bool}:
  match a:
    case False{}:
      {==}
    case True{}:
      e

def and_assoc(+a: Bool, +b: Bool, +c: Bool) -> {(a && (b && c)) == ((a && b) && c) : Bool}:
  match a:
    case False{}:
      {==}
    case True{}:
      {==}

def or_intro_l(+a: Bool, +b: Bool, e: {a == True{} : Bool}) -> {(a || b) == True{} : Bool}:
  match a:
    case False{}:
      Empty.absurd({b == True{} : Bool}, false_ne_true(e))
    case True{}:
      {==}

def or_intro_r(+a: Bool, +b: Bool, e: {b == True{} : Bool}) -> {(a || b) == True{} : Bool}:
  match a:
    case False{}:
      e
    case True{}:
      {==}

def or_map_r(+a: Bool, +b: Bool, +c: Bool, f: {b == True{} : Bool} -> {c == True{} : Bool},
  e: {(a || b) == True{} : Bool}) -> {(a || c) == True{} : Bool}:
  match a:
    case False{}:
      f(e)
    case True{}:
      {==}

def or_false_intro(+a: Bool, +b: Bool, ea: {a == False{} : Bool}, eb: {b == False{} : Bool}) ->
  {(a || b) == False{} : Bool}:
  match a:
    case False{}:
      eb
    case True{}:
      ea

def or_false_map_r(+a: Bool, +b: Bool, +c: Bool, f: {b == False{} : Bool} -> {c == False{} : Bool},
  e: {(a || b) == False{} : Bool}) -> {(a || c) == False{} : Bool}:
  match a:
    case False{}:
      f(e)
    case True{}:
      Empty.absurd({True{} == False{} : Bool}, true_ne_false(e))

def nat_eq_refl(+n: Nat) -> {Nat.is_eq(n, n) == True{} : Bool}:
  match n:
    case 0n:
      {==}
    case 1n+p:
      nat_eq_refl(p)

def IsZero(n: Nat) -> Type:
  match n:
    case 0n:
      Unit
    case 1n+p:
      Empty

def zero_ne_succ(-n: Nat, e: {0n == 1n+n : Nat}) -> Empty:
  %e : IsZero(_)
  Unit{}

def pred(n: Nat) -> Nat:
  match n:
    case 0n:
      0n
    case 1n+p:
      p

# A. access.py
# ============

def chat_eq_refl(+c: A.Chat) -> {A.Chat.eq(c, c) == True{} : Bool}:
  match c:
    case A.Chat{i, t}:
      %Equal.sym(Bool, Nat.is_eq(i, i), True{}, nat_eq_refl(i)) : {(_ && Nat.is_eq(t, t)) == True{} : Bool}
      nat_eq_refl(t)

def NoChats(xs: List<&2, A.Chat>) -> Type:
  match xs:
    case Nil{}:
      Unit
    case h <> t:
      Empty

def nil_ne_con(-h: A.Chat, -t: List<&2, A.Chat>, e: {Nil{} == h <> t : List<&2, A.Chat>}) -> Empty:
  %e : NoChats(_)
  Unit{}

def head_or(d: A.Chat, xs: List<&2, A.Chat>) -> A.Chat:
  match xs:
    case Nil{}:
      d
    case h <> t:
      h

def NotFound(r: A.Res) -> Type:
  match r:
    case A.Denied{}:
      Unit
    case A.Ambiguous{}:
      Unit
    case A.Found{c}:
      Empty

def denied_ne_found(-c: A.Chat, e: {A.Denied{} == A.Found{c} : A.Res}) -> Empty:
  %e : NotFound(_)
  Unit{}

def ambiguous_ne_found(-c: A.Chat, e: {A.Ambiguous{} == A.Found{c} : A.Res}) -> Empty:
  %e : NotFound(_)
  Unit{}

def found_or(d: A.Chat, r: A.Res) -> A.Chat:
  match r:
    case A.Denied{}:
      d
    case A.Ambiguous{}:
      d
    case A.Found{c}:
      c

# A chat found by pick is the only element of the list.
def pick_found(+ms: List<&2, A.Chat>, +c: A.Chat, e: {A.pick(ms) == A.Found{c} : A.Res}) ->
  {ms == [c] : List<&2, A.Chat>}:
  match ms:
    case Nil{}:
      Empty.absurd({Nil{} == [c] : List<&2, A.Chat>}, denied_ne_found(c, e))
    case x <> Nil{}:
      Equal.cong(A.Res, List<&2, A.Chat>, r => [found_or(x, r)], A.Found{x}, A.Found{c}, e)
    case x <> y <> r:
      Empty.absurd({x <> y <> r == [c] : List<&2, A.Chat>}, ambiguous_ne_found(c, e))

def mem_single(+ms: List<&2, A.Chat>, +c: A.Chat, e: {ms == [c] : List<&2, A.Chat>}) ->
  {A.mem(c, ms) == True{} : Bool}:
  %Equal.sym(List<&2, A.Chat>, ms, [c], e) : {A.mem(c, _) == True{} : Bool}
  or_intro_l(A.Chat.eq(c, c), False{}, chat_eq_refl(c))

def mem_keep(+sel: A.Sel, +h: A.Chat, +t: List<&2, A.Chat>, +c: A.Chat, +hit: Bool,
  ih: {A.mem(c, A.select(sel, t)) == True{} : Bool} -> {A.mem(c, t) == True{} : Bool},
  e: {A.mem(c, A.keep(h, A.select(sel, t), hit)) == True{} : Bool}) ->
  {(A.Chat.eq(h, c) || A.mem(c, t)) == True{} : Bool}:
  match hit:
    case False{}:
      or_intro_r(A.Chat.eq(h, c), A.mem(c, t), ih(e))
    case True{}:
      or_map_r(A.Chat.eq(h, c), A.mem(c, A.select(sel, t)), A.mem(c, t), ih, e)

# Whatever select returns comes from the list it was given.
def mem_select(+sel: A.Sel, +chats: List<&2, A.Chat>, +c: A.Chat,
  e: {A.mem(c, A.select(sel, chats)) == True{} : Bool}) -> {A.mem(c, chats) == True{} : Bool}:
  match chats:
    case Nil{}:
      e
    case h <> t:
      mem_keep(sel, h, t, c, A.fits(sel, h), e2 => mem_select(sel, t, c, e2), e)

def mem_or_else(+c: A.Chat, +xs: List<&2, A.Chat>, +ys: List<&2, A.Chat>, +all: List<&2, A.Chat>,
  f: {A.mem(c, xs) == True{} : Bool} -> {A.mem(c, all) == True{} : Bool},
  g: {A.mem(c, ys) == True{} : Bool} -> {A.mem(c, all) == True{} : Bool},
  e: {A.mem(c, A.or_else(xs, ys)) == True{} : Bool}) -> {A.mem(c, all) == True{} : Bool}:
  match xs:
    case Nil{}:
      g(e)
    case h <> t:
      f(e)

# Whatever _match returns comes from the whitelist.
def mem_matches(+ref: A.Ref, +chats: List<&2, A.Chat>, +c: A.Chat,
  e: {A.mem(c, A.matches(ref, chats)) == True{} : Bool}) -> {A.mem(c, chats) == True{} : Bool}:
  match ref:
    case A.RInt{i}:
      mem_select(A.ById{i}, chats, c, e)
    case A.RStr{None{}, t}:
      mem_select(A.ByTitle{t}, chats, c, e)
    case A.RStr{Some{i}, t}:
      mem_or_else(c, A.select(A.ById{i}, chats), A.select(A.ByTitle{t}, chats), chats,
        e2 => mem_select(A.ById{i}, chats, c, e2), e2 => mem_select(A.ByTitle{t}, chats, c, e2), e)

def Laws.a2_found_is_the_only_match(ref, chats, c, e):
  pick_found(A.matches(ref, chats), c, e)

def Laws.a1_found_is_allowed(ref, chats, c, e):
  mem_matches(ref, chats, c, mem_single(A.matches(ref, chats), c, pick_found(A.matches(ref, chats), c, e)))

def unknown_keep(+sel: A.Sel, +h: A.Chat, +t: List<&2, A.Chat>, +hit: Bool,
  ih: {A.known(sel, t) == False{} : Bool} -> {A.select(sel, t) == [] : List<&2, A.Chat>},
  e: {(hit || A.known(sel, t)) == False{} : Bool}) ->
  {A.keep(h, A.select(sel, t), hit) == [] : List<&2, A.Chat>}:
  match hit:
    case False{}:
      ih(e)
    case True{}:
      Empty.absurd({h <> A.select(sel, t) == [] : List<&2, A.Chat>}, true_ne_false(e))

# No chat fits: select finds nothing.
def unknown_select(+sel: A.Sel, +chats: List<&2, A.Chat>, e: {A.known(sel, chats) == False{} : Bool}) ->
  {A.select(sel, chats) == [] : List<&2, A.Chat>}:
  match chats:
    case Nil{}:
      {==}
    case h <> t:
      unknown_keep(sel, h, t, A.fits(sel, h), e2 => unknown_select(sel, t, e2), e)

def Laws.a1_unknown_id_is_denied(i, chats, e):
  %Equal.sym(List<&2, A.Chat>, A.select(A.ById{i}, chats), [], unknown_select(A.ById{i}, chats, e)) : {A.pick(_) == A.Denied{} : A.Res}
  {==}

def Laws.a1_unknown_title_is_denied(t, chats, e):
  %Equal.sym(List<&2, A.Chat>, A.select(A.ByTitle{t}, chats), [], unknown_select(A.ByTitle{t}, chats, e)) : {A.pick(_) == A.Denied{} : A.Res}
  {==}

def Laws.a1_unknown_numeric_string_is_denied(i, t, chats, ei, et):
  %Equal.sym(List<&2, A.Chat>, A.select(A.ById{i}, chats), [], unknown_select(A.ById{i}, chats, ei)) : {A.pick(A.or_else(_, A.select(A.ByTitle{t}, chats))) == A.Denied{} : A.Res}
  %Equal.sym(List<&2, A.Chat>, A.select(A.ByTitle{t}, chats), [], unknown_select(A.ByTitle{t}, chats, et)) : {A.pick(_) == A.Denied{} : A.Res}
  {==}

def Laws.a2_two_matches_are_ambiguous(ref, chats, a, b, rest, e):
  %Equal.sym(List<&2, A.Chat>, A.matches(ref, chats), a <> b <> rest, e) : {A.pick(_) == A.Ambiguous{} : A.Res}
  {==}

def count_keep(+sel: A.Sel, +h: A.Chat, +t: List<&2, A.Chat>, +hit: Bool,
  ih: {List.length(&2, A.Chat, A.select(sel, t)) == A.count(sel, t) : Nat}) ->
  {List.length(&2, A.Chat, A.keep(h, A.select(sel, t), hit)) == A.bump(A.count(sel, t), hit) : Nat}:
  match hit:
    case False{}:
      ih
    case True{}:
      %ih : {1n+List.length(&2, A.Chat, A.select(sel, t)) == 1n+_ : Nat}
      {==}

# select returns as many chats as fit.
def count_select(+sel: A.Sel, +chats: List<&2, A.Chat>) ->
  {List.length(&2, A.Chat, A.select(sel, chats)) == A.count(sel, chats) : Nat}:
  match chats:
    case Nil{}:
      {==}
    case h <> t:
      count_keep(sel, h, t, A.fits(sel, h), count_select(sel, t))

def pick_two(+ms: List<&2, A.Chat>, +k: Nat, e: {List.length(&2, A.Chat, ms) == 2n+k : Nat}) ->
  {A.pick(ms) == A.Ambiguous{} : A.Res}:
  match ms:
    case Nil{}:
      Empty.absurd({A.Denied{} == A.Ambiguous{} : A.Res}, zero_ne_succ(1n+k, e))
    case x <> Nil{}:
      Empty.absurd({A.Found{x} == A.Ambiguous{} : A.Res},
        zero_ne_succ(k, Equal.cong(Nat, Nat, n => pred(n), 1n, 2n+k, e)))
    case x <> y <> r:
      {==}

def Laws.a2_shared_title_is_ambiguous(t, chats, k, e):
  pick_two(A.select(A.ByTitle{t}, chats), k,
    Equal.trans(Nat, List.length(&2, A.Chat, A.select(A.ByTitle{t}, chats)),
      A.count(A.ByTitle{t}, chats), 2n+k, count_select(A.ByTitle{t}, chats), e))

def Laws.a3_int_is_matched_by_id_only(i, chats):
  {==}

def head_keep(+sel: A.Sel, +h: A.Chat, +t: List<&2, A.Chat>, +c: A.Chat, +rest: List<&2, A.Chat>,
  +hit: Bool, eq: {A.fits(sel, h) == hit : Bool},
  ih: {A.select(sel, t) == c <> rest : List<&2, A.Chat>} -> {A.fits(sel, c) == True{} : Bool},
  e: {A.keep(h, A.select(sel, t), hit) == c <> rest : List<&2, A.Chat>}) ->
  {A.fits(sel, c) == True{} : Bool}:
  match hit:
    case False{}:
      ih(e)
    case True{}:
      %Equal.cong(List<&2, A.Chat>, A.Chat, xs => head_or(h, xs), h <> A.select(sel, t), c <> rest, e) : {A.fits(sel, _) == True{} : Bool}
      eq

# The first chat select returns fits.
def head_fits(+sel: A.Sel, +chats: List<&2, A.Chat>, +c: A.Chat, +rest: List<&2, A.Chat>,
  e: {A.select(sel, chats) == c <> rest : List<&2, A.Chat>}) -> {A.fits(sel, c) == True{} : Bool}:
  match chats:
    case Nil{}:
      Empty.absurd({A.fits(sel, c) == True{} : Bool}, nil_ne_con(c, rest, e))
    case h <> t:
      head_keep(sel, h, t, c, rest, A.fits(sel, h), {==}, e2 => head_fits(sel, t, c, rest, e2), e)

def Laws.a3_int_finds_that_id(i, chats, c, e):
  head_fits(A.ById{i}, chats, c, [], pick_found(A.select(A.ById{i}, chats), c, e))

def Laws.a4_numeric_string_falls_back_to_title(i, t, chats, e):
  %Equal.sym(List<&2, A.Chat>, A.select(A.ById{i}, chats), [], unknown_select(A.ById{i}, chats, e)) : {A.or_else(_, A.select(A.ByTitle{t}, chats)) == A.select(A.ByTitle{t}, chats) : List<&2, A.Chat>}
  {==}

def Laws.a5_failed_refresh_locks(state, call, err, ran, fail):
  %Equal.sym(Bool, A.skips(state, call), False{}, ran) : {A.next_if(_, state, A.outcome(call)) == A.State{[], [], False{}} : A.State}
  %Equal.sym(A.Outcome, A.outcome(call), A.Failed{err}, fail) : {A.apply(_) == A.State{[], [], False{}} : A.State}
  {==}

def Laws.a5_failed_refresh_raises(state, call, ref, err, ran, fail):
  %Equal.sym(Bool, A.skips(state, call), False{}, ran) : {A.answer_if(_, ref, state, A.outcome(call)) == A.Raised{err} : A.Ans}
  %Equal.sym(A.Outcome, A.outcome(call), A.Failed{err}, fail) : {A.answer_fresh(ref, _) == A.Raised{err} : A.Ans}
  {==}

def failed_locks(+o: A.Outcome, e: {A.is_failed(o) == True{} : Bool}) -> {A.apply(o) == A.locked() : A.State}:
  match o:
    case A.Refreshed{ids, chats}:
      Empty.absurd({A.State{chats, ids, True{}} == A.locked() : A.State}, false_ne_true(e))
    case A.Failed{err}:
      {==}

def locked_step(+h: A.Call, +t: List<&2, A.Call>, now: {A.is_failed(A.outcome(h)) == True{} : Bool},
  ih: {A.run(t, A.locked()) == A.locked() : A.State}) ->
  {A.run(t, A.apply(A.outcome(h))) == A.locked() : A.State}:
  %Equal.sym(A.State, A.apply(A.outcome(h)), A.locked(), failed_locks(A.outcome(h), now)) : {A.run(t, _) == A.locked() : A.State}
  ih

def Laws.a5_locked_stays_locked(calls, fails):
  match calls:
    case Nil{}:
      {==}
    case A.Call{cached, cfg_acct, sess_acct, tg} <> t:
      and_use(A.is_failed(A.outcome(A.Call{cached, cfg_acct, sess_acct, tg})), A.all_fail(t),
        {A.run(t, A.apply(A.outcome(A.Call{cached, cfg_acct, sess_acct, tg}))) == A.locked() : A.State}, fails,
        now => later => locked_step(A.Call{cached, cfg_acct, sess_acct, tg}, t, now, Laws.a5_locked_stays_locked(t, later)))

# A locked whitelist never serves its cache: the call refreshes, and raises if
# the refresh fails.
def locked_raises(+call: A.Call, +ref: A.Ref, +err: A.Err, fail: {A.outcome(call) == A.Failed{err} : A.Outcome}) ->
  {A.answer(A.locked(), call, ref) == A.Raised{err} : A.Ans}:
  match call:
    case A.Call{cached, cfg_acct, sess_acct, tg}:
      %Equal.sym(A.Outcome, A.outcome(A.Call{cached, cfg_acct, sess_acct, tg}), A.Failed{err}, fail) : {A.answer_fresh(ref, _) == A.Raised{err} : A.Ans}
      {==}

def Laws.a5_fail_closed(state, first, err0, calls, call, ref, err, ran, fail0, fails, fail):
  %Equal.sym(A.State, A.next(state, first), A.locked(), Laws.a5_failed_refresh_locks(state, first, err0, ran, fail0)) : {A.answer(A.run(calls, _), call, ref) == A.Raised{err} : A.Ans}
  %Equal.sym(A.State, A.run(calls, A.locked()), A.locked(), Laws.a5_locked_stays_locked(calls, fails)) : {A.answer(_, call, ref) == A.Raised{err} : A.Ans}
  locked_raises(call, ref, err, fail)

def Laws.a6_mismatch_fails_refresh(cached, cfg_acct, sess_acct, tg, diff):
  %Equal.sym(Bool, A.acct_eq(cfg_acct, sess_acct), False{}, diff) : {A.refresh_as(_, tg) == A.Failed{A.Mismatch{}} : A.Outcome}
  {==}

def Laws.a6_mismatch_locks(state, cached, cfg_acct, sess_acct, tg, ran, diff):
  Laws.a5_failed_refresh_locks(state, A.Call{cached, cfg_acct, sess_acct, tg}, A.Mismatch{}, ran,
    Laws.a6_mismatch_fails_refresh(cached, cfg_acct, sess_acct, tg, diff))

def Laws.a6_mismatch_raises(state, cached, cfg_acct, sess_acct, tg, ref, ran, diff):
  Laws.a5_failed_refresh_raises(state, A.Call{cached, cfg_acct, sess_acct, tg}, ref, A.Mismatch{}, ran,
    Laws.a6_mismatch_fails_refresh(cached, cfg_acct, sess_acct, tg, diff))

# B. tg.py and features.py
# ========================

def Laws.b1_no_feature_no_extra(reg):
  match reg:
    case Nil{}:
      {==}
    case F.Feature{key, available, requests} <> t:
      Laws.b1_no_feature_no_extra(t)

# With no extra name, a request that passes ensure_read_only is a read.
def plain_read(+name: Nat, +reads: Bool, +denied: Bool, +fields: List<&2, List<&2, G.Peer>>,
  +kind: G.Peerless,
  e: {G.read_only([], [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool}) ->
  {(reads && Bool.not(denied)) == True{} : Bool}:
  and_left(reads && Bool.not(denied), True{}, e)

def Laws.b1_non_read_is_refused(reg, name, reads, denied, fields, kind, e):
  plain_read(name, reads, denied, fields, kind,
    subst(List<&2, Nat>, xs => {G.read_only(xs, [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool},
      F.allowed_requests(reg, []), [], Laws.b1_no_feature_no_extra(reg), e))

def client_read(+dl: List<&2, Nat>, +g: G.Guard, +name: Nat, +reads: Bool, +denied: Bool,
  +fields: List<&2, List<&2, G.Peer>>, +kind: G.Peerless,
  e: {G.passes(dl, g, [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool}) ->
  {(F.has(name, dl) || (reads && Bool.not(denied))) == True{} : Bool}:
  and_left(F.has(name, dl) || (reads && Bool.not(denied)), True{},
    and_left(G.read_only(dl, [G.Req{name, reads, denied, fields, kind}]),
      G.check(g, dl, [G.Req{name, reads, denied, fields, kind}]), e))

def Laws.b1_client_non_read_is_refused(reg, dl, g, name, reads, denied, fields, kind, e):
  client_read(dl, g, name, reads, denied, fields, kind,
    subst(List<&2, Nat>,
      xs => {G.passes(F.join(xs, dl), g, [G.Req{name, reads, denied, fields, kind}]) == True{} : Bool},
      F.allowed_requests(reg, []), [], Laws.b1_no_feature_no_extra(reg), e))

def unavailable_step(+key: Nat, +requests: List<&2, Nat>, +t: List<&2, F.Feature>,
  +enabled: List<&2, Nat>, ih: {F.allowed_requests(t, enabled) == [] : List<&2, Nat>}) ->
  {F.grant(requests, F.allowed_requests(t, enabled), F.has(key, enabled) && False{}) == [] : List<&2, Nat>}:
  %Equal.sym(Bool, F.has(key, enabled) && False{}, False{}, and_false_right(F.has(key, enabled), False{}, {==})) : {F.grant(requests, F.allowed_requests(t, enabled), _) == [] : List<&2, Nat>}
  ih

def Laws.b2_unavailable_adds_nothing(reg, enabled, e):
  match reg:
    case Nil{}:
      {==}
    case F.Feature{key, False{}, requests} <> t:
      unavailable_step(key, requests, t, enabled, Laws.b2_unavailable_adds_nothing(t, enabled, e))
    case F.Feature{key, True{}, requests} <> t:
      Empty.absurd({F.grant(requests, F.allowed_requests(t, enabled), F.has(key, enabled) && True{}) == [] : List<&2, Nat>}, false_ne_true(e))

def Laws.b2_shipped_registry_adds_nothing(enabled):
  Laws.b2_unavailable_adds_nothing(F.registry(), enabled, {==})

# One peer outside the whitelist fails its whole field.
def field_bad(+g: G.Guard, +before: List<&2, G.Peer>, +p: G.Peer, +after: List<&2, G.Peer>,
  e: {G.peer_ok(g, p) == False{} : Bool}) ->
  {G.field_ok(g, List.append(&2, G.Peer, before, p <> after)) == False{} : Bool}:
  match before:
    case Nil{}:
      and_false_left(G.peer_ok(g, p), G.field_ok(g, after), e)
    case h <> t:
      and_false_right(G.peer_ok(g, h), G.field_ok(g, List.append(&2, G.Peer, t, p <> after)),
        field_bad(g, t, p, after, e))

# One failed field fails the list of fields.
def fields_bad(+g: G.Guard, +before: List<&2, List<&2, G.Peer>>, +f: List<&2, G.Peer>,
  +after: List<&2, List<&2, G.Peer>>, e: {G.field_ok(g, f) == False{} : Bool}) ->
  {G.fields_ok(g, List.append(&2, List<&2, G.Peer>, before, f <> after)) == False{} : Bool}:
  match before:
    case Nil{}:
      and_false_left(G.field_ok(g, f), G.fields_ok(g, after), e)
    case h <> t:
      and_false_right(G.field_ok(g, h), G.fields_ok(g, List.append(&2, List<&2, G.Peer>, t, f <> after)),
        fields_bad(g, t, f, after, e))

def Laws.b3_peer_outside_whitelist_is_refused(g, extra, name, reads, denied, kind, fields_before,
  peers_before, p, peers_after, fields_after, e):
  match fields_before:
    case Nil{}:
      and_false_left(G.field_ok(g, List.append(&2, G.Peer, peers_before, p <> peers_after)),
        G.fields_ok(g, fields_after), field_bad(g, peers_before, p, peers_after, e))
    case h <> t:
      and_false_right(G.field_ok(g, h),
        G.fields_ok(g, List.append(&2, List<&2, G.Peer>, t,
          List.append(&2, G.Peer, peers_before, p <> peers_after) <> fields_after)),
        fields_bad(g, t, List.append(&2, G.Peer, peers_before, p <> peers_after), fields_after,
          field_bad(g, peers_before, p, peers_after, e)))

def Laws.b3_peer_ok_means_whitelisted(allowed, self_id, i):
  {==}

def Laws.b3_unverifiable_peer_is_refused(g):
  match g:
    case G.Guard{allowed, self_id}:
      {==}

def Laws.b3_self_needs_known_account(allowed):
  {==}

def Laws.b4_peerless_passes_only_if_listed(g, extra, name, reads, denied, kind, e):
  match kind:
    case G.KIdPeers{ids}:
      {==}
    case G.KAllowed{}:
      {==}
    case G.KOther{}:
      e

def ids_bad(+g: G.Guard, +before: List<&2, G.Peer>, +p: G.Peer, +after: List<&2, G.Peer>,
  e: {G.id_ok(g, p) == False{} : Bool}) ->
  {G.ids_ok(g, List.append(&2, G.Peer, before, p <> after)) == False{} : Bool}:
  match before:
    case Nil{}:
      and_false_left(G.id_ok(g, p), G.ids_ok(g, after), e)
    case h <> t:
      and_false_right(G.id_ok(g, h), G.ids_ok(g, List.append(&2, G.Peer, t, p <> after)),
        ids_bad(g, t, p, after, e))

def Laws.b4_id_outside_whitelist_is_refused(g, extra, name, reads, denied, ids_before, p, ids_after, e):
  ids_bad(g, ids_before, p, ids_after, e)

def Laws.b4_id_is_checked_as_peer(g, p, e):
  match g p:
    case G.Guard{allowed, self_id} G.PId{i}:
      {==}
    case G.Guard{allowed, self_id} G.PUserSelf{}:
      Empty.absurd({True{} == G.self_ok(allowed, self_id) : Bool}, true_ne_false(e))
    case G.Guard{allowed, self_id} G.PPeerSelf{}:
      {==}
    case G.Guard{allowed, self_id} G.PBad{}:
      {==}

def Laws.b5_read_only_checks_every_request(extra, xs, ys):
  match xs:
    case Nil{}:
      {==}
    case h <> t:
      %Equal.sym(Bool, G.read_only(extra, List.append(&2, G.Req, t, ys)), G.read_only(extra, t) && G.read_only(extra, ys), Laws.b5_read_only_checks_every_request(extra, t, ys)) : {(G.read_ok(extra, h) && _) == ((G.read_ok(extra, h) && G.read_only(extra, t)) && G.read_only(extra, ys)) : Bool}
      and_assoc(G.read_ok(extra, h), G.read_only(extra, t), G.read_only(extra, ys))

def Laws.b5_check_checks_every_request(g, extra, xs, ys):
  match xs:
    case Nil{}:
      {==}
    case h <> t:
      %Equal.sym(Bool, G.check(g, extra, List.append(&2, G.Req, t, ys)), G.check(g, extra, t) && G.check(g, extra, ys), Laws.b5_check_checks_every_request(g, extra, t, ys)) : {(G.check_one(g, extra, h) && _) == ((G.check_one(g, extra, h) && G.check(g, extra, t)) && G.check(g, extra, ys)) : Bool}
      and_assoc(G.check_one(g, extra, h), G.check(g, extra, t), G.check(g, extra, ys))

def read_only_bad(+extra: List<&2, Nat>, +before: List<&2, G.Req>, +r: G.Req, +after: List<&2, G.Req>,
  e: {G.read_ok(extra, r) == False{} : Bool}) ->
  {G.read_only(extra, List.append(&2, G.Req, before, r <> after)) == False{} : Bool}:
  match before:
    case Nil{}:
      and_false_left(G.read_ok(extra, r), G.read_only(extra, after), e)
    case h <> t:
      and_false_right(G.read_ok(extra, h), G.read_only(extra, List.append(&2, G.Req, t, r <> after)),
        read_only_bad(extra, t, r, after, e))

def check_bad(+g: G.Guard, +extra: List<&2, Nat>, +before: List<&2, G.Req>, +r: G.Req,
  +after: List<&2, G.Req>, e: {G.check_one(g, extra, r) == False{} : Bool}) ->
  {G.check(g, extra, List.append(&2, G.Req, before, r <> after)) == False{} : Bool}:
  match before:
    case Nil{}:
      and_false_left(G.check_one(g, extra, r), G.check(g, extra, after), e)
    case h <> t:
      and_false_right(G.check_one(g, extra, h), G.check(g, extra, List.append(&2, G.Req, t, r <> after)),
        check_bad(g, extra, t, r, after, e))

# ro and co are what the two guards say about r alone.
def refuse_batch(+extra: List<&2, Nat>, +g: G.Guard, +before: List<&2, G.Req>, +r: G.Req,
  +after: List<&2, G.Req>, +ro: Bool, +co: Bool,
  hro: {G.read_ok(extra, r) == ro : Bool}, hco: {G.check_one(g, extra, r) == co : Bool},
  e: {((ro && True{}) && (co && True{})) == False{} : Bool}) ->
  {G.passes(extra, g, List.append(&2, G.Req, before, r <> after)) == False{} : Bool}:
  match ro co:
    case False{} False{}:
      and_false_left(G.read_only(extra, List.append(&2, G.Req, before, r <> after)),
        G.check(g, extra, List.append(&2, G.Req, before, r <> after)),
        read_only_bad(extra, before, r, after, hro))
    case False{} True{}:
      and_false_left(G.read_only(extra, List.append(&2, G.Req, before, r <> after)),
        G.check(g, extra, List.append(&2, G.Req, before, r <> after)),
        read_only_bad(extra, before, r, after, hro))
    case True{} False{}:
      and_false_right(G.read_only(extra, List.append(&2, G.Req, before, r <> after)),
        G.check(g, extra, List.append(&2, G.Req, before, r <> after)),
        check_bad(g, extra, before, r, after, hco))
    case True{} True{}:
      Empty.absurd({G.passes(extra, g, List.append(&2, G.Req, before, r <> after)) == False{} : Bool},
        true_ne_false(e))

def Laws.b5_one_refused_refuses_the_batch(extra, g, before, r, after, e):
  refuse_batch(extra, g, before, r, after, G.read_ok(extra, r), G.check_one(g, extra, r), {==}, {==}, e)

def kept_step(+g: G.Guard, +h: G.MsgPeer, +t: List<&2, G.MsgPeer>, +hit: Bool,
  eq: {G.keeps(g, h) == hit : Bool}, ih: {G.all_kept(g, G.filter_msgs(g, t)) == True{} : Bool}) ->
  {G.all_kept(g, G.keep_msg(h, G.filter_msgs(g, t), hit)) == True{} : Bool}:
  match hit:
    case False{}:
      ih
    case True{}:
      %Equal.sym(Bool, G.keeps(g, h), True{}, eq) : {(_ && G.all_kept(g, G.filter_msgs(g, t))) == True{} : Bool}
      ih

def Laws.b6_filter_leaves_only_whitelisted(g, ms):
  match ms:
    case Nil{}:
      {==}
    case h <> t:
      kept_step(g, h, t, G.keeps(g, h), {==}, Laws.b6_filter_leaves_only_whitelisted(g, t))

def Laws.b6_kept_means_whitelisted(allowed, self_id, i):
  {==}

def Laws.b6_message_without_peer_is_dropped(g):
  match g:
    case G.Guard{allowed, self_id}:
      {==}

def Laws.b6_message_with_odd_peer_is_dropped(g):
  match g:
    case G.Guard{allowed, self_id}:
      {==}

# C. sanitize.py
# ==============

# The first p characters and "…" fit in p + 1.
def clipped_fits(+p: Nat, +ys: List<&2, S.Sym>) ->
  {S.longer(S.push(S.take(p, ys), S.Dots{}), 1n+p) == False{} : Bool}:
  match p ys:
    case 0n Nil{}:
      {==}
    case 0n h <> t:
      {==}
    case 1n+q Nil{}:
      {==}
    case 1n+q h <> t:
      clipped_fits(q, t)

def cut_fits(+ys: List<&2, S.Sym>, +limit: Nat, +over: Bool, eq: {S.longer(ys, limit) == over : Bool}) ->
  {S.longer(S.cut_if(over, ys, limit), limit) == False{} : Bool}:
  match limit over:
    case 0n False{}:
      eq
    case 0n True{}:
      {==}
    case 1n+p False{}:
      eq
    case 1n+p True{}:
      clipped_fits(p, ys)

def Laws.c1_clip_fits_the_limit(xs, limit):
  cut_fits(S.flat(S.strip(xs)), limit, S.longer(S.flat(S.strip(xs)), limit), {==})

def Laws.c1_no_mark_without_hidden(xs, limit, e):
  %Equal.sym(Bool, S.has_hidden(xs), False{}, e) : {S.mark_if(S.clip_body(xs, limit), _) == S.clip_body(xs, limit) : List<&2, S.Sym>}
  {==}

def Laws.c2_clip_ends_with_the_mark(xs, limit, e):
  %Equal.sym(Bool, S.has_hidden(xs), True{}, e) : {S.mark_if(S.clip_body(xs, limit), _) == S.push(S.push(S.clip_body(xs, limit), S.Space{}), S.Mark{}) : List<&2, S.Sym>}
  {==}

def Laws.c2_clean_ends_with_the_mark(xs, e):
  %Equal.sym(Bool, S.has_hidden(xs), True{}, e) : {S.mark_if(S.strip(xs), _) == S.push(S.push(S.strip(xs), S.Space{}), S.Mark{}) : List<&2, S.Sym>}
  {==}

def Laws.c2_nothing_removed_without_hidden(xs, e):
  match xs:
    case Nil{}:
      {==}
    case S.Plain{} <> t:
      %Laws.c2_nothing_removed_without_hidden(t, e) : {S.Plain{} <> S.strip(t) == S.Plain{} <> _ : List<&2, S.Sym>}
      {==}
    case S.Hidden{} <> t:
      Empty.absurd({S.strip(t) == S.Hidden{} <> t : List<&2, S.Sym>}, true_ne_false(e))
    case S.Space{} <> t:
      %Laws.c2_nothing_removed_without_hidden(t, e) : {S.Space{} <> S.strip(t) == S.Space{} <> _ : List<&2, S.Sym>}
      {==}
    case S.Dots{} <> t:
      %Laws.c2_nothing_removed_without_hidden(t, e) : {S.Dots{} <> S.strip(t) == S.Dots{} <> _ : List<&2, S.Sym>}
      {==}
    case S.Mark{} <> t:
      %Laws.c2_nothing_removed_without_hidden(t, e) : {S.Mark{} <> S.strip(t) == S.Mark{} <> _ : List<&2, S.Sym>}
      {==}

# _strip leaves no hidden character.
def strip_clean(+xs: List<&2, S.Sym>) -> {S.has_hidden(S.strip(xs)) == False{} : Bool}:
  match xs:
    case Nil{}:
      {==}
    case S.Plain{} <> t:
      strip_clean(t)
    case S.Hidden{} <> t:
      strip_clean(t)
    case S.Space{} <> t:
      strip_clean(t)
    case S.Dots{} <> t:
      strip_clean(t)
    case S.Mark{} <> t:
      strip_clean(t)

def Laws.c2_removal_means_hidden(xs, e):
  %e : {S.has_hidden(_) == False{} : Bool}
  strip_clean(xs)

def emit_clean(+c: S.Sym, +st: S.Gap, +rest: List<&2, S.Sym>, ec: {S.is_hidden(c) == False{} : Bool},
  er: {S.has_hidden(rest) == False{} : Bool}) -> {S.has_hidden(S.emit(c, st, rest)) == False{} : Bool}:
  match st:
    case S.Start{}:
      or_false_intro(S.is_hidden(c), S.has_hidden(rest), ec, er)
    case S.InWord{}:
      or_false_intro(S.is_hidden(c), S.has_hidden(rest), ec, er)
    case S.Pending{}:
      or_false_intro(S.is_hidden(c), S.has_hidden(rest), ec, er)

# Collapsing whitespace adds no hidden character.
def words_clean(+xs: List<&2, S.Sym>, +st: S.Gap, e: {S.has_hidden(xs) == False{} : Bool}) ->
  {S.has_hidden(S.words(xs, st)) == False{} : Bool}:
  match xs:
    case Nil{}:
      {==}
    case S.Plain{} <> t:
      emit_clean(S.Plain{}, st, S.words(t, S.InWord{}), {==}, words_clean(t, S.InWord{}, e))
    case S.Hidden{} <> t:
      Empty.absurd({S.has_hidden(S.emit(S.Hidden{}, st, S.words(t, S.InWord{}))) == False{} : Bool}, true_ne_false(e))
    case S.Space{} <> t:
      words_clean(t, S.after_space(st), e)
    case S.Dots{} <> t:
      emit_clean(S.Dots{}, st, S.words(t, S.InWord{}), {==}, words_clean(t, S.InWord{}, e))
    case S.Mark{} <> t:
      emit_clean(S.Mark{}, st, S.words(t, S.InWord{}), {==}, words_clean(t, S.InWord{}, e))

def take_clean(+p: Nat, +ys: List<&2, S.Sym>, e: {S.has_hidden(ys) == False{} : Bool}) ->
  {S.has_hidden(S.take(p, ys)) == False{} : Bool}:
  match p ys:
    case 0n Nil{}:
      {==}
    case 0n h <> t:
      {==}
    case 1n+q Nil{}:
      {==}
    case 1n+q h <> t:
      or_false_map_r(S.is_hidden(h), S.has_hidden(t), S.has_hidden(S.take(q, t)), e2 => take_clean(q, t, e2), e)

def push_clean(+xs: List<&2, S.Sym>, +s: S.Sym, ex: {S.has_hidden(xs) == False{} : Bool},
  es: {S.is_hidden(s) == False{} : Bool}) -> {S.has_hidden(S.push(xs, s)) == False{} : Bool}:
  match xs:
    case Nil{}:
      or_false_intro(S.is_hidden(s), False{}, es, {==})
    case h <> t:
      or_false_map_r(S.is_hidden(h), S.has_hidden(t), S.has_hidden(S.push(t, s)), e2 => push_clean(t, s, e2, es), ex)

def cut_clean(+ys: List<&2, S.Sym>, +limit: Nat, +over: Bool, e: {S.has_hidden(ys) == False{} : Bool}) ->
  {S.has_hidden(S.cut_if(over, ys, limit)) == False{} : Bool}:
  match limit over:
    case 0n False{}:
      e
    case 0n True{}:
      {==}
    case 1n+p False{}:
      e
    case 1n+p True{}:
      push_clean(S.take(p, ys), S.Dots{}, take_clean(p, ys, e), {==})

def mark_clean(+body: List<&2, S.Sym>, +marked: Bool, e: {S.has_hidden(body) == False{} : Bool}) ->
  {S.has_hidden(S.mark_if(body, marked)) == False{} : Bool}:
  match marked:
    case False{}:
      e
    case True{}:
      push_clean(S.push(body, S.Space{}), S.Mark{}, push_clean(body, S.Space{}, e, {==}), {==})

def Laws.c3_clip_has_no_hidden(xs, limit):
  mark_clean(S.clip_body(xs, limit), S.has_hidden(xs),
    cut_clean(S.flat(S.strip(xs)), limit, S.longer(S.flat(S.strip(xs)), limit),
      words_clean(S.strip(xs), S.Start{}, strip_clean(xs))))

def Laws.c3_clean_has_no_hidden(xs):
  mark_clean(S.strip(xs), S.has_hidden(xs), strip_clean(xs))
