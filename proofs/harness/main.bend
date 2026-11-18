# Entry point of the binary tests/test_bend_model.py talks to.
#
# It reads one request per line on stdin, runs the model on it and prints one
# line with the answer, so the tests can compare the model with the Python
# code on the same input. Nothing here is proven: it only parses and prints.
#
# A line is `command|field|field...`. Inside a field, `;` separates the items
# of a list, `,` the parts of an item, `/` and ` ` and `:` what is nested
# deeper. Every value is a decimal number. tests/test_bend_model.py has the
# encoder for each command, next to the Python call it is compared with.
import Base
import ../model/access.bend as A
import ../model/features.bend as F
import ../model/guard.bend as G
import ../model/sanitize.bend as S

# Reading
# -------

def nums.put(m: Maybe<&2, Nat>, rest: List<&2, Nat>) -> List<&2, Nat>:
  match m:
    case None{}:
      rest
    case Some{n}:
      n <> rest

def nums.go(ws: List<&2, String>) -> List<&2, Nat>:
  match ws:
    case Nil{}:
      Nil{}
    case h <> t:
      nums.put(Nat.read(h), nums.go(t))

# The numbers of a space-separated string; anything else is skipped.
def nums(s: String) -> List<&2, Nat>:
  nums.go(String.split(s, ' '))

def first(xs: List<&2, Nat>) -> Nat:
  match xs:
    case Nil{}:
      0n
    case h <> t:
      h

def num(s: String) -> Nat:
  first(nums(s))

def bool(n: Nat) -> Bool:
  match n:
    case 0n:
      False{}
    case 1n+p:
      True{}

# 0 is None, n + 1 is n.
def opt(n: Nat) -> Maybe<&2, Nat>:
  match n:
    case 0n:
      None{}
    case 1n+p:
      Some{p}

# The non-empty parts of s around sep.
def parts.put(h: String, rest: List<&2, String>, empty: Bool) -> List<&2, String>:
  match empty:
    case True{}:
      rest
    case False{}:
      h <> rest

def parts.go(ws: List<&2, String>) -> List<&2, String>:
  match ws:
    case Nil{}:
      Nil{}
    case +h <> t:
      parts.put(h, parts.go(t), String.is_empty(String.trim(h)))

def parts(s: String, sep: Char) -> List<&2, String>:
  parts.go(String.split(s, sep))

# "id:title"
def chat.of(xs: List<&2, Nat>) -> A.Chat:
  match xs:
    case i <> t <> r:
      A.Chat{i, t}
    case _:
      A.Chat{0n, 0n}

def chats.go(ws: List<&2, String>) -> List<&2, A.Chat>:
  match ws:
    case Nil{}:
      Nil{}
    case h <> t:
      chat.of(nums.go(String.split(h, ':'))) <> chats.go(t)

def chats(s: String) -> List<&2, A.Chat>:
  chats.go(parts(s, ' '))

# "kind:id:title": kind 0 is an int, 1 a str, 2 a numeric-looking str.
def ref.of(xs: List<&2, Nat>) -> A.Ref:
  match xs:
    case 0n <> i <> r:
      A.RInt{i}
    case 1n <> i <> t <> r:
      A.RStr{None{}, t}
    case k <> i <> t <> r:
      A.RStr{Some{i}, t}
    case _:
      A.RInt{0n}

def ref(s: String) -> A.Ref:
  ref.of(nums.go(String.split(s, ':')))

def tg(ok: Bool, ids: List<&2, Nat>, cs: List<&2, A.Chat>) -> A.Tg:
  match ok:
    case False{}:
      A.TgFail{}
    case True{}:
      A.TgOk{ids, cs}

# "cached,cfg_acct,sess_acct,ok,ids,chats,ref"
def call.of(fs: List<&2, String>) -> A.Call:
  match fs:
    case c <> a <> s <> k <> i <> h <> r:
      A.Call{bool(num(c)), opt(num(a)), opt(num(s)), tg(bool(num(k)), nums(i), chats(h))}
    case _:
      A.Call{False{}, None{}, None{}, A.TgFail{}}

def call.ref(fs: List<&2, String>) -> A.Ref:
  match fs:
    case c <> a <> s <> k <> i <> h <> r <> z:
      ref(r)
    case _:
      A.RInt{0n}

# 0 PBad, 1 InputUserSelf, 2 InputPeerSelf, n + 3 the id n.
def peer(n: Nat) -> G.Peer:
  match n:
    case 0n:
      G.PBad{}
    case 1n:
      G.PUserSelf{}
    case 2n:
      G.PPeerSelf{}
    case 3n+p:
      G.PId{p}

def peers.go(xs: List<&2, Nat>) -> List<&2, G.Peer>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      peer(h) <> peers.go(t)

def peers(s: String) -> List<&2, G.Peer>:
  peers.go(nums(s))

def fields.go(ws: List<&2, String>) -> List<&2, List<&2, G.Peer>>:
  match ws:
    case Nil{}:
      Nil{}
    case h <> t:
      peers(h) <> fields.go(t)

