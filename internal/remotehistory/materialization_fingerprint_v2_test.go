package remotehistory_test

import (
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

func TestRemoteMetadataV2DistinguishesMissingFromZero(t *testing.T) {
	zeroSize := int64(0)
	zeroMode := uint32(0)
	modified := "2026-09-30T00:00:00Z"
	base := remotehistory.RemoteMetadataFingerprintInputV2{
		GenerationID: "gen", PublicationSequence: 1, ProviderID: "google-drive",
		ScanRoot: "root", SourceScopeID: "scope",
		MaterializationPolicyID: remotehistory.LightweightAllMaterializationPolicyIDV2,
		Entries: []remotehistory.RemoteMetadataFingerprintEntryV2{{
			ProviderObjectID: "obj",
			Locators:         []corpus.Locator{{ProviderID: "google-drive", Root: "root", Path: "id:obj"}},
			Kind:             corpus.EntryOther,
		}},
	}
	missing, err := remotehistory.FingerprintRemoteMetadataSnapshotV2(base)
	if err != nil {
		t.Fatal(err)
	}
	base.Entries[0].Size = &zeroSize
	base.Entries[0].Mode = &zeroMode
	base.Entries[0].ModifiedAt = &modified
	known, err := remotehistory.FingerprintRemoteMetadataSnapshotV2(base)
	if err != nil {
		t.Fatal(err)
	}
	if missing == known {
		t.Fatal("v2 fingerprint conflated unavailable facts with known zero values")
	}
}

func TestRemoteMetadataPolicyPairsAreExact(t *testing.T) {
	if !remotehistory.IsRemoteMetadataSnapshotPolicyPair(remotehistory.RemoteMetadataSnapshotFingerprintVersion, remotehistory.LightweightAllMaterializationPolicyID) ||
		!remotehistory.IsRemoteMetadataSnapshotPolicyPair(remotehistory.RemoteMetadataSnapshotFingerprintVersionV2, remotehistory.LightweightAllMaterializationPolicyIDV2) {
		t.Fatal("supported pairs rejected")
	}
	if remotehistory.IsRemoteMetadataSnapshotPolicyPair(remotehistory.RemoteMetadataSnapshotFingerprintVersion, remotehistory.LightweightAllMaterializationPolicyIDV2) ||
		remotehistory.IsRemoteMetadataSnapshotPolicyPair(remotehistory.RemoteMetadataSnapshotFingerprintVersionV2, remotehistory.LightweightAllMaterializationPolicyID) {
		t.Fatal("mixed pair accepted")
	}
}
