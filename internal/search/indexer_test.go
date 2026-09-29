package search_test

import (
	"context"
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/extract"
	"github.com/efremov-aleksei-96/keelaryn/internal/search"
)

type revisionReader map[corpus.ArtifactID][]corpus.RevisionRecord

func (r revisionReader) RevisionHistory(_ context.Context, artifactID corpus.ArtifactID) ([]corpus.RevisionRecord, error) {
	return append([]corpus.RevisionRecord(nil), r[artifactID]...), nil
}

func TestDocumentFromExtraction(t *testing.T) {
	evidence := corpus.ContentEvidence{Algorithm: corpus.ContentAlgorithmSHA256, Digest: "aaa", Size: 5}
	reader := revisionReader{
		"art-1": {{
			Revision: corpus.Revision{ID: "rev-1", ArtifactID: "art-1"},
			Sequence: 1,
			Evidence: evidence,
		}},
	}
	result := extract.Result{
		Status: extract.StatusExtracted, ArtifactID: "art-1", RevisionID: "rev-1",
		ExtractorID: "builtin:text-utf8:v1", MediaType: "text/plain",
		Evidence: evidence, Text: "hello",
	}
	document, err := search.DocumentFromExtraction(context.Background(), reader, result)
	if err != nil {
		t.Fatal(err)
	}
	if document.ArtifactID != result.ArtifactID ||
		document.RevisionID != result.RevisionID ||
		document.Text != result.Text ||
		document.Evidence != result.Evidence {
		t.Fatalf("document=%#v result=%#v", document, result)
	}
}

func TestDocumentFromExtractionAcceptsExactHistoricalRevision(t *testing.T) {
	oldEvidence := corpus.ContentEvidence{Algorithm: corpus.ContentAlgorithmSHA256, Digest: "aaa", Size: 5}
	newEvidence := corpus.ContentEvidence{Algorithm: corpus.ContentAlgorithmSHA256, Digest: "bbb", Size: 6}
	reader := revisionReader{
		"art-1": {
			{Revision: corpus.Revision{ID: "rev-1", ArtifactID: "art-1"}, Sequence: 1, Evidence: oldEvidence},
			{Revision: corpus.Revision{ID: "rev-2", ArtifactID: "art-1"}, Sequence: 2, Evidence: newEvidence},
		},
	}
	document, err := search.DocumentFromExtraction(context.Background(), reader, extract.Result{
		Status: extract.StatusExtracted, ArtifactID: "art-1", RevisionID: "rev-1",
		ExtractorID: "builtin:text-utf8:v1", Evidence: oldEvidence, Text: "hello",
	})
	if err != nil {
		t.Fatal(err)
	}
	if document.RevisionID != "rev-1" || document.Evidence != oldEvidence {
		t.Fatalf("document=%#v", document)
	}
}

func TestDocumentFromExtractionRejectsEvidenceMismatch(t *testing.T) {
	evidence := corpus.ContentEvidence{Algorithm: corpus.ContentAlgorithmSHA256, Digest: "aaa", Size: 5}
	reader := revisionReader{
		"art-1": {{
			Revision: corpus.Revision{ID: "rev-1", ArtifactID: "art-1"},
			Sequence: 1,
			Evidence: evidence,
		}},
	}
	wrong := evidence
	wrong.Digest = "wrong"
	_, err := search.DocumentFromExtraction(context.Background(), reader, extract.Result{
		Status: extract.StatusExtracted, ArtifactID: "art-1", RevisionID: "rev-1",
		ExtractorID: "builtin:text-utf8:v1", Evidence: wrong, Text: "hello",
	})
	if !errors.Is(err, search.ErrExtractionRevisionMismatch) {
		t.Fatalf("error=%v want ErrExtractionRevisionMismatch", err)
	}
}

func TestDocumentFromExtractionRejectsNonExtracted(t *testing.T) {
	_, err := search.DocumentFromExtraction(context.Background(), revisionReader{}, extract.Result{
		Status: extract.StatusUnsupported,
	})
	if !errors.Is(err, search.ErrExtractionNotIndexable) {
		t.Fatalf("error=%v want ErrExtractionNotIndexable", err)
	}
}
