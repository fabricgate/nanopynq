# Contributing to nanopynq

Thanks for your interest. Bug reports, board and driver additions, gateware fixes, examples and documentation
fixes are all welcome. For anything larger than a fix, open an issue first so we can agree on the approach.

## Development setup

```sh
git clone https://github.com/fabricgate/nanopynq.git
cd nanopynq
uv sync                       # https://docs.astral.sh/uv/ (installs the dev group too)
task hooks                    # optional: pre-commit hooks (https://taskfile.dev for `task`)
```

Python 3.11+ is required. `uv.lock` is committed and CI installs with `--frozen`: run `uv lock` when you change
dependencies. The repository also has a dev container (`.devcontainer/`) with the simulator and the build tools;
programming a board needs USB, so do that from the host.

## Checks

| Command | What it runs | CI job |
|---|---|---|
| `task verify` | `ruff check`, `ruff format --check`, `mypy`, the unit tests | Lint, Unit |
| `task test-toolchain` | tests that run the pinned YoWASP build tools (slow on the first run) | Toolchain |
| `task test-sim` | the cocotb simulations of the gateware (Icarus Verilog 14, as in CI) | Sim |

All of them must pass before a pull request is merged. Without `task`, run the commands in `Taskfile.yaml`.

Changes that touch a board (transports, drivers, gateware) cannot be fully checked in CI. Say in the pull
request which board you tried it on, or that you could not.

## Files that must stay byte-for-byte

- `.v`, `.sv` and `.cst` files: `build.json` records their sha256, so even line endings matter
  (`.gitattributes` keeps them LF).
- The bundled designs (`src/nanopynq/data/designs/`): rebuild them with `tools/build_base.py`, never edit
  `base.fs`, `base.npq` or `build.json` by hand. A rebuild changes the bitstream; say in the pull request on
  which board you tried the new one.

`.editorconfig` and the pre-commit hooks leave these files alone.

## Pull requests

- One topic per pull request, with tests for the behaviour it changes.
- Describe what changed, why, and how you checked it.
- Do not commit secrets, local paths or bitstreams built from unreleased third-party IP.

## License

By contributing, you agree that your contributions are licensed under the MIT License (`LICENSE`). Code taken
from another project must keep its license: add it to `THIRD_PARTY_NOTICES.md` and its license text to
`licenses/`.

## Issue numbers in the code

Comments, tests and `reports/` mention issue numbers such as `#44` or `#50`. They come from the project's
development before this repository was published, and do not refer to the issues here.

## Security

Report vulnerabilities privately as described in `SECURITY.md`, not in a public issue.
