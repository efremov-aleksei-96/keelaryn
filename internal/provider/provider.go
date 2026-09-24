package provider

import (
	"context"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

// Discoverer performs read-only observation of one corpus root.
type Discoverer interface {
	Discover(ctx context.Context, root string) ([]corpus.Observation, error)
}
