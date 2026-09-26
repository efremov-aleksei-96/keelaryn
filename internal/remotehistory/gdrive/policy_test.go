package gdrive_test

import (
	"errors"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
)

func TestGoogleDriveScopePolicyFingerprintIsDeterministicAndScopeBound(t *testing.T) {
	base := gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "actual-root-id",
		Kind:           gdrive.StreamMyDrive,
	}
	first, err := gdrive.ScopePolicyFingerprint(base)
	if err != nil {
		t.Fatal(err)
	}
	again, err := gdrive.ScopePolicyFingerprint(base)
	if err != nil {
		t.Fatal(err)
	}
	if first != again || first == "" {
		t.Fatalf("fingerprints first=%q again=%q", first, again)
	}

	changed := base
	changed.Root = "other-root-id"
	other, err := gdrive.ScopePolicyFingerprint(changed)
	if err != nil {
		t.Fatal(err)
	}
	if other == first {
		t.Fatal("different canonical history root reused scope-policy fingerprint")
	}

	changed = base
	changed.IdentityDomain = "google-drive:user:user-2"
	other, err = gdrive.ScopePolicyFingerprint(changed)
	if err != nil {
		t.Fatal(err)
	}
	if other == first {
		t.Fatal("different identity domain reused scope-policy fingerprint")
	}
}

func TestGoogleDriveScopePolicyFingerprintRejectsRootAlias(t *testing.T) {
	config := gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "root",
		Kind:           gdrive.StreamMyDrive,
	}
	_, err := gdrive.ScopePolicyFingerprint(config)
	if !errors.Is(err, gdrive.ErrNonCanonicalHistoryRoot) {
		t.Fatalf("err=%v", err)
	}
}

func TestGoogleDriveSharedDrivePolicyDiffersFromMyDrive(t *testing.T) {
	myDrive, err := gdrive.ScopePolicyFingerprint(gdrive.Config{
		IdentityDomain: "google-drive:user:user-1",
		StreamID:       "google-drive:user:user-1:my-drive:changes",
		Root:           "actual-root-id",
		Kind:           gdrive.StreamMyDrive,
	})
	if err != nil {
		t.Fatal(err)
	}
	shared, err := gdrive.ScopePolicyFingerprint(gdrive.Config{
		IdentityDomain: "google-drive:shared:drive-1",
		StreamID:       "google-drive:shared:drive-1:changes",
		Root:           "drive-1",
		Kind:           gdrive.StreamSharedDrive,
		DriveID:        "drive-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if myDrive == shared {
		t.Fatal("My Drive and shared-drive policy fingerprints unexpectedly match")
	}
}
