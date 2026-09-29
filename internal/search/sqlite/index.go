package sqlite

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
	zsqlite "zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

const (
	applicationID int32 = 0x4b4c5352 // "KLSR"
	maxSearchLimit      = 100
)

var (
	ErrUnsupportedSchemaVersion = errors.New("unsupported Keelaryn search schema version")
	ErrDuplicateDocument        = errors.New("duplicate search document")
	ErrInvalidQuery             = errors.New("invalid search query")
	ErrInvalidLimit             = errors.New("invalid search result limit")
)

var schema = sqlitemigration.Schema{
	AppID: applicationID,
	Migrations: []string{
		`
CREATE TABLE search_documents (
	document_id INTEGER PRIMARY KEY,
	artifact_id TEXT NOT NULL,
	revision_id TEXT NOT NULL,
	extractor_id TEXT NOT NULL CHECK (extractor_id<>''),
	media_type TEXT NOT NULL,
	content_algorithm TEXT NOT NULL,
	content_digest TEXT NOT NULL,
	content_size INTEGER NOT NULL CHECK (content_size>=0),
	text TEXT NOT NULL,
	UNIQUE (artifact_id, revision_id, extractor_id)
) STRICT;

CREATE VIRTUAL TABLE search_documents_fts USING fts5(
	text,
	content='search_documents',
	content_rowid='document_id',
	tokenize='unicode61'
);

CREATE TRIGGER search_documents_ai
AFTER INSERT ON search_documents
BEGIN
	INSERT INTO search_documents_fts(rowid, text)
	VALUES (NEW.document_id, NEW.text);
END;

CREATE TRIGGER search_documents_ad
AFTER DELETE ON search_documents
BEGIN
	INSERT INTO search_documents_fts(search_documents_fts, rowid, text)
	VALUES ('delete', OLD.document_id, OLD.text);
END;

CREATE TRIGGER search_documents_au
AFTER UPDATE ON search_documents
BEGIN
	INSERT INTO search_documents_fts(search_documents_fts, rowid, text)
	VALUES ('delete', OLD.document_id, OLD.text);
	INSERT INTO search_documents_fts(rowid, text)
	VALUES (NEW.document_id, NEW.text);
END;
`,
	},
}

// Index owns rebuildable full-text state only. Identity/provenance authority
// remains in the separate Keelaryn state Store.
type Index struct {
	pool *sqlitemigration.Pool
	path string
}

func Open(ctx context.Context, path string) (*Index, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("resolve search database path: %w", err)
	}
	index := &Index{path: absPath}
	index.pool = sqlitemigration.NewPool(absPath, schema, sqlitemigration.Options{
		Flags:    zsqlite.OpenReadWrite | zsqlite.OpenCreate,
		PoolSize: 1,
	})
	conn, err := index.pool.Get(ctx)
	if err != nil {
		_ = index.pool.Close()
		return nil, fmt.Errorf("open Keelaryn search index: %w", err)
	}
	if err := requireExactSchemaVersionConn(conn); err != nil {
		index.pool.Put(conn)
		_ = index.pool.Close()
		return nil, fmt.Errorf("open Keelaryn search index: %w", err)
	}
	index.pool.Put(conn)
	return index, nil
}

func requireExactSchemaVersionConn(conn *zsqlite.Conn) error {
	var version int64
	if err := sqlitex.ExecuteTransient(conn, "PRAGMA user_version;", &sqlitex.ExecOptions{
		ResultFunc: func(stmt *zsqlite.Stmt) error {
			version = stmt.ColumnInt64(0)
			return nil
		},
	}); err != nil {
		return fmt.Errorf("read search schema version: %w", err)
	}
	supported := int64(len(schema.Migrations))
	if version != supported {
		return fmt.Errorf("%w: database=%d binary=%d", ErrUnsupportedSchemaVersion, version, supported)
	}
	return nil
}

func (i *Index) Close() error {
	if i == nil || i.pool == nil {
		return nil
	}
	return i.pool.Close()
}

func (i *Index) Path() string {
	if i == nil {
		return ""
	}
	return i.path
}

// ReplaceAll atomically replaces the complete derived document set. Every
// supplied extraction is first revalidated against exact immutable Revision
// authority; callers cannot persist a raw Document that bypasses provenance
// validation. A failure leaves the previous complete cache unchanged.
func (i *Index) ReplaceAll(
	ctx context.Context,
	revisions search.RevisionReader,
	results []extract.Result,
) error {
	if revisions == nil {
		return search.ErrExtractionNotIndexable
	}
	documents := make([]search.Document, 0, len(results))
	for _, result := range results {
		document, err := search.DocumentFromExtraction(ctx, revisions, result)
		if err != nil {
			return err
		}
		documents = append(documents, document)
	}
	return i.replaceAllDocuments(ctx, documents)
}

func (i *Index) replaceAllDocuments(ctx context.Context, documents []search.Document) (err error) {
	normalized, err := normalizeDocuments(documents)
	if err != nil {
		return err
	}
	conn, err := i.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get search connection: %w", err)
	}
	defer i.pool.Put(conn)

	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return fmt.Errorf("begin search replacement transaction: %w", err)
	}
	defer end(&err)

	if err := sqlitex.Execute(conn, "DELETE FROM search_documents", nil); err != nil {
		return fmt.Errorf("clear search documents: %w", err)
	}
	for _, document := range normalized {
		if err := insertDocumentConn(conn, document); err != nil {
			return err
		}
	}
	if err := integrityCheckConn(conn); err != nil {
		return err
	}
	return nil
}

