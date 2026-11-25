# Security Policy

## Supported versions

Security fixes go into the latest minor release on PyPI. Older releases are not patched; upgrade to get a fix.

## Reporting a vulnerability

Please report vulnerabilities privately. **Do not open a public issue.**

1. Open a private report with GitHub's
   [private vulnerability reporting](https://github.com/fabricgate/nanopynq/security/advisories/new)
   ("Report a vulnerability" on the Security tab).
2. Include a description, steps to reproduce, the potential impact, and a suggested fix if you have one.

| Step | Timeline |
|------|----------|
| Acknowledgement | within 5 business days |
| Initial assessment | within 10 business days |
| Fix and disclosure | within 90 days (coordinated disclosure) |

Reporters are credited in the release notes unless they ask to stay anonymous.

## Scope

In scope for this repository:

- the `nanopynq` Python package (`src/nanopynq/`): the transports to the board (UART, JTAG over USB), the
  design and metadata loaders (`.npq`, `manifest.yaml`), `nanopynq build`, and the bundled designs
- the gateware and the browser code shipped here (`gateware/`, `src/nanopynq/rtl/`, `examples/`)
- the release pipeline (`.github/workflows/`)

Out of scope: third-party dependencies and tools (report them upstream, e.g. YoWASP, Apicula, nextpnr, pyusb),
the FabricGate registry service, and physical attacks on a board you hold.

Note that a bitstream programs the FPGA on your board: only load designs you trust.
