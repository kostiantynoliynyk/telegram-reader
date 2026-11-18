# Model of src/telegram_reader/access.py: which chat a reference resolves to,
# and how the whitelist behaves across refreshes.
#
# Abstractions (see proofs/README.md):
# - a chat id is a Nat (the tests map real ids to small numbers one to one);
# - a title is a Nat naming its class under access._norm (same number = same
#   normalized title);
# - Telegram, the config store and the clock are inputs: each call says what
#   they answered.
import Base

# models.ChatInfo, cut down to what access._match reads.
type Chat is Data:
  Chat{id: Nat, title: Nat}

# The chat reference a tool call passes to Access.resolve.
# RInt: a Python int. RStr: a Python str; as_id is access._as_id(ref) and
# title is the class of access._norm(ref).
type Ref is Data:
  RInt{id: Nat}
  RStr{as_id: Maybe<&2, Nat>, title: Nat}

# One of the two list comprehensions in access._match.
type Sel is Data:
  ById{id: Nat}
  ByTitle{title: Nat}

# What Access.resolve does: raise AccessDenied, raise AmbiguousChat, or return.
type Res is Data:
  Denied{}
  Ambiguous{}
  Found{chat: Chat}

def Chat.eq(a: Chat, b: Chat) -> Bool:
  match a b:
    case Chat{i, t} Chat{j, u}:
      Nat.is_eq(i, j) && Nat.is_eq(t, u)

# c is one of chats.
def mem(+c: Chat, chats: List<&2, Chat>) -> Bool:
  match chats:
    case Nil{}:
      False{}
    case h <> t:
      Chat.eq(h, c) || mem(c, t)

# `c.id == chat_id` / `_norm(c.title) == wanted`.
def fits(sel: Sel, c: Chat) -> Bool:
  match sel c:
    case ById{i} Chat{id, title}:
      Nat.is_eq(id, i)
    case ByTitle{t} Chat{id, title}:
      Nat.is_eq(title, t)

def keep(c: Chat, rest: List<&2, Chat>, hit: Bool) -> List<&2, Chat>:
  match hit:
    case False{}:
      rest
    case True{}:
      c <> rest

# [c for c in chats if fits(sel, c)]
def select(+sel: Sel, chats: List<&2, Chat>) -> List<&2, Chat>:
  match chats:
    case Nil{}:
      Nil{}
    case +h <> t:
      keep(h, select(sel, t), fits(sel, h))

# Some chat of the list fits sel.
def known(+sel: Sel, chats: List<&2, Chat>) -> Bool:
  match chats:
    case Nil{}:
      False{}
    case h <> t:
      fits(sel, h) || known(sel, t)

# How many chats of the list fit sel.
def bump(n: Nat, hit: Bool) -> Nat:
  match hit:
    case False{}:
      n
    case True{}:
      1n+n

def count(+sel: Sel, chats: List<&2, Chat>) -> Nat:
  match chats:
    case Nil{}:
      0n
    case h <> t:
      bump(count(sel, t), fits(sel, h))

# `if by_id or isinstance(ref, int): return by_id`, for a numeric-looking str.
def or_else(first: List<&2, Chat>, second: List<&2, Chat>) -> List<&2, Chat>:
  match first:
    case Nil{}:
      second
    case h <> t:
      h <> t

# access._match
def matches(ref: Ref, +chats: List<&2, Chat>) -> List<&2, Chat>:
  match ref:
    case RInt{i}:
      select(ById{i}, chats)
    case RStr{None{}, t}:
      select(ByTitle{t}, chats)
    case RStr{Some{i}, t}:
      or_else(select(ById{i}, chats), select(ByTitle{t}, chats))

# The tail of Access.resolve: no match, one match, several.
def pick(ms: List<&2, Chat>) -> Res:
  match ms:
    case Nil{}:
      Denied{}
    case c <> Nil{}:
      Found{c}
    case c <> d <> r:
      Ambiguous{}

# Access.resolve on an up-to-date whitelist.
def resolve(ref: Ref, +chats: List<&2, Chat>) -> Res:
  pick(matches(ref, chats))

# Whitelist state across calls
# ----------------------------

# Why a refresh raised: AccountMismatch, or anything else (BaseException).
type Err is Data:
  Mismatch{}
  TgError{}

