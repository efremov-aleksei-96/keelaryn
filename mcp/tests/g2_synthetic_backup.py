#!/usr/bin/env python3
"""G2 disposable, offline *synthetic-only* encrypted snapshot/restore prototype.

Not a backup service, production format, Drive integration or secret manager.
Requires cryptography. Does not import Keelaryn MCP at restore time.
Snapshot serializes G1 cooperative writes using its exact journal .lock.
Restore verifies AES-256-GCM and per-file SHA before an empty-root publication.
"""
import base64
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import stat
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"KOSG2\x01"
SALT_SIZE = 16
NONCE_SIZE = 12
MAX_PLAINTEXT = 1_500_000
MAX_ENCRYPTED = MAX_PLAINTEXT + 64
MAX_FILE = 65536
MAX_RECEIPTS = 128
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(md|csv|json)\Z")
REQ = re.compile(r"[0-9a-f]{32}\.json\Z")
VERSION = re.compile(r"v[0-9]{4}\Z")
OWNER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
D = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
F = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _key(passphrase, salt):
    if not isinstance(passphrase, str) or len(passphrase) < 16 or len(passphrase) > 256:
        raise ValueError("A separate strong recovery passphrase is required")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8"))


def _private_dir(path, empty=False):
    p = pathlib.Path(path)
    if not p.is_absolute() or os.path.normpath(str(p)) != str(p):
        raise ValueError("Use an absolute non-traversing path")
    # This is a test-only root, not a general trusted-path resolver:
    # reject all symlink ancestors instead of resolving them.
    current = pathlib.Path("/")
    for part in p.parts[1:]:
        if part in ("", ".", ".."):
            raise ValueError("Unsafe directory path")
        current = current / part
        st = os.lstat(current)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise ValueError("Symlink or non-directory in root path")
    fd = os.open(p, D)
    st = os.fstat(fd)
    if (st.st_uid != os.geteuid() or st.st_mode & 0o077
            or not stat.S_ISDIR(st.st_mode)):
        os.close(fd)
        raise ValueError("Test data root must be private and same-UID")
    if empty and os.listdir(fd):
        os.close(fd)
        raise ValueError("Restore destination is not empty")
    return fd


def _bounded_read(parent, name, cap=MAX_FILE):
    fd = os.open(name, F, dir_fd=parent)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or st.st_mode & 0o077
                or st.st_size > cap):
            raise ValueError("Unsafe file ownership, links or size")
        raw = os.read(fd, cap + 1)
        if len(raw) != st.st_size or len(raw) > cap:
            raise ValueError("File read was truncated or concurrent")
        return raw
    finally:
        os.close(fd)


def _validated_records(journal, names):
    if ".lock" not in names or len(names) > MAX_RECEIPTS + 1:
        raise ValueError("Missing lock or excessive receipts")
    # Require a real single-link private lock: snapshot holds flock on it.
    for name in names:
        if name == ".lock":
            continue
        if not REQ.fullmatch(name):
            raise ValueError("Unresolved intent/temp or unknown journal object")


def _owner_image(root, allow, owner, version):
    if not OWNER.fullmatch(owner) or not VERSION.fullmatch(version):
        raise ValueError("Invalid synthetic owner/version")
    if (not isinstance(allow, list) or not 1 <= len(allow) <= 20
            or len(allow) != len(set(allow))
            or any(not isinstance(n, str) or not NAME.fullmatch(n)
                   for n in allow)):
        raise ValueError("Invalid exact synthetic allowlist")
    rfd = _private_dir(root)
    try:
        names = os.listdir(rfd)
        if ".keelaryn-g1" not in names or set(names) - set(allow) - {".keelaryn-g1"}:
            raise ValueError("Unexpected owner-root objects")
        jfd = os.open(".keelaryn-g1", D, dir_fd=rfd)
        try:
            jst = os.fstat(jfd)
            if jst.st_uid != os.geteuid() or jst.st_mode & 0o077:
                raise ValueError("Unsafe G1 journal root")
            lock_fd = os.open(".lock", F, dir_fd=jfd)
            try:
                lock_st = os.fstat(lock_fd)
                if (not stat.S_ISREG(lock_st.st_mode) or lock_st.st_nlink != 1
                        or lock_st.st_uid != os.geteuid()
                        or lock_st.st_mode & 0o077):
                    raise ValueError("Unsafe G1 writer lock")
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                try:
                    records = sorted(os.listdir(jfd))
                    _validated_records(jfd, records)
                    if any(n not in allow and n != ".keelaryn-g1" for n in os.listdir(rfd)):
                        raise ValueError("Unexpected owner file during snapshot")
                    blobs = []
                    for n in sorted(os.listdir(rfd)):
                        if n == ".keelaryn-g1":
                            continue
                        data = _bounded_read(rfd, n)
                        data.decode("utf-8")
                        blobs.append((n, data))
                    for n in records:
                        if n == ".lock":
                            continue
                        raw = _bounded_read(jfd, n, 4096)
                        record = json.loads(raw)
                        if (not isinstance(record, dict)
                                or record.get("request_id") != n[:-5]
                                or record.get("status") != "committed"):
                            raise ValueError("Pending/invalid G1 receipt")
                        blobs.append((".keelaryn-g1/" + n, raw))
                    # Re-check the complete name set under the same G1 lock.
                    expected_files = {n for n, _ in blobs if "/" not in n}
                    if set(os.listdir(rfd)) != expected_files | {".keelaryn-g1"}:
                        raise ValueError("Owner root changed during snapshot")
                    if set(os.listdir(jfd)) != set(records):
                        raise ValueError("Journal changed during snapshot")
                    def item(n, b):
                        return {"path": n, "sha256": _sha(b), "size": len(b),
                                "base64": base64.b64encode(b).decode("ascii")}
                    return {"schema": "keelaryn_g2_synthetic_snapshot_v1",
                            "owner": owner, "version": version,
                            "allow": sorted(allow),
                            "files": [item(n, b) for n, b in blobs]}
                finally:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        finally:
            os.close(jfd)
    finally:
        os.close(rfd)


