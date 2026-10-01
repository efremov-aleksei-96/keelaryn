package doctor

import (
	"context"
	"errors"
	"os"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	searchsqlite "github.com/efremov-aleksei-96/keelaryn/internal/search/sqlite"
	sqlitestate "github.com/efremov-aleksei-96/keelaryn/internal/state/sqlite"
)

type Status string

const (
	StatusPass    Status = "PASS"
	StatusFail    Status = "FAIL"
	StatusSkipped Status = "SKIPPED"
)

var ErrFailed = errors.New("doctor detected failures")

type Check struct {
	ID     string `json:"id"`
	Status Status `json:"status"`
	Error  string `json:"error,omitempty"`
}

type Report struct {
	Status Status  `json:"status"`
	Checks []Check `json:"checks"`
}

func (r Report) Passed() bool {
	return r.Status == StatusPass
}

// Run performs diagnostics only. It never creates, migrates, repairs, or
// writes control state, and it emits no report file.
func Run(ctx context.Context, controlDir string) Report {
	report := Report{Status: StatusPass}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		report.Status = StatusFail
		report.Checks = append(report.Checks,
			Check{ID: "control-storage", Status: StatusFail, Error: err.Error()},
			Check{ID: "state-database", Status: StatusSkipped},
			Check{ID: "search-database", Status: StatusSkipped},
			Check{ID: "control-storage-post", Status: StatusSkipped},
		)
		return report
	}
	report.Checks = append(report.Checks, Check{ID: "control-storage", Status: StatusPass})

	if err := sqlitestate.VerifyReadOnly(ctx, layout.StateDB); err != nil {
		report.Status = StatusFail
		report.Checks = append(report.Checks, Check{ID: "state-database", Status: StatusFail, Error: err.Error()})
	} else {
		report.Checks = append(report.Checks, Check{ID: "state-database", Status: StatusPass})
	}

	// search.db is rebuildable derived state. Its absence is a valid control
	// profile (for example a metadata-only remote bootstrap). If it exists,
	// it remains subject to the same strict read-only verification.
	if _, err := os.Lstat(layout.SearchDB); errors.Is(err, os.ErrNotExist) {
		report.Checks = append(report.Checks, Check{ID: "search-database", Status: StatusSkipped})
	} else if err != nil {
		report.Status = StatusFail
		report.Checks = append(report.Checks, Check{ID: "search-database", Status: StatusFail, Error: err.Error()})
	} else if err := searchsqlite.VerifyReadOnly(ctx, layout.SearchDB); err != nil {
		report.Status = StatusFail
		report.Checks = append(report.Checks, Check{ID: "search-database", Status: StatusFail, Error: err.Error()})
	} else {
		report.Checks = append(report.Checks, Check{ID: "search-database", Status: StatusPass})
	}

	if err := controlstorage.Verify(layout.Dir); err != nil {
		report.Status = StatusFail
		report.Checks = append(report.Checks, Check{ID: "control-storage-post", Status: StatusFail, Error: err.Error()})
	} else {
		report.Checks = append(report.Checks, Check{ID: "control-storage-post", Status: StatusPass})
	}
	return report
}