func normalizeDocuments(documents []search.Document) ([]search.Document, error) {
	out := append([]search.Document(nil), documents...)
	type key struct {
		artifact  corpus.ArtifactID
		revision  corpus.RevisionID
		extractor string
	}
	seen := make(map[key]struct{}, len(out))
	for _, document := range out {
		if err := search.ValidateDocument(document); err != nil {
			return nil, err
		}
		k := key{artifact: document.ArtifactID, revision: document.RevisionID, extractor: document.ExtractorID}
		if _, exists := seen[k]; exists {
			return nil, fmt.Errorf("%w: artifact=%s revision=%s extractor=%s",
				ErrDuplicateDocument, document.ArtifactID, document.RevisionID, document.ExtractorID)
		}
		seen[k] = struct{}{}
	}
	sort.Slice(out, func(a, b int) bool {
		if out[a].ArtifactID != out[b].ArtifactID {
			return out[a].ArtifactID < out[b].ArtifactID
		}
		if out[a].RevisionID != out[b].RevisionID {
			return out[a].RevisionID < out[b].RevisionID
		}
		return out[a].ExtractorID < out[b].ExtractorID
	})
	return out, nil
}

func insertDocumentConn(conn *zsqlite.Conn, document search.Document) error {
	if err := sqlitex.Execute(conn,
		`INSERT INTO search_documents (
			artifact_id, revision_id, extractor_id, media_type,
			content_algorithm, content_digest, content_size, text
		) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`,
		&sqlitex.ExecOptions{Args: []any{
			string(document.ArtifactID), string(document.RevisionID), document.ExtractorID, document.MediaType,
			document.Evidence.Algorithm, document.Evidence.Digest, document.Evidence.Size, document.Text,
		}}); err != nil {
		return fmt.Errorf("insert search document: %w", err)
	}
	return nil
}

func (i *Index) Search(ctx context.Context, query string, limit int) ([]search.Hit, error) {
	expression, err := literalQuery(query)
	if err != nil {
		return nil, err
	}
	if limit < 1 || limit > maxSearchLimit {
		return nil, ErrInvalidLimit
	}
	conn, err := i.pool.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("get search connection: %w", err)
	}
	defer i.pool.Put(conn)

	var hits []search.Hit
	err = sqlitex.Execute(conn,
		`SELECT
			d.artifact_id,
			d.revision_id,
			d.extractor_id,
			d.media_type,
			d.content_algorithm,
			d.content_digest,
			d.content_size
		FROM search_documents_fts
		JOIN search_documents d ON d.document_id=search_documents_fts.rowid
		WHERE search_documents_fts MATCH ?1
		ORDER BY bm25(search_documents_fts), d.document_id
		LIMIT ?2`,
		&sqlitex.ExecOptions{
			Args: []any{expression, int64(limit)},
			ResultFunc: func(stmt *zsqlite.Stmt) error {
				hits = append(hits, search.Hit{
					ArtifactID:  corpus.ArtifactID(stmt.ColumnText(0)),
					RevisionID:  corpus.RevisionID(stmt.ColumnText(1)),
					ExtractorID: stmt.ColumnText(2),
					MediaType:   stmt.ColumnText(3),
					Evidence: corpus.ContentEvidence{
						Algorithm: stmt.ColumnText(4),
						Digest:    stmt.ColumnText(5),
						Size:      stmt.ColumnInt64(6),
					},
				})
				return nil
			},
		})
	if err != nil {
		return nil, fmt.Errorf("search FTS5 documents: %w", err)
	}
	return hits, nil
}

func literalQuery(query string) (string, error) {
	if !utf8.ValidString(query) {
		return "", ErrInvalidQuery
	}
	fields := strings.Fields(query)
	if len(fields) == 0 {
		return "", ErrInvalidQuery
	}
	parts := make([]string, 0, len(fields))
	for _, field := range fields {
		escaped := strings.ReplaceAll(field, `"`, `""`)
		parts = append(parts, `"`+escaped+`"`)
	}
	return strings.Join(parts, " AND "), nil
}

func (i *Index) Verify(ctx context.Context) error {
	conn, err := i.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get search connection: %w", err)
	}
	defer i.pool.Put(conn)
	return integrityCheckConn(conn)
}

func integrityCheckConn(conn *zsqlite.Conn) error {
	if err := sqlitex.ExecuteTransient(
		conn,
		"INSERT INTO search_documents_fts(search_documents_fts, rank) VALUES('integrity-check', 1)",
		nil,
	); err != nil {
		return fmt.Errorf("verify FTS5 search index: %w", err)
	}
	return nil
}

// RebuildFTS discards and reconstructs FTS structures from the derived
// search_documents table. It does not read or mutate identity authority.
func (i *Index) RebuildFTS(ctx context.Context) (err error) {
	conn, err := i.pool.Get(ctx)
	if err != nil {
		return fmt.Errorf("get search connection: %w", err)
	}
	defer i.pool.Put(conn)
	end, err := sqlitex.ImmediateTransaction(conn)
	if err != nil {
		return fmt.Errorf("begin FTS5 rebuild transaction: %w", err)
	}
	defer end(&err)
	if err := sqlitex.ExecuteTransient(
		conn,
		"INSERT INTO search_documents_fts(search_documents_fts) VALUES('rebuild')",
		nil,
	); err != nil {
		return fmt.Errorf("rebuild FTS5 search index: %w", err)
	}
	return integrityCheckConn(conn)
}
