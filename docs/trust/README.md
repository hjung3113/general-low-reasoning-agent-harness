# Release Trust Root

## What `allowed-signers` is

`docs/trust/allowed-signers` is an OpenSSH allowed-signers file.  Each line
authorizes one release engineer's SSH public key to sign harness release tags:

```
release@harness namespaces="git" ssh-ed25519 AAAA... maintainer@example.com
```

Git uses this file (via `gpg.ssh.allowedSignersFile`) during `git verify-tag`
to confirm that the tag's SSH signature was made by a listed key.

**First-trust bootstrap**: this file ships in the repo, so a coworker who
clones from a compromised mirror could receive a poisoned `allowed-signers`.
Verify the maintainer's SSH key fingerprint out-of-band (Slack, email,
in-person) before trusting a new install.  This is normal TOFU.

## Adding an authorized signer

1. Obtain the maintainer's SSH public key (`cat ~/.ssh/id_ed25519.pub`).
2. Verify the fingerprint out-of-band: `ssh-keygen -lf <pubkey-file>`.
3. Add a line to `docs/trust/allowed-signers`:
   ```
   release@harness namespaces="git" <pubkey line>
   ```
4. Commit and push to `main` before creating the next release tag.

## Signing a release tag (maintainer)

```bash
git config user.signingKey ~/.ssh/id_ed25519   # or path to your key
git config gpg.format ssh
git tag -s v0.7.0 -m "Release v0.7.0"
git push origin v0.7.0
```

Requires Git ≥ 2.34.  Git for Windows bundles a compatible `ssh-keygen`.

## Verifying a tag (consumer)

```bash
git -c gpg.ssh.allowedSignersFile=docs/trust/allowed-signers verify-tag v0.7.0
```

The harness upgrade command runs this automatically before computing any
file hashes; file hashes are read from the signed commit tree, not the
local working tree.

## Dev installs and trust-downgrade refusal

If you are running from an unsigned development checkout, set:

```bash
export HARNESS_ALLOW_UNSIGNED_DEV=1
harness upgrade ...
```

This bypasses signature verification and emits a `trust_origin: dev_unsigned`
manifest.

**Trust-downgrade is always refused**: if the target's installed manifest
already carries `trust_origin: signed_tag`, the upgrade will abort even with
`HARNESS_ALLOW_UNSIGNED_DEV=1`.  Use a properly signed release tag to upgrade
a production install.

## Key rotation

To retire a signing key, remove its line from `allowed-signers` and add the
replacement key.  Tags signed with the retired key will no longer verify.
Document the rotation in a comment in `allowed-signers` with the date and
reason.

## Key revocation (v0.7.0 limitation)

Revocation today: remove the line from `docs/trust/allowed-signers` and
re-broadcast the updated file out-of-band to all consumers.

**Limitation**: previously-signed tags continue to verify locally until every
consumer's checkout has the updated `allowed-signers`. If a maintainer key is
leaked, their signed tags will appear valid to consumers still running old
checkouts until propagation completes.

**Planned for v0.9.0**: explicit `revoked_keys` file consulted alongside
`allowed-signers` for immediate revocation without waiting for propagation.
