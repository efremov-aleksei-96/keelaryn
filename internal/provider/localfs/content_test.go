package localfs_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestSnapshotContentEvidenceSHA256(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "abc.txt"), []byte("abc"))

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	got, err := snapshot.ContentEvidence(context.Background(), "abc.txt")
	if err != nil {
		t.Fatal(err)
	}
	if got.Algorithm != corpus.ContentAlgorithmSHA256 {
		t.Fatalf("algorithm=%q", got.Algorithm)
	}
	if got.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("digest=%q", got.Digest)
	}
	if got.Size != 3 {
		t.Fatalf("size=%d, want 3", got.Size)
	}
}

func TestSnapshotContentEvidenceAllowsContentChangeOnSameProviderObject(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	mustWrite(t, path, []byte("A"))

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	mustWrite(t, path, []byte("B"))
	got, err := snapshot.ContentEvidence(context.Background(), "file.txt")
	if err != nil {
		t.Fatal(err)
	}
	if got.Size != 1 {
		t.Fatalf("size=%d, want 1", got.Size)
	}
}

func TestSnapshotContentEvidenceRejectsReplacementAtSameLocator(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	mustWrite(t, path, []byte("old"))

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, path, []byte("new"))

	_, err = snapshot.ContentEvidence(context.Background(), "file.txt")
	if !errors.Is(err, localfs.ErrObservedObjectChanged) {
		t.Fatalf("error=%v, want ErrObservedObjectChanged", err)
	}
}

func TestSnapshotContentEvidenceRejectsSymlinkIdentity(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "root")
	target := filepath.Join(base, "target.txt")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, target, []byte("target"))
	if err := os.Symlink(target, filepath.Join(root, "link")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	_, err = snapshot.ContentEvidence(context.Background(), "link")
	if !errors.Is(err, localfs.ErrIdentityEvidenceAbsent) {
		t.Fatalf("error=%v, want ErrIdentityEvidenceAbsent", err)
	}
}

func TestSnapshotContentEvidenceHonorsCanceledContext(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("content"))

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = snapshot.ContentEvidence(ctx, "file.txt")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error=%v, want context.Canceled", err)
	}
}
