package sqlitestate_test

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestVerifyReadOnlyPreservesStateDatabaseBytes(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	if err := sqlitestate.VerifyReadOnly(ctx, path); err != nil {
		t.Fatal(err)
	}

	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("read-only state verification changed database bytes")
	}
}

func TestVerifyReadOnlyMissingStateDoesNotCreateDatabase(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.db")
	if err := sqlitestate.VerifyReadOnly(context.Background(), path); err == nil {
		t.Fatal("missing state database unexpectedly verified")
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("read-only verification created missing state database: %v", err)
	}
}

func TestVerifyReadOnlyRejectsOldSchemaWithoutMigration(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "state.db")
	store, err := sqlitestate.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	conn, err := sqlite.OpenConn(path, sqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	var current int64
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA user_version;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *sqlite.Stmt) error {
			current = stmt.ColumnInt64(0)
			return nil
		},
	}); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if current < 2 {
		conn.Close()
		t.Fatalf("unexpected current state schema %d", current)
	}
	old := current - 1
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA user_version = "+fmt.Sprint(old)+";", nil); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	err = sqlitestate.VerifyReadOnly(ctx, path)
	if !errors.Is(err, sqlitestate.ErrUnsupportedSchemaVersion) {
		t.Fatalf("error=%v want ErrUnsupportedSchemaVersion", err)
	}
	after, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("read-only state verification migrated or otherwise changed old schema database")
	}
}
