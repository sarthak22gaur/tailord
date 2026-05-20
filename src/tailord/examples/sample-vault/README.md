# Sample vault

A fictional candidate ("Jane Doe") that exercises every layer of the
framework. CI builds against this vault to verify that the public contract
still works after framework changes.

Use it as a worked example for what your own vault should look like:

```
tailord/
  examples/sample-vault/        ← you can copy this dir to start your own
    data/
      master.yaml               ← your resume facts
      variants/*.yaml           ← static resume variants
      cover-letter-master.yaml  ← voice + length policy
      cover-letter-variants/*.yaml
    docs/resume-research/       ← evidence corpus (text you want bullets to cite)
    jobs/generated/             ← per-JD outputs (gitignored in real vaults)
    output/                     ← rendered PDFs (gitignored in real vaults)
```

To render the sample vault:

```bash
make build VAULT=$(pwd)/examples/sample-vault VARIANT=master
# → examples/sample-vault/output/jane_doe_master.pdf
```

Or set `RESUME_VAULT` directly:

```bash
RESUME_VAULT=$(pwd)/examples/sample-vault python -m scripts.build --variant master
```