# "f 3 4/f/f 5": one `f` per peer field that is not None, then its peers.
def fields(s: String) -> List<&2, List<&2, G.Peer>>:
  fields.go(parts(s, '/'))

def kind(n: Nat, ids: String) -> G.Peerless:
  match n:
    case 0n:
      G.KOther{}
    case 1n:
      G.KAllowed{}
    case 2n+p:
      G.KIdPeers{peers(ids)}

# "name,reads,denied,fields,kind,ids"
def req.of(fs: List<&2, String>) -> G.Req:
  match fs:
    case n <> r <> d <> f <> k <> i <> z:
      G.Req{num(n), bool(num(r)), bool(num(d)), fields(f), kind(num(k), i)}
    case _:
      G.Req{0n, False{}, False{}, [], G.KOther{}}

def reqs.go(ws: List<&2, String>) -> List<&2, G.Req>:
  match ws:
    case Nil{}:
      Nil{}
    case h <> t:
      req.of(String.split(h, ',')) <> reqs.go(t)

def reqs(s: String) -> List<&2, G.Req>:
  reqs.go(parts(s, ';'))

# "allowed ids,self_id"
def guard.of(fs: List<&2, String>) -> G.Guard:
  match fs:
    case a <> s <> z:
      G.Guard{nums(a), opt(num(s))}
    case _:
      G.Guard{[], None{}}

def guard(s: String) -> G.Guard:
  guard.of(String.split(s, ','))

# "key,available,requests"
def feature.of(fs: List<&2, String>) -> F.Feature:
  match fs:
    case k <> a <> r <> z:
      F.Feature{num(k), bool(num(a)), nums(r)}
    case _:
      F.Feature{0n, False{}, []}

def features.go(ws: List<&2, String>) -> List<&2, F.Feature>:
  match ws:
    case Nil{}:
      Nil{}
    case h <> t:
      feature.of(String.split(h, ',')) <> features.go(t)

def features(s: String) -> List<&2, F.Feature>:
  features.go(parts(s, ';'))

# 0 no peer_id, 1 not a peer, n + 2 the chat id n.
def msg(n: Nat) -> G.MsgPeer:
  match n:
    case 0n:
      G.MNone{}
    case 1n:
      G.MBad{}
    case 2n+p:
      G.MId{p}

def msgs.go(xs: List<&2, Nat>) -> List<&2, G.MsgPeer>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      msg(h) <> msgs.go(t)

# 0 Plain, 1 Hidden, 2 Space.
def sym(n: Nat) -> S.Sym:
  match n:
    case 0n:
      S.Plain{}
    case 1n:
      S.Hidden{}
    case 2n:
      S.Space{}
    case 3n:
      S.Dots{}
    case 4n+p:
      S.Mark{}

def syms.go(xs: List<&2, Nat>) -> List<&2, S.Sym>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      sym(h) <> syms.go(t)

# Printing
# --------

def show.bool(b: Bool) -> String:
  match b:
    case False{}:
      "0"
    case True{}:
      "1"

def show.nats.go(xs: List<&2, Nat>) -> List<&2, String>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      Nat.show(h) <> show.nats.go(t)

def show.nats(xs: List<&2, Nat>) -> String:
  String.join(show.nats.go(xs), " ")

def show.chat(c: A.Chat) -> String:
  match c:
    case A.Chat{i, t}:
      Nat.show(i) ++ ":" ++ Nat.show(t)

def show.chats.go(xs: List<&2, A.Chat>) -> List<&2, String>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      show.chat(h) <> show.chats.go(t)

def show.chats(xs: List<&2, A.Chat>) -> String:
  String.join(show.chats.go(xs), " ")

# D AccessDenied, A AmbiguousChat, F id:title the chat found.
def show.res(r: A.Res) -> String:
  match r:
    case A.Denied{}:
      "D"
    case A.Ambiguous{}:
      "A"
    case A.Found{c}:
      "F " ++ show.chat(c)

# M AccountMismatch, E any other error of the refresh.
def show.ans(a: A.Ans) -> String:
  match a:
    case A.Raised{A.Mismatch{}}:
      "M"
    case A.Raised{A.TgError{}}:
      "E"
    case A.Resolved{r}:
      show.res(r)

# "valid,guard ids,allowed chats"
def show.state(s: A.State) -> String:
  match s:
    case A.State{allowed, guard, valid}:
      show.bool(valid) ++ "," ++ show.nats(guard) ++ "," ++ show.chats(allowed)

def show.feature(f: F.Feature) -> String:
  match f:
    case F.Feature{key, available, requests}:
      Nat.show(key) ++ "," ++ show.bool(available) ++ "," ++ show.nats(requests)

def show.features.go(xs: List<&2, F.Feature>) -> List<&2, String>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      show.feature(h) <> show.features.go(t)

def show.msg(m: G.MsgPeer) -> Nat:
  match m:
    case G.MNone{}:
      0n
    case G.MBad{}:
      1n
    case G.MId{i}:
      2n+i

