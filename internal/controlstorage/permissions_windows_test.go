//go:build windows

package controlstorage_test

import (
	"errors"
	"path/filepath"
	"testing"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"golang.org/x/sys/windows"
)

func TestWindowsVerifyRejectsPermissiveUnprotectedDACL(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "control")
	if _, err := controlstorage.Prepare(dir); err != nil {
		t.Fatal(err)
	}

	sd, err := windows.SecurityDescriptorFromString("D:(A;OICI;FA;;;WD)")
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(
		dir,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.UNPROTECTED_DACL_SECURITY_INFORMATION,
		nil,
		nil,
		dacl,
		nil,
	); err != nil {
		t.Fatal(err)
	}

	_, err = controlstorage.OpenExisting(dir)
	if !errors.Is(err, controlstorage.ErrControlDirInsecure) {
		t.Fatalf("error=%v want ErrControlDirInsecure", err)
	}
}
