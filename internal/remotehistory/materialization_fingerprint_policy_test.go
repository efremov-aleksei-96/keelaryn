package remotehistory

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestRemoteMetadataFingerprintRejectsNonLightweightPolicy(t *testing.T) {
	_, err := FingerprintRemoteMetadataSnapshot(RemoteMetadataFingerprintInput{
		GenerationID:            "hgen_test",
		PublicationSequence:     1,
		ProviderID:              "provider",
		ScanRoot:                "root",
		SourceScopeID:           "scope",
		MaterializationPolicyID: "OTHER:v1",
		Entries: []RemoteMetadataFingerprintEntry{{
			ProviderObjectID: "object",
			Locators: []corpus.Locator{{
				ProviderID: "provider",
				Root:       "root",
				Path:       "object",
			}},
			Kind:       corpus.EntryRegularFile,
			Size:       1,
			Mode:       0,
			ModifiedAt: "2026-09-27T00:00:00Z",
		}},
	})
	if !errors.Is(err, ErrInvalidRemoteMetadataFingerprint) {
		t.Fatalf("error=%v want ErrInvalidRemoteMetadataFingerprint", err)
	}
}
