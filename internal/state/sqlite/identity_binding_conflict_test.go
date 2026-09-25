package sqlitestate

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestHardenedSameRejectsConflictingProviderBinding(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	base:=time.Date(2026,9,25,22,40,0,0,time.UTC)

	firstScan,err:=store.StartScan(ctx,"drive","drive-root",base); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-bound-origin","obj-bound-same",nil,base))
	first,err:=store.AcceptNewObservationInScan(ctx,identityRequest("req-bound-origin",firstScan.ID,"obj-bound-same","file-id/obj-bound-same","auth-bound-origin",base,"same")); if err!=nil { t.Fatal(err) }
	if err=store.CompleteScan(ctx,firstScan.ID,base.Add(time.Minute)); err!=nil { t.Fatal(err) }

	other,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	if _,err=store.ObserveRevision(ctx,other.ID,internalEvidence("same",4)); err!=nil { t.Fatal(err) }

	secondAt:=base.Add(2*time.Minute)
	secondScan,err:=store.StartScan(ctx,"drive","drive-root",secondAt); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-conflict",other.ID,"obj-bound-same",secondAt))
	before:=internalTableCount(t,store.Path(),"observations")
	_,err=store.AcceptSameObservationInScan(ctx,identityRequest("req-conflict",secondScan.ID,"obj-bound-same","file-id/obj-bound-same","auth-conflict",secondAt,"same"))
	if !errors.Is(err,ErrProviderObjectBindingConflict) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"observations")!=before { t.Fatal("conflicting binding mutated observations") }
	binding,err:=store.ProviderArtifactBinding(ctx,"drive:test-account","drive","obj-bound-same"); if err!=nil { t.Fatal(err) }
	if binding.ArtifactID!=first.Observation.ArtifactID { t.Fatalf("binding changed=%#v",binding) }
}
