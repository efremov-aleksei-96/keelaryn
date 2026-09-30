package doctor_test

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

func TestDoctorPassesAndDoesNotModifyProtectedControlState(t *testing.T) {
	root := t.TempDir()
	control := filepath.Join(t.TempDir(), "control")
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("doctor searchable content"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := localruntime.BootstrapProtectedIndex(context.Background(), localruntime.ProtectedIndexOptions{
		Root: root,
		ControlDir: control,
		ObservedAt: time.Date(2026, 9, 30, 9, 0, 0, 0, time.UTC),
		MaxBytes: 4096,
	}); err != nil {
		t.Fatal(err)
	}
	before := snapshotDir(t, control)

	report := doctor.Run(context.Background(), control)
	if !report.Passed() {
		t.Fatalf("report=%#v", report)
	}
	after := snapshotDir(t, control)
	if len(before) != len(after) {
		t.Fatalf("control entries changed: before=%v after=%v", mapKeys(before), mapKeys(after))
	}
	for name, want := range before {
		if got, ok := after[name]; !ok || !bytes.Equal(want, got) {
			t.Fatalf("control file %s changed during Doctor", name)
		}
	}
}

func TestDoctorMissingControlDoesNotCreateState(t *testing.T) {
	control := filepath.Join(t.TempDir(), "missing")
	report := doctor.Run(context.Background(), control)
	if report.Passed() {
		t.Fatalf("missing control unexpectedly passed: %#v", report)
	}
	if _, err := os.Stat(control); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("Doctor created missing control directory: %v", err)
	}
}

func snapshotDir(t *testing.T, dir string) map[string][]byte {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	out := make(map[string][]byte, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			t.Fatalf("unexpected directory in control state: %s", entry.Name())
		}
		data, err := os.ReadFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		out[entry.Name()] = data
	}
	return out
}

func mapKeys(m map[string][]byte) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
