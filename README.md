# Second Brain (Hermes L1 vault)

Provenance-first tiered memory. L0 = Hermes memory tool pointers,
L1 = this vault (claims + evidence), L2 = Hermes session transcripts (opaque).

- claims/: one file per claim: `YYYYMMDD-cid.md`
- truth lifecycle: status in (active, superseded, expired, disputed)
- recall withholds expired/superseded/disputed and says why (see `recall`)
- git = audit trail. Engine: `python engine.py <cmd>`

Vault: D:\projects\second-brain
