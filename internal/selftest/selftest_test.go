package selftest

import (
	"context"
	"os"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
)

func TestRunPassesAndRemovesDisposableWorkspace(t *testing.T) {
	parent := t.TempDir()
	report := run(context.Background(), parent)
	if !report.Passed() {
		t.Fatalf("report=%#v", report)
	}
	if report.Proof.ArtifactID == "" || report.Proof.RevisionID == "" {
		t.Fatalf("missing exact provenance: %#v", report.Proof)
	}
	if report.Proof.Reason != fixtureReason || !report.Proof.CorpusUnchanged || !report.Proof.Cleaned {
		t.Fatalf("proof=%#v", report.Proof)
	}
	entries, err := os.ReadDir(parent)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("disposable workspace leaked: %#v", entries)
	}
	for _, check := range report.Checks {
		if check.Status != doctor.StatusPass {
			t.Fatalf("check=%#v", check)
		}
	}
}
