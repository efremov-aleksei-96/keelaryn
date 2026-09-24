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

func TestSnapshotRenameIsSameProviderObject(t *testing.T) {
	root := t.TempDir()
	oldPath := filepath.Join(root, "before.txt")
	newPath := filepath.Join(root, "after.txt")
	mustWrite(t, oldPath, []byte("same bytes"))

	p := localfs.New("localfs-test")
	before, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(oldPath, newPath); err != nil {
		t.Fatal(err)
	}
	after, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	same, err := before.SameProviderObject("before.txt", after, "after.txt")
	if err != nil {
		t.Fatal(err)
	}
	if !same {
		t.Fatal("rename lost physical provider-object continuity")
	}
}

func TestSnapshotByteIdenticalCopyIsDifferentProviderObject(t *testing.T) {
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	copyPath := filepath.Join(root, "copy.bin")
	content := []byte("identical content")
	mustWrite(t, original, content)

	p := localfs.New("localfs-test")
	before, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	mustWrite(t, copyPath, content)
	after, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	same, err := before.SameProviderObject("original.bin", after, "copy.bin")
	if err != nil {
		t.Fatal(err)
	}
	if same {
		t.Fatal("byte-identical copy collapsed into original provider object")
	}
}

func TestSnapshotHardLinkIsSameProviderObjectWithAnotherLocator(t *testing.T) {
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	link := filepath.Join(root, "hardlink.bin")
	mustWrite(t, original, []byte("one object"))

	if err := os.Link(original, link); err != nil {
		t.Skipf("hard links unavailable on this filesystem: %v", err)
	}

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	same, err := snapshot.SameProviderObject("original.bin", snapshot, "hardlink.bin")
	if err != nil {
		t.Fatal(err)
	}
	if !same {
		t.Fatal("hard-link locators were not recognized as the same provider object")
	}
}

func TestSnapshotObjectGroupsSeparateObjectFromLocators(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "root")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}

	original := filepath.Join(root, "original.bin")
	hardlink := filepath.Join(root, "hardlink.bin")
	copyPath := filepath.Join(root, "copy.bin")
	symlink := filepath.Join(root, "symlink.bin")
	content := []byte("same bytes")
	mustWrite(t, original, content)
	mustWrite(t, copyPath, content)

	if err := os.Link(original, hardlink); err != nil {
		t.Skipf("hard links unavailable on this filesystem: %v", err)
	}
	symlinkCreated := os.Symlink(original, symlink) == nil

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	groups := snapshot.ObjectGroups()
	if len(groups) != 2 {
		t.Fatalf("groups=%d, want 2: %#v", len(groups), groups)
	}

	got := make([][]string, len(groups))
	for i, group := range groups {
		for _, locator := range group.Locators {
			got[i] = append(got[i], locator.Path)
			if symlinkCreated && locator.Path == "symlink.bin" {
				t.Fatal("symlink inherited target provider-object group")
			}
		}
	}
	want := [][]string{
		{"copy.bin"},
		{"hardlink.bin", "original.bin"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("groups=%#v, want %#v", got, want)
	}
}

func TestCompareObjectGroupsRenameIsEvidenceNotAutomaticMerge(t *testing.T) {
	root := t.TempDir()
	beforePath := filepath.Join(root, "before.txt")
	afterPath := filepath.Join(root, "after.txt")
	mustWrite(t, beforePath, []byte("same bytes"))

	p := localfs.New("localfs-test")
	before, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	beforeGroups := before.ObjectGroups()
	if len(beforeGroups) != 1 {
		t.Fatalf("before groups=%d, want 1", len(beforeGroups))
	}

	if err := os.Rename(beforePath, afterPath); err != nil {
		t.Fatal(err)
	}
	after, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	afterGroups := after.ObjectGroups()
	if len(afterGroups) != 1 {
		t.Fatalf("after groups=%d, want 1", len(afterGroups))
	}

	evidence, err := localfs.CompareObjectGroups(before, beforeGroups[0], after, afterGroups[0])
	if err != nil {
		t.Fatal(err)
	}
	if evidence.Kind != corpus.ContinuityNativeIdentityMatch {
		t.Fatalf("kind=%q, want %q", evidence.Kind, corpus.ContinuityNativeIdentityMatch)
	}
	if evidence.AutomaticMergeAllowed {
		t.Fatal("native file identity must not auto-authorize Artifact merge")
	}
	if !reflect.DeepEqual(pathsFromLocators(evidence.PreviousLocators), []string{"before.txt"}) {
		t.Fatalf("previous locators=%#v", evidence.PreviousLocators)
	}
	if !reflect.DeepEqual(pathsFromLocators(evidence.CurrentLocators), []string{"after.txt"}) {
		t.Fatalf("current locators=%#v", evidence.CurrentLocators)
	}
}

func TestCompareObjectGroupsCopyIsMismatchEvidence(t *testing.T) {
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	copyPath := filepath.Join(root, "copy.bin")
	content := []byte("identical bytes")
	mustWrite(t, original, content)

	p := localfs.New("localfs-test")
	before, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	mustWrite(t, copyPath, content)
	after, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}

	beforeGroup := groupContaining(t, before.ObjectGroups(), "original.bin")
	copyGroup := groupContaining(t, after.ObjectGroups(), "copy.bin")
	evidence, err := localfs.CompareObjectGroups(before, beforeGroup, after, copyGroup)
	if err != nil {
		t.Fatal(err)
	}
	if evidence.Kind != corpus.ContinuityNativeIdentityMismatch {
		t.Fatalf("kind=%q, want %q", evidence.Kind, corpus.ContinuityNativeIdentityMismatch)
	}
	if evidence.AutomaticMergeAllowed {
		t.Fatal("mismatch evidence cannot authorize merge")
	}
}

func groupContaining(t *testing.T, groups []localfs.ObjectGroup, path string) localfs.ObjectGroup {
	t.Helper()
	for _, group := range groups {
		for _, locator := range group.Locators {
			if locator.Path == path {
				return group
			}
		}
	}
	t.Fatalf("group containing %q not found in %#v", path, groups)
	return localfs.ObjectGroup{}
}

func pathsFromLocators(locators []corpus.Locator) []string {
	out := make([]string, len(locators))
	for i := range locators {
		out[i] = locators[i].Path
	}
	return out
}

func TestSnapshotSymlinkHasNoRegularFileIdentityEvidence(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "root")
	outside := filepath.Join(base, "outside.txt")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, outside, []byte("outside"))

	link := filepath.Join(root, "link")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink unavailable on this platform: %v", err)
	}

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	_, err = snapshot.SameProviderObject("link", snapshot, "link")
	if !errors.Is(err, localfs.ErrIdentityEvidenceAbsent) {
		t.Fatalf("error=%v, want ErrIdentityEvidenceAbsent", err)
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

func TestSnapshotUnknownLocatorFailsClosed(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "known.txt"), []byte("x"))

	p := localfs.New("localfs-test")
	snapshot, err := p.Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	_, err = snapshot.SameProviderObject("missing.txt", snapshot, "known.txt")
	if !errors.Is(err, localfs.ErrLocatorNotObserved) {
		t.Fatalf("error=%v, want ErrLocatorNotObserved", err)
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
