# Model of the read-only guards in src/telegram_reader/tg.py:
# ensure_read_only, PeerGuard.check_request, PeerGuard.filter_response and
# ReadOnlyTelegramClient._call, which runs the first two on every request.
#
# A request is reduced to what the guards read (see proofs/README.md):
# - name: type(r).__name__, numbered;
# - reads: name.startswith(_READ_PREFIXES);
# - denied: name in _DENIED_READS;
# - fields: the values of the _PEER_FIELDS that are not None, each a list of
#   peers (a single peer is a list of one);
# - kind: where _qualified(r) falls: _ID_PEERS (with its `id` list),
#   _PEERLESS_ALLOWED, or neither.
import Base
import ./features.bend as F

# A peer as PeerGuard._peer_id sees it: an id it can compute, InputUserSelf,
# InputPeerSelf, or something it cannot verify (it raises).
type Peer is Data:
  PId{id: Nat}
  PUserSelf{}
  PPeerSelf{}
  PBad{}

type Peerless is Data:
  KIdPeers{ids: List<&2, Peer>}
  KAllowed{}
  KOther{}

type Req is Data:
  Req{name: Nat, reads: Bool, denied: Bool, fields: List<&2, List<&2, Peer>>, kind: Peerless}

# tg.PeerGuard
type Guard is Data:
  Guard{allowed: List<&2, Nat>, self_id: Maybe<&2, Nat>}

# ensure_read_only
# ----------------

# The body of the loop in ensure_read_only, for one request.
def read_ok(extra: List<&2, Nat>, r: Req) -> Bool:
  match r:
    case Req{+name, reads, denied, fields, kind}:
      F.has(name, extra) || (reads && Bool.not(denied))

# ensure_read_only does not raise.
def read_only(+extra: List<&2, Nat>, rs: List<&2, Req>) -> Bool:
  match rs:
    case Nil{}:
      True{}
    case h <> t:
      read_ok(extra, h) && read_only(extra, t)

# PeerGuard.check_request
# -----------------------

def self_ok(allowed: List<&2, Nat>, self_id: Maybe<&2, Nat>) -> Bool:
  match self_id:
    case None{}:
      False{}
    case Some{s}:
      F.has(s, allowed)

# PeerGuard._peer_id then `pid in self.allowed`, for a peer field.
def peer_ok(g: Guard, p: Peer) -> Bool:
  match g p:
    case Guard{allowed, self_id} PId{i}:
      F.has(i, allowed)
    case Guard{allowed, self_id} PUserSelf{}:
      self_ok(allowed, self_id)
    case Guard{allowed, self_id} PPeerSelf{}:
      self_ok(allowed, self_id)
    case Guard{allowed, self_id} PBad{}:
      False{}

# The same for an item of `id`: InputUserSelf is skipped (get_me).
def id_ok(g: Guard, p: Peer) -> Bool:
  match p:
    case PUserSelf{}:
      True{}
    case PId{i}:
      peer_ok(g, PId{i})
    case PPeerSelf{}:
      peer_ok(g, PPeerSelf{})
    case PBad{}:
      False{}

# PeerGuard._check(value, field) for a peer field.
def field_ok(+g: Guard, ps: List<&2, Peer>) -> Bool:
  match ps:
    case Nil{}:
      True{}
    case h <> t:
      peer_ok(g, h) && field_ok(g, t)

# PeerGuard._check(value, "id")
def ids_ok(+g: Guard, ps: List<&2, Peer>) -> Bool:
  match ps:
    case Nil{}:
      True{}
    case h <> t:
      id_ok(g, h) && ids_ok(g, t)

def fields_ok(+g: Guard, fs: List<&2, List<&2, Peer>>) -> Bool:
  match fs:
    case Nil{}:
      True{}
    case h <> t:
      field_ok(g, h) && fields_ok(g, t)

