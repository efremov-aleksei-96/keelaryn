package ingest_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/ingest"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestLocalFSAttemptSourceFingerprintIsDistinctAndContentAware(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	path := filepath.Join(root, "file.bin")
	mustWrite(t, path, []byte("one"))
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	at := fixedTime()

	version, first, err := ingest.LocalFSAttemptSourceFingerprint(ctx, localfs.New("localfs"), root, at)
	if err != nil {
		t.Fatal(err)
	}
	if version != ingest.LocalFSAttemptSourceFingerprintVersion {
		t.Fatalf("version=%q, want %q", version, ingest.LocalFSAttemptSourceFingerprintVersion)
	}
	bootstrapVersion, bootstrap, err := ingest.BootstrapLocalFSSnapshotFingerprint(ctx, localfs.New("localfs"), root, at)
	if err != nil {
		t.Fatal(err)
	}
	if bootstrapVersion != ingest.LocalFSSnapshotFingerprintVersion {
		t.Fatalf("bootstrap version=%q", bootstrapVersion)
	}
	if first == bootstrap {
		t.Fatal("attempt fingerprint aliases bootstrap receipt despite distinct contract")
	}

	mustWrite(t, path, []byte("two"))
	if err := os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	_, second, err := ingest.LocalFSAttemptSourceFingerprint(ctx, localfs.New("localfs"), root, at)
	if err != nil {
		t.Fatal(err)
	}
	if second == first {
		t.Fatal("same-size content change with restored mtime did not change attempt fingerprint")
	}
}


func TestLocalFSAttemptSourceFingerprintAtRootPreservesAuthorityRoot(t *testing.T) {
	ctx := context.Background()
	readRoot := t.TempDir()
	mustWrite(t, filepath.Join(readRoot, "file.bin"), []byte("stable"))
	at := fixedTime()

	_, wrapper, err := ingest.LocalFSAttemptSourceFingerprint(ctx, localfs.New("localfs"), readRoot, at)
	if err != nil {
		t.Fatal(err)
	}
	_, sameRoot, err := ingest.LocalFSAttemptSourceFingerprintAtRoot(
		ctx, localfs.New("localfs"), readRoot, readRoot, at,
	)
	if err != nil {
		t.Fatal(err)
	}
	if wrapper != sameRoot {
		t.Fatal("same-root wrapper does not preserve the canonical attempt fingerprint")
	}

	authorityRoot := filepath.Join(t.TempDir(), "durable-authority-root")
	_, pinned, err := ingest.LocalFSAttemptSourceFingerprintAtRoot(
		ctx, localfs.New("localfs"), readRoot, authorityRoot, at,
	)
	if err != nil {
		t.Fatal(err)
	}
	if pinned == wrapper {
		t.Fatal("authority-root pinning did not participate in the attempt fingerprint")
	}

	otherAuthorityRoot := authorityRoot + "-other"
	_, otherPinned, err := ingest.LocalFSAttemptSourceFingerprintAtRoot(
		ctx, localfs.New("localfs"), readRoot, otherAuthorityRoot, at,
	)
	if err != nil {
		t.Fatal(err)
	}
	if otherPinned == pinned {
		t.Fatal("distinct authority roots produced the same attempt fingerprint")
	}
}