def make_snapshot(source, repository, owner, version, allow, passphrase,
                  interrupt_before_publish=False):
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid snapshot version")
    image = _owner_image(source, allow, owner, version)
    payload = json.dumps(image, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PLAINTEXT:
        raise ValueError("Synthetic owner snapshot too large")
    salt, nonce = os.urandom(SALT_SIZE), os.urandom(NONCE_SIZE)
    header = MAGIC + salt + nonce
    artifact = header + AESGCM(_key(passphrase, salt)).encrypt(nonce, payload, header)
    rfd = _private_dir(repository)
    try:
        final = version + ".kg2"
        try:
            fd = os.open(final, F, dir_fd=rfd)
        except FileNotFoundError:
            pass
        else:
            os.close(fd)
            raise ValueError("Snapshot version already published")
        tmp = ".pending-" + secrets.token_hex(16)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=rfd)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(artifact)
                out.flush()
                os.fsync(out.fileno())
            if interrupt_before_publish:
                os._exit(81)
            os.link(tmp, final, src_dir_fd=rfd, dst_dir_fd=rfd,
                    follow_symlinks=False)
            os.fsync(rfd)
        finally:
            if not interrupt_before_publish:
                try:
                    os.unlink(tmp, dir_fd=rfd)
                    os.fsync(rfd)
                except FileNotFoundError:
                    pass
        verify = _bounded_read(rfd, final, MAX_ENCRYPTED)
        if verify != artifact:
            raise ValueError("Published snapshot changed")
        return {"version": version, "cipher_sha256": _sha(artifact),
                "artifact_bytes": len(artifact), "entry_count": len(image["files"])}
    finally:
        os.close(rfd)


def list_versions(repository):
    fd = _private_dir(repository)
    try:
        values = []
        for name in os.listdir(fd):
            if VERSION.fullmatch(name[:-4]) and name.endswith(".kg2"):
                _bounded_read(fd, name, MAX_ENCRYPTED)
                values.append(name)
            elif name.startswith(".pending-"):
                # Interrupted unpublished temp cannot masquerade as backup.
                continue
            else:
                raise ValueError("Unexpected backup repository object")
        return sorted(values)
    finally:
        os.close(fd)


