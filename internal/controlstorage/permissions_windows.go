//go:build windows

package controlstorage

import (
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

const windowsFileAllAccess windows.ACCESS_MASK = 0x001F01FF

func createProtectedDir(path string) error {
	user, err := currentUserSID()
	if err != nil {
		return err
	}
	sd, err := windows.SecurityDescriptorFromString(directorySDDL(user))
	if err != nil {
		return fmt.Errorf("build control directory security descriptor: %w", err)
	}
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return fmt.Errorf("encode control directory path: %w", err)
	}
	attrs := &windows.SecurityAttributes{
		Length:             uint32(unsafe.Sizeof(windows.SecurityAttributes{})),
		SecurityDescriptor: sd,
	}
	if err := windows.CreateDirectory(name, attrs); err != nil {
		return err
	}
	return nil
}

func verifyProtectedDir(path string) error {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return fmt.Errorf("encode control directory path: %w", err)
	}
	attrs, err := windows.GetFileAttributes(name)
	if err != nil {
		return fmt.Errorf("read control directory attributes: %w", err)
	}
	if attrs&windows.FILE_ATTRIBUTE_DIRECTORY == 0 || attrs&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return fmt.Errorf("%w: directory is not a plain filesystem directory", ErrControlDirInsecure)
	}

	user, err := currentUserSID()
	if err != nil {
		return err
	}
	sd, err := windows.GetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION,
	)
	if err != nil {
		return fmt.Errorf("read control directory security descriptor: %w", err)
	}
	if sd == nil {
		return fmt.Errorf("%w: missing security descriptor", ErrControlDirInsecure)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return fmt.Errorf("read control directory owner: %w", err)
	}
	if owner == nil || !owner.Equals(user) {
		return fmt.Errorf("%w: owner is not current process user", ErrControlDirInsecure)
	}
	control, _, err := sd.Control()
	if err != nil {
		return fmt.Errorf("read control directory DACL control: %w", err)
	}
	if control&windows.SE_DACL_PROTECTED == 0 {
		return fmt.Errorf("%w: DACL inherits from parent", ErrControlDirInsecure)
	}
	dacl, _, err := sd.DACL()
	if err != nil || dacl == nil {
		if err == nil {
			err = windows.ERROR_OBJECT_NOT_FOUND
		}
		return fmt.Errorf("%w: read protected DACL: %v", ErrControlDirInsecure, err)
	}

	system, err := windows.CreateWellKnownSid(windows.WinLocalSystemSid)
	if err != nil {
		return fmt.Errorf("create LocalSystem SID: %w", err)
	}
	admins, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		return fmt.Errorf("create Administrators SID: %w", err)
	}
	expected := []*windows.SID{user, system, admins}
	seen := make([]bool, len(expected))

	if int(dacl.AceCount) != len(expected) {
		return fmt.Errorf("%w: ACE count=%d want=%d", ErrControlDirInsecure, dacl.AceCount, len(expected))
	}
	for i := uint32(0); i < uint32(dacl.AceCount); i++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			return fmt.Errorf("read control directory ACE %d: %w", i, err)
		}
		if ace == nil ||
			ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE ||
			ace.Mask != windowsFileAllAccess ||
			ace.Header.AceFlags != windows.OBJECT_INHERIT_ACE|windows.CONTAINER_INHERIT_ACE {
			return fmt.Errorf("%w: unexpected ACE %d", ErrControlDirInsecure, i)
		}
		aceSID := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		match := -1
		for j, sid := range expected {
			if !seen[j] && aceSID.Equals(sid) {
				match = j
				break
			}
		}
		if match < 0 {
			return fmt.Errorf("%w: unexpected or duplicate ACE principal", ErrControlDirInsecure)
		}
		seen[match] = true
	}
	for i, ok := range seen {
		if !ok {
			return fmt.Errorf("%w: required ACE %d missing", ErrControlDirInsecure, i)
		}
	}
	return nil
}

func verifyControlFile(path string) error {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	attrs, err := windows.GetFileAttributes(name)
	if err != nil {
		return err
	}
	if attrs&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return fmt.Errorf("control file is a reparse point")
	}

	user, err := currentUserSID()
	if err != nil {
		return err
	}
	sd, err := windows.GetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION,
	)
	if err != nil {
		return fmt.Errorf("read control file security descriptor: %w", err)
	}
	if sd == nil {
		return fmt.Errorf("missing control file security descriptor")
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return fmt.Errorf("read control file owner: %w", err)
	}
	dacl, _, err := sd.DACL()
	if err != nil || dacl == nil {
		if err == nil {
			err = windows.ERROR_OBJECT_NOT_FOUND
		}
		return fmt.Errorf("read control file DACL: %v", err)
	}

	system, err := windows.CreateWellKnownSid(windows.WinLocalSystemSid)
	if err != nil {
		return fmt.Errorf("create LocalSystem SID: %w", err)
	}
	admins, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		return fmt.Errorf("create Administrators SID: %w", err)
	}
	expected := []*windows.SID{user, system, admins}
	if owner == nil || !sidMatchesAny(owner, expected) {
		return fmt.Errorf("control file owner is not a trusted control principal")
	}
	seen := make([]bool, len(expected))
	if int(dacl.AceCount) != len(expected) {
		return fmt.Errorf("control file ACE count=%d want=%d", dacl.AceCount, len(expected))
	}
	for i := uint32(0); i < uint32(dacl.AceCount); i++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			return fmt.Errorf("read control file ACE %d: %w", i, err)
		}
		if ace == nil ||
			ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE ||
			ace.Mask != windowsFileAllAccess ||
			ace.Header.AceFlags&windows.INHERIT_ONLY_ACE != 0 {
			return fmt.Errorf("unexpected control file ACE %d", i)
		}
		aceSID := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		match := -1
		for j, sid := range expected {
			if !seen[j] && aceSID.Equals(sid) {
				match = j
				break
			}
		}
		if match < 0 {
			return fmt.Errorf("unexpected or duplicate control file ACE principal")
		}
		seen[match] = true
	}
	return nil
}

func sidMatchesAny(candidate *windows.SID, expected []*windows.SID) bool {
	if candidate == nil {
		return false
	}
	for _, sid := range expected {
		if sid != nil && candidate.Equals(sid) {
			return true
		}
	}
	return false
}

func currentUserSID() (*windows.SID, error) {
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		return nil, fmt.Errorf("read current process user SID: %w", err)
	}
	if user == nil || user.User.Sid == nil {
		return nil, fmt.Errorf("current process user SID missing")
	}
	return user.User.Sid, nil
}

func directorySDDL(user *windows.SID) string {
	sid := user.String()
	return fmt.Sprintf(
		"O:%sD:P(A;OICI;FA;;;%s)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)",
		sid,
		sid,
	)
}
