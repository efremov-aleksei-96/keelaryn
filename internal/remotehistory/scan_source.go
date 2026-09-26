package remotehistory

import (
	"encoding/hex"
	"errors"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

type RemoteScanSourceInput struct {
	GenerationID              HistoryGenerationID
	PublicationSequence       HistoryPublicationSequence
	SourceScopeID             string
	MaterializationPolicyID   string
	SnapshotFingerprintVersion string
	SnapshotFingerprintSHA256  string
}

type RemoteScanSource struct {
	ScanID corpus.ScanSessionID
	RemoteScanSourceInput
}

type RemoteScanSourceState string

const (
	RemoteScanSourceCurrent  RemoteScanSourceState = "CURRENT"
	RemoteScanSourceAdvanced RemoteScanSourceState = "ADVANCED"
	RemoteScanSourceClosed   RemoteScanSourceState = "CLOSED"
)

var ErrInvalidRemoteScanSource = errors.New("invalid remote scan source")

func ValidateRemoteScanSourceInput(source RemoteScanSourceInput) error {
	if source.GenerationID == "" ||
		source.PublicationSequence == 0 ||
		strings.TrimSpace(source.SourceScopeID) == "" ||
		strings.TrimSpace(source.MaterializationPolicyID) == "" ||
		strings.TrimSpace(source.SnapshotFingerprintVersion) == "" ||
		len(source.SnapshotFingerprintSHA256) != 64 ||
		source.SnapshotFingerprintSHA256 != strings.ToLower(source.SnapshotFingerprintSHA256) {
		return ErrInvalidRemoteScanSource
	}
	if _, err := hex.DecodeString(source.SnapshotFingerprintSHA256); err != nil {
		return ErrInvalidRemoteScanSource
	}
	return nil
}
