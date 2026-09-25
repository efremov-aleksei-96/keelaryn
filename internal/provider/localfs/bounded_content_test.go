package localfs_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/provider/localfs"
)

func TestReadBoundedRegularFileReturnsBytesAndEvidenceFromSameRead(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "abc.txt"), []byte("abc"))
	got, err := localfs.New("localfs-test").ReadBoundedRegularFile(context.Background(), root, "abc.txt", 3)
	if err != nil {
		t.Fatal(err)
	}
	if string(got.Bytes) != "abc" || got.Evidence.Size != 3 ||
		got.Evidence.Digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("sample=%#v bytes=%q", got.ContentSample, got.Bytes)
	}
}

func TestReadBoundedRegularFileRejectsOverLimitBeforeReturningBytes(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "large.txt"), []byte("12345"))
	got, err := localfs.New("localfs-test").ReadBoundedRegularFile(context.Background(), root, "large.txt", 4)
	if !errors.Is(err, localfs.ErrContentLimitExceeded) {
		t.Fatalf("error=%v, want ErrContentLimitExceeded", err)
	}
	if len(got.Bytes) != 0 {
		t.Fatalf("limit failure returned bytes: %q", got.Bytes)
	}
}

func TestReadBoundedRegularFileRejectsNegativeLimit(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "file.txt"), []byte("x"))
	_, err := localfs.New("localfs-test").ReadBoundedRegularFile(context.Background(), root, "file.txt", -1)
	if !errors.Is(err, localfs.ErrInvalidContentLimit) {
		t.Fatalf("error=%v, want ErrInvalidContentLimit", err)
	}
}
