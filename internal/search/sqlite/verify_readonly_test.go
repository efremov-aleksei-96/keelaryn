package sqlite_test

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	"github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestVerifyReadOnlyPreservesSearchDatabaseBytes(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := sqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	if err := sqlite.VerifyReadOnly(ctx, path); err != nil {
		t.Fatal(err)
	}

	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("read-only search verification changed database bytes")
	}
}

func TestVerifyReadOnlyMissingSearchDoesNotCreateDatabase(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.db")
	if err := sqlite.VerifyReadOnly(context.Background(), path); err == nil {
		t.Fatal("missing search database unexpectedly verified")
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("read-only verification created missing search database: %v", err)
	}
}

func TestVerifyReadOnlyDoesNotCompletePendingSecurityUpgrade(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := sqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}

	conn, err := zsqlite.OpenConn(path, zsqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn, "UPDATE search_security_upgrade SET vacuum_pending=1 WHERE id=1", nil); err != nil {
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

	if err := sqlite.VerifyReadOnly(ctx, path); err == nil {
		t.Fatal("read-only verification repaired pending search security upgrade")
	}
	after, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("read-only search verification changed pending-upgrade database")
	}
}

func TestVerifyReadOnlyDetectsFTSDriftWithoutChangingSource(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "search.db")
	index, err := sqlite.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	result := searchExtraction("art-doctor", "rev-doctor", "doctor fts drift token")
	if err := index.ReplaceAll(ctx, revisionsFor([]extract.Result{result}), []extract.Result{result}); err != nil {
		index.Close()
		t.Fatal(err)
	}
	if err := index.Close(); err != nil {
		t.Fatal(err)
	}

	conn, err := zsqlite.OpenConn(path, zsqlite.OpenReadWrite)
	if err != nil {
		t.Fatal(err)
	}
	var rowID int64
	var textValue string
	if err := sqlitex.Execute(conn,
		"SELECT document_id, text FROM search_documents WHERE artifact_id='art-doctor'",
		&sqlitex.ExecOptions{ResultFunc: func(stmt *zsqlite.Stmt) error {
			rowID = stmt.ColumnInt64(0)
			textValue = stmt.ColumnText(1)
			return nil
		}}); err != nil {
		conn.Close()
		t.Fatal(err)
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO search_documents_fts(search_documents_fts, rowid, text) VALUES('delete', ?1, ?2)",
		&sqlitex.ExecOptions{Args: []any{rowID, textValue}}); err != nil {
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

	if err := sqlite.VerifyReadOnly(ctx, path); err == nil {
		t.Fatal("read-only verification accepted FTS drift")
	}
	after, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("FTS verification changed source search database")
	}
}
