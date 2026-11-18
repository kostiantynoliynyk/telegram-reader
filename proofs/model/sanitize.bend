# Model of clean and clip in src/telegram_reader/sanitize.py.
#
# A string is a list of character classes, not real Unicode:
# - Plain: a visible character that is not whitespace;
# - Hidden: a character sanitize._strip removes;
# - Space: whitespace, as str.split() sees it;
# - Dots: the "…" clip puts where it cut;
# - Mark: the whole text of HIDDEN_MARK.
# Inputs are made of the first three. The zero-width joiner, which _strip_zwj
# keeps between emoji and removes elsewhere, is not modelled.
import Base

type Sym is Data:
  Plain{}
  Hidden{}
  Space{}
  Dots{}
  Mark{}

def is_hidden(s: Sym) -> Bool:
  match s:
    case Plain{}:
      False{}
    case Hidden{}:
      True{}
    case Space{}:
      False{}
    case Dots{}:
      False{}
    case Mark{}:
      False{}

# The text holds a hidden character.
def has_hidden(xs: List<&2, Sym>) -> Bool:
  match xs:
    case Nil{}:
      False{}
    case h <> t:
      is_hidden(h) || has_hidden(t)

# sanitize._strip
def strip(xs: List<&2, Sym>) -> List<&2, Sym>:
  match xs:
    case Nil{}:
      Nil{}
    case Plain{} <> t:
      Plain{} <> strip(t)
    case Hidden{} <> t:
      strip(t)
    case Space{} <> t:
      Space{} <> strip(t)
    case Dots{} <> t:
      Dots{} <> strip(t)
    case Mark{} <> t:
      Mark{} <> strip(t)

# Where " ".join(text.split()) stands: before the first word, inside a word,
# or after a word with whitespace seen since.
type Gap is Data:
  Start{}
  InWord{}
  Pending{}

def after_space(st: Gap) -> Gap:
  match st:
    case Start{}:
      Start{}
    case InWord{}:
      Pending{}
    case Pending{}:
      Pending{}

def emit(c: Sym, st: Gap, rest: List<&2, Sym>) -> List<&2, Sym>:
  match st:
    case Start{}:
      c <> rest
    case InWord{}:
      c <> rest
    case Pending{}:
      Space{} <> c <> rest

def words(xs: List<&2, Sym>, st: Gap) -> List<&2, Sym>:
  match xs:
    case Nil{}:
      Nil{}
    case Plain{} <> t:
      emit(Plain{}, st, words(t, InWord{}))
    case Hidden{} <> t:
      emit(Hidden{}, st, words(t, InWord{}))
    case Space{} <> t:
      words(t, after_space(st))
    case Dots{} <> t:
      emit(Dots{}, st, words(t, InWord{}))
    case Mark{} <> t:
      emit(Mark{}, st, words(t, InWord{}))

# " ".join(text.split())
def flat(xs: List<&2, Sym>) -> List<&2, Sym>:
  words(xs, Start{})

# len(xs) > n
def longer(xs: List<&2, Sym>, n: Nat) -> Bool:
  match xs n:
    case Nil{} 0n:
      False{}
    case Nil{} 1n+p:
      False{}
    case h <> t 0n:
      True{}
    case h <> t 1n+p:
      longer(t, p)

# xs[:n]
def take(n: Nat, xs: List<&2, Sym>) -> List<&2, Sym>:
  match n xs:
    case 0n Nil{}:
      Nil{}
    case 0n h <> t:
      Nil{}
    case 1n+p Nil{}:
      Nil{}
    case 1n+p h <> t:
      h <> take(p, t)

# xs + [s]
def push(xs: List<&2, Sym>, s: Sym) -> List<&2, Sym>:
  match xs:
    case Nil{}:
      [s]
    case h <> t:
      h <> push(t, s)

# `flat[: limit - 1] + "…" if limit > 0 else ""`
def clipped(limit: Nat, ys: List<&2, Sym>) -> List<&2, Sym>:
  match limit:
    case 0n:
      Nil{}
    case 1n+p:
      push(take(p, ys), Dots{})

def cut_if(over: Bool, ys: List<&2, Sym>, limit: Nat) -> List<&2, Sym>:
  match over:
    case False{}:
      ys
    case True{}:
      clipped(limit, ys)

# `if len(flat) > limit: flat = ...`
def cut(+ys: List<&2, Sym>, +limit: Nat) -> List<&2, Sym>:
  cut_if(longer(ys, limit), ys, limit)

# f"{body} {HIDDEN_MARK}" when something was removed.
def mark_if(body: List<&2, Sym>, marked: Bool) -> List<&2, Sym>:
  match marked:
    case False{}:
      body
    case True{}:
      push(push(body, Space{}), Mark{})

# clip without the mark.
def clip_body(xs: List<&2, Sym>, limit: Nat) -> List<&2, Sym>:
  cut(flat(strip(xs)), limit)

# sanitize.clip. `stripped != text` is has_hidden(xs): see the laws
# c2_nothing_removed_without_hidden and c2_removal_means_hidden.
def clip(+xs: List<&2, Sym>, limit: Nat) -> List<&2, Sym>:
  mark_if(clip_body(xs, limit), has_hidden(xs))

# sanitize.clean
def clean(+xs: List<&2, Sym>) -> List<&2, Sym>:
  mark_if(strip(xs), has_hidden(xs))