# The request's qualified name is in _PEERLESS_ALLOWED (_ID_PEERS is part of it).
def listed(kind: Peerless) -> Bool:
  match kind:
    case KIdPeers{ids}:
      True{}
    case KAllowed{}:
      True{}
    case KOther{}:
      False{}

# isinstance(item, types.InputUserSelf)
def is_user_self(p: Peer) -> Bool:
  match p:
    case PId{i}:
      False{}
    case PUserSelf{}:
      True{}
    case PPeerSelf{}:
      False{}
    case PBad{}:
      False{}

# The branch of check_request for a request with no peer field.
def peerless_ok(g: Guard, extra: List<&2, Nat>, name: Nat, kind: Peerless) -> Bool:
  match kind:
    case KIdPeers{ids}:
      ids_ok(g, ids)
    case KAllowed{}:
      True{}
    case KOther{}:
      F.has(name, extra)

def check_parts(+g: Guard, extra: List<&2, Nat>, name: Nat, kind: Peerless,
  fields: List<&2, List<&2, Peer>>) -> Bool:
  match fields:
    case Nil{}:
      peerless_ok(g, extra, name, kind)
    case h <> t:
      field_ok(g, h) && fields_ok(g, t)

# The body of the loop in check_request, for one request.
def check_one(g: Guard, extra: List<&2, Nat>, r: Req) -> Bool:
  match r:
    case Req{name, reads, denied, fields, kind}:
      check_parts(g, extra, name, kind, fields)

# PeerGuard.check_request does not raise.
def check(+g: Guard, +extra: List<&2, Nat>, rs: List<&2, Req>) -> Bool:
  match rs:
    case Nil{}:
      True{}
    case h <> t:
      check_one(g, extra, h) && check(g, extra, t)

# ReadOnlyTelegramClient._call
# ----------------------------

# `self.extra_requests | DOWNLOAD_REQUESTS`: dl is the numbered
# DOWNLOAD_REQUESTS, the rest comes from the features enabled in the config.
def extra_of(reg: List<&2, F.Feature>, enabled: List<&2, Nat>, dl: List<&2, Nat>) -> List<&2, Nat>:
  F.join(F.allowed_requests(reg, enabled), dl)

# Both guards let the request (or the batch) through to Telegram.
def passes(+extra: List<&2, Nat>, g: Guard, +rs: List<&2, Req>) -> Bool:
  read_only(extra, rs) && check(g, extra, rs)

def call_ok(reg: List<&2, F.Feature>, enabled: List<&2, Nat>, dl: List<&2, Nat>, g: Guard,
  rs: List<&2, Req>) -> Bool:
  passes(extra_of(reg, enabled, dl), g, rs)

# PeerGuard.filter_response
# -------------------------

# msg.peer_id as PeerGuard._keep sees it: missing, not a peer (TypeError), or
# a chat id.
type MsgPeer is Data:
  MNone{}
  MBad{}
  MId{id: Nat}

# PeerGuard._keep
def keeps(g: Guard, m: MsgPeer) -> Bool:
  match g m:
    case Guard{allowed, self_id} MNone{}:
      False{}
    case Guard{allowed, self_id} MBad{}:
      False{}
    case Guard{allowed, self_id} MId{i}:
      F.has(i, allowed)

def keep_msg(m: MsgPeer, rest: List<&2, MsgPeer>, hit: Bool) -> List<&2, MsgPeer>:
  match hit:
    case False{}:
      rest
    case True{}:
      m <> rest

# [m for m in messages if self._keep(m)]
def filter_msgs(+g: Guard, ms: List<&2, MsgPeer>) -> List<&2, MsgPeer>:
  match ms:
    case Nil{}:
      Nil{}
    case +h <> t:
      keep_msg(h, filter_msgs(g, t), keeps(g, h))

# Every message of the list is from a whitelisted chat.
def all_kept(+g: Guard, ms: List<&2, MsgPeer>) -> Bool:
  match ms:
    case Nil{}:
      True{}
    case h <> t:
      keeps(g, h) && all_kept(g, t)