def show.msgs.go(xs: List<&2, G.MsgPeer>) -> List<&2, Nat>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      show.msg(h) <> show.msgs.go(t)

def show.sym(s: S.Sym) -> Nat:
  match s:
    case S.Plain{}:
      0n
    case S.Hidden{}:
      1n
    case S.Space{}:
      2n
    case S.Dots{}:
      3n
    case S.Mark{}:
      4n

def show.syms.go(xs: List<&2, S.Sym>) -> List<&2, Nat>:
  match xs:
    case Nil{}:
      Nil{}
    case h <> t:
      show.sym(h) <> show.syms.go(t)

# Commands
# --------

# resolve|ref|chats
def do.resolve(args: List<&2, String>) -> String:
  match args:
    case r <> c <> z:
      show.res(A.resolve(ref(r), chats(c)))
    case _:
      "?"

# One answer and the state after it per call, `;` between calls.
def do.access.go(calls: List<&2, String>, +state: A.State) -> List<&2, String>:
  match calls:
    case Nil{}:
      Nil{}
    case h <> t:
      +fs = String.split(h, ',')
      +call = call.of(fs)
      +after = A.next(state, call)
      (show.ans(A.answer(state, call, call.ref(fs))) ++ "," ++ show.state(after)) <> do.access.go(t, after)

# access|call;call;...   starting from a fresh Access
def do.access(args: List<&2, String>) -> String:
  match args:
    case c <> z:
      String.join(do.access.go(parts(c, ';'), A.locked()), ";")
    case _:
      "?"

# features|registry|enabled
def do.features(args: List<&2, String>) -> String:
  match args:
    case r <> e <> z:
      show.nats(F.allowed_requests(features(r), nums(e)))
    case _:
      "?"

# guard|registry|enabled|download names|guard|requests
# Prints read_only, check and call_ok.
def do.guard.run(+extra: List<&2, Nat>, +g: G.Guard, +rs: List<&2, G.Req>) -> String:
  show.bool(G.read_only(extra, rs)) ++ " " ++ show.bool(G.check(g, extra, rs)) ++ " " ++ show.bool(G.passes(extra, g, rs))

def do.guard(args: List<&2, String>) -> String:
  match args:
    case r <> e <> d <> g <> q <> z:
      do.guard.run(G.extra_of(features(r), nums(e), nums(d)), guard(g), reqs(q))
    case _:
      "?"

# filter|guard|messages
def do.filter(args: List<&2, String>) -> String:
  match args:
    case g <> m <> z:
      show.nats(show.msgs.go(G.filter_msgs(guard(g), msgs.go(nums(m)))))
    case _:
      "?"

# clip|limit|symbols
def do.clip(args: List<&2, String>) -> String:
  match args:
    case l <> x <> z:
      show.nats(show.syms.go(S.clip(syms.go(nums(x)), num(l))))
    case _:
      "?"

# clean|symbols
def do.clean(args: List<&2, String>) -> String:
  match args:
    case x <> z:
      show.nats(show.syms.go(S.clean(syms.go(nums(x)))))
    case _:
      "?"

def run(cmd: Nat, args: List<&2, String>) -> String:
  match cmd:
    case 0n:
      String.join(show.features.go(F.registry()), ";")
    case 1n:
      do.resolve(args)
    case 2n:
      do.access(args)
    case 3n:
      do.features(args)
    case 4n:
      do.guard(args)
    case 5n:
      do.filter(args)
    case 6n:
      do.clip(args)
    case 7n:
      do.clean(args)
    case 8n+p:
      "?"

# The command is a number: 0 registry, 1 resolve, 2 access, 3 features,
# 4 guard, 5 filter, 6 clip, 7 clean.
def answer.of(fs: List<&2, String>) -> String:
  match fs:
    case Nil{}:
      "?"
    case h <> t:
      run(num(h), t)

def answer(line: String) -> String:
  answer.of(String.split(line, '|'))

# Loop
# ----

def on_line(f: File, k: File -> IO(Unit), +line: String, end: Bool) -> IO(Unit):
  match end:
    case True{}:
      File.close(f)
    case False{}:
      do IO<Unit>:
        IO.print(answer(String.trim(line)))
        k(f)

def on_read(k: File -> IO(Unit), r: File & Result<&1, &1, U32 & String, String>) -> IO(Unit):
  match r:
    case (f, Fail{e}):
      File.close(f)
    case (f, Done{+line}):
      on_line(f, k, line, String.is_empty(line))

# Answers lines until stdin ends. The fuel only satisfies the termination
# check; the tests start a new process long before it runs out.
def loop(fuel: Nat, f: File) -> IO(Unit):
  match fuel:
    case 0n:
      File.close(f)
    case 1n+p:
      do IO<Unit>:
        r : File & Result<&1, &1, U32 & String, String> <- File.read_line(f, 1048576)
        on_read(f2 => loop(p, f2), r)

def main() -> IO(Unit):
  do IO<Unit>:
    f : File <- IO.try(File, File.open("/dev/stdin", "r"))
    loop(4000000n, f)
