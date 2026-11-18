# Model of src/telegram_reader/features.py: which Telegram request names the
# enabled features add on top of plain reads.
#
# A feature key and a request name are Nats (the tests number the real
# strings). Only the fields allowed_requests reads are kept.
import Base

# features.Feature
type Feature is Data:
  Feature{key: Nat, available: Bool, requests: List<&2, Nat>}

# `x in xs`
def has(+x: Nat, xs: List<&2, Nat>) -> Bool:
  match xs:
    case Nil{}:
      False{}
    case h <> t:
      Nat.is_eq(h, x) || has(x, t)

def join(xs: List<&2, Nat>, ys: List<&2, Nat>) -> List<&2, Nat>:
  match xs:
    case Nil{}:
      ys
    case h <> t:
      h <> join(t, ys)

# `out.update(feature.requests)` when the feature counts.
def grant(requests: List<&2, Nat>, rest: List<&2, Nat>, counts: Bool) -> List<&2, Nat>:
  match counts:
    case False{}:
      rest
    case True{}:
      join(requests, rest)

# features.allowed_requests over a registry: the requests of every feature
# that is enabled in the config and available. Python walks the enabled keys
# and looks each up in FEATURES; walking the registry gives the same set.
def allowed_requests(reg: List<&2, Feature>, +enabled: List<&2, Nat>) -> List<&2, Nat>:
  match reg:
    case Nil{}:
      Nil{}
    case Feature{key, available, requests} <> t:
      grant(requests, allowed_requests(t, enabled), has(key, enabled) && available)

# No feature of the registry is available.
def none_available(reg: List<&2, Feature>) -> Bool:
  match reg:
    case Nil{}:
      True{}
    case Feature{key, available, requests} <> t:
      Bool.not(available) && none_available(t)

# features.FEATURES as shipped: "write" (key 0), not available, no requests.
# tests/test_bend_model.py fails if this drifts from the Python registry.
def registry() -> List<&2, Feature>:
  [Feature{0n, False{}, []}]
