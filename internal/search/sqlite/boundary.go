package sqlite

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitex"
)

var (
	ErrInvalidSourceBoundary  = errors.New("invalid search source boundary")
	ErrSourceBoundaryMismatch = errors.New("search cache source boundary mismatch")
)

type SourceBoundary struct {
	ProviderID         corpus.ProviderID
	Root               string
	ScanID             corpus.ScanSessionID
	StartedAt          time.Time
	FingerprintVersion string
	FingerprintSHA256  string
}

func validateSourceBoundary(boundary SourceBoundary) error {
	if boundary.ProviderID == "" ||
		strings.TrimSpace(boundary.Root) == "" ||
		boundary.ScanID == "" ||
		boundary.StartedAt.IsZero() ||
		strings.TrimSpace(boundary.FingerprintVersion) == "" ||
		len(boundary.FingerprintSHA256) != 64 ||
		boundary.FingerprintSHA256 != strings.ToLower(boundary.FingerprintSHA256) {
		return ErrInvalidSourceBoundary
	}
	if _, err := hex.DecodeString(boundary.FingerprintSHA256); err != nil {
		return ErrInvalidSourceBoundary
	}
	return nil
}

func replaceSourceBoundaryConn(conn *zsqlite.Conn, boundary *SourceBoundary) error {
	if err := sqlitex.Execute(conn, "DELETE FROM search_source_boundary", nil); err != nil {
		return fmt.Errorf("clear search source boundary: %w", err)
	}
	if boundary == nil {
		return nil
	}
	if err := validateSourceBoundary(*boundary); err != nil {
		return err
	}
	if err := sqlitex.Execute(conn, `
INSERT INTO search_source_boundary (
	id, provider_id, root, scan_id, started_at, fingerprint_version, fingerprint_sha256
) VALUES (1, ?1, ?2, ?3, ?4, ?5, ?6)
`, &sqlitex.ExecOptions{Args: []any{
		string(boundary.ProviderID),
		boundary.Root,
		string(boundary.ScanID),
		boundary.StartedAt.UTC().Format(time.RFC3339Nano),
		boundary.FingerprintVersion,
		boundary.FingerprintSHA256,
	}}); err != nil {
		return fmt.Errorf("write search source boundary: %w", err)
	}
	return nil
}

func sourceBoundaryConn(conn *zsqlite.Conn) (SourceBoundary, bool, error) {
	var out SourceBoundary
	var startedAtText string
	var found bool
	if err := sqlitex.Execute(conn, `
SELECT provider_id, root, scan_id, started_at, fingerprint_version, fingerprint_sha256
FROM search_source_boundary
WHERE id=1
`, &sqlitex.ExecOptions{ResultFunc: func(stmt *zsqlite.Stmt) error {
		if found {
			return fmt.Errorf("%w: multiple rows", ErrInvalidSourceBoundary)
		}
		found = true
		out.ProviderID = corpus.ProviderID(stmt.ColumnText(0))
		out.Root = stmt.ColumnText(1)
		out.ScanID = corpus.ScanSessionID(stmt.ColumnText(2))
		startedAtText = stmt.ColumnText(3)
		out.FingerprintVersion = stmt.ColumnText(4)
		out.FingerprintSHA256 = stmt.ColumnText(5)
		return nil
	}}); err != nil {
		return SourceBoundary{}, false, fmt.Errorf("read search source boundary: %w", err)
	}
	if !found {
		return SourceBoundary{}, false, nil
	}
	startedAt, err := time.Parse(time.RFC3339Nano, startedAtText)
	if err != nil {
		return SourceBoundary{}, false, fmt.Errorf("%w: started_at: %v", ErrInvalidSourceBoundary, err)
	}
	out.StartedAt = startedAt.UTC()
	if err := validateSourceBoundary(out); err != nil {
		return SourceBoundary{}, false, err
	}
	return out, true, nil
}

func sameSourceBoundary(a, b SourceBoundary) bool {
	return a.ProviderID == b.ProviderID &&
		a.Root == b.Root &&
		a.ScanID == b.ScanID &&
		a.StartedAt.Equal(b.StartedAt) &&
		a.FingerprintVersion == b.FingerprintVersion &&
		a.FingerprintSHA256 == b.FingerprintSHA256
}

func (i *Index) VerifySourceBoundary(ctx context.Context, expected SourceBoundary) error {
	if i == nil || i.pool == nil {
		return ErrInvalidSourceBoundary
	}
	if err := validateSourceBoundary(expected); err != nil {
		return err
	}
	conn, err := i.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get search connection: %w", err)
	}
	defer i.pool.Put(conn)
	got, found, err := sourceBoundaryConn(conn)
	if err != nil {
		return err
	}
	if !found || !sameSourceBoundary(got, expected) {
		return ErrSourceBoundaryMismatch
	}
	return nil
}
