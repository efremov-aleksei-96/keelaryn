package controlstorage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var ErrSearchMutationLocked = errors.New("search cache mutation lock is already held")

type SearchMutationLock struct {
	file *os.File
}

func AcquireSearchMutationLock(layout Layout) (*SearchMutationLock, error) {
	if strings.TrimSpace(layout.Dir) == "" ||
		filepath.Clean(layout.SearchLock) != filepath.Join(filepath.Clean(layout.Dir), SearchMutationLockName) {
		return nil, ErrInvalidControlDir
	}
	if err := verifyProtectedDir(layout.Dir); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(layout.SearchLock, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open search mutation lock: %w", err)
	}
	if err := verifyControlFile(layout.SearchLock); err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("%w: %s: %v", ErrControlFileUnsafe, layout.SearchLock, err)
	}
	if err := lockSearchMutationFile(file); err != nil {
		_ = file.Close()
		return nil, err
	}
	return &SearchMutationLock{file: file}, nil
}

func (l *SearchMutationLock) Close() error {
	if l == nil || l.file == nil {
		return nil
	}
	file := l.file
	l.file = nil
	unlockErr := unlockSearchMutationFile(file)
	closeErr := file.Close()
	return errors.Join(unlockErr, closeErr)
}
