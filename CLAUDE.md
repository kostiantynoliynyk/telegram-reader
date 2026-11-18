# telegram-reader

Read-only MCP server that lets Claude read whitelisted Telegram chats. Python, `uv`, pytest.

```bash
uv sync
uv run pytest -q
```

## Bend

The security rules of this project are stated formally in `proofs/LAWS.bend` and proven in
`proofs/PROOF.bend` over the models in `proofs/model/`. `proofs/README.md` says what is proven
and how each model maps to the Python code.

- The security rules are the laws in `proofs/LAWS.bend`. Read them before touching the access
  or read-only logic.
- Any change in `src/telegram_reader/access.py`, `tg.py`, `features.py` or `sanitize.py`
  requires updating the model in `proofs/model/` to match, and both of these passing:

  ```bash
  bend proofs/PROOF.bend   # must print ALL PROOFS CHECK
  uv run pytest            # includes tests/test_bend_model.py, the model against the code
  ```

- Do not weaken a law without the owner's explicit agreement. If a proof no longer goes
  through, first find out where the error is: the model, the law or the Python code.
- No `@unsafe` and no `def f?(..)` in `proofs/`: they switch the check off.
- Before any work with Bend, run `bend guide` and read it in full. Bend 2 syntax is new: do
  not guess it from memory and do not carry it over from Bend 1 or HVM.

Setup: `curl -fsSL https://bend-lang.com/install.sh | sh` installs Bend into `~/.bend`
without sudo; add `~/.bend/bin` to `PATH` and set `BEND_NO_TELEMETRY=1`. CI pins Bend 2.0.40
in the `bend-proofs` job. Without `bend` installed, `tests/test_bend_model.py` is skipped
locally and fails under CI.
