package sqlite

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

// VerifyReadOnly validates an existing derived search database without
// creating, migrating, repairing, vacuuming, or writing the source database.
// FTS5's special integrity-check command is write-shaped, so it runs only
// against an ephemeral on-disk SQLite backup of the read-only source. This
// keeps memory bounded by SQLite page buffers rather than full index size.
func VerifyReadOnly(ctx context.Context, path string) error {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("resolve search database path: %w", err)
	}
	src, err := zsqlite.OpenConn(absPath, zsqlite.OpenReadOnly)
	if err != nil {
		return fmt.Errorf("open Keelaryn search index read-only: %w", err)
	}
	defer src.Close()
	oldInterrupt := src.SetInterrupt(ctx.Done())
	defer src.SetInterrupt(oldInterrupt)

	// Runtime search connections always enable secure_delete. This PRAGMA is
	// connection-local; applying it to a read-only handle does not modify the
	// database file.
	if err := sqlitex.ExecuteTransient(src, "PRAGMA secure_delete = ON;", nil); err != nil {
		return fmt.Errorf("configure read-only search secure_delete: %w", err)
	}
	if err := sqlitex.ExecuteTransient(src, "PRAGMA query_only = ON;", nil); err != nil {
		return fmt.Errorf("enable search query-only mode: %w", err)
	}
	if err := requireReadOnlyApplicationIDConn(src); err != nil {
		return err
	}
	if err := requireExactSchemaVersionConn(src); err != nil {
		return err
	}
	if err := verifySearchSecurityPolicyConn(src); err != nil {
		return fmt.Errorf("verify search security policy: %w", err)
	}
	if err := verifyReadOnlySQLiteIntegrityConn(src); err != nil {
		return err
	}
	if err := verifyReadOnlyForeignKeysConn(src); err != nil {
		return err
	}
	if err := verifyFTSOnScratchBackup(ctx, src); err != nil {
		return err
	}
	return nil
}

func requireReadOnlyApplicationIDConn(conn *zsqlite.Conn) error {
	var got int64
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA application_id;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			got = stmt.ColumnInt64(0)
			return nil
		},
	}); err != nil {
		return fmt.Errorf("read search application_id: %w", err)
	}
	if got != int64(applicationID) {
		return fmt.Errorf("search application_id mismatch: database=%d binary=%d", got, applicationID)
	}
	return nil
}

func verifyReadOnlySQLiteIntegrityConn(conn *zsqlite.Conn) error {
	seen := false
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA integrity_check;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			seen = true
			if got := stmt.ColumnText(0); got != "ok" {
				return fmt.Errorf("search SQLite integrity_check: %s", got)
			}
			return nil
		},
	}); err != nil {
		return fmt.Errorf("search SQLite integrity_check: %w", err)
	}
	if !seen {
		return fmt.Errorf("search SQLite integrity_check returned no result")
	}
	return nil
}

func verifyReadOnlyForeignKeysConn(conn *zsqlite.Conn) error {
	return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_key_check;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			return fmt.Errorf(
				"search foreign_key_check: table=%s rowid=%s parent=%s fk=%s",
				stmt.ColumnText(0), stmt.ColumnText(1), stmt.ColumnText(2), stmt.ColumnText(3),
			)
		},
	})
}

func verifyFTSOnScratchBackup(ctx context.Context, src *zsqlite.Conn) error {
	dir, err := controlstorage.CreateProtectedTempDir("keelaryn-search-verify-")
	if err != nil {
		return fmt.Errorf("create protected search verification scratch directory: %w", err)
	}
	defer os.RemoveAll(dir)

	dstPath := filepath.Join(dir, "search.db")
	dst, err := zsqlite.OpenConn(dstPath, zsqlite.OpenReadWrite|zsqlite.OpenCreate)
	if err != nil {
		return fmt.Errorf("open scratch search verification copy: %w", err)
	}
	defer dst.Close()
	if err := controlstorage.VerifyProtectedTempFile(dstPath); err != nil {
		return fmt.Errorf("verify protected search verification scratch file: %w", err)
	}
	oldInterrupt := dst.SetInterrupt(ctx.Done())
	defer dst.SetInterrupt(oldInterrupt)

	backup, err := zsqlite.NewBackup(dst, "main", src, "main")
	if err != nil {
		return fmt.Errorf("start scratch search backup: %w", err)
	}
	defer backup.Close()

	for {
		more, err := backup.Step(256)
		if err != nil {
			return fmt.Errorf("copy search database for FTS verification: %w", err)
		}
		if !more {
			break
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
	}
	if err := integrityCheckConn(dst); err != nil {
		return fmt.Errorf("verify FTS5 search index on scratch copy: %w", err)
	}
	return nil
}