def _decode_snapshot(repository, version, passphrase):
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid snapshot version")
    fd = _private_dir(repository)
    try:
        blob = _bounded_read(fd, version + ".kg2", MAX_ENCRYPTED)
    finally:
        os.close(fd)
    offset = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if len(blob) < offset + 16 or not blob.startswith(MAGIC):
        raise ValueError("Invalid encrypted snapshot header")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:offset]
    try:
        raw = AESGCM(_key(passphrase, salt)).decrypt(
            nonce, blob[offset:], blob[:offset])
    except InvalidTag:
        raise ValueError("Snapshot authentication failed") from None
    if len(raw) > MAX_PLAINTEXT:
        raise ValueError("Oversized decrypted snapshot")
    image = json.loads(raw)
    if (not isinstance(image, dict)
            or set(image) != {"schema", "owner", "version", "allow", "files"}
            or image["schema"] != "keelaryn_g2_synthetic_snapshot_v1"
            or image["version"] != version
            or not OWNER.fullmatch(image["owner"])
            or not isinstance(image["allow"], list)
            or not image["allow"]
            or len(image["allow"]) != len(set(image["allow"]))
            or any(not isinstance(x, str) or not NAME.fullmatch(x)
                   for x in image["allow"])):
        raise ValueError("Invalid decrypted snapshot schema")
    allowed = set(image["allow"])
    blobs, names = {}, set()
    if not isinstance(image["files"], list) or not 1 <= len(image["files"]) <= 150:
        raise ValueError("Invalid restored file count")
    for item in image["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size", "base64"}:
            raise ValueError("Invalid restored file record")
        name = item["path"]
        journal = isinstance(name, str) and name.startswith(".keelaryn-g1/")
        receipt = name[len(".keelaryn-g1/"):] if journal else ""
        if (not isinstance(name, str) or name in names or
                (not journal and name not in allowed) or
                (journal and not REQ.fullmatch(receipt))):
            raise ValueError("Unexpected snapshot path/duplicate")
        names.add(name)
        if (not isinstance(item["sha256"], str) or not HASH.fullmatch(item["sha256"])
                or type(item["size"]) is not int
                or not 0 <= item["size"] <= (4096 if journal else MAX_FILE)):
            raise ValueError("Invalid snapshot size/hash")
        data = base64.b64decode(item["base64"], validate=True)
        if len(data) != item["size"] or _sha(data) != item["sha256"]:
            raise ValueError("Snapshot per-file integrity mismatch")
        if journal:
            record = json.loads(data)
            if (not isinstance(record, dict) or record.get("request_id") != receipt[:-5]
                    or record.get("status") != "committed"):
                raise ValueError("Inconsistent G1 journal state")
        else:
            data.decode("utf-8")
        blobs[name] = data
    if not any(n.startswith(".keelaryn-g1/") for n in blobs):
        raise ValueError("Snapshot lacks G1 receipts")
    return image, blobs


def restore_snapshot(repository, version, destination, owner, passphrase):
    # Entire crypto/manifest verification comes BEFORE creating any output.
    image, blobs = _decode_snapshot(repository, version, passphrase)
    if image["owner"] != owner:
        raise ValueError("Snapshot belongs to another owner")
    target = pathlib.Path(destination)
    if not target.is_absolute() or target.name in ("", ".", ".."):
        raise ValueError("Unsafe restore destination")
    parent = target.parent
    pfd = _private_dir(parent)
    try:
        if target.exists() or target.is_symlink():
            raise ValueError("Refusing existing or nonempty destination")
        temp = ".restore-" + secrets.token_hex(16)
        os.mkdir(temp, 0o700, dir_fd=pfd)
        try:
            rfd = os.open(temp, D, dir_fd=pfd)
            try:
                os.mkdir(".keelaryn-g1", 0o700, dir_fd=rfd)
                jfd = os.open(".keelaryn-g1", D, dir_fd=rfd)
                try:
                    towrite = [(name, data) for name, data in blobs.items()
                               if "/" not in name]
                    towrite += [(".keelaryn-g1/" + n, data)
                                for n, data in
                                ((k.split("/", 1)[1], v) for k, v in blobs.items()
                                 if "/" in k)]
                    for name, data in towrite + [(".keelaryn-g1/.lock", b"")]:
                        folder, leaf = (jfd, name.split("/", 1)[1]) if "/" in name else (rfd, name)
                        f = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                    os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=folder)
                        with os.fdopen(f, "wb") as out:
                            out.write(data)
                            out.flush()
                            os.fsync(out.fileno())
                        if name in blobs and _bounded_read(folder, leaf) != data:
                            raise ValueError("Restore file readback mismatch")
                    os.fsync(jfd)
                finally:
                    os.close(jfd)
                os.fsync(rfd)
            finally:
                os.close(rfd)
            if target.exists() or target.is_symlink():
                raise ValueError("Restore destination changed during restore")
            # Publication is one directory rename, not a multi-owner transaction.
            os.rename(temp, target.name, src_dir_fd=pfd, dst_dir_fd=pfd)
            os.fsync(pfd)
        except BaseException:
            # A failed restore can leave an unpublished temp subtree;
            # refuse to expose it as a restored owner. Caller may clean
            # its disposable test parent; never delete unknown real data.
            raise
        return {"owner": owner, "version": version,
                "files_restored": len(blobs), "destination": str(target),
                "sha256": {name: _sha(data) for name, data in blobs.items()}}
    finally:
        os.close(pfd)


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "restore":
        raise SystemExit("Usage: python -I g2_synthetic_backup.py restore REPOSITORY VERSION DESTINATION; recovery passphrase via stdin")
    repo, version, dest = sys.argv[2:]
    # Owner is an explicit expected value in the backup's own test contract.
    expected_owner = os.environ.get("G2_EXPECTED_SYNTHETIC_OWNER", "")
    passphrase = sys.stdin.read(257).rstrip("\n")
    try:
        result = restore_snapshot(repo, version, dest, expected_owner, passphrase)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, TypeError) as exc:
        raise SystemExit(type(exc).__name__ + ": synthetic restore refused") from None