# What Telegram answered during one Access._refresh: the ids of the selected
# folders and the metadata of those chats, or an exception at any point.
type Tg is Data:
  TgOk{ids: List<&2, Nat>, chats: List<&2, Chat>}
  TgFail{}

# The world as one Access call sees it.
# cached: `not fresh_metadata and cfg is self._cfg and clock() - refreshed_at <
# FOLDER_TTL_SECONDS`, the part of the cache test that does not depend on the
# state. cfg_acct / sess_acct: Config.account_id and TgClient.account_id
# (None or an id).
type Call is Data:
  Call{cached: Bool, cfg_acct: Maybe<&2, Nat>, sess_acct: Maybe<&2, Nat>, tg: Tg}

# Access._allowed, the ids last given to TgClient.set_allowed (the PeerGuard
# whitelist), and `self._refreshed_at is not None`.
type State is Data:
  State{allowed: List<&2, Chat>, guard: List<&2, Nat>, valid: Bool}

type Outcome is Data:
  Refreshed{ids: List<&2, Nat>, chats: List<&2, Chat>}
  Failed{err: Err}

# What a call to Access.resolve does: raise the refresh error, or resolve.
type Ans is Data:
  Raised{err: Err}
  Resolved{res: Res}

# `cfg.account_id != self._tg.account_id`, negated.
def acct_eq(a: Maybe<&2, Nat>, b: Maybe<&2, Nat>) -> Bool:
  match a b:
    case None{} None{}:
      True{}
    case None{} Some{y}:
      False{}
    case Some{x} None{}:
      False{}
    case Some{x} Some{y}:
      Nat.is_eq(x, y)

def refresh_tg(tg: Tg) -> Outcome:
  match tg:
    case TgOk{ids, chats}:
      Refreshed{ids, chats}
    case TgFail{}:
      Failed{TgError{}}

def refresh_as(same_acct: Bool, tg: Tg) -> Outcome:
  match same_acct:
    case False{}:
      Failed{Mismatch{}}
    case True{}:
      refresh_tg(tg)

# Access._refresh: the account check first, then Telegram.
def outcome(call: Call) -> Outcome:
  match call:
    case Call{cached, cfg_acct, sess_acct, tg}:
      refresh_as(acct_eq(cfg_acct, sess_acct), tg)

# The early `return` of Access._ensure_fresh.
def skips(state: State, call: Call) -> Bool:
  match state call:
    case State{allowed, guard, valid} Call{cached, cfg_acct, sess_acct, tg}:
      valid && cached

# Access._lock_down
def locked() -> State:
  State{[], [], False{}}

def apply(o: Outcome) -> State:
  match o:
    case Refreshed{ids, chats}:
      State{chats, ids, True{}}
    case Failed{err}:
      locked()

def next_if(skip: Bool, state: State, o: Outcome) -> State:
  match skip:
    case True{}:
      state
    case False{}:
      apply(o)

# The state Access._ensure_fresh leaves behind.
def next(+state: State, +call: Call) -> State:
  next_if(skips(state, call), state, outcome(call))

def answer_fresh(ref: Ref, o: Outcome) -> Ans:
  match o:
    case Refreshed{ids, +chats}:
      Resolved{resolve(ref, chats)}
    case Failed{err}:
      Raised{err}

def answer_cached(ref: Ref, state: State) -> Ans:
  match state:
    case State{+allowed, guard, valid}:
      Resolved{resolve(ref, allowed)}

def answer_if(skip: Bool, ref: Ref, state: State, o: Outcome) -> Ans:
  match skip:
    case True{}:
      answer_cached(ref, state)
    case False{}:
      answer_fresh(ref, o)

# Access.resolve, end to end: _ensure_fresh, then _match on the whitelist.
def answer(+state: State, +call: Call, ref: Ref) -> Ans:
  answer_if(skips(state, call), ref, state, outcome(call))

def is_failed(o: Outcome) -> Bool:
  match o:
    case Refreshed{ids, chats}:
      False{}
    case Failed{err}:
      True{}

# Every call of the list would fail its refresh.
def all_fail(calls: List<&2, Call>) -> Bool:
  match calls:
    case Nil{}:
      True{}
    case h <> t:
      is_failed(outcome(h)) && all_fail(t)

# The state after a sequence of calls.
def run(calls: List<&2, Call>, +state: State) -> State:
  match calls:
    case Nil{}:
      state
    case +h <> t:
      run(t, next(state, h))
