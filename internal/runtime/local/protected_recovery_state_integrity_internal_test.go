package local

import (
	"bytes"
	"context"
	"os"
	"strings"
	"testing"

	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestProtectedRecoveryRejectsUnrelatedStateForeignKeyDamageBeforeSearchMutation(t *testing.T) {
	ctx := context.Background()
	_, _, options, layout := newProtectedRecoveryFixture(t, "state verification must precede recovery", 25)

	activeBefore, err := os.ReadFile(layout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(layout.SearchStagingDB, activeBefore, 0o600); err != nil {
		t.Fatal(err)
	}
	stagingBefore, err := os.ReadFile(layout.SearchStagingDB)
	if err != nil {
		t.Fatal(err)
	}

	dropRemoteHistoryParentForForeignKeyCorruption(t, layout.StateDB)
	stateBefore, err := os.ReadFile(layout.StateDB)
	if err != nil {
		t.Fatal(err)
	}

	_, err = bootstrapProtectedIndex(ctx, options, defaultProtectedSearchRecoveryOps())
	if err == nil {
		t.Fatal("protected search recovery succeeded with unrelated state foreign-key damage")
	}
	if !strings.Contains(err.Error(), "remote_history_generations") {
		t.Fatalf("error=%v does not identify the damaged state authority", err)
	}

	activeAfter, err := os.ReadFile(layout.SearchDB)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(activeBefore, activeAfter) {
		t.Fatal("active derived search cache changed before state verification rejected recovery")
	}
	stagingAfter, err := os.ReadFile(layout.SearchStagingDB)
	if err != nil {
		t.Fatalf("staged derived cache was removed before state verification rejected recovery: %v", err)
	}
	if !bytes.Equal(stagingBefore, stagingAfter) {
		t.Fatal("staged derived search cache changed before state verification rejected recovery")
	}
	stateAfter, err := os.ReadFile(layout.StateDB)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(stateBefore, stateAfter) {
		t.Fatal("authoritative state changed while rejecting recovery")
	}
}

func dropRemoteHistoryParentForForeignKeyCorruption(t *testing.T, statePath string) {
	t.Helper()

	conn, err := sqlite.OpenConn(statePath, sqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA foreign_keys = OFF;", nil); err != nil {
		_ = conn.Close()
		t.Fatal(err)
	}
	if err := sqlitex.ExecuteTransient(conn, "DROP TABLE remote_history_generations;", nil); err != nil {
		_ = conn.Close()
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}
}
