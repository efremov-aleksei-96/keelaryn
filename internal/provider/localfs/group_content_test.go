package localfs_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestSampleObjectGroupContentHashesOneHardLinkedObject(t *testing.T) {
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	hardlink := filepath.Join(root, "hardlink.bin")
	mustWrite(t, original, []byte("abc"))
	if err := os.Link(original, hardlink); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}

	snapshot, err := localfs.New("localfs").Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	groups := snapshot.ObjectGroups()
	if len(groups) != 1 {
		t.Fatalf("groups=%d, want 1", len(groups))
	}

	sample, err := snapshot.SampleObjectGroupContent(context.Background(), groups[0])
	if err != nil {
		t.Fatal(err)
	}
	if sample.Evidence.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("digest=%q", sample.Evidence.Digest)
	}
	if sample.Evidence.Size != 3 {
		t.Fatalf("size=%d, want 3", sample.Evidence.Size)
	}
}

func TestSampleObjectGroupContentRejectsChangedHardLinkGroup(t *testing.T) {
	root := t.TempDir()
	original := filepath.Join(root, "original.bin")
	hardlink := filepath.Join(root, "hardlink.bin")
	mustWrite(t, original, []byte("old"))
	if err := os.Link(original, hardlink); err != nil {
		t.Skipf("hard links unavailable: %v", err)
	}

	snapshot, err := localfs.New("localfs").Snapshot(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	group := snapshot.ObjectGroups()[0]

	if err := os.Remove(hardlink); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, hardlink, []byte("replacement"))

	_, err = snapshot.SampleObjectGroupContent(context.Background(), group)
	if !errors.Is(err, localfs.ErrObservedGroupChanged) {
		t.Fatalf("error=%v, want ErrObservedGroupChanged", err)
	}
}
