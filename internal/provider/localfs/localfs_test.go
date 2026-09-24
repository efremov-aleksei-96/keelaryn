package localfs_test

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestDiscoverIsDeterministicAndNested(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "z.txt"), []byte("z"))
	mustWrite(t, filepath.Join(root, "a.txt"), []byte("a"))
	if err := os.MkdirAll(filepath.Join(root, "nested"), 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(root, "nested", "b.txt"), []byte("b"))

	p := localfs.New("localfs-test")
	first, err := p.Discover(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	second, err := p.Discover(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	got := paths(first)
	want := []string{"a.txt", "nested/b.txt", "z.txt"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("paths = %#v, want %#v", got, want)
	}
	if !reflect.DeepEqual(first, second) {
		t.Fatalf("repeat scan differs:\nfirst=%#v\nsecond=%#v", first, second)
	}

	for _, observation := range first {
		if observation.ProviderObject.ID != "" {
			t.Fatalf("invented provider object identity from locator: %#v", observation)
		}
		if observation.ProviderObject.IdentityState != corpus.ObjectIdentityUnresolved {
			t.Fatalf("identity state = %q, want UNRESOLVED", observation.ProviderObject.IdentityState)
		}
	}
}

func TestDiscoverDoesNotFollowSymlink(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "root")
	outside := filepath.Join(base, "outside")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(outside, "secret.txt"), []byte("outside"))

	link := filepath.Join(root, "outside-link")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink unavailable on this platform: %v", err)
	}

	p := localfs.New("localfs-test")
	observations, err := p.Discover(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if len(observations) != 1 {
		t.Fatalf("observations = %d, want 1: %#v", len(observations), observations)
	}
	if observations[0].Locator.Path != "outside-link" {
		t.Fatalf("path = %q", observations[0].Locator.Path)
	}
	if observations[0].Kind != corpus.EntrySymlink {
		t.Fatalf("kind = %q, want %q", observations[0].Kind, corpus.EntrySymlink)
	}
}

func TestDiscoverDoesNotMutateContent(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "evidence.bin")
	content := []byte{0, 1, 2, 3, 4, 5}
	mustWrite(t, path, content)

	fixed := time.Date(2026, 9, 24, 12, 0, 0, 0, time.UTC)
	if err := os.Chtimes(path, fixed, fixed); err != nil {
		t.Fatal(err)
	}
	before, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}

	p := localfs.New("localfs-test")
	if _, err := p.Discover(context.Background(), root); err != nil {
		t.Fatal(err)
	}

	afterContent, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	after, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}

	if !bytes.Equal(afterContent, content) {
		t.Fatalf("content changed: %v", afterContent)
	}
	if !after.ModTime().Equal(before.ModTime()) {
		t.Fatalf("mtime changed: before=%v after=%v", before.ModTime(), after.ModTime())
	}
	if after.Size() != before.Size() {
		t.Fatalf("size changed: before=%d after=%d", before.Size(), after.Size())
	}
}

func TestDiscoverRejectsNonDirectoryRoot(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "single.txt")
	mustWrite(t, path, []byte("x"))

	p := localfs.New("localfs-test")
	_, err := p.Discover(context.Background(), path)
	if !errors.Is(err, localfs.ErrRootNotDirectory) {
		t.Fatalf("error = %v, want ErrRootNotDirectory", err)
	}
}

func paths(observations []corpus.Observation) []string {
	out := make([]string, len(observations))
	for i := range observations {
		out[i] = observations[i].Locator.Path
	}
	return out
}

func mustWrite(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
}
