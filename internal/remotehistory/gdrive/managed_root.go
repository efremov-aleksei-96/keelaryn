package gdrive

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"strings"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

const managedRootScanRootVersion = "google-drive:managed-root:v1"

// ManagedRootScanRoot returns the canonical ScanSession.Root key for one
// managed Google Drive corpus root. The provider identity domain disambiguates
// otherwise identical raw Drive object IDs; this is locator scope, never
// Keelaryn Artifact identity.
func ManagedRootScanRoot(identityDomain string, managedRootObjectID corpus.ProviderObjectID) (string, error) {
	if strings.TrimSpace(identityDomain) == "" || managedRootObjectID == "" {
		return "", ErrInvalidTopologyState
	}
	domainDigest := sha256.Sum256([]byte(identityDomain))
	objectSegment := base64.RawURLEncoding.EncodeToString([]byte(managedRootObjectID))
	return managedRootScanRootVersion + ":" + hex.EncodeToString(domainDigest[:]) + ":" + objectSegment, nil
}
