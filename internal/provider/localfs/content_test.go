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

func TestReadContentEvidenceSHA256(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "abc.txt"), []byte("abc"))

	p := localfs.New("localfs-test")
	got, err := p.ReadContentEvidence(context.Background(), root, "abc.txt")
	if err != nil {
		t.Fatal(err)
	}
	if got.Evidence.Algorithm != corpus.ContentAlgorithmSHA256 {
		t.Fatalf("algorithm=%q", got.Evidence.Algorithm)
	}
	if got.Evidence.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("digest=%q", got.Evidence.Digest)
	}
	if got.Evidence.Size != 3 || got.Observation.Size != 3 {
		t.Fatalf("sizes evidence=%d observation=%d", got.Evidence.Size, got.Observation.Size)
	}
	if got.Observation.Locator.Path != "abc.txt" {
		t.Fatalf("path=%q", got.Observation.Locator.Path)
	}
	if got.Observation.ProviderObject.ID != "" {
		t.Fatalf("content sample invented ProviderObject ID: %#v", got.Observation.ProviderObject)
	}
}

func TestReadContentEvidenceSamplesReplacementAsNewObservation(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "file.txt")
	mustWrite(t, path, []byte("old"))

	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, path, []byte("new"))

	p := localfs.New("localfs-test")
	got, err := p.ReadContentEvidence(context.Background(), root, "file.txt")
	if err != nil {
		t.Fatal(err)
	}
	if got.Evidence.Digest != "11507a0e2f5e69d5dfa40a62a1bd7b6ee57e6bcd85c67c9b8431b36fff21c437" {
		t.Fatalf("digest=%q, want digest of current bytes", got.Evidence.Digest)
	}
}

func TestReadContentEvidenceRejectsSymlink(t *testing.T) {
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
	_, err := p.ReadContentEvidence(context.Background(), root, "link")
	if !errors.Is(err, localfs.ErrContentNotRegular) {
		t.Fatalf("error=%v, want ErrContentNotRegular", err)
	}
}

func TestReadContentEvidenceRejectsTraversal(t *testing.T) {
	root := t.TempDir()
	p := localfs.New("localfs-test")

	for _, path := range []string{"../outside", "../../outside"} {
		_, err := p.ReadContentEvidence(context.Background(), root, path)
		if !errors.Is(err, localfs.ErrInvalidContentLocator) {
			t.Fatalf("path=%q error=%v, want ErrInvalidContentLocator", path, err)
		}
	}
}

func TestReadContentEvidenceHonorsCanceledContext(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("content"))

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	p := localfs.New("localfs-test")
	_, err := p.ReadContentEvidence(ctx, root, "file.txt")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error=%v, want context.Canceled", err)
	}
}
