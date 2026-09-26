package gdrive

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
)

const historyScopePolicyVersion = "google-drive-history-universe:v1"

type historyScopePolicy struct {
	Version                   string `json:"version"`
	IdentityDomain            string `json:"identity_domain"`
	StreamID                  string `json:"stream_id"`
	Root                      string `json:"root"`
	Kind                      string `json:"kind"`
	DriveID                   string `json:"drive_id,omitempty"`
	Spaces                    string `json:"spaces"`
	IncludeRemoved            bool   `json:"include_removed"`
	RestrictToMyDrive         bool   `json:"restrict_to_my_drive"`
	IncludeItemsFromAllDrives bool   `json:"include_items_from_all_drives"`
	SupportsAllDrives         bool   `json:"supports_all_drives"`
}

func ScopePolicyFingerprint(config Config) (remotehistory.ScopePolicyFingerprint, error) {
	if err := validateConfig(config); err != nil {
		return "", err
	}
	policy := historyScopePolicy{
		Version:        historyScopePolicyVersion,
		IdentityDomain: config.IdentityDomain,
		StreamID:       string(config.StreamID),
		Root:           config.Root,
		Kind:           string(config.Kind),
		DriveID:        config.DriveID,
		Spaces:         "drive",
		IncludeRemoved: true,
	}
	switch config.Kind {
	case StreamMyDrive:
		policy.RestrictToMyDrive = true
	case StreamSharedDrive:
		policy.IncludeItemsFromAllDrives = true
		policy.SupportsAllDrives = true
	default:
		return "", ErrInvalidConfig
	}
	encoded, err := json.Marshal(policy)
	if err != nil {
		return "", fmt.Errorf("encode Google Drive history scope policy: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return remotehistory.ScopePolicyFingerprint(historyScopePolicyVersion + ":" + hex.EncodeToString(sum[:])), nil
}
