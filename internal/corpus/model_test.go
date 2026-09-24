package corpus_test

import (
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestIdentityDomainsRemainDistinct(t *testing.T) {
	artifact := corpus.Artifact{ID: "artifact-1"}
	object := corpus.ProviderObject{
		ProviderID:    "provider-1",
		ID:            "provider-object-1",
		IdentityState: corpus.ObjectIdentityObserved,
	}
	revision := corpus.Revision{ID: "revision-1", ArtifactID: artifact.ID}
	locator := corpus.Locator{ProviderID: object.ProviderID, Root: "/corpus", Path: "file.txt"}

	if string(artifact.ID) == string(object.ID) {
		t.Fatal("Artifact ID must not collapse into ProviderObject ID")
	}
	if string(revision.ID) == locator.Path {
		t.Fatal("Revision ID must not collapse into a locator path")
	}
}

func TestCatalogStartsEmptyAndSeparated(t *testing.T) {
	catalog := corpus.NewCatalog()
	if len(catalog.Artifacts) != 0 || len(catalog.ProviderObjects) != 0 || len(catalog.Revisions) != 0 || len(catalog.Observations) != 0 {
		t.Fatalf("new catalog is not empty: %#v", catalog)
	}
}
