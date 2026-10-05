package sqlitestate

import (
	"context"
	"fmt"
	"path/filepath"

	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

// VerifyReadOnly validates an existing authoritative state database without
// creating, migrating, repairing, or otherwise writing durable state.
func VerifyReadOnly(ctx context.Context, path string) error {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("resolve state database path: %w", err)
	}
	conn, err := zsqlite.OpenConn(absPath, zsqlite.OpenReadOnly)
	if err != nil {
		return fmt.Errorf("open Keelaryn state store read-only: %w", err)
	}
	defer conn.Close()
	oldInterrupt := conn.SetInterrupt(ctx.Done())
	defer conn.SetInterrupt(oldInterrupt)

	if err := sqlitex.ExecuteTransient(conn, "PRAGMA query_only = ON;", nil); err != nil {
		return fmt.Errorf("enable state query-only mode: %w", err)
	}
	if err := requireReadOnlyApplicationIDConn(conn); err != nil {
		return err
	}
	if err := requireExactSchemaVersionConn(conn); err != nil {
		return err
	}

	// Store.prepareConn only configures connection-local PRAGMAs/UDFs and
	// authorization state. The underlying SQLite handle remains read-only and
	// query_only, so integrity checks can evaluate Keelaryn schema functions
	// without opening a write path.
	verificationStore := &Store{path: absPath}
	if err := verificationStore.prepareConn(conn); err != nil {
		return fmt.Errorf("prepare read-only state verification connection: %w", err)
	}

	if err := verifyReadOnlySQLiteIntegrityConn(conn); err != nil {
		return err
	}
	if err := verifyReadOnlyForeignKeysConn(conn); err != nil {
		return err
	}
	if err := verifyRemoteHistoryHistoricalAuthorityConn(conn); err != nil {
		return fmt.Errorf("verify RemoteHistory authority: %w", err)
	}
	if err := verifyGoogleDriveHistoricalAuthorityConn(conn); err != nil {
		return fmt.Errorf("verify Google Drive authority: %w", err)
	}
	if err := verifyHistoricalCoreIdentityAuthorityConn(conn); err != nil {
		return fmt.Errorf("verify core identity authority: %w", err)
	}
	if err := verifyLocalAttemptHistoricalAuthorityConn(conn); err != nil {
		return fmt.Errorf("verify LocalFS attempt authority: %w", err)
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
		return fmt.Errorf("read state application_id: %w", err)
	}
	if got != int64(applicationID) {
		return fmt.Errorf("state application_id mismatch: database=%d binary=%d", got, applicationID)
	}
	return nil
}

func verifyReadOnlySQLiteIntegrityConn(conn *zsqlite.Conn) error {
	seen := false
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA integrity_check;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			seen = true
			if got := stmt.ColumnText(0); got != "ok" {
				return fmt.Errorf("state SQLite integrity_check: %s", got)
			}
			return nil
		},
	}); err != nil {
		return fmt.Errorf("state SQLite integrity_check: %w", err)
	}
	if !seen {
		return fmt.Errorf("state SQLite integrity_check returned no result")
	}
	return nil
}

func verifyReadOnlyForeignKeysConn(conn *zsqlite.Conn) error {
	return sqlitex.ExecuteTransient(conn, "PRAGMA foreign_key_check;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			return fmt.Errorf(
				"state foreign_key_check: table=%s rowid=%s parent=%s fk=%s",
				stmt.ColumnText(0), stmt.ColumnText(1), stmt.ColumnText(2), stmt.ColumnText(3),
			)
		},
	})
}
