# 0001: Pure functional cores with thin shells for I/O

**Status:** accepted

## Context

Every stage calls something slow, paid or non-deterministic: feeds, a language
model, the verifier, the file system. Tests that call these are slow, flaky and
cost money, and logic mixed with I/O is hard to test at all.

## Decision

Each stage with real logic is split in two:

- a **core** module (`ranking_core`, `verify_core`, `repair_core` and others)
  with pure functions: data in, data out, no network, clock or files;
- a **shell** module (`ranking`, `verifier`, `repairer`) that does the I/O and
  calls the core. Its dependencies, such as `complete=` and `system_one=`, are
  parameters with real defaults, so tests pass fakes.

## Consequences

- The 370-odd tests run in about two seconds with no network and no keys.
- The ranking eval reuses the same shell with a cached `complete`, so the code
  it measures is the code that runs in production.
- There are more modules. Each package's `__init__.py` says which is which.
