package remotehistory

import (
	"errors"
	"testing"
)

func TestRemoteScanSourceReservesMetadataFingerprintPolicyPair(t *testing.T) {
	const digest = "0000000000000000000000000000000000000000000000000000000000000000"
	base := RemoteScanSourceInput{
		GenerationID:               "hgen_test",
		PublicationSequence:        1,
		SourceScopeID:              "scope",
		MaterializationPolicyID:    LightweightAllMaterializationPolicyID,
		SnapshotFingerprintVersion: RemoteMetadataSnapshotFingerprintVersion,
		SnapshotFingerprintSHA256:  digest,
	}
	if err := ValidateRemoteScanSourceInput(base); err != nil {
		t.Fatalf("qualified metadata source rejected: %v", err)
	}
	cases := []RemoteScanSourceInput{
		func() RemoteScanSourceInput {
			v := base
			v.MaterializationPolicyID = "OTHER:v1"
			return v
		}(),
		func() RemoteScanSourceInput {
			v := base
			v.SnapshotFingerprintVersion = "other-fingerprint:v1"
			return v
		}(),
	}
	for i, input := range cases {
		if err := ValidateRemoteScanSourceInput(input); !errors.Is(err, ErrInvalidRemoteScanSource) {
			t.Fatalf("case %d error=%v want ErrInvalidRemoteScanSource", i, err)
		}
	}
}
