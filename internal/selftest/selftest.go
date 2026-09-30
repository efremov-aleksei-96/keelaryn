package selftest

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
	localruntime "github.com/efremov-aleksei-96/keelaryn/internal/runtime/local"
)

var ErrFailed = errors.New("self-test detected failures")

const (
	fixtureText   = "keelaryn selftest exact provenance"
	fixtureQuery  = "selftest provenance"
	fixtureReason = "prove disposable exact provenance"
)

type Proof struct {
	ArtifactID      string `json:"artifact_id,omitempty"`
	RevisionID      string `json:"revision_id,omitempty"`
	Reason          string `json:"reason,omitempty"`
	CorpusUnchanged bool   `json:"corpus_unchanged"`
	Cleaned         bool   `json:"cleaned"`
}

type Report struct {
	Status doctor.Status `json:"status"`
	Checks []doctor.Check `json:"checks"`
	Proof  Proof          `json:"proof"`
}

func (r Report) Passed() bool {
	return r.Status == doctor.StatusPass
}

// Run exercises the protected local happy path exclusively in disposable
// temporary state. It accepts no user paths and removes the workspace before
// returning.
func Run(ctx context.Context) Report {
	return run(ctx, "")
}

func run(ctx context.Context, tempParent string) Report {
	report := newReport()
	workspace, err := os.MkdirTemp(tempParent, "keelaryn-selftest-")
	if err != nil {
		report.fail("workspace", fmt.Errorf("create disposable workspace: %w", err))
		return report
	}
	report.pass("workspace")

	corpusRoot := filepath.Join(workspace, "corpus")
	controlDir := filepath.Join(workspace, "control")
	fixturePath := filepath.Join(corpusRoot, "docs", "note.txt")

	var before map[string]snapshotEntry
	fixtureReady := false
	if err := os.MkdirAll(filepath.Dir(fixturePath), 0o700); err != nil {
		report.fail("fixture", fmt.Errorf("create fixture directory: %w", err))
	} else if err := os.WriteFile(fixturePath, []byte(fixtureText), 0o600); err != nil {
		report.fail("fixture", fmt.Errorf("write fixture: %w", err))
	} else if before, err = snapshotCorpus(corpusRoot); err != nil {
		report.fail("fixture", fmt.Errorf("snapshot fixture: %w", err))
	} else {
		fixtureReady = true
		report.pass("fixture")
	}

	bootstrapOK := false
	if fixtureReady {
		result, runErr := localruntime.BootstrapProtectedIndex(ctx, localruntime.ProtectedIndexOptions{
			Root:       corpusRoot,
			ControlDir: controlDir,
			ObservedAt: time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC),
			MaxBytes:   4096,
		})
		if runErr != nil {
			report.fail("bootstrap", runErr)
		} else if result.Indexed != 1 || result.ScanID == "" {
			report.fail("bootstrap", fmt.Errorf("unexpected bootstrap result: indexed=%d scan_id=%q", result.Indexed, result.ScanID))
		} else {
			bootstrapOK = true
			report.pass("bootstrap")
		}
	}

	searchOK := false
	var artifactID, revisionID string
	if bootstrapOK {
		hits, runErr := localruntime.QueryProtected(ctx, controlDir, fixtureQuery, 10)
		if runErr != nil {
			report.fail("search", runErr)
		} else if len(hits) != 1 || hits[0].ArtifactID == "" || hits[0].RevisionID == "" {
			report.fail("search", fmt.Errorf("unexpected exact-provenance search result count=%d", len(hits)))
		} else {
			artifactID = string(hits[0].ArtifactID)
			revisionID = string(hits[0].RevisionID)
			report.Proof.ArtifactID = artifactID
			report.Proof.RevisionID = revisionID
			searchOK = true
			report.pass("search")
		}
	}

	contextOK := false
	if searchOK {
		bundle, runErr := localruntime.BuildProtectedContext(ctx, localruntime.ProtectedContextOptions{
			Root:       corpusRoot,
			ControlDir: controlDir,
			Query:      fixtureQuery,
			Reason:     fixtureReason,
			Limit:      10,
			MaxBytes:   4096,
		})
		if runErr != nil {
			report.fail("context-bundle", runErr)
		} else if len(bundle.Items) != 1 {
			report.fail("context-bundle", fmt.Errorf("unexpected ContextBundle item count=%d", len(bundle.Items)))
		} else {
			item := bundle.Items[0]
			if string(item.ArtifactID) != artifactID ||
				string(item.RevisionID) != revisionID ||
				item.Reason != fixtureReason ||
				item.Text != fixtureText {
				report.fail("context-bundle", fmt.Errorf("ContextBundle exact provenance mismatch"))
			} else {
				report.Proof.Reason = item.Reason
				contextOK = true
				report.pass("context-bundle")
			}
		}
	}

	if contextOK {
		doctorReport := doctor.Run(ctx, controlDir)
		if !doctorReport.Passed() {
			report.fail("doctor", fmt.Errorf("Doctor failed: %v", doctorReport.Checks))
		} else {
			report.pass("doctor")
		}
	}

	if fixtureReady {
		after, snapshotErr := snapshotCorpus(corpusRoot)
		if snapshotErr != nil {
			report.fail("corpus-unchanged", snapshotErr)
		} else if !reflect.DeepEqual(before, after) {
			report.fail("corpus-unchanged", errors.New("disposable corpus bytes or topology changed"))
		} else {
			report.Proof.CorpusUnchanged = true
			report.pass("corpus-unchanged")
		}
	}

	if err := os.RemoveAll(workspace); err != nil {
		report.fail("cleanup", fmt.Errorf("remove disposable workspace: %w", err))
	} else if _, err := os.Stat(workspace); !errors.Is(err, os.ErrNotExist) {
		report.fail("cleanup", fmt.Errorf("disposable workspace still exists after cleanup: %v", err))
	} else {
		report.Proof.Cleaned = true
		report.pass("cleanup")
	}
	return report
}

func newReport() Report {
	ids := []string{
		"workspace",
		"fixture",
		"bootstrap",
		"search",
		"context-bundle",
		"doctor",
		"corpus-unchanged",
		"cleanup",
	}
	report := Report{Status: doctor.StatusPass, Checks: make([]doctor.Check, len(ids))}
	for i, id := range ids {
		report.Checks[i] = doctor.Check{ID: id, Status: doctor.StatusSkipped}
	}
	return report
}

func (r *Report) pass(id string) {
	r.set(id, doctor.StatusPass, "")
}

func (r *Report) fail(id string, err error) {
	r.Status = doctor.StatusFail
	r.set(id, doctor.StatusFail, err.Error())
}

func (r *Report) set(id string, status doctor.Status, message string) {
	for i := range r.Checks {
		if r.Checks[i].ID == id {
			r.Checks[i].Status = status
			r.Checks[i].Error = message
			return
		}
	}
}

type snapshotEntry struct {
	Kind   string
	Digest [sha256.Size]byte
	Target string
}

func snapshotCorpus(root string) (map[string]snapshotEntry, error) {
	out := make(map[string]snapshotEntry)
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if entry.IsDir() {
			out[rel] = snapshotEntry{Kind: "dir"}
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			out[rel] = snapshotEntry{Kind: "symlink", Target: target}
			return nil
		}
		if !entry.Type().IsRegular() {
			out[rel] = snapshotEntry{Kind: entry.Type().String()}
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		out[rel] = snapshotEntry{Kind: "file", Digest: sha256.Sum256(data)}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("snapshot corpus: %w", err)
	}
	return out, nil
}
